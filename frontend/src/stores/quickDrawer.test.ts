import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

vi.mock("@/services/api", () => ({
  workflowApi: {
    listWithInputs: vi.fn(),
    execute: vi.fn(),
    executeStream: vi.fn(),
    get: vi.fn(),
  },
  fileIntakeApi: { upload: vi.fn() },
}));

import { fileIntakeApi, workflowApi } from "@/services/api";
import { useQuickDrawerStore } from "@/stores/quickDrawer";

const fileWorkflow = {
  id: "wf-1",
  name: "Invoice reader",
  description: null,
  input_fields: [],
  file_input: { label: "invoice", max_size_mb: 5, allowed_types: ["application/pdf"] },
  output_node: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("quick drawer file runs", () => {
  beforeEach(async () => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    vi.mocked(workflowApi.listWithInputs).mockResolvedValue([fileWorkflow]);
  });

  async function storeWithFileWorkflow(): Promise<ReturnType<typeof useQuickDrawerStore>> {
    const store = useQuickDrawerStore();
    await store.ensureWorkflows(true);
    store.selectWorkflow("wf-1");
    return store;
  }

  it("reads the file input from the workflow list", async () => {
    const store = await storeWithFileWorkflow();

    expect(store.selectedWorkflow?.fileInput).toEqual({
      label: "invoice",
      maxSizeMb: 5,
      allowedTypes: ["application/pdf"],
    });
  });

  it("mints a Quick Drawer upload link, uploads the file and shows the result", async () => {
    vi.mocked(workflowApi.execute).mockResolvedValue({
      workflow_id: "wf-1",
      status: "awaiting_file_upload",
      outputs: { upload_url: "http://heym.example/api/file-intake/u/token" },
      execution_time_ms: 0,
      node_results: [],
      execution_history_id: null,
    } as never);
    vi.mocked(fileIntakeApi.upload).mockResolvedValue({
      run_id: "run-1",
      status: "success",
      file: { id: "f-1", name: "march.pdf", mime: "application/pdf", size: 4, download_url: "" },
      output: { total: 42 },
    });
    const store = await storeWithFileWorkflow();
    const file = new File(["%PDF"], "march.pdf", { type: "application/pdf" });
    store.selectFile(file);

    await store.runSelectedWorkflow();

    expect(workflowApi.execute).toHaveBeenCalledWith(
      "wf-1",
      {},
      { triggerSource: "Quick Drawer", simpleResponse: false },
    );
    expect(fileIntakeApi.upload).toHaveBeenCalledWith(
      "http://heym.example/api/file-intake/u/token",
      file,
    );
    expect(store.runState.status).toBe("success");
    expect(store.runState.outputs).toEqual({ total: 42 });
    expect(store.runState.executionHistoryId).toBe("run-1");
    expect(store.selectedFile).toBeNull();
    expect(workflowApi.executeStream).not.toHaveBeenCalled();
  });

  it("does not run without a file", async () => {
    const store = await storeWithFileWorkflow();

    await store.runSelectedWorkflow();

    expect(workflowApi.execute).not.toHaveBeenCalled();
    expect(store.runState.status).toBe("idle");
  });

  it("shows the server's reason when the upload is refused", async () => {
    vi.mocked(workflowApi.execute).mockResolvedValue({
      status: "awaiting_file_upload",
      outputs: { upload_url: "/api/file-intake/u/token" },
    } as never);
    vi.mocked(fileIntakeApi.upload).mockRejectedValue(new Error("File type not allowed"));
    const store = await storeWithFileWorkflow();
    store.selectFile(new File(["x"], "notes.txt"));

    await store.runSelectedWorkflow();

    expect(store.runState.status).toBe("error");
    expect(store.runState.errorMessage).toBe("File type not allowed");
  });
});
