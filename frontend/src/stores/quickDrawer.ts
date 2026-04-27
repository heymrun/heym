import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { useToast } from "@/composables/useToast";
import { workflowApi, type WorkflowWithInputs } from "@/services/api";
import type {
  QuickDrawerPreferences,
  QuickDrawerRunState,
  QuickDrawerWorkflowViewModel,
} from "@/types/quickDrawer";
import type { NodeResult, Workflow } from "@/types/workflow";

const PREFERENCES_STORAGE_KEY = "heym-quick-drawer-preferences";
const WORKFLOW_CACHE_TTL_MS = 60_000;

function readStoredPreferences(): Partial<QuickDrawerPreferences> | null {
  if (typeof window === "undefined") return null;

  try {
    const raw = window.localStorage.getItem(PREFERENCES_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as Partial<QuickDrawerPreferences>;
  } catch {
    return null;
  }
}

export function getStoredQuickDrawerPinnedWorkflowIds(): string[] {
  const parsed = readStoredPreferences();
  if (!parsed || !Array.isArray(parsed.pinnedWorkflowIds)) {
    return [];
  }

  return parsed.pinnedWorkflowIds.filter(
    (workflowId): workflowId is string => typeof workflowId === "string",
  );
}

function createEmptyRunState(): QuickDrawerRunState {
  return {
    status: "idle",
    executionId: null,
    outputs: null,
    executionTimeMs: null,
    executionHistoryId: null,
    errorMessage: null,
    nodeResults: [],
    startedAt: null,
  };
}

function normalizeWorkflow(workflow: WorkflowWithInputs): QuickDrawerWorkflowViewModel {
  return {
    id: workflow.id,
    name: workflow.name,
    description: workflow.description,
    inputFields: workflow.input_fields.map((field) => ({
      key: field.key,
      defaultValue: field.defaultValue,
    })),
    outputNode: workflow.output_node
      ? {
          label: workflow.output_node.label,
          nodeType: workflow.output_node.node_type,
          outputExpression: workflow.output_node.output_expression,
        }
      : null,
    createdAt: workflow.created_at,
    updatedAt: workflow.updated_at,
    pinned: false,
    searchableText: `${workflow.name} ${workflow.description ?? ""}`.toLowerCase(),
  };
}

function extractErrorMessage(outputs: Record<string, unknown> | null): string | null {
  if (!outputs) return null;

  const detail = outputs.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }

  const error = outputs.error;
  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }

  const message = outputs.message;
  if (typeof message === "string" && message.trim()) {
    return message.trim();
  }

  return null;
}

function buildNodeLabelMap(workflow: Workflow): Record<string, string> {
  return workflow.nodes.reduce<Record<string, string>>((labels, node) => {
    const rawLabel = typeof node.data.label === "string" ? node.data.label.trim() : "";
    labels[node.id] = rawLabel || node.id;
    return labels;
  }, {});
}

async function loadNodeLabelMap(workflowId: string): Promise<Record<string, string>> {
  try {
    const workflow = await workflowApi.get(workflowId);
    return buildNodeLabelMap(workflow);
  } catch {
    return {};
  }
}

function resolveNodeLabel(
  nodeLabelsById: Record<string, string>,
  nodeId: string,
  streamedLabel?: string | null,
): string {
  const mappedLabel = nodeLabelsById[nodeId];
  if (mappedLabel) {
    return mappedLabel;
  }

  if (typeof streamedLabel === "string" && streamedLabel.trim()) {
    return streamedLabel.trim();
  }

  return nodeId;
}

function normalizeOutputs(
  outputs: Record<string, unknown> | null,
  nodeResults: NodeResult[],
  nodeLabelsById: Record<string, string>,
): Record<string, unknown> | null {
  if (!outputs) return null;

  const normalizedOutputs: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(outputs)) {
    const matchingNode = nodeResults.find(
      (nodeResult) => nodeResult.node_id === key || nodeResult.node_label === key,
    );
    const normalizedKey = matchingNode
      ? resolveNodeLabel(nodeLabelsById, matchingNode.node_id, matchingNode.node_label)
      : key;

    normalizedOutputs[normalizedKey] = value;
  }

  return normalizedOutputs;
}

