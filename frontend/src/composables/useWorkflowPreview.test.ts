import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

import { useWorkflowPreview } from "./useWorkflowPreview";
import { workflowApi } from "@/services/api";
import type {
  AllExecutionHistoryEntryLight,
  HistoryListResponse,
  Workflow,
} from "@/types/workflow";

// Unlike useWorkflowRowStatus/useOverlayBackHandler, this composable has NO
// onMounted/onUnmounted - it only uses ref/watch, which work fine called
// directly in a test with no component or effectScope needed. You can call
// useWorkflowPreview(selectedId) directly at the top of a test body.

// `watch(selectedId, () => void load(), { immediate: true })` means the
// initial load fires SYNCHRONOUSLY on calling useWorkflowPreview - but the
// load() function itself is async (awaits workflowApi.get/getHistory), so
// the *results* land on a later microtask. You'll need to await something
// after creating the composable before asserting on detail/lastRun/loading -
// `await vi.waitFor(() => expect(loading.value).toBe(false))` is a reliable
// way to wait for a load to settle without hardcoding a specific await count.
//
// Later changes to selectedId.value need `await nextTick()` before the watch
// callback (and therefore a new load()) actually fires - same reactivity
// timing rule as everywhere else in this codebase's composables.

function buildWorkflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    id: "wf-1",
    name: "Test workflow",
    description: null,
    nodes: [],
    edges: [],
    auth_type: "anonymous",
    auth_header_key: null,
    auth_header_value: null,
    auth_header_value_set: false,
    webhook_body_mode: "generic",
    allow_anonymous: false,
    owner_id: "user-1",
    cache_ttl_seconds: null,
    rate_limit_requests: null,
    rate_limit_window_seconds: null,
    sse_enabled: false,
    sse_node_config: {},
    auto_recover_runs: false,
    error_workflow_id: null,
    minutes_saved_per_run: null,
    workflow_timeout_seconds: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function buildHistoryEntry(
  overrides: Partial<AllExecutionHistoryEntryLight> = {},
): AllExecutionHistoryEntryLight {
  return {
    id: "exec-1",
    workflow_id: "wf-1",
    workflow_name: "Test workflow",
    run_type: "workflow",
    started_at: "2026-01-01T00:00:00Z",
    status: "success",
    execution_time_ms: 100,
    ...overrides,
  };
}

function buildHistoryResponse(
  items: AllExecutionHistoryEntryLight[] = [],
): HistoryListResponse<AllExecutionHistoryEntryLight> {
  return { total: items.length, items };
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.spyOn(workflowApi, "get").mockResolvedValue(buildWorkflow());
  vi.spyOn(workflowApi, "getHistory").mockResolvedValue(
    buildHistoryResponse([buildHistoryEntry()]),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useWorkflowPreview - no selection", () => {
  it("does nothing when no workflow is selected", async () => {
    const selectedId = ref<string | null>(null);
    const { detail, lastRun, loading, error } = useWorkflowPreview(selectedId);

    expect(detail.value).toBeNull();
    expect(lastRun.value).toBeNull();
    expect(loading.value).toBe(false);
    expect(error.value).toBeNull();
    expect(workflowApi.get).not.toHaveBeenCalled();
    expect(workflowApi.getHistory).not.toHaveBeenCalled();
  });
});

describe("useWorkflowPreview - loading a selection", () => {
  it("loads the workflow detail and most recent run for the selected id", async () => {
    const entry = buildHistoryEntry({ id: "exec-9" });
    vi.mocked(workflowApi.get).mockResolvedValue(buildWorkflow({ id: "wf-1" }));
    vi.mocked(workflowApi.getHistory).mockResolvedValue(buildHistoryResponse([entry]));

    const selectedId = ref<string | null>("wf-1");
    const { detail, lastRun, loading, error } = useWorkflowPreview(selectedId);

    await vi.waitFor(() => expect(loading.value).toBe(false));
    expect(detail.value?.id).toBe("wf-1");
    expect(lastRun.value).toEqual(entry);
    expect(error.value).toBeNull();
  });

  it("lastRun is null when the workflow has no execution history yet", async () => {
    vi.mocked(workflowApi.getHistory).mockResolvedValue(buildHistoryResponse([]));

    const selectedId = ref<string | null>("wf-1");
    const { detail, lastRun, loading } = useWorkflowPreview(selectedId);

    await vi.waitFor(() => expect(loading.value).toBe(false));
    expect(lastRun.value).toBeNull();
    expect(detail.value).not.toBeNull();
  });

  it("loading is true immediately, before the API calls settle", () => {
    const selectedId = ref<string | null>("wf-1");
    const { loading } = useWorkflowPreview(selectedId);

    expect(loading.value).toBe(true);
  });
});

