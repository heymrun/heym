import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import type { ExecutionResult, ServerExecutionHistory, Workflow } from "@/types/workflow";

vi.mock("@/services/api", () => ({
  lastWrittenWorkflowRevision: vi.fn(() => null),
  workflowApi: {
    get: vi.fn(),
    executeStream: vi.fn(),
    getWorkflowHistoryEntry: vi.fn(),
    streamActiveExecution: vi.fn(),
    clearHistory: vi.fn(),
  },
}));

import { workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";

function makeWorkflow(id: string): Workflow {
  return {
    id,
    name: `Workflow ${id}`,
    description: null,
    nodes: [
      {
        id: `${id}-node`,
        type: "textInput",
        position: { x: 0, y: 0 },
        data: { label: `${id} node` },
      },
    ],
    edges: [],
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
    workflow_timeout_seconds: null,
    created_at: "2026-08-11T00:00:00.000Z",
    updated_at: "2026-08-11T00:00:00.000Z",
  };
}

describe("workflow execution state", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("does not apply an old workflow's completed stream to a newly opened workflow", async () => {
    const workflowA = makeWorkflow("workflow-a");
    const workflowB = makeWorkflow("workflow-b");
    const getWorkflow = vi.mocked(workflowApi.get);
    const executeStream = vi.mocked(workflowApi.executeStream);
    const stream = {
      started: null as ((data: { execution_id: string }) => void) | null,
      complete: null as ((result: ExecutionResult) => void) | null,
      signal: undefined as AbortSignal | undefined,
    };

    getWorkflow.mockImplementation(async (id: string): Promise<Workflow> => {
      return id === workflowA.id ? workflowA : workflowB;
    });
    executeStream.mockImplementation(
      (
        _id,
        _body,
        onExecutionStarted,
        _onNodeStart,
        _onNodeComplete,
        onComplete,
        _onError,
        _testRun,
        signal,
      ): void => {
        stream.started = onExecutionStarted;
        stream.complete = onComplete;
        stream.signal = signal;
      },
    );

    const store = useWorkflowStore();
    await store.loadWorkflow(workflowA.id);

    const execution = store.executeWorkflow({});
    await vi.waitFor(() => expect(executeStream).toHaveBeenCalledOnce());

    stream.started?.({ execution_id: "execution-a" });
    store.clearWorkflow();
    await store.loadWorkflow(workflowB.id);
    expect(stream.signal?.aborted).toBe(true);

    stream.complete?.({
      workflow_id: workflowA.id,
      status: "success",
      outputs: { leaked: true },
      execution_time_ms: 42,
      node_results: [
        {
          node_id: `${workflowA.id}-node`,
          node_label: "A node",
          node_type: "textInput",
          status: "success",
          output: { leaked: true },
          execution_time_ms: 42,
          error: null,
        },
      ],
      highlight: { records: [] },
    });
    await execution;

    expect(store.currentWorkflow?.id).toBe(workflowB.id);
    expect(store.executionResult).toBeNull();
    expect(store.nodeResults).toEqual([]);
    expect(store.nodes[0]?.data.status).toBeUndefined();
    expect(store.isExecuting).toBe(false);
  });

  it("does not resume a canvas execution after leaving and reopening the same workflow", async () => {
    const workflow = makeWorkflow("workflow-a");
    const getWorkflow = vi.mocked(workflowApi.get);
    const executeStream = vi.mocked(workflowApi.executeStream);
    const stream = {
      started: null as ((data: { execution_id: string }) => void) | null,
      complete: null as ((result: ExecutionResult) => void) | null,
      signal: undefined as AbortSignal | undefined,
    };

    getWorkflow.mockResolvedValue(workflow);
    executeStream.mockImplementation(
      (
        _id,
        _body,
        onExecutionStarted,
        _onNodeStart,
        _onNodeComplete,
        onComplete,
        _onError,
        _testRun,
        signal,
      ): void => {
        stream.started = onExecutionStarted;
        stream.complete = onComplete;
        stream.signal = signal;
      },
    );

    const store = useWorkflowStore();
    await store.loadWorkflow(workflow.id);

    const execution = store.executeWorkflow({});
    await vi.waitFor(() => expect(executeStream).toHaveBeenCalledOnce());
    stream.started?.({ execution_id: "execution-a" });

    store.clearWorkflow();
    await store.loadWorkflow(workflow.id);
    expect(stream.signal?.aborted).toBe(true);

    stream.complete?.({
      workflow_id: workflow.id,
      status: "success",
      outputs: { shouldNotAppear: true },
      execution_time_ms: 42,
      node_results: [],
      highlight: { records: [] },
    });
    await execution;

    expect(store.currentWorkflow?.id).toBe(workflow.id);
    expect(store.executionResult).toBeNull();
    expect(store.nodeResults).toEqual([]);
    expect(store.nodes[0]?.data.status).toBeUndefined();
    expect(store.isExecuting).toBe(false);
  });

  it("uses the streamed start timestamp for a running canvas node", async () => {
    const workflow = makeWorkflow("workflow-a");
    const getWorkflow = vi.mocked(workflowApi.get);
    const executeStream = vi.mocked(workflowApi.executeStream);
    const stream = {
      started: null as ((data: { execution_id: string; server_now_ms?: number }) => void) | null,
      nodeStart: null as ((data: { node_id: string; started_at_ms: number }) => void) | null,
      complete: null as ((result: ExecutionResult) => void) | null,
    };

    getWorkflow.mockResolvedValue(workflow);
    executeStream.mockImplementation(
      (
        _id,
        _body,
        onExecutionStarted,
        onNodeStart,
        _onNodeComplete,
        onComplete,
      ): void => {
        stream.started = onExecutionStarted as unknown as typeof stream.started;
        stream.nodeStart = onNodeStart as unknown as typeof stream.nodeStart;
        stream.complete = onComplete;
      },
    );

    const store = useWorkflowStore();
    await store.loadWorkflow(workflow.id);

    const execution = store.executeWorkflow({});
    await vi.waitFor(() => expect(executeStream).toHaveBeenCalledOnce());
    vi.spyOn(Date, "now").mockReturnValue(3_601_000);
    stream.started?.({
      execution_id: "execution-a",
      server_now_ms: 1_000,
    });
    expect(store.serverClockOffsetMs).toBe(-3_600_000);
    stream.nodeStart?.({
      node_id: `${workflow.id}-node`,
      started_at_ms: 1_000,
    });

    expect(store.nodeResults).toMatchObject([
      {
        node_id: `${workflow.id}-node`,
        status: "running",
        metadata: {
          started_at_ms: 1_000,
          ended_at_ms: 1_000,
        },
      },
    ]);

    stream.complete?.({
      workflow_id: workflow.id,
      status: "success",
      outputs: {},
      execution_time_ms: 0,
      node_results: [],
      highlight: { records: [] },
    });
    await execution;
  });

  it("applies the completion of a live execution opened in another tab", async () => {
    const workflow = makeWorkflow("workflow-a");
    const getWorkflow = vi.mocked(workflowApi.get);
    const getWorkflowHistoryEntry = vi.mocked(workflowApi.getWorkflowHistoryEntry);
    const streamActiveExecution = vi.mocked(workflowApi.streamActiveExecution);
    const stream = {
      started: null as ((data: { execution_id: string; inputs: Record<string, unknown> }) => void) | null,
      nodeStart: null as ((data: { node_id: string; started_at_ms: number }) => void) | null,
      complete: null as ((result: ExecutionResult) => void) | null,
    };

    getWorkflow.mockResolvedValue(workflow);
    getWorkflowHistoryEntry.mockResolvedValue({
      id: "execution-a",
      workflow_id: workflow.id,
      inputs: {},
      outputs: { completed: true },
      node_results: [],
      status: "success",
      execution_time_ms: 42,
      started_at: "2026-08-11T00:00:00.000Z",
      highlight: { records: [] },
    } satisfies ServerExecutionHistory);
    streamActiveExecution.mockImplementation(
      (
        _workflowId,
        _executionId,
        onExecutionStarted,
        onNodeStart,
        _onNodeComplete,
        onComplete,
      ): void => {
        stream.started = onExecutionStarted;
        stream.nodeStart = onNodeStart as unknown as typeof stream.nodeStart;
        stream.complete = onComplete;
      },
    );

    const store = useWorkflowStore();
    await store.loadWorkflow(workflow.id);

    const observation = store.observeExecution("execution-a");
    await vi.waitFor(() => expect(streamActiveExecution).toHaveBeenCalledOnce());
    stream.started?.({ execution_id: "execution-a", inputs: {} });
    stream.nodeStart?.({
      node_id: `${workflow.id}-node`,
      started_at_ms: 1_000,
    });
    expect(store.nodeResults[0]?.metadata).toMatchObject({
      started_at_ms: 1_000,
      ended_at_ms: 1_000,
    });
    await stream.complete?.({
      workflow_id: workflow.id,
      status: "success",
      outputs: { completed: true },
      execution_time_ms: 42,
      node_results: [],
      execution_history_id: "execution-a",
      highlight: { records: [] },
    });
    await observation;

    expect(store.executionResult?.outputs).toEqual({ completed: true });
    expect(store.executionResult?.highlight).toEqual({ records: [] });
    expect(store.isExecuting).toBe(false);
  });

  it("clears local execution history on successful deletion", async () => {
    const workflow = makeWorkflow("workflow-a");
    const getWorkflow = vi.mocked(workflowApi.get);
    const clearHistory = vi.mocked(workflowApi.clearHistory);
    getWorkflow.mockResolvedValue(workflow);
    clearHistory.mockResolvedValue(undefined);

    const store = useWorkflowStore();
    await store.loadWorkflow(workflow.id);

    // Seed some history
    store.executionHistoryList = [
      { id: "run-1", workflow_id: workflow.id, workflow_name: "A", status: "success", started_at: "2026-08-11T00:00:00Z", execution_time_ms: 10, run_type: "workflow", trigger_source: null }
    ];
    store.executionHistoryTotal = 1;
    store.executionHistoryDetails.set("run-1", { id: "run-1", started_at: "", inputs: {}, status: "success", recovered: false, result: { workflow_id: workflow.id, status: "success", outputs: {}, execution_time_ms: 10, node_results: [], execution_history_id: "run-1", highlight: null } });

    await store.clearExecutionHistory();

    expect(clearHistory).toHaveBeenCalledWith(workflow.id);
    expect(store.executionHistoryList).toEqual([]);
    expect(store.executionHistoryTotal).toBe(0);
    expect(store.executionHistoryDetails.size).toBe(0);
  });

  it("preserves local execution history on forbidden error from clearHistory", async () => {
    const workflow = makeWorkflow("workflow-a");
    const getWorkflow = vi.mocked(workflowApi.get);
    const clearHistory = vi.mocked(workflowApi.clearHistory);
    getWorkflow.mockResolvedValue(workflow);
    const error403 = Object.assign(new Error("Forbidden"), {
      isAxiosError: true,
      response: { status: 403 }
    });
    clearHistory.mockRejectedValue(error403);

    const store = useWorkflowStore();
    await store.loadWorkflow(workflow.id);

    // Seed some history
    store.executionHistoryList = [
      { id: "run-1", workflow_id: workflow.id, workflow_name: "A", status: "success", started_at: "2026-08-11T00:00:00Z", execution_time_ms: 10, run_type: "workflow", trigger_source: null }
    ];
    store.executionHistoryTotal = 1;
    store.executionHistoryDetails.set("run-1", { id: "run-1", started_at: "", inputs: {}, status: "success", recovered: false, result: { workflow_id: workflow.id, status: "success", outputs: {}, execution_time_ms: 10, node_results: [], execution_history_id: "run-1", highlight: null } });

    await expect(store.clearExecutionHistory()).rejects.toThrow("Forbidden");

    expect(clearHistory).toHaveBeenCalledWith(workflow.id);
    expect(store.executionHistoryTotal).toBe(1);
    expect(store.executionHistoryList.length).toBe(1);
    expect(store.executionHistoryDetails.size).toBe(1);
  });
});