export const useQuickDrawerStore = defineStore("quickDrawer", () => {
  const { showToast } = useToast();

  const hydrated = ref(false);
  const isDrawerOpen = ref(false);
  const workflows = ref<QuickDrawerWorkflowViewModel[]>([]);
  const pinnedWorkflowIds = ref<string[]>([]);
  const lastSelectedWorkflowId = ref<string | null>(null);
  const selectedWorkflowId = ref<string | null>(null);
  const filterText = ref("");
  const isLoadingWorkflows = ref(false);
  const workflowLoadError = ref<string | null>(null);
  const workflowsFetchedAt = ref(0);
  const inputValuesByWorkflowId = ref<Record<string, Record<string, string>>>({});
  const isDetailPanelOpen = ref(false);
  const runState = ref<QuickDrawerRunState>(createEmptyRunState());

  let loadPromise: Promise<void> | null = null;
  let abortController: AbortController | null = null;

  const selectedWorkflow = computed<QuickDrawerWorkflowViewModel | null>(() => {
    return workflows.value.find((workflow) => workflow.id === selectedWorkflowId.value) ?? null;
  });

  const currentInputValues = computed<Record<string, string>>(() => {
    if (!selectedWorkflowId.value) return {};
    return inputValuesByWorkflowId.value[selectedWorkflowId.value] ?? {};
  });

  const normalizedFilter = computed(() => filterText.value.trim().toLowerCase());

  const filteredPinnedWorkflows = computed<QuickDrawerWorkflowViewModel[]>(() => {
    const workflowMap = new Map(workflows.value.map((workflow) => [workflow.id, workflow]));
    return pinnedWorkflowIds.value
      .map((workflowId) => workflowMap.get(workflowId) ?? null)
      .filter((workflow): workflow is QuickDrawerWorkflowViewModel => workflow !== null)
      .filter((workflow) => {
        if (!normalizedFilter.value) return true;
        return workflow.searchableText.includes(normalizedFilter.value);
      });
  });

  const filteredOtherWorkflows = computed<QuickDrawerWorkflowViewModel[]>(() => {
    const pinnedIds = new Set(pinnedWorkflowIds.value);
    return workflows.value.filter((workflow) => {
      if (pinnedIds.has(workflow.id)) return false;
      if (!normalizedFilter.value) return true;
      return workflow.searchableText.includes(normalizedFilter.value);
    });
  });

  /** Reload preferences from localStorage (same tab + other tabs). */
  function syncPreferencesFromStorage(): void {
    if (typeof window === "undefined") return;

    try {
      const parsed = readStoredPreferences();
      if (!parsed) {
        pinnedWorkflowIds.value = [];
        lastSelectedWorkflowId.value = null;
        selectedWorkflowId.value = null;
      } else {
        if (Array.isArray(parsed.pinnedWorkflowIds)) {
          pinnedWorkflowIds.value = parsed.pinnedWorkflowIds.filter(
            (workflowId): workflowId is string => typeof workflowId === "string",
          );
        }
        if (
          parsed.lastSelectedWorkflowId === null ||
          typeof parsed.lastSelectedWorkflowId === "string"
        ) {
          lastSelectedWorkflowId.value = parsed.lastSelectedWorkflowId;
          selectedWorkflowId.value = parsed.lastSelectedWorkflowId;
        }
      }
      applyPinnedFlags();
      if (workflows.value.length > 0) {
        reconcileSelection();
      }
    } catch {
      pinnedWorkflowIds.value = [];
      lastSelectedWorkflowId.value = null;
      selectedWorkflowId.value = null;
    }
  }

  function hydratePreferences(): void {
    if (hydrated.value || typeof window === "undefined") return;

    syncPreferencesFromStorage();
    hydrated.value = true;
  }

  function savePreferences(): void {
    if (typeof window === "undefined") return;

    const preferences: QuickDrawerPreferences = {
      pinnedWorkflowIds: pinnedWorkflowIds.value,
      lastSelectedWorkflowId: lastSelectedWorkflowId.value,
    };

    try {
      window.localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(preferences));
    } catch {
      // Ignore storage failures so the drawer still works without persistence.
    }
  }

  function applyPinnedFlags(): void {
    const pinnedIds = new Set(pinnedWorkflowIds.value);
    workflows.value = workflows.value.map((workflow) => ({
      ...workflow,
      pinned: pinnedIds.has(workflow.id),
    }));
  }

  function ensureInputValues(workflowId: string): void {
    const workflow = workflows.value.find((item) => item.id === workflowId);
    if (!workflow) return;

    const existingValues = inputValuesByWorkflowId.value[workflowId] ?? {};
    const nextValues: Record<string, string> = {};

    for (const field of workflow.inputFields) {
      nextValues[field.key] = existingValues[field.key] ?? field.defaultValue ?? "";
    }

    inputValuesByWorkflowId.value = {
      ...inputValuesByWorkflowId.value,
      [workflowId]: nextValues,
    };
  }

  function clearRunState(): void {
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    runState.value = createEmptyRunState();
  }

  function reconcileSelection(): void {
    const availableIds = new Set(workflows.value.map((workflow) => workflow.id));
    const filteredPinnedIds = pinnedWorkflowIds.value.filter((workflowId) => availableIds.has(workflowId));

    if (filteredPinnedIds.length !== pinnedWorkflowIds.value.length) {
      pinnedWorkflowIds.value = filteredPinnedIds;
      savePreferences();
    }

    const nextInputValues: Record<string, Record<string, string>> = {};
    for (const workflowId of Object.keys(inputValuesByWorkflowId.value)) {
      if (availableIds.has(workflowId)) {
        nextInputValues[workflowId] = inputValuesByWorkflowId.value[workflowId];
      }
    }
    inputValuesByWorkflowId.value = nextInputValues;

    if (selectedWorkflowId.value && availableIds.has(selectedWorkflowId.value)) {
      ensureInputValues(selectedWorkflowId.value);
      return;
    }

    const firstPinnedWorkflowId = filteredPinnedIds[0] ?? null;
    const firstOtherWorkflowId =
      workflows.value.find((workflow) => !filteredPinnedIds.includes(workflow.id))?.id ?? null;

    const nextSelection =
      selectedWorkflowId.value === null &&
      lastSelectedWorkflowId.value &&
      availableIds.has(lastSelectedWorkflowId.value)
        ? lastSelectedWorkflowId.value
        : firstPinnedWorkflowId ?? firstOtherWorkflowId;

    selectedWorkflowId.value = nextSelection;
    lastSelectedWorkflowId.value = nextSelection;
    if (nextSelection) {
      ensureInputValues(nextSelection);
    }
    savePreferences();
  }

  async function ensureWorkflows(force = false): Promise<void> {
    hydratePreferences();

    const isCacheFresh =
      workflows.value.length > 0 && Date.now() - workflowsFetchedAt.value < WORKFLOW_CACHE_TTL_MS;
    if (!force && isCacheFresh) return;
    if (loadPromise) return loadPromise;

    loadPromise = (async () => {
      isLoadingWorkflows.value = true;
      workflowLoadError.value = null;

      try {
        const items = await workflowApi.listWithInputs();
        workflows.value = items.map(normalizeWorkflow);
        workflowsFetchedAt.value = Date.now();
        applyPinnedFlags();
        reconcileSelection();
      } catch (error) {
        workflowLoadError.value =
          error instanceof Error ? error.message : "Failed to load workflows";
        showToast("Failed to load quick workflows", "error");
      } finally {
        isLoadingWorkflows.value = false;
        loadPromise = null;
      }
    })();

    return loadPromise;
  }

  async function ensureWorkflowsIfStale(): Promise<void> {
    const isStale = Date.now() - workflowsFetchedAt.value >= WORKFLOW_CACHE_TTL_MS;
    await ensureWorkflows(isStale);
  }

  function openDrawer(): void {
    hydratePreferences();
    isDrawerOpen.value = true;
  }

  function closeDrawer(): void {
    isDrawerOpen.value = false;
    isDetailPanelOpen.value = false;
  }

  function toggleDrawer(): void {
    if (isDrawerOpen.value) {
      closeDrawer();
    } else {
      openDrawer();
    }
  }

  function selectWorkflow(workflowId: string, openDetail = true): void {
    hydratePreferences();
    if (selectedWorkflowId.value === workflowId) {
      ensureInputValues(workflowId);
      if (openDetail) {
        isDetailPanelOpen.value = true;
      }
      return;
    }

    selectedWorkflowId.value = workflowId;
    lastSelectedWorkflowId.value = workflowId;
    ensureInputValues(workflowId);
    savePreferences();
    clearRunState();
    isDetailPanelOpen.value = openDetail;
  }

  function closeDetailPanel(): void {
    isDetailPanelOpen.value = false;
  }

  function togglePin(workflowId: string): void {
    hydratePreferences();
    const isPinned = pinnedWorkflowIds.value.includes(workflowId);

    pinnedWorkflowIds.value = isPinned
      ? pinnedWorkflowIds.value.filter((id) => id !== workflowId)
      : [workflowId, ...pinnedWorkflowIds.value.filter((id) => id !== workflowId)];

    applyPinnedFlags();
    reconcileSelection();
    savePreferences();
  }

  function updateFilter(value: string): void {
    filterText.value = value;
  }

  function updateInputValue(key: string, value: string): void {
    if (!selectedWorkflowId.value) return;

    const workflowId = selectedWorkflowId.value;
    const currentValues = inputValuesByWorkflowId.value[workflowId] ?? {};
    inputValuesByWorkflowId.value = {
      ...inputValuesByWorkflowId.value,
      [workflowId]: {
        ...currentValues,
        [key]: value,
      },
    };
  }

  function buildSelectedInputs(): Record<string, string> {
    if (!selectedWorkflow.value) return {};

    const inputs: Record<string, string> = {};
    const values = inputValuesByWorkflowId.value[selectedWorkflow.value.id] ?? {};

    for (const field of selectedWorkflow.value.inputFields) {
      const value = values[field.key] ?? field.defaultValue ?? "";
      if (value !== "") {
        inputs[field.key] = value;
      }
    }

    return inputs;
  }

  /** Append each SSE node_complete; same node_id may appear multiple times (e.g. delegated sub-agents). */
  function appendStreamNodeResult(nodeResult: NodeResult): void {
    runState.value = {
      ...runState.value,
      nodeResults: [...runState.value.nodeResults, nodeResult],
    };
  }

  async function runSelectedWorkflow(): Promise<void> {
    if (!selectedWorkflow.value) return;

    clearRunState();
    const controller = new AbortController();
    abortController = controller;

    const workflow = selectedWorkflow.value;
    const inputs = buildSelectedInputs();

    runState.value = {
      ...createEmptyRunState(),
      status: "running",
      startedAt: Date.now(),
    };

    const nodeLabelsById = await loadNodeLabelMap(workflow.id);
    if (controller.signal.aborted || abortController !== controller) {
      return;
    }

    workflowApi.executeStream(
      workflow.id,
      inputs,
      (data) => {
        runState.value = {
          ...runState.value,
          executionId: data.execution_id,
        };
      },
      (_nodeId) => {},
      (data) => {
        appendStreamNodeResult({
          node_id: data.node_id,
          node_label: resolveNodeLabel(nodeLabelsById, data.node_id, data.node_label),
          node_type: data.node_type || "unknown",
          status: data.status as NodeResult["status"],
          output: data.output,
          execution_time_ms: data.execution_time_ms,
          error: data.error || null,
        });
      },
      (result) => {
        if (abortController === controller) {
          abortController = null;
        }
        const normalizedNodeResults = result.node_results.map((nodeResult) => ({
          ...nodeResult,
          node_label: resolveNodeLabel(nodeLabelsById, nodeResult.node_id, nodeResult.node_label),
        }));
        const normalizedOutputs = normalizeOutputs(
          result.outputs,
          normalizedNodeResults,
          nodeLabelsById,
        );

        runState.value = {
          status: result.status,
          executionId: null,
          outputs: normalizedOutputs,
          executionTimeMs: result.execution_time_ms,
          executionHistoryId: result.execution_history_id ?? null,
          errorMessage:
            result.status === "error"
              ? extractErrorMessage(normalizedOutputs) ?? "Workflow execution failed"
              : null,
          nodeResults: normalizedNodeResults,
          startedAt: runState.value.startedAt,
        };

        if (result.status === "success") {
          showToast(`Workflow "${workflow.name}" completed`, "success");
        } else if (result.status === "pending") {
          showToast(`Workflow "${workflow.name}" is pending review`, "info");
        }
      },
      (error: Error) => {
        if (controller.signal.aborted) return;
        if (abortController === controller) {
          abortController = null;
        }
        const errorMessage = error.message || "Workflow execution failed";
        runState.value = {
          ...runState.value,
          executionId: null,
          status: "error",
          errorMessage,
        };
        showToast(errorMessage, "error");
      },
      false,
      controller.signal,
      undefined,
      undefined,
      undefined,
      undefined,
      { triggerSource: "Quick Drawer" },
    );
  }

  async function stopSelectedWorkflowExecution(): Promise<void> {
    const workflowId = selectedWorkflow.value?.id;
    const executionId = runState.value.executionId;

    if (workflowId && executionId) {
      try {
        await workflowApi.cancelExecution(workflowId, executionId);
      } catch {
        // The execution may have already finished between the stop click and the request.
      }
    }

    if (abortController) {
      abortController.abort();
      abortController = null;
    }

    runState.value = createEmptyRunState();
    showToast("Workflow execution stopped", "info");
  }

  return {
    pinnedWorkflowIds,
    isDrawerOpen,
    workflows,
    filterText,
    isLoadingWorkflows,
    workflowLoadError,
    selectedWorkflowId,
    selectedWorkflow,
    currentInputValues,
    isDetailPanelOpen,
    filteredPinnedWorkflows,
    filteredOtherWorkflows,
    runState,
    ensureWorkflows,
    ensureWorkflowsIfStale,
    hydratePreferences,
    syncPreferencesFromStorage,
    openDrawer,
    closeDrawer,
    toggleDrawer,
    selectWorkflow,
    closeDetailPanel,
    togglePin,
    updateFilter,
    updateInputValue,
    runSelectedWorkflow,
    stopSelectedWorkflowExecution,
    clearRunState,
  };
});
