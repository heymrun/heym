import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import type { Workflow } from "@/types/workflow";

vi.mock("@/services/api", () => ({
  lastWrittenWorkflowRevision: vi.fn(() => null),
  workflowApi: {
    get: vi.fn(),
    update: vi.fn(),
    executeStream: vi.fn(),
    getFileUploadSlot: vi.fn(),
    getWorkflowHistoryEntry: vi.fn(),
    streamActiveExecution: vi.fn(),
    clearHistory: vi.fn(),
  },
}));

import { workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";

function makeFileUploadWorkflow(id: string, ttlMinutes = 60, timeoutSeconds?: number): Workflow {
  return {
    id,
    name: `Workflow ${id}`,
    description: null,
    nodes: [
      {
        id: "upload-node",
        type: "fileUploadTrigger",
        position: { x: 0, y: 0 },
        data: { label: "Upload Trigger", ttlMinutes },
      },
      {
        id: "out-node",
        type: "output",
        position: { x: 200, y: 0 },
        data: { label: "Result" },
      },
    ],
    edges: [{ id: "e1", source: "upload-node", target: "out-node" }],
    auth_type: "jwt",
    auth_header_key: null,
    auth_header_value: null,
    auth_header_value_set: false,
    webhook_body_mode: "legacy",
    allow_anonymous: false,
    owner_id: "owner-id",
    cache_ttl_seconds: null,
    rate_limit_requests: null,
    rate_limit_window_seconds: null,
    sse_enabled: false,
    sse_node_config: {},
    auto_recover_runs: false,
    error_workflow_id: null,
    minutes_saved_per_run: null,
    workflow_timeout_seconds: timeoutSeconds ?? null,
    created_at: "2026-08-11T00:00:00.000Z",
    updated_at: "2026-08-11T00:00:00.000Z",
  };
}

class MockDocument {
  visibilityState = "visible";
  private listeners: Record<string, ((event: { type: string }) => void)[]> = {};

  addEventListener(event: string, fn: (event: { type: string }) => void): void {
    this.listeners[event] = this.listeners[event] || [];
    this.listeners[event]!.push(fn);
  }

  removeEventListener(event: string, fn: (event: { type: string }) => void): void {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event]!.filter((l) => l !== fn);
    }
  }

  dispatchEvent(event: { type: string }): boolean {
    if (this.listeners[event.type]) {
      [...this.listeners[event.type]!].forEach((fn) => fn(event));
    }
    return true;
  }
}