describe("useWorkflowPreview - partial/full failure", () => {
  it("a failed workflow fetch does not prevent the history fetch from populating lastRun", async () => {
    const entry = buildHistoryEntry({ id: "exec-9" });
    vi.mocked(workflowApi.get).mockRejectedValue(new Error("not found"));
    vi.mocked(workflowApi.getHistory).mockResolvedValue(buildHistoryResponse([entry]));

    const selectedId = ref<string | null>("wf-1");
    const { detail, lastRun, loading, error } = useWorkflowPreview(selectedId);

    await vi.waitFor(() => expect(loading.value).toBe(false));
    expect(detail.value).toBeNull();
    expect(error.value).toBe("Could not load this workflow's details.");
    expect(lastRun.value).toEqual(entry);
  });

  it("a failed history fetch does not block the workflow detail from populating", async () => {
    vi.mocked(workflowApi.get).mockResolvedValue(buildWorkflow({ id: "wf-1" }));
    vi.mocked(workflowApi.getHistory).mockRejectedValue(new Error("history unavailable"));

    const selectedId = ref<string | null>("wf-1");
    const { detail, lastRun, loading, error } = useWorkflowPreview(selectedId);

    await vi.waitFor(() => expect(loading.value).toBe(false));
    expect(detail.value?.id).toBe("wf-1");
    expect(lastRun.value).toBeNull();
    expect(error.value).toBeNull();
  });
});

describe("useWorkflowPreview - stale response discarding", () => {
  it("a late-resolving response from a previous selection is discarded", async () => {
    const firstDetail = deferred<Workflow>();
    const firstHistory = deferred<HistoryListResponse<AllExecutionHistoryEntryLight>>();
    const secondWorkflow = buildWorkflow({ id: "wf-2" });
    const secondEntry = buildHistoryEntry({ id: "exec-2", workflow_id: "wf-2" });

    vi.mocked(workflowApi.get).mockImplementation((id: string) =>
      id === "wf-1" ? firstDetail.promise : Promise.resolve(secondWorkflow),
    );
    vi.mocked(workflowApi.getHistory).mockImplementation((id: string) =>
      id === "wf-1" ? firstHistory.promise : Promise.resolve(buildHistoryResponse([secondEntry])),
    );

    const selectedId = ref<string | null>("wf-1");
    const { detail, lastRun, loading } = useWorkflowPreview(selectedId);

    selectedId.value = "wf-2";
    await nextTick();
    await vi.waitFor(() => expect(loading.value).toBe(false));

    // Generation 1 (wf-1) resolves AFTER generation 2 (wf-2) already settled.
    firstDetail.resolve(buildWorkflow({ id: "wf-1" }));
    firstHistory.resolve(buildHistoryResponse([buildHistoryEntry({ id: "exec-1" })]));
    await Promise.resolve();
    await Promise.resolve();

    expect(detail.value?.id).toBe("wf-2");
    expect(lastRun.value).toEqual(secondEntry);
  });
});

describe("useWorkflowPreview - reload", () => {
  it("reload() re-fetches for the current selection without changing selectedId", async () => {
    const selectedId = ref<string | null>("wf-1");
    const { detail, loading, reload } = useWorkflowPreview(selectedId);
    await vi.waitFor(() => expect(loading.value).toBe(false));

    const updatedWorkflow = buildWorkflow({ id: "wf-1", name: "Renamed" });
    vi.mocked(workflowApi.get).mockResolvedValue(updatedWorkflow);

    await reload();

    expect(workflowApi.get).toHaveBeenCalledWith("wf-1");
    expect(detail.value?.name).toBe("Renamed");
  });
});