describe("fileUploadTrigger lifecycle & polling", () => {
  let createdMockDocument = false;

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    vi.useFakeTimers();

    if (typeof (globalThis as unknown as { document?: unknown }).document === "undefined") {
      (globalThis as unknown as { document: MockDocument }).document = new MockDocument();
      createdMockDocument = true;
    } else {
      (globalThis as unknown as { document: { visibilityState: string } }).document.visibilityState = "visible";
    }
  });

  afterEach(() => {
    vi.useRealTimers();
    if (createdMockDocument) {
      delete (globalThis as unknown as { document?: unknown }).document;
      createdMockDocument = false;
    }
  });

  it("1. Normal upload: arrives before 30 minutes and canvas receives result", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-normal", 60);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-normal");

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-1" });
        onComplete?.({
          workflow_id: "wf-normal",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-1",
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "pending",
      run_id: null,
      run: null,
      expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    });

    await store.executeWorkflow({});
    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Advance 5 minutes
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
    expect(vi.mocked(workflowApi.getFileUploadSlot)).toHaveBeenCalled();

    // File uploaded at minute 5:
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "consumed",
      run_id: "run-1",
      run: {
        status: "success",
        outputs: { result: "File processed" },
        node_results: [
          { node_id: "upload-node", node_label: "Upload", node_type: "fileUploadTrigger", status: "success", output: {}, execution_time_ms: 1, error: null },
          { node_id: "out-node", node_label: "Result", node_type: "output", status: "success", output: { result: "File processed" }, execution_time_ms: 1, error: null },
        ],
        execution_time_ms: 10,
        execution_history_id: "run-1",
      },
    });

    // Advance 10s (the backoff delay at minute 5)
    await vi.advanceTimersByTimeAsync(10000);

    expect(store.executionResult?.status).toBe("success");
    expect(store.executionResult?.outputs).toEqual({ result: "File processed" });
    expect(store.nodeResults).toHaveLength(2);
  });

  it("2. Late valid upload: arrives at minute 35 with a 60-minute TTL and canvas retrieves result", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-late", 60);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-late");

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-2" });
        onComplete?.({
          workflow_id: "wf-late",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-2",
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "pending",
      run_id: null,
      run: null,
      expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    });

    await store.executeWorkflow({});
    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Advance 34 minutes
    await vi.advanceTimersByTimeAsync(34 * 60 * 1000);
    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Upload arrives at minute 35:
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "consumed",
      run_id: "run-2",
      run: {
        status: "success",
        outputs: { result: "Late upload processed" },
        node_results: [
          { node_id: "upload-node", node_label: "Upload", node_type: "fileUploadTrigger", status: "success", output: {}, execution_time_ms: 2, error: null },
          { node_id: "out-node", node_label: "Result", node_type: "output", status: "success", output: { result: "Late upload processed" }, execution_time_ms: 2, error: null },
        ],
        execution_time_ms: 20,
        execution_history_id: "run-2",
      },
    });

    // Advance 30s (the backoff poll interval at minute 35)
    await vi.advanceTimersByTimeAsync(30000);

    expect(store.executionResult?.status).toBe("success");
    expect(store.executionResult?.outputs).toEqual({ result: "Late upload processed" });
  });

  it("3. Expired upload: slot remains pending beyond expiry and displays explicit error", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-expired", 10);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-expired");

    const tenMinutesMs = 10 * 60 * 1000;
    const expiryIso = new Date(Date.now() + tenMinutesMs).toISOString();

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-3" });
        onComplete?.({
          workflow_id: "wf-expired",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-3",
            expires_at: expiryIso,
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    vi.mocked(workflowApi.getFileUploadSlot).mockImplementation(async () => ({
      status: Date.now() >= Date.parse(expiryIso) ? "expired" : "pending",
      run_id: null,
      run: null,
      expires_at: expiryIso,
    }));

    await store.executeWorkflow({});
    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Advance to 10 minutes + 1 second
    await vi.advanceTimersByTimeAsync(tenMinutesMs + 1000);

    // Canvas transitions to explicit error state
    expect(store.executionResult?.status).toBe("error");
    expect(store.executionResult?.outputs).toMatchObject({
      error: "Upload link expired before a file was uploaded",
      slot_id: "slot-3",
    });

    // Verify polling stopped: advancing further triggers no more calls
    const callCountAtExpiry = vi.mocked(workflowApi.getFileUploadSlot).mock.calls.length;
    await vi.advanceTimersByTimeAsync(60000);
    expect(vi.mocked(workflowApi.getFileUploadSlot).mock.calls.length).toBe(callCountAtExpiry);
  });

  it("4. Execution crossing expiry: upload accepted at m59, completes at m65, canvas retrieves result", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-cross", 60);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-cross");

    const expiryIso = new Date(Date.now() + 60 * 60 * 1000).toISOString();

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-4" });
        onComplete?.({
          workflow_id: "wf-cross",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-4",
            expires_at: expiryIso,
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "pending",
      run_id: null,
      run: null,
      expires_at: expiryIso,
    });

    await store.executeWorkflow({});

    // Advance to minute 59
    await vi.advanceTimersByTimeAsync(59 * 60 * 1000);

    // Upload accepted at minute 59: status=consumed, run_id=null (executing)
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "consumed",
      run_id: null,
      run: null,
      expires_at: expiryIso,
    });
    await vi.advanceTimersByTimeAsync(30000);

    // Advance past slot expiry (minute 60) to minute 65
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
    // Polling did NOT abort at minute 60 because upload was already accepted!
    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Execution finishes at minute 65:
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "consumed",
      run_id: "run-4",
      run: {
        status: "success",
        outputs: { result: "Crossing expiry run done" },
        node_results: [
          { node_id: "upload-node", node_label: "Upload", node_type: "fileUploadTrigger", status: "success", output: {}, execution_time_ms: 5, error: null },
          { node_id: "out-node", node_label: "Result", node_type: "output", status: "success", output: { result: "Crossing expiry run done" }, execution_time_ms: 5, error: null },
        ],
        execution_time_ms: 50,
        execution_history_id: "run-4",
      },
    });

    await vi.advanceTimersByTimeAsync(2500);

    expect(store.executionResult?.status).toBe("success");
    expect(store.executionResult?.outputs).toEqual({ result: "Crossing expiry run done" });
  });

  it("5. Accepted upload with delayed completion: status=consumed initially, later poll completes", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-delayed", 60);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-delayed");

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-5" });
        onComplete?.({
          workflow_id: "wf-delayed",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-5",
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    // First poll returns consumed but run is null
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValueOnce({
      status: "consumed",
      run_id: null,
      run: null,
    });

    await store.executeWorkflow({});
    await vi.advanceTimersByTimeAsync(2500);

    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Second poll returns completed run
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValueOnce({
      status: "consumed",
      run_id: "run-5",
      run: {
        status: "success",
        outputs: { result: "Delayed execution ready" },
        node_results: [
          { node_id: "upload-node", node_label: "Upload", node_type: "fileUploadTrigger", status: "success", output: {}, execution_time_ms: 5, error: null },
        ],
        execution_time_ms: 10,
        execution_history_id: "run-5",
      },
    });

    await vi.advanceTimersByTimeAsync(2500);

    expect(store.executionResult?.status).toBe("success");
    expect(store.executionResult?.outputs).toEqual({ result: "Delayed execution ready" });
  });

  it("6. Failed execution: displays failed run result rather than remaining in awaiting_file_upload", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-fail", 60);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-fail");

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-6" });
        onComplete?.({
          workflow_id: "wf-fail",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-6",
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "consumed",
      run_id: "run-6",
      run: {
        status: "error",
        outputs: { error: "Parse error in uploaded file" },
        node_results: [
          { node_id: "upload-node", node_label: "Upload", node_type: "fileUploadTrigger", status: "error", output: {}, execution_time_ms: 2, error: "Parse error" },
        ],
        execution_time_ms: 5,
        execution_history_id: "run-6",
      },
    });

    await store.executeWorkflow({});
    await vi.advanceTimersByTimeAsync(2500);

    expect(store.executionResult?.status).toBe("error");
    expect(store.executionResult?.outputs).toEqual({ error: "Parse error in uploaded file" });
    expect(store.nodes[0]?.data.status).toBe("error");
  });

  it("7. Cancellation: starting another run or clearing cancels poller", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-cancel", 60);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-cancel");

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-7" });
        onComplete?.({
          workflow_id: "wf-cancel",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-7",
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "pending",
      run_id: null,
      run: null,
    });

    await store.executeWorkflow({});
    await vi.advanceTimersByTimeAsync(2500);
    const initialCallCount = vi.mocked(workflowApi.getFileUploadSlot).mock.calls.length;
    expect(initialCallCount).toBeGreaterThan(0);

    // Stop execution
    store.stopExecution();

    // Advance time further
    await vi.advanceTimersByTimeAsync(60000);

    // Polling was cancelled immediately
    expect(vi.mocked(workflowApi.getFileUploadSlot).mock.calls.length).toBe(initialCallCount);
  });

  it("8. Visibility handling: hidden tabs pause rapid polling, visible resumes immediately", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-vis", 60);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-vis");

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-8" });
        onComplete?.({
          workflow_id: "wf-vis",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-8",
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "pending",
      run_id: null,
      run: null,
    });

    await store.executeWorkflow({});
    await vi.advanceTimersByTimeAsync(2500);
    const callCountBeforeHidden = vi.mocked(workflowApi.getFileUploadSlot).mock.calls.length;

    // Simulate tab becoming hidden
    const doc = (globalThis as unknown as { document: { visibilityState: string; dispatchEvent: (e: { type: string }) => boolean } }).document;
    doc.visibilityState = "hidden";
    doc.dispatchEvent({ type: "visibilitychange" });

    // Advance 30 seconds while hidden
    await vi.advanceTimersByTimeAsync(30000);

    // Hidden tab does not rapidly poll (sleep interval is 60s while hidden)
    expect(vi.mocked(workflowApi.getFileUploadSlot).mock.calls.length).toBe(callCountBeforeHidden);

    // Now user switches back to tab: tab becomes visible
    doc.visibilityState = "visible";
    doc.dispatchEvent({ type: "visibilitychange" });

    // Immediate status check is triggered by visibilitychange!
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.mocked(workflowApi.getFileUploadSlot).mock.calls.length).toBe(callCountBeforeHidden + 1);
  });

  it("A. Workflow timeout is null: accepted upload does not abort after 15m30s without timeout", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-notimeout", 60, undefined);
    expect(wf.workflow_timeout_seconds).toBeNull();

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-notimeout");

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-a" });
        onComplete?.({
          workflow_id: "wf-notimeout",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-a",
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    // Initial polls return status consumed with run_id null
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "consumed",
      run_id: null,
      run: null,
    });

    await store.executeWorkflow({});
    await vi.advanceTimersByTimeAsync(2500);
    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Advance fake time beyond 15 minutes and 30 seconds (16 minutes = 960,000ms)
    await vi.advanceTimersByTimeAsync(16 * 60 * 1000);

    // Verify the canvas has not been marked as failed merely because of an invented timeout
    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Later return a completed run
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "consumed",
      run_id: "run-a",
      run: {
        status: "success",
        outputs: { result: "Completed after 20 minutes" },
        node_results: [
          {
            node_id: "upload-node",
            node_label: "Upload",
            node_type: "fileUploadTrigger",
            status: "success",
            output: {},
            execution_time_ms: 5,
            error: null,
          },
        ],
        execution_time_ms: 1200000,
        execution_history_id: "run-a",
      },
    });

    await vi.advanceTimersByTimeAsync(2500);

    // Verify the canvas displays the completed output
    expect(store.executionResult?.status).toBe("success");
    expect(store.executionResult?.outputs).toEqual({ result: "Completed after 20 minutes" });
  });

  it("B. Upload accepted just before expiry: does not report expiration if next poll wakes after expiry", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-race", 60);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-race");

    const expiryMs = 60 * 60 * 1000;
    const expiryIso = new Date(Date.now() + expiryMs).toISOString();

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-b" });
        onComplete?.({
          workflow_id: "wf-race",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-b",
            expires_at: expiryIso,
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    // Initial polls return pending
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "pending",
      run_id: null,
      run: null,
      expires_at: expiryIso,
    });

    await store.executeWorkflow({});

    // Arrange the last pending poll immediately before expiry (minute 59, second 30)
    await vi.advanceTimersByTimeAsync(59 * 60 * 1000 + 30 * 1000);
    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Simulate upload acceptance just before expiry: status=consumed, run_id=null
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "consumed",
      run_id: null,
      run: null,
      expires_at: expiryIso,
    });

    // Make the next poll wake after expiry (advance 35 seconds, which crosses the 60m expiry mark)
    await vi.advanceTimersByTimeAsync(35 * 1000);

    // Verify the frontend does not report expiration
    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Return the completed run on a subsequent poll
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "consumed",
      run_id: "run-b",
      run: {
        status: "success",
        outputs: { result: "Race won: upload accepted just before expiry" },
        node_results: [
          {
            node_id: "upload-node",
            node_label: "Upload",
            node_type: "fileUploadTrigger",
            status: "success",
            output: {},
            execution_time_ms: 10,
            error: null,
          },
        ],
        execution_time_ms: 50,
        execution_history_id: "run-b",
      },
    });

    await vi.advanceTimersByTimeAsync(2500);

    // Verify the canvas displays it
    expect(store.executionResult?.status).toBe("success");
    expect(store.executionResult?.outputs).toEqual({
      result: "Race won: upload accepted just before expiry",
    });
  });

  it("C. Backend-authoritative expiry: transitions to explicit error when backend reports expired and stops polling", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-authoritative-expiry", 10);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-authoritative-expiry");

    const tenMinutesMs = 10 * 60 * 1000;
    const expiryIso = new Date(Date.now() + tenMinutesMs).toISOString();

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-c" });
        onComplete?.({
          workflow_id: "wf-authoritative-expiry",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-c",
            expires_at: expiryIso,
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    // Status endpoint returns pending before expiry, expired after expiry time
    vi.mocked(workflowApi.getFileUploadSlot).mockImplementation(async () => {
      const isPastExpiry = Date.now() >= Date.parse(expiryIso);
      return {
        status: isPastExpiry ? "expired" : "pending",
        run_id: null,
        run: null,
        expires_at: expiryIso,
      };
    });

    await store.executeWorkflow({});
    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Advance time past expiry
    await vi.advanceTimersByTimeAsync(tenMinutesMs + 5000);

    // Verify canvas transitions to explicit expiry error
    expect(store.executionResult?.status).toBe("error");
    expect(store.executionResult?.outputs).toMatchObject({
      error: "Upload link expired before a file was uploaded",
      slot_id: "slot-c",
    });

    // Verify polling terminates
    const callCount = vi.mocked(workflowApi.getFileUploadSlot).mock.calls.length;
    await vi.advanceTimersByTimeAsync(60000);
    expect(vi.mocked(workflowApi.getFileUploadSlot).mock.calls.length).toBe(callCount);
  });

  it("D. Clock skew: browser clock ahead of server does not declare slot expired solely from local clock", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-skew", 10);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-skew");

    const tenMinutesMs = 10 * 60 * 1000;
    const expiryIso = new Date(Date.now() + tenMinutesMs).toISOString();

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-d" });
        onComplete?.({
          workflow_id: "wf-skew",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-d",
            expires_at: expiryIso,
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    // Backend still reports "pending" even when local time passes expiresAt
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "pending",
      run_id: null,
      run: null,
      expires_at: expiryIso,
    });

    await store.executeWorkflow({});

    // Advance local time past expiry timestamp
    await vi.advanceTimersByTimeAsync(tenMinutesMs + 5000);

    // Verify the browser does NOT independently declare the slot expired solely from its local clock
    expect(store.executionResult?.status).toBe("awaiting_file_upload");
    expect(vi.mocked(workflowApi.getFileUploadSlot)).toHaveBeenCalled();

    // Now server finally marks it expired:
    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "expired",
      run_id: null,
      run: null,
      expires_at: expiryIso,
    });

    await vi.advanceTimersByTimeAsync(30000);

    // Now that backend reports expired, canvas transitions to error
    expect(store.executionResult?.status).toBe("error");
    expect(store.executionResult?.outputs).toMatchObject({
      error: "Upload link expired before a file was uploaded",
      slot_id: "slot-d",
    });
  });

  it("E. Positive workflow timeout: times out if accepted upload exceeds configured timeout + grace period", async () => {
    const store = useWorkflowStore();
    const wf = makeFileUploadWorkflow("wf-timeout-pos", 60, 20);

    vi.mocked(workflowApi.get).mockResolvedValue(wf);
    await store.loadWorkflow("wf-timeout-pos");

    vi.mocked(workflowApi.executeStream).mockImplementation(
      (_id, _body, onStarted, _onNodeStart, _onNodeComplete, onComplete) => {
        onStarted?.({ execution_id: "exec-pos" });
        onComplete?.({
          workflow_id: "wf-timeout-pos",
          status: "awaiting_file_upload",
          outputs: {
            slot_id: "slot-pos",
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
          },
          execution_time_ms: 0,
          node_results: [],
        });
      },
    );

    vi.mocked(workflowApi.getFileUploadSlot).mockResolvedValue({
      status: "consumed",
      run_id: null,
      run: null,
      consumed_at: new Date(Date.now()).toISOString(),
    });

    await store.executeWorkflow({});
    await vi.advanceTimersByTimeAsync(2500);
    expect(store.executionResult?.status).toBe("awaiting_file_upload");

    // Advance 51 seconds (> 20s timeout + 30s grace)
    await vi.advanceTimersByTimeAsync(51 * 1000);

    expect(store.executionResult?.status).toBe("error");
    expect(store.executionResult?.outputs).toMatchObject({
      error: "Workflow execution timed out after 20s without reporting a result",
      slot_id: "slot-pos",
    });
  });
});
