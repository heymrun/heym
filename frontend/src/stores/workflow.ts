import { computed, ref, shallowRef } from "vue";
import { defineStore } from "pinia";

import { buildLegacyWebhookBody, getHistoryWebhookBody, parseWebhookJson, stringifyWebhookJson } from "@/lib/webhookBody";
import { getLatestNodeResultForNode } from "@/lib/executionLog";
import { replaceNodeLabelRefs } from "@/lib/utils";
import { workflowApi } from "@/services/api";
import { useToast } from "@/composables/useToast";
import type {
  AgentProgressEntry,
  AllExecutionHistoryEntryLight,
  ExecutionHistoryEntry,
  ExecutionResult,
  LLMBatchProgressEntry,
  NodeResult,
  ServerExecutionHistory,
  Workflow,
  WorkflowEdge,
  WorkflowNode,
} from "@/types/workflow";

export interface ValidationError {
  nodeId: string;
  nodeLabel: string;
  nodeType: string;
  message: string;
}

export interface ValidationResult {
  isValid: boolean;
  errors: ValidationError[];
}

interface HistoryState {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

interface EvaluateLoopSelection {
  loopNodeId: string;
  iterationIndex: number;
}

export const useWorkflowStore = defineStore("workflow", () => {
  const currentWorkflow = ref<Workflow | null>(null);
  const nodes = ref<WorkflowNode[]>([]);
  const edges = ref<WorkflowEdge[]>([]);
  const selectedNodeId = ref<string | null>(null);
  const selectedNodeIds = ref<Set<string>>(new Set());
  const executionResult = ref<ExecutionResult | null>(null);
  const nodeResults = shallowRef<NodeResult[]>([]);
  const executionHistoryList = ref<AllExecutionHistoryEntryLight[]>([]);
  const executionHistoryDetails = ref<Map<string, ExecutionHistoryEntry>>(
    new Map(),
  );
  const executionHistoryTotal = ref(0);
  const isHistoryLoading = ref(false);
  const isHistoryDetailLoading = ref(false);
  const currentExecutionId = ref<string | null>(null);
  const isExecuting = ref(false);
  const isSaving = ref(false);
  const hasUnsavedChanges = ref(false);
  const runningNodeId = ref<string | null>(null);
  const propertiesPanelOpen = ref(false);
  /** When true, workflow canvas global key handlers and editor undo should stay inactive (agent memory graph modal). */
  const agentMemoryGraphDialogOpen = ref(false);
  const propertiesPanelTab = ref<"properties" | "config">("config");
  /** When true, WorkflowCanvas skips syncing Vue Flow selection into the store (prevents reverting programmatic picks). */
  const suppressVueFlowSelectionEcho = ref(false);
  const focusField = ref<string | null>(null);
  /** When set, PropertiesPanel shows this `node_results` row for the selected node (timeline span pick). */
  const timelinePickedNodeResultIndex = ref<number | null>(null);
  /** Persists evaluator loop item selection even when there is no matching canvas result row yet. */
  const evaluateLoopSelection = ref<EvaluateLoopSelection | null>(null);
  /** When true, the next `propertiesPanelOpen` pulse skips `openPrimaryExpandDialogForSelectedNode`. */
  const skipPrimaryExpandOnNextPropertiesOpen = ref(false);
  const abortController = ref<AbortController | null>(null);
  const debugPanelHeight = ref(192);
  const nodeSearchQuery = ref("");
  const runInputText = ref("");
  const runInputValues = ref<Record<string, string>>({});
  const runInputJson = ref("{}");
  const pendingHistoryInputs = ref<Record<string, unknown> | null>(null);
  const pendingHistoryNodeResults = ref<NodeResult[] | null>(null);
  const pendingHistoryExecutionResult = ref<ExecutionResult | null>(null);
  const pendingConnectionSource = ref<{
    nodeId: string;
    handleId: string | null;
  } | null>(null);

  const pendingInsertEdge = ref<{
    edgeId: string;
    sourceId: string;
    targetId: string;
    sourceHandle?: string;
    targetHandle?: string;
  } | null>(null);

  const agentProgressLogs = shallowRef<Map<string, AgentProgressEntry[]>>(
    new Map(),
  );
  const llmBatchProgressLogs = shallowRef<Map<string, LLMBatchProgressEntry[]>>(
    new Map(),
  );

  const allInputFields = computed(() => {
    const targetNodeIds = new Set(edges.value.map((edge) => edge.target));
    const startNodes = nodes.value.filter(
      (node) =>
        !targetNodeIds.has(node.id) &&
        node.type === "textInput" &&
        node.data.active !== false,
    );

    const fields: Array<{
      nodeLabel: string;
      key: string;
      defaultValue: string;
    }> = [];

    for (const node of startNodes) {
      const nodeFields = node.data.inputFields || [];
      for (const field of nodeFields) {
        fields.push({
          nodeLabel: node.data.label,
          key: field.key,
          defaultValue: field.defaultValue || "",
        });
      }
    }

    return fields;
  });

  const webhookBodyMode = computed(() => {
    return currentWorkflow.value?.webhook_body_mode || "legacy";
  });

  function buildLegacyExecutionBody(): Record<string, string> {
    return buildLegacyWebhookBody(
      allInputFields.value,
      runInputValues.value,
      runInputText.value,
    );
  }

  function resetRunInputJsonFromMode(): void {
    if (webhookBodyMode.value === "generic") {
      runInputJson.value = "{}";
      return;
    }

    runInputJson.value = stringifyWebhookJson(buildLegacyExecutionBody());
  }

  function buildExecutionRequestBody(): unknown {
    if (webhookBodyMode.value === "generic") {
      return parseWebhookJson(runInputJson.value).value;
    }

    return buildLegacyExecutionBody();
  }

  function loadHistoryInputs(
    inputs: Record<string, unknown>,
    historicalNodeResults?: NodeResult[],
    historicalExecutionResult?: ExecutionResult,
  ): void {
    const bodyInputs = getHistoryWebhookBody(inputs);
    if (webhookBodyMode.value === "generic") {
      runInputJson.value = stringifyWebhookJson(bodyInputs);
      Object.keys(runInputValues.value).forEach((key) => {
        delete runInputValues.value[key];
      });
      runInputText.value = "";
    } else {
      const fieldInputs =
        bodyInputs &&
        typeof bodyInputs === "object" &&
        !Array.isArray(bodyInputs)
          ? (bodyInputs as Record<string, unknown>)
          : {};

      const converted: Record<string, string> = {};
      for (const [key, value] of Object.entries(fieldInputs)) {
        if (typeof value === "string") {
          converted[key] = value;
        } else {
          converted[key] = JSON.stringify(value);
        }
      }

      Object.keys(runInputValues.value).forEach((key) => {
        delete runInputValues.value[key];
      });
      Object.assign(runInputValues.value, converted);
      runInputText.value = converted.text || "";
      runInputJson.value = stringifyWebhookJson(buildLegacyExecutionBody());
    }

    if (historicalExecutionResult) {
      executionResult.value = historicalExecutionResult;
      if (
        historicalExecutionResult.node_results &&
        historicalExecutionResult.node_results.length > 0
      ) {
        timelinePickedNodeResultIndex.value = null;
        nodeResults.value = historicalExecutionResult.node_results;
      }
    } else if (
      historicalNodeResults &&
      historicalNodeResults.length > 0 &&
      currentWorkflow.value
    ) {
      timelinePickedNodeResultIndex.value = null;
      nodeResults.value = historicalNodeResults;
      executionResult.value = {
        workflow_id: currentWorkflow.value.id,
        status: historicalNodeResults.some((r) => r.status === "error")
          ? "error"
          : "success",
        outputs: {},
        execution_time_ms: historicalNodeResults.reduce(
          (sum, r) => sum + r.execution_time_ms,
          0,
        ),
        node_results: historicalNodeResults,
      };
    } else if (historicalNodeResults && historicalNodeResults.length > 0) {
      timelinePickedNodeResultIndex.value = null;
      nodeResults.value = historicalNodeResults;
    }

    if (historicalExecutionResult || (historicalNodeResults && historicalNodeResults.length > 0)) {
      clearSelection();
    }

    pendingHistoryInputs.value = null;
    pendingHistoryNodeResults.value = null;
    pendingHistoryExecutionResult.value = null;
  }

  // Cache edges before node deletion for auto-reconnect
  const pendingNodeDeletion = ref<string | null>(null);
  const cachedEdgesForReconnect = ref<WorkflowEdge[]>([]);

  const { showToast } = useToast();

  // Clipboard for copy/paste (supports multiple nodes)
  const clipboardNode = ref<WorkflowNode | null>(null);
  const clipboardNodes = ref<WorkflowNode[]>([]);
  const clipboardEdges = ref<WorkflowEdge[]>([]);

  // Undo/Redo history
  const history = ref<HistoryState[]>([]);
  const historyIndex = ref(-1);
  const maxHistorySize = 50;
  const isUndoRedo = ref(false);

  const canUndo = computed(() => historyIndex.value > 0);
  const canRedo = computed(() => historyIndex.value < history.value.length - 1);

  function saveToHistory(): void {
    if (isUndoRedo.value) return;

    // Remove any future history if we're not at the end
    if (historyIndex.value < history.value.length - 1) {
      history.value = history.value.slice(0, historyIndex.value + 1);
    }

    // Deep clone current state
    const state: HistoryState = {
      nodes: JSON.parse(JSON.stringify(nodes.value)),
      edges: JSON.parse(JSON.stringify(edges.value)),
    };

    history.value.push(state);

    // Limit history size
    if (history.value.length > maxHistorySize) {
      history.value.shift();
    }

    historyIndex.value = history.value.length - 1;
  }

  function undo(): void {
    if (!canUndo.value) return;

    isUndoRedo.value = true;
    historyIndex.value--;
    const state = history.value[historyIndex.value];
    nodes.value = JSON.parse(JSON.stringify(state.nodes));
    edges.value = JSON.parse(JSON.stringify(state.edges));
    hasUnsavedChanges.value = true;
    isUndoRedo.value = false;
  }

  function redo(): void {
    if (!canRedo.value) return;

    isUndoRedo.value = true;
    historyIndex.value++;
    const state = history.value[historyIndex.value];
    nodes.value = JSON.parse(JSON.stringify(state.nodes));
    edges.value = JSON.parse(JSON.stringify(state.edges));
    hasUnsavedChanges.value = true;
    isUndoRedo.value = false;
  }

  const selectedNode = computed(() => {
    if (!selectedNodeId.value) return null;
    return nodes.value.find((n) => n.id === selectedNodeId.value) || null;
  });

  const selectedNodes = computed(() => {
    return nodes.value.filter((n) => selectedNodeIds.value.has(n.id));
  });

  function convertServerHistoryToEntry(
    h: ServerExecutionHistory,
  ): ExecutionHistoryEntry {
    return {
      id: h.id,
      started_at: h.started_at,
      inputs: h.inputs,
      status: h.status as "running" | "success" | "error" | "pending",
      result: {
        workflow_id: h.workflow_id,
        status: h.status as "success" | "error" | "pending",
        outputs: h.outputs,
        execution_time_ms: h.execution_time_ms,
        node_results: h.node_results || [],
        execution_history_id: h.id,
      },
    };
  }

  function upsertExecutionHistoryEntry(entry: ExecutionHistoryEntry): void {
    const nextDetails = new Map(executionHistoryDetails.value);
    nextDetails.set(entry.id, entry);
    executionHistoryDetails.value = nextDetails;

    const existingIndex = executionHistoryList.value.findIndex(
      (item) => item.id === entry.id,
    );
    if (existingIndex >= 0) {
      const nextList = [...executionHistoryList.value];
      const currentItem = nextList[existingIndex];
      nextList.splice(existingIndex, 1, {
        ...currentItem,
        workflow_id: entry.result?.workflow_id || currentItem.workflow_id,
        workflow_name:
          currentItem.workflow_name ||
          currentWorkflow.value?.name ||
          "Workflow",
        started_at: entry.started_at,
        status: entry.status,
        execution_time_ms: entry.result?.execution_time_ms || 0,
        trigger_source: entry.trigger_source ?? currentItem.trigger_source,
      });
      executionHistoryList.value = nextList;
      return;
    }

    if (executionHistoryList.value.length > 0 || executionHistoryTotal.value > 0) {
      executionHistoryList.value = [
        {
          id: entry.id,
          workflow_id: entry.result?.workflow_id || currentWorkflow.value?.id || null,
          workflow_name: currentWorkflow.value?.name || "Workflow",
          run_type: "workflow",
          started_at: entry.started_at,
          status: entry.status,
          execution_time_ms: entry.result?.execution_time_ms || 0,
          trigger_source: entry.trigger_source ?? null,
        },
        ...executionHistoryList.value,
      ];
      executionHistoryTotal.value += 1;
    }
  }

  async function fetchExecutionHistory(
    triggerSource?: string,
    {
      keepDetails = false,
      search,
    }: { keepDetails?: boolean; search?: string } = {},
  ): Promise<void> {
    if (!currentWorkflow.value) return;
    isHistoryLoading.value = true;
    try {
      const { total, items } = await workflowApi.getHistory(
        currentWorkflow.value.id,
        50,
        0,
        search,
        triggerSource,
      );
      executionHistoryList.value = items;
      executionHistoryTotal.value = total;
      if (!keepDetails) {
        executionHistoryDetails.value = new Map();
      }
    } catch {
      executionHistoryList.value = [];
      executionHistoryTotal.value = 0;
    } finally {
      isHistoryLoading.value = false;
    }
  }

  async function fetchExecutionHistoryEntry(
    entryId: string,
    force = false,
  ): Promise<ExecutionHistoryEntry | null> {
    if (!currentWorkflow.value) return null;
    const cached = !force ? executionHistoryDetails.value.get(entryId) : undefined;
    if (cached) return cached;
    isHistoryDetailLoading.value = true;
    try {
      const serverHistory = await workflowApi.getWorkflowHistoryEntry(
        currentWorkflow.value.id,
        entryId,
      );
      const entry = convertServerHistoryToEntry(serverHistory);
      upsertExecutionHistoryEntry(entry);
      return entry;
    } catch {
      return null;
    } finally {
      isHistoryDetailLoading.value = false;
    }
  }

  function applyExecutionResultSnapshot(
    result: ExecutionResult,
    options?: { preserveSelection?: boolean },
  ): void {
    executionResult.value = result;
    timelinePickedNodeResultIndex.value = null;
    nodeResults.value = result.node_results || [];
    clearNodeStatuses();

    const completedNodeIds = new Set(
      (result.node_results || []).map((nodeResult) => nodeResult.node_id),
    );

    for (const nodeResult of result.node_results || []) {
      setNodeStatus(
        nodeResult.node_id,
        nodeResult.status as "success" | "error" | "pending" | "skipped",
      );
    }

    for (const node of nodes.value) {
      if (!completedNodeIds.has(node.id)) {
        const currentStatus = node.data.status;
        if (currentStatus === "running" || currentStatus === "pending") {
          setNodeStatus(node.id, "skipped");
        }
      }
    }

    isExecuting.value = false;
    runningNodeId.value = null;
    abortController.value = null;
    currentExecutionId.value = result.execution_history_id || null;
    if (!options?.preserveSelection) {
      clearSelection();
    }
  }

  function applyExecutionHistoryEntry(entry: ExecutionHistoryEntry): void {
    if (!entry.result) return;
    upsertExecutionHistoryEntry(entry);
    applyExecutionResultSnapshot({
      ...entry.result,
      execution_history_id: entry.id,
    });
  }

  async function loadWorkflow(id: string): Promise<void> {
    const workflow = await workflowApi.get(id);
    currentWorkflow.value = workflow;
    nodes.value = workflow.nodes || [];
    edges.value = workflow.edges || [];
    resetRunInputJsonFromMode();
    hasUnsavedChanges.value = false;
    executionResult.value = null;
    timelinePickedNodeResultIndex.value = null;
    clearEvaluateLoopSelection();
    nodeResults.value = [];
    executionHistoryList.value = [];
    executionHistoryDetails.value = new Map();
    executionHistoryTotal.value = 0;
    currentExecutionId.value = null;
    clearNodeStatuses();

    history.value = [
      {
        nodes: JSON.parse(JSON.stringify(nodes.value)),
        edges: JSON.parse(JSON.stringify(edges.value)),
      },
    ];
    historyIndex.value = 0;
  }

  async function saveWorkflow(): Promise<void> {
    if (!currentWorkflow.value) return;

    isSaving.value = true;
    try {
      await workflowApi.update(currentWorkflow.value.id, {
        nodes: nodes.value,
        edges: edges.value,
      });
      hasUnsavedChanges.value = false;
    } finally {
      isSaving.value = false;
    }
  }

  function generateUniqueNodeLabel(baseLabel: string): string {
    const existingLabels = new Set(nodes.value.map((n) => n.data.label));

    if (!existingLabels.has(baseLabel)) {
      return baseLabel;
    }

    const baseName = baseLabel.replace(/\d+$/, "");
    let counter = 1;
    let newLabel = `${baseName}${counter}`;

    while (existingLabels.has(newLabel)) {
      counter++;
      newLabel = `${baseName}${counter}`;
    }

    return newLabel;
  }

  function addNode(node: WorkflowNode): void {
    saveToHistory();
    const uniqueLabel = generateUniqueNodeLabel(node.data.label);
    node.data = { ...node.data, label: uniqueLabel };
    nodes.value.push(node);
    hasUnsavedChanges.value = true;
  }

  function isAgentOrchestrator(nodeId: string): boolean {
    const node = nodes.value.find((n) => n.id === nodeId);
    if (!node) return false;
    return node.type === "agent" && node.data?.isOrchestrator === true;
  }

  function isEdgeAllowed(edge: WorkflowEdge): boolean {
    const sourceNode = nodes.value.find((n) => n.id === edge.source);
    const targetNode = nodes.value.find((n) => n.id === edge.target);
    if (!sourceNode || !targetNode) return true;

    const isAgentToAgent = sourceNode.type === "agent" && targetNode.type === "agent";
    if (isAgentToAgent && !isAgentOrchestrator(sourceNode.id)) {
      return false;
    }

    return true;
  }

  function updateNode(id: string, data: Partial<WorkflowNode["data"]>): void {
    const node = nodes.value.find((n) => n.id === id);
    if (node) {
      saveToHistory();
      node.data = { ...node.data, ...data };
      hasUnsavedChanges.value = true;
    }
  }

  function canTogglePin(nodeId: string): boolean {
    const node = nodes.value.find((n) => n.id === nodeId);
    if (!node) return false;
    if (node.data.pinnedData) return true;
    const result = getLatestNodeResultForNode(nodeResults.value, nodeId);
    return !!result;
  }

  function togglePinnedData(nodeId: string): void {
    const node = nodes.value.find((n) => n.id === nodeId);
    if (!node) return;

    if (node.data.pinnedData) {
      updateNode(nodeId, { pinnedData: null });
      return;
    }

    const result = getLatestNodeResultForNode(nodeResults.value, nodeId);
    if (!result) return;

    updateNode(nodeId, { pinnedData: result.output });
  }

  function toggleNodeActive(id: string): void {
    const node = nodes.value.find((n) => n.id === id);
    if (node) {
      saveToHistory();
      const currentActive = node.data.active !== false;
      node.data = { ...node.data, active: !currentActive };
      hasUnsavedChanges.value = true;
    }
  }

  function toggleSelectedNodesActive(): void {
    if (selectedNodeIds.value.size === 0) return;

    saveToHistory();

    const selectedNodes = nodes.value.filter((n) =>
      selectedNodeIds.value.has(n.id),
    );

    const allActive = selectedNodes.every((n) => n.data.active !== false);
    const newActiveState = !allActive;

    for (const node of selectedNodes) {
      node.data = { ...node.data, active: newActiveState };
    }

    hasUnsavedChanges.value = true;
  }

  function prepareNodeDeletion(id: string): void {
    pendingNodeDeletion.value = id;
    cachedEdgesForReconnect.value = edges.value.filter(
      (e) => e.source === id || e.target === id,
    );
  }

  function removeNode(id: string): void {
    saveToHistory();

    const edgesToUse =
      pendingNodeDeletion.value === id &&
      cachedEdgesForReconnect.value.length > 0
        ? cachedEdgesForReconnect.value
        : edges.value.filter((e) => e.source === id || e.target === id);

    const incomingEdges = edgesToUse.filter((e) => e.target === id);
    const outgoingEdges = edgesToUse.filter((e) => e.source === id);

    // Auto-reconnect: connect each source to each target
    const newEdges: WorkflowEdge[] = [];
    incomingEdges.forEach((incoming) => {
      outgoingEdges.forEach((outgoing) => {
        // Check if this connection already exists
        const exists = edges.value.some(
          (e) => e.source === incoming.source && e.target === outgoing.target,
        );
        const alreadyInNew = newEdges.some(
          (e) => e.source === incoming.source && e.target === outgoing.target,
        );
        if (!exists && !alreadyInNew) {
          const candidate: WorkflowEdge = {
            id: `edge_${incoming.source}_${outgoing.target}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
            source: incoming.source,
            target: outgoing.target,
            sourceHandle: incoming.sourceHandle,
            targetHandle: outgoing.targetHandle,
          };
          if (isEdgeAllowed(candidate)) {
            newEdges.push(candidate);
          }
        }
      });
    });

    nodes.value = nodes.value.filter((n) => n.id !== id);
    edges.value = edges.value.filter((e) => e.source !== id && e.target !== id);
    edges.value.push(...newEdges);

    if (pendingNodeDeletion.value === id) {
      pendingNodeDeletion.value = null;
      cachedEdgesForReconnect.value = [];
    }

    if (selectedNodeId.value === id) {
      selectedNodeId.value = null;
    }
    hasUnsavedChanges.value = true;
  }

  function addEdge(edge: WorkflowEdge): void {
    if (!isEdgeAllowed(edge)) return;
    const exists = edges.value.some(
      (e) => e.source === edge.source && e.target === edge.target,
    );
    if (!exists) {
      saveToHistory();
      edges.value.push(edge);
      hasUnsavedChanges.value = true;
    }
  }

  function removeEdge(id: string): void {
    saveToHistory();
    edges.value = edges.value.filter((e) => e.id !== id);
    hasUnsavedChanges.value = true;
  }

  function applyClipboardData(nodesToCopy: WorkflowNode[], edgesToCopy: WorkflowEdge[]): void {
    clipboardNodes.value = JSON.parse(JSON.stringify(nodesToCopy));
    clipboardEdges.value = JSON.parse(JSON.stringify(edgesToCopy));
    clipboardNode.value = nodesToCopy.length === 1 ? clipboardNodes.value[0] : null;
    const count = nodesToCopy.length;
    const label = count === 1 ? nodesToCopy[0].data.label || "node" : `${count} nodes`;
    void navigator.clipboard
      .writeText(JSON.stringify({ heym: true, nodes: clipboardNodes.value, edges: clipboardEdges.value }))
      .catch(() => undefined);
    showToast(`Copied ${label}`, "success", 2000);
  }

  function copyNode(): void {
    if (selectedNodeIds.value.size > 1) {
      const nodesToCopy = nodes.value.filter((n) => selectedNodeIds.value.has(n.id));
      const nodeIdSet = new Set(nodesToCopy.map((n) => n.id));
      const edgesToCopy = edges.value.filter((e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target));
      applyClipboardData(nodesToCopy, edgesToCopy);
      return;
    }
    if (!selectedNodeId.value) return;
    const node = nodes.value.find((n) => n.id === selectedNodeId.value);
    if (node) applyClipboardData([node], []);
  }

  function cutNode(): void {
    if (selectedNodeIds.value.size > 1) {
      copyNode();
      removeSelectedNodes();
      return;
    }
    if (!selectedNodeId.value) return;
    const node = nodes.value.find((n) => n.id === selectedNodeId.value);
    if (!node) return;
    applyClipboardData([node], []);
    removeNode(selectedNodeId.value);
  }

  async function pasteNode(): Promise<void> {
    try {
      const text = await navigator.clipboard.readText();
      const parsed = JSON.parse(text) as { heym?: boolean; nodes: WorkflowNode[]; edges: WorkflowEdge[] };
      if (parsed.heym && Array.isArray(parsed.nodes)) {
        clipboardNodes.value = parsed.nodes;
        clipboardEdges.value = parsed.edges || [];
        clipboardNode.value = parsed.nodes.length === 1 ? parsed.nodes[0] : null;
      }
    } catch {
      // clipboard read failed or non-heym content — use in-memory clipboard
    }

    if (clipboardNodes.value.length > 1) {
      pasteMultipleNodes();
      return;
    }

    if (!clipboardNode.value && clipboardNodes.value.length === 1) {
      clipboardNode.value = clipboardNodes.value[0];
    }

    if (!clipboardNode.value) return;

    const newNode: WorkflowNode = {
      id: `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      type: clipboardNode.value.type,
      position: {
        x: clipboardNode.value.position.x + 50,
        y: clipboardNode.value.position.y + 50,
      },
      data: { ...clipboardNode.value.data },
    };

    addNode(newNode);
    selectNode(newNode.id);
  }

  function pasteMultipleNodes(): void {
    if (clipboardNodes.value.length === 0) return;

    saveToHistory();

    const oldToNewIdMap = new Map<string, string>();
    const newNodes: WorkflowNode[] = [];

    for (const node of clipboardNodes.value) {
      const newId = `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      oldToNewIdMap.set(node.id, newId);

      const uniqueLabel = generateUniqueNodeLabel(node.data.label);
      const newNode: WorkflowNode = {
        id: newId,
        type: node.type,
        position: {
          x: node.position.x + 50,
          y: node.position.y + 50,
        },
        data: { ...node.data, label: uniqueLabel },
      };
      newNodes.push(newNode);
      nodes.value.push(newNode);
    }

    for (const edge of clipboardEdges.value) {
      const newSourceId = oldToNewIdMap.get(edge.source);
      const newTargetId = oldToNewIdMap.get(edge.target);
      if (newSourceId && newTargetId) {
        const newEdge: WorkflowEdge = {
          id: `edge_${newSourceId}_${newTargetId}_${Date.now()}`,
          source: newSourceId,
          target: newTargetId,
          sourceHandle: edge.sourceHandle,
          targetHandle: edge.targetHandle,
        };
        if (isEdgeAllowed(newEdge)) {
          edges.value.push(newEdge);
        }
      }
    }

    hasUnsavedChanges.value = true;
    selectNodes(newNodes.map((n) => n.id));
  }

  function selectNode(id: string | null): void {
    timelinePickedNodeResultIndex.value = null;
    selectedNodeId.value = id;
    if (id) {
      selectedNodeIds.value = new Set([id]);
    } else {
      selectedNodeIds.value = new Set();
    }
  }

  function selectNodes(ids: string[]): void {
    timelinePickedNodeResultIndex.value = null;
    selectedNodeIds.value = new Set(ids);
    selectedNodeId.value = ids.length > 0 ? ids[ids.length - 1] : null;
  }

  function setTimelinePickedNodeResultIndex(index: number | null): void {
    timelinePickedNodeResultIndex.value = index;
  }

  function setEvaluateLoopSelection(
    selection: EvaluateLoopSelection | null,
  ): void {
    evaluateLoopSelection.value = selection;
  }

  function clearEvaluateLoopSelection(): void {
    evaluateLoopSelection.value = null;
  }

  function setSuppressVueFlowSelectionEcho(value: boolean): void {
    suppressVueFlowSelectionEcho.value = value;
  }

  /** Registered by PropertiesPanel so Evaluate dialog graph Prev/Next can switch nodes reliably. */
  let expressionGraphNavigateHandler: ((payload: { targetNodeId: string }) => void) | null = null;

  function setExpressionGraphNavigateHandler(
    handler: ((payload: { targetNodeId: string }) => void) | null,
  ): void {
    expressionGraphNavigateHandler = handler;
  }

  function runExpressionGraphNavigate(payload: { targetNodeId: string }): void {
    expressionGraphNavigateHandler?.(payload);
  }

  /** Evaluate-dialog graph navigation landed on a node with no ExpressionInput fields (e.g. merge, textInput). */
  const expressionEvaluateFallbackOpen = ref(false);
  const expressionEvaluateFallbackNodeId = ref<string | null>(null);

  function openExpressionEvaluateFallbackDialog(nodeId: string): void {
    expressionEvaluateFallbackNodeId.value = nodeId;
    expressionEvaluateFallbackOpen.value = true;
  }

  function closeExpressionEvaluateFallbackDialog(): void {
    expressionEvaluateFallbackOpen.value = false;
    expressionEvaluateFallbackNodeId.value = null;
  }

  function addToSelection(id: string): void {
    timelinePickedNodeResultIndex.value = null;
    const newSet = new Set(selectedNodeIds.value);
    newSet.add(id);
    selectedNodeIds.value = newSet;
    selectedNodeId.value = id;
  }

  function removeFromSelection(id: string): void {
    timelinePickedNodeResultIndex.value = null;
    const newSet = new Set(selectedNodeIds.value);
    newSet.delete(id);
    selectedNodeIds.value = newSet;
    if (selectedNodeId.value === id) {
      const remaining = Array.from(newSet);
      selectedNodeId.value =
        remaining.length > 0 ? remaining[remaining.length - 1] : null;
    }
  }

  function toggleNodeSelection(id: string): void {
    if (selectedNodeIds.value.has(id)) {
      removeFromSelection(id);
    } else {
      addToSelection(id);
    }
  }

  function selectAllNodes(): void {
    const allIds = nodes.value.map((n) => n.id);
    selectNodes(allIds);
  }

  function clearSelection(): void {
    selectedNodeIds.value = new Set();
    selectedNodeId.value = null;
    timelinePickedNodeResultIndex.value = null;
    clearEvaluateLoopSelection();
  }

  function isNodeSelected(id: string): boolean {
    return selectedNodeIds.value.has(id);
  }

  function removeSelectedNodes(): void {
    if (selectedNodeIds.value.size === 0) return;

    saveToHistory();
    const idsToRemove = Array.from(selectedNodeIds.value);

    for (const id of idsToRemove) {
      const edgesToUse = edges.value.filter(
        (e) => e.source === id || e.target === id,
      );
      const incomingEdges = edgesToUse.filter((e) => e.target === id);
      const outgoingEdges = edgesToUse.filter((e) => e.source === id);

      const newEdges: WorkflowEdge[] = [];
      incomingEdges.forEach((incoming) => {
        if (idsToRemove.includes(incoming.source)) return;
        outgoingEdges.forEach((outgoing) => {
          if (idsToRemove.includes(outgoing.target)) return;
          const exists = edges.value.some(
            (e) => e.source === incoming.source && e.target === outgoing.target,
          );
          const alreadyInNew = newEdges.some(
            (e) => e.source === incoming.source && e.target === outgoing.target,
          );
          if (!exists && !alreadyInNew) {
            const candidate: WorkflowEdge = {
              id: `edge_${incoming.source}_${outgoing.target}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
              source: incoming.source,
              target: outgoing.target,
              sourceHandle: incoming.sourceHandle,
              targetHandle: outgoing.targetHandle,
            };
            if (isEdgeAllowed(candidate)) {
              newEdges.push(candidate);
            }
          }
        });
      });

      nodes.value = nodes.value.filter((n) => n.id !== id);
      edges.value = edges.value.filter(
        (e) => e.source !== id && e.target !== id,
      );
      edges.value.push(...newEdges);
    }

    clearSelection();
    hasUnsavedChanges.value = true;
  }

  function updateNodePosition(
    id: string,
    position: { x: number; y: number },
  ): void {
    const node = nodes.value.find((n) => n.id === id);
    if (node) {
      node.position = position;
      hasUnsavedChanges.value = true;
    }
  }

  function setNodeStatus(
    id: string,
    status: "pending" | "running" | "success" | "error" | "skipped",
  ): void {
    const node = nodes.value.find((n) => n.id === id);
    if (node) {
      node.data = { ...node.data, status };
    }
    if (status === "running") {
      runningNodeId.value = id;
    }
  }

  function clearNodeStatuses(): void {
    nodes.value.forEach((node) => {
      if (
        node.data.status
        || node.data.batchRuntimeStatus
        || node.data.batchRuntimeRawStatus
        || node.data.batchRuntimeRequestCounts
      ) {
        node.data = {
          ...node.data,
          status: undefined,
          batchRuntimeStatus: undefined,
          batchRuntimeRawStatus: undefined,
          batchRuntimeRequestCounts: undefined,
        };
      }
    });
    runningNodeId.value = null;
  }

  async function executeWorkflow(
    body: unknown,
  ): Promise<void> {
    const wf = currentWorkflow.value;
    if (!wf) return;

    isExecuting.value = true;
    executionResult.value = null;
    timelinePickedNodeResultIndex.value = null;
    clearEvaluateLoopSelection();
    nodeResults.value = [];
    agentProgressLogs.value = new Map();
    llmBatchProgressLogs.value = new Map();
    clearNodeStatuses();

    abortController.value = new AbortController();
    const streamAbort = abortController.value;
    currentExecutionId.value = null;

    try {
      if (hasUnsavedChanges.value) {
        await saveWorkflow();
      }

      nodes.value.forEach((node) => {
        setNodeStatus(node.id, "pending");
      });

      let receivedFinalOutput = false;

      await new Promise<void>((resolve, reject) => {
        let settled = false;
        const settle = (fn: () => void): void => {
          if (settled) {
            return;
          }
          settled = true;
          fn();
        };

        workflowApi.executeStream(
          wf.id,
          body,
          (data) => {
            currentExecutionId.value = data.execution_id;
          },
          (nodeId) => {
            setNodeStatus(nodeId, "running");
          },
          (data) => {
            setNodeStatus(
              data.node_id,
              data.status as "success" | "error" | "pending" | "skipped",
            );

            const completedNode = nodes.value.find((n) => n.id === data.node_id);
            if (completedNode && completedNode.data.retryAttempt) {
              completedNode.data = {
                ...completedNode.data,
                retryAttempt: undefined,
              };
            }

            const row: NodeResult = {
              node_id: data.node_id,
              node_label: data.node_label || data.node_id,
              node_type: data.node_type || "unknown",
              status: data.status as "success" | "error" | "pending" | "skipped",
              output: data.output,
              execution_time_ms: data.execution_time_ms,
              error: data.error ?? null,
            };
            if (data.metadata && typeof data.metadata === "object") {
              row.metadata = data.metadata;
            }
            nodeResults.value = [...nodeResults.value, row];

            if (
              data.node_type === "disableNode" &&
              data.status === "success" &&
              data.output?.targetNode
            ) {
              const targetNode = nodes.value.find(
                (n) => n.data.label === data.output.targetNode,
              );
              if (targetNode) {
                targetNode.data = { ...targetNode.data, active: false };
              }
            }
          },
          (result) => {
            const finalRows = (result.node_results || []) as NodeResult[];
            timelinePickedNodeResultIndex.value = null;
            nodeResults.value = finalRows;

            if (receivedFinalOutput) {
              executionResult.value = {
                ...result,
                node_results: finalRows,
                status: executionResult.value?.status || result.status,
                outputs: executionResult.value?.outputs || result.outputs,
              };
            } else {
              executionResult.value = {
                ...result,
                node_results: finalRows,
              };
            }

            const completedNodeIds = new Set(finalRows.map((r) => r.node_id));
            for (const nodeResult of finalRows) {
              setNodeStatus(
                nodeResult.node_id,
                nodeResult.status as "success" | "error" | "pending" | "skipped",
              );
            }
            for (const node of nodes.value) {
              if (!completedNodeIds.has(node.id)) {
                const currentStatus = node.data.status;
                if (currentStatus === "running" || currentStatus === "pending") {
                  setNodeStatus(node.id, "skipped");
                }
              }
            }

            isExecuting.value = false;
            runningNodeId.value = null;
            abortController.value = null;
            currentExecutionId.value = result.execution_history_id || null;
            settle(() => resolve());
          },
          (error: Error) => {
            clearNodeStatuses();
            isExecuting.value = false;
            runningNodeId.value = null;
            abortController.value = null;
            currentExecutionId.value = null;
            settle(() => reject(error));
          },
          true,
          streamAbort.signal,
        (data) => {
          receivedFinalOutput = true;
          const mapperNode = nodes.value.find((n) => n.id === data.node_id);
          const unwrappedJsonMapper =
            (data.node_type === "jsonOutputMapper" || mapperNode?.type === "jsonOutputMapper")
            && data.output !== null
            && typeof data.output === "object"
            && !Array.isArray(data.output);
          const outputs: Record<string, unknown> = unwrappedJsonMapper
            ? { ...(data.output as Record<string, unknown>) }
            : { [data.node_label]: data.output };
          executionResult.value = {
            workflow_id: currentWorkflow.value?.id || "",
            status: "success",
            outputs,
            execution_time_ms: data.execution_time_ms,
            node_results: nodeResults.value,
          };
        },
        (data) => {
          const node = nodes.value.find((n) => n.id === data.node_id);
          if (node) {
            node.data = {
              ...node.data,
              retryAttempt: data.attempt,
            };
          }

          const retryResult = data.retry_result;
          if (!retryResult || typeof retryResult !== "object") {
            return;
          }

          const row: NodeResult = {
            node_id: retryResult.node_id,
            node_label: retryResult.node_label || retryResult.node_id,
            node_type: retryResult.node_type || "unknown",
            status: retryResult.status as "success" | "error" | "pending" | "skipped",
            output: retryResult.output,
            execution_time_ms: retryResult.execution_time_ms,
            error: retryResult.error ?? null,
          };
          if (retryResult.metadata && typeof retryResult.metadata === "object") {
            row.metadata = retryResult.metadata;
          }
          nodeResults.value = [...nodeResults.value, row];
        },
        (data) => {
          const m = new Map(agentProgressLogs.value);
          const arr = m.get(data.node_id) ?? [];
          const entry = data.entry;
          const toolCallId = (entry as any)?.tool_call_id as string | null | undefined;
          const phase = (entry as any)?.phase as string | undefined;
          if (toolCallId && phase && phase !== "start") {
            const idx = [...arr]
              .map((e) => (e as any)?.tool_call_id as string | null | undefined)
              .lastIndexOf(toolCallId);
            if (idx >= 0) {
              const next = [...arr];
              next[idx] = { ...(next[idx] as any), ...(entry as any) };
              m.set(data.node_id, next);
              agentProgressLogs.value = m;
              return;
            }
          }
          arr.push(entry);
          m.set(data.node_id, arr);
          agentProgressLogs.value = m;
        },
        (data) => {
          const m = new Map(llmBatchProgressLogs.value);
          const arr = m.get(data.node_id) ?? [];
          arr.push(data.entry);
          m.set(data.node_id, arr);
          llmBatchProgressLogs.value = m;

          const node = nodes.value.find((n) => n.id === data.node_id);
          if (node) {
            node.data = {
              ...node.data,
              batchRuntimeStatus: data.entry.status,
              batchRuntimeRawStatus: data.entry.rawStatus,
              batchRuntimeRequestCounts: data.entry.requestCounts,
            };
          }
        },
        {
          bodyMode: wf.webhook_body_mode,
          triggerSource: "Canvas",
        },
      );
      });
    } catch (e: unknown) {
      clearNodeStatuses();
      isExecuting.value = false;
      runningNodeId.value = null;
      abortController.value = null;
      currentExecutionId.value = null;
      throw e;
    }
  }

  async function stopExecution(): Promise<void> {
    const workflowId = currentWorkflow.value?.id;
    const executionId = currentExecutionId.value;
    if (workflowId && executionId) {
      try {
        await workflowApi.cancelExecution(workflowId, executionId);
      } catch {
        // Ignore already-finished or not-yet-registered executions.
      }
    }
    if (abortController.value) {
      abortController.value.abort();
      abortController.value = null;
    }
    isExecuting.value = false;
    runningNodeId.value = null;
    clearNodeStatuses();
    currentExecutionId.value = null;
  }

  function clearWorkflow(): void {
    currentWorkflow.value = null;
    nodes.value = [];
    edges.value = [];
    selectedNodeId.value = null;
    runInputJson.value = "{}";
    executionResult.value = null;
    clearEvaluateLoopSelection();
    executionHistoryList.value = [];
    executionHistoryDetails.value = new Map();
    executionHistoryTotal.value = 0;
    currentExecutionId.value = null;
    hasUnsavedChanges.value = false;
  }

  function clearExecution(): void {
    executionResult.value = null;
    timelinePickedNodeResultIndex.value = null;
    nodeResults.value = [];
    agentProgressLogs.value = new Map();
    llmBatchProgressLogs.value = new Map();
    clearNodeStatuses();
  }

  function clearCanvas(): void {
    if (nodes.value.length === 0 && edges.value.length === 0) return;
    saveToHistory();
    nodes.value = [];
    edges.value = [];
    selectedNodeId.value = null;
    clearEvaluateLoopSelection();
    hasUnsavedChanges.value = true;
  }

  async function clearExecutionHistory(): Promise<void> {
    if (!currentWorkflow.value) return;
    try {
      await workflowApi.clearHistory(currentWorkflow.value.id);
      executionHistoryList.value = [];
      executionHistoryDetails.value = new Map();
      executionHistoryTotal.value = 0;
    } catch {
      executionHistoryList.value = [];
      executionHistoryDetails.value = new Map();
      executionHistoryTotal.value = 0;
    }
  }

  function openPropertiesPanel(
    fieldToFocus?: string,
    options?: { skipPrimaryExpand?: boolean },
  ): void {
    skipPrimaryExpandOnNextPropertiesOpen.value = options?.skipPrimaryExpand ?? false;
    propertiesPanelOpen.value = true;
    focusField.value = fieldToFocus || null;
  }

  function clearSkipPrimaryExpandOnNextPropertiesOpen(): void {
    skipPrimaryExpandOnNextPropertiesOpen.value = false;
  }

  function clearFocusField(): void {
    focusField.value = null;
  }

  function setDebugPanelHeight(height: number): void {
    debugPanelHeight.value = height;
  }

  function setNodeSearchQuery(query: string): void {
    nodeSearchQuery.value = query;
  }

  function clearNodeSearchQuery(): void {
    nodeSearchQuery.value = "";
  }

  function setPendingConnectionSource(
    source: { nodeId: string; handleId: string | null } | null,
  ): void {
    pendingConnectionSource.value = source;
  }

  function clearPendingConnectionSource(): void {
    pendingConnectionSource.value = null;
  }

  function setPendingInsertEdge(
    edge: {
      edgeId: string;
      sourceId: string;
      targetId: string;
      sourceHandle?: string;
      targetHandle?: string;
    } | null,
  ): void {
    pendingInsertEdge.value = edge;
  }

  function clearPendingInsertEdge(): void {
    pendingInsertEdge.value = null;
  }

  function insertNodeBetween(newNode: WorkflowNode): void {
    if (!pendingInsertEdge.value) return;

    const { edgeId, sourceId, targetId, sourceHandle, targetHandle } =
      pendingInsertEdge.value;

    saveToHistory();

    const sourceNode = nodes.value.find((n) => n.id === sourceId);
    const targetNode = nodes.value.find((n) => n.id === targetId);

    if (sourceNode && targetNode) {
      newNode.position = {
        x: (sourceNode.position.x + targetNode.position.x) / 2,
        y: (sourceNode.position.y + targetNode.position.y) / 2,
      };
    }

    const uniqueLabel = generateUniqueNodeLabel(newNode.data.label);
    newNode.data = { ...newNode.data, label: uniqueLabel };
    nodes.value.push(newNode);

    edges.value = edges.value.filter((e) => e.id !== edgeId);

    const timestamp = Date.now();
    const edge1: WorkflowEdge = {
      id: `edge_${sourceId}_${newNode.id}_${timestamp}`,
      source: sourceId,
      target: newNode.id,
      sourceHandle: sourceHandle,
      targetHandle: "input",
    };

    const edge2: WorkflowEdge = {
      id: `edge_${newNode.id}_${targetId}_${timestamp + 1}`,
      source: newNode.id,
      target: targetId,
      sourceHandle: undefined,
      targetHandle: targetHandle,
    };

    if (isEdgeAllowed(edge1)) edges.value.push(edge1);
    if (isEdgeAllowed(edge2)) edges.value.push(edge2);

    pendingInsertEdge.value = null;
    hasUnsavedChanges.value = true;
  }

  const shouldTidyUp = ref(false);

  function requestTidyUp(): void {
    shouldTidyUp.value = true;
  }

  function clearTidyUp(): void {
    shouldTidyUp.value = false;
  }

  function isValidUUID(value: string | undefined): boolean {
    if (!value) return false;
    const uuidRegex =
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    return uuidRegex.test(value);
  }

  function isValidJsonObjectLike(value: string | undefined): boolean {
    const trimmed = (value || "").trim();
    if (!trimmed) {
      return true;
    }
    if (trimmed.startsWith("$")) {
      return true;
    }
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      return !!parsed && typeof parsed === "object" && !Array.isArray(parsed);
    } catch {
      return false;
    }
  }

  function getLoopBranchNodes(loopNodeId: string): Set<string> {
    const loopBranchNodes = new Set<string>();
    const forwardEdges = edges.value.filter((e) => e.targetHandle !== "loop");
    const loopOutEdges = forwardEdges.filter(
      (e) => e.source === loopNodeId && e.sourceHandle === "loop",
    );
    const toVisit = loopOutEdges.map((e) => e.target);

    while (toVisit.length > 0) {
      const nodeId = toVisit.shift()!;
      if (loopBranchNodes.has(nodeId) || nodeId === loopNodeId) continue;
      loopBranchNodes.add(nodeId);

      const childEdges = forwardEdges.filter((e) => e.source === nodeId);
      childEdges.forEach((e) => {
        if (!loopBranchNodes.has(e.target) && e.target !== loopNodeId) {
          toVisit.push(e.target);
        }
      });
    }

    return loopBranchNodes;
  }

  function validateWorkflow(): ValidationResult {
    const errors: ValidationError[] = [];

    const loopNodes = nodes.value.filter((n) => n.type === "loop");
    const allLoopBranchNodes = new Set<string>();

    for (const loopNode of loopNodes) {
      const branchNodes = getLoopBranchNodes(loopNode.id);
      branchNodes.forEach((id) => allLoopBranchNodes.add(id));
    }

    for (const node of nodes.value) {
      if (node.data.active === false) continue;

      if (
        (node.type === "output" || node.type === "jsonOutputMapper")
        && allLoopBranchNodes.has(node.id)
      ) {
        errors.push({
          nodeId: node.id,
          nodeLabel: node.data.label,
          nodeType: node.type === "jsonOutputMapper" ? "JSON output mapper" : "Output",
          message:
            "Output and JSON output mapper nodes cannot be used inside loop branches. Use a Set node instead, or connect to the loop's 'done' branch.",
        });
      }

      if (node.type === "llm") {
        if (!node.data.credentialId || !isValidUUID(node.data.credentialId)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "LLM",
            message: "Credential is not selected",
          });
        }
        if (!node.data.model || node.data.model.trim() === "") {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "LLM",
            message: "Model is not selected",
          });
        }
        if (node.data.batchModeEnabled && node.data.outputType === "image") {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "LLM",
            message: "Batch mode works only with text output.",
          });
        }
        if (node.data.batchModeEnabled && node.data.imageInputEnabled) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "LLM",
            message: "Batch mode does not support image input.",
          });
        }
        if (node.data.guardrailsEnabled) {
          if (
            !node.data.guardrailCredentialId ||
            !isValidUUID(node.data.guardrailCredentialId)
          ) {
            errors.push({
              nodeId: node.id,
              nodeLabel: node.data.label,
              nodeType: "LLM",
              message:
                "Guardrails are enabled. Please select a Guardrail Credential.",
            });
          }
          if (
            !node.data.guardrailModel ||
            node.data.guardrailModel.trim() === ""
          ) {
            errors.push({
              nodeId: node.id,
              nodeLabel: node.data.label,
              nodeType: "LLM",
              message:
                "Guardrails are enabled. Please select a Guardrail Model.",
            });
          }
        }
      }

      if (node.type === "agent") {
        if (node.data.guardrailsEnabled) {
          if (
            !node.data.guardrailCredentialId ||
            !isValidUUID(node.data.guardrailCredentialId)
          ) {
            errors.push({
              nodeId: node.id,
              nodeLabel: node.data.label,
              nodeType: "AI Agent",
              message:
                "Guardrails are enabled. Please select a Guardrail Credential.",
            });
          }
          if (
            !node.data.guardrailModel ||
            node.data.guardrailModel.trim() === ""
          ) {
            errors.push({
              nodeId: node.id,
              nodeLabel: node.data.label,
              nodeType: "AI Agent",
              message:
                "Guardrails are enabled. Please select a Guardrail Model.",
            });
          }
        }
      }

      if (node.type === "telegram") {
        if (!node.data.credentialId || !isValidUUID(node.data.credentialId)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Telegram",
            message: "Credential is not selected",
          });
        }
        if (!node.data.chatId || node.data.chatId.trim() === "") {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Telegram",
            message: "Chat ID is not specified",
          });
        }
      }

      if (node.type === "slack") {
        if (!node.data.credentialId || !isValidUUID(node.data.credentialId)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Slack",
            message: "Credential is not selected",
          });
        }
      }

      if (node.type === "execute") {
        const executeWorkflowId = (node.data.executeWorkflowId as string | undefined) ?? "";
        const executeWorkflowIdValid = !!executeWorkflowId && isValidUUID(executeWorkflowId);
        if (
          !executeWorkflowId ||
          !executeWorkflowIdValid
        ) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Execute",
            message: "Target workflow is not selected",
          });
        }
      }

      if (node.type === "sendEmail") {
        if (!node.data.credentialId || !isValidUUID(node.data.credentialId)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Send Email",
            message: "Credential is not selected",
          });
        }
        if (!node.data.to || node.data.to.trim() === "") {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Send Email",
            message: "Recipient (To) is not specified",
          });
        }
      }

      if (node.type === "telegramTrigger") {
        if (!node.data.credentialId || !isValidUUID(node.data.credentialId)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Telegram Trigger",
            message: "Credential is not selected",
          });
        }
      }

      if (node.type === "imapTrigger") {
        if (!node.data.credentialId || !isValidUUID(node.data.credentialId)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "IMAP Trigger",
            message: "Credential is not selected",
          });
        }
        const pollInterval =
          typeof node.data.pollIntervalMinutes === "number"
            ? node.data.pollIntervalMinutes
            : Number.parseInt(String(node.data.pollIntervalMinutes || ""), 10);
        if (!Number.isInteger(pollInterval) || pollInterval < 1) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "IMAP Trigger",
            message: "Poll interval must be at least 1 minute",
          });
        }
      }

      if (node.type === "websocketTrigger") {
        if (!node.data.websocketUrl || node.data.websocketUrl.trim() === "") {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "WebSocket Trigger",
            message: "WebSocket URL is required",
          });
        }
        if (!isValidJsonObjectLike(node.data.websocketHeaders)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "WebSocket Trigger",
            message: "Headers must be empty, a JSON object, or a full expression",
          });
        }
        if ((node.data.websocketTriggerEvents || []).length === 0) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "WebSocket Trigger",
            message: "Select at least one emitted event",
          });
        }
        if (node.data.retryEnabled !== false) {
          const retryWaitSeconds =
            typeof node.data.retryWaitSeconds === "number"
              ? node.data.retryWaitSeconds
              : Number.parseInt(String(node.data.retryWaitSeconds || ""), 10);
          if (!Number.isInteger(retryWaitSeconds) || retryWaitSeconds < 1) {
            errors.push({
              nodeId: node.id,
              nodeLabel: node.data.label,
              nodeType: "WebSocket Trigger",
              message: "Retry wait must be at least 1 second",
            });
          }
        }
      }

      if (node.type === "websocketSend") {
        if (!node.data.websocketUrl || node.data.websocketUrl.trim() === "") {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "WebSocket Send",
            message: "WebSocket URL is required",
          });
        }
        if (!node.data.websocketMessage || node.data.websocketMessage.trim() === "") {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "WebSocket Send",
            message: "Message is required",
          });
        }
        if (!isValidJsonObjectLike(node.data.websocketHeaders)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "WebSocket Send",
            message: "Headers must be empty, a JSON object, or a full expression",
          });
        }
      }

      if (node.type === "disableNode") {
        if (
          !node.data.targetNodeLabel ||
          node.data.targetNodeLabel.trim() === ""
        ) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Disable Node",
            message: "Target node is not selected",
          });
        }
      }

      if (node.type === "throwError") {
        const hasMessage =
          node.data.errorMessage && node.data.errorMessage.trim() !== "";
        const hasHttpCode =
          node.data.httpStatusCode !== undefined &&
          node.data.httpStatusCode !== null;
        if (!hasMessage && !hasHttpCode) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Throw Error",
            message: "Error message or HTTP status code is required",
          });
        }
      }

      if (node.type === "redis") {
        if (!node.data.credentialId || !isValidUUID(node.data.credentialId)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Redis",
            message: "Credential is not selected",
          });
        }
        if (!node.data.redisOperation) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Redis",
            message: "Operation is not selected",
          });
        }
        if (!node.data.redisKey || node.data.redisKey.trim() === "") {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Redis",
            message: "Key is not specified",
          });
        }
        if (
          node.data.redisOperation === "set" &&
          (!node.data.redisValue || node.data.redisValue.trim() === "")
        ) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Redis",
            message: "Value is required for set operation",
          });
        }
      }
    }

    return {
      isValid: errors.length === 0,
      errors,
    };
  }

  async function validateExecuteTargetsExist(): Promise<ValidationResult> {
    const errors: ValidationError[] = [];
    let validWorkflowIds = new Set<string>();

    try {
      const workflows = await workflowApi.list();
      validWorkflowIds = new Set(workflows.map((workflow) => workflow.id));
    } catch {
      return { isValid: true, errors: [] };
    }

    for (const node of nodes.value) {
      if (node.data.active === false || node.type !== "execute") continue;

      const executeWorkflowId = (node.data.executeWorkflowId as string | undefined) ?? "";
      const existsInOptions = !!executeWorkflowId && validWorkflowIds.has(executeWorkflowId);
      if (!executeWorkflowId || !existsInOptions) {
        errors.push({
          nodeId: node.id,
          nodeLabel: node.data.label,
          nodeType: "Execute",
          message: "Target workflow is not selected",
        });
      }
    }

    return {
      isValid: errors.length === 0,
      errors,
    };
  }

  function setAgentMemoryGraphDialogOpen(open: boolean): void {
    agentMemoryGraphDialogOpen.value = open;
  }

  function duplicateSelectedNodes(): void {
    if (selectedNodeIds.value.size === 0) return;

    saveToHistory();

    const nodesToDuplicate = nodes.value.filter((n) =>
      selectedNodeIds.value.has(n.id),
    );

    const oldToNewIdMap = new Map<string, string>();
    const newNodes: WorkflowNode[] = [];

    for (const node of nodesToDuplicate) {
      const newId = `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      oldToNewIdMap.set(node.id, newId);

      const uniqueLabel = generateUniqueNodeLabel(node.data.label);
      const newNode: WorkflowNode = {
        id: newId,
        type: node.type,
        position: {
          x: node.position.x + 50,
          y: node.position.y + 50,
        },
        data: { ...node.data, label: uniqueLabel },
      };
      newNodes.push(newNode);
      nodes.value.push(newNode);
    }

    const nodeIdSet = new Set(nodesToDuplicate.map((n) => n.id));
    const edgesToDuplicate = edges.value.filter(
      (e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target),
    );

    for (const edge of edgesToDuplicate) {
      const newSourceId = oldToNewIdMap.get(edge.source);
      const newTargetId = oldToNewIdMap.get(edge.target);
      if (newSourceId && newTargetId) {
        const newEdge: WorkflowEdge = {
          id: `edge_${newSourceId}_${newTargetId}_${Date.now()}`,
          source: newSourceId,
          target: newTargetId,
          sourceHandle: edge.sourceHandle,
          targetHandle: edge.targetHandle,
        };
        if (isEdgeAllowed(newEdge)) {
          edges.value.push(newEdge);
        }
      }
    }

    hasUnsavedChanges.value = true;
    selectNodes(newNodes.map((n) => n.id));
  }

  interface ExtractInfo {
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
    externalInputs: Array<{
      sourceNodeId: string;
      sourceNodeLabel: string;
      targetNodeId: string;
      sourceHandle?: string;
    }>;
    externalOutputs: Array<{
      sourceNodeId: string;
      targetNodeId: string;
      targetNodeLabel: string;
      sourceHandle?: string;
    }>;
  }

  function getExtractInfo(): ExtractInfo {
    const selectedIds = new Set(selectedNodeIds.value);
    const selectedNodesArr = nodes.value.filter((n) => selectedIds.has(n.id));
    const internalEdges = edges.value.filter(
      (e) => selectedIds.has(e.source) && selectedIds.has(e.target),
    );

    const externalInputs: ExtractInfo["externalInputs"] = [];
    const externalOutputs: ExtractInfo["externalOutputs"] = [];

    for (const edge of edges.value) {
      if (!selectedIds.has(edge.source) && selectedIds.has(edge.target)) {
        const sourceNode = nodes.value.find((n) => n.id === edge.source);
        if (sourceNode) {
          externalInputs.push({
            sourceNodeId: edge.source,
            sourceNodeLabel: sourceNode.data.label,
            targetNodeId: edge.target,
            sourceHandle: edge.sourceHandle,
          });
        }
      }

      if (selectedIds.has(edge.source) && !selectedIds.has(edge.target)) {
        const targetNode = nodes.value.find((n) => n.id === edge.target);
        if (targetNode) {
          externalOutputs.push({
            sourceNodeId: edge.source,
            targetNodeId: edge.target,
            targetNodeLabel: targetNode.data.label,
            sourceHandle: edge.sourceHandle,
          });
        }
      }
    }

    return {
      nodes: selectedNodesArr,
      edges: internalEdges,
      externalInputs,
      externalOutputs,
    };
  }

  function replaceNodesWithExecute(
    nodeIds: string[],
    executeWorkflowId: string,
    executeWorkflowName: string,
    extractedNodeLabels: string[] = [],
  ): void {
    saveToHistory();

    const nodeIdSet = new Set(nodeIds);
    const extractInfo = getExtractInfo();

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    for (const node of extractInfo.nodes) {
      minX = Math.min(minX, node.position.x);
      minY = Math.min(minY, node.position.y);
      maxX = Math.max(maxX, node.position.x);
      maxY = Math.max(maxY, node.position.y);
    }

    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;

    const executeNodeId = `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const uniqueLabel = generateUniqueNodeLabel("execute");

    let executeInputRef = "$input";
    if (extractInfo.externalInputs.length > 0) {
      const firstInput = extractInfo.externalInputs[0];
      const sourceNode = nodes.value.find(
        (n) => n.id === firstInput.sourceNodeId,
      );
      if (sourceNode) {
        const isTextInput = sourceNode.type === "textInput";
        if (isTextInput) {
          const inputFields = sourceNode.data.inputFields as
            | Array<{ key: string }>
            | undefined;
          const fieldKey = inputFields?.[0]?.key || "text";
          executeInputRef = `$${firstInput.sourceNodeLabel}.body.${fieldKey}`;
        } else {
          executeInputRef = `$${firstInput.sourceNodeLabel}`;
        }
      }
    }

    const executeNode: WorkflowNode = {
      id: executeNodeId,
      type: "execute",
      position: { x: centerX, y: centerY },
      data: {
        label: uniqueLabel,
        executeWorkflowId: executeWorkflowId,
        targetWorkflowName: executeWorkflowName,
        executeInput: executeInputRef,
        executeTargets: [],
        executeInputMappings: [{ key: "data", value: executeInputRef }],
        targetWorkflowInputFields: [{ key: "data" }],
      },
    };

    nodes.value.push(executeNode);

    for (const input of extractInfo.externalInputs) {
      const newEdge: WorkflowEdge = {
        id: `edge_${input.sourceNodeId}_${executeNodeId}_${Date.now()}`,
        source: input.sourceNodeId,
        target: executeNodeId,
        sourceHandle: input.sourceHandle,
        targetHandle: "input",
      };
      edges.value.push(newEdge);
    }

    for (const output of extractInfo.externalOutputs) {
      const newEdge: WorkflowEdge = {
        id: `edge_${executeNodeId}_${output.targetNodeId}_${Date.now()}`,
        source: executeNodeId,
        target: output.targetNodeId,
        sourceHandle: undefined,
        targetHandle: "input",
      };
      edges.value.push(newEdge);
    }

    edges.value = edges.value.filter(
      (e) => !nodeIdSet.has(e.source) && !nodeIdSet.has(e.target),
    );

    nodes.value = nodes.value.filter((n) => !nodeIdSet.has(n.id));

    if (extractedNodeLabels.length > 0) {
      const downstreamNodeIds = new Set(
        extractInfo.externalOutputs.map((o) => o.targetNodeId),
      );
      const labelMap = new Map<string, string>();

      for (const output of extractInfo.externalOutputs) {
        const sourceNode = extractInfo.nodes.find(
          (n) => n.id === output.sourceNodeId,
        );
        if (sourceNode) {
          const label = sourceNode.data.label;
          let fieldPath = "";
          if (sourceNode.type === "set") {
            const mappings = sourceNode.data.mappings as
              | Array<{ key: string }>
              | undefined;
            if (mappings && mappings.length > 0) {
              fieldPath = `.${mappings[0].key}`;
            }
          } else if (sourceNode.type === "llm") {
            fieldPath = ".text";
          }
          if (fieldPath) {
            labelMap.set(
              `${label}${fieldPath}`,
              `$${uniqueLabel}.outputs.output.result`,
            );
          }
          labelMap.set(label, `$${uniqueLabel}.outputs.output.result`);
        }
      }

      for (const node of nodes.value) {
        if (downstreamNodeIds.has(node.id)) {
          node.data = replaceNodeLabelRefs(node.data, labelMap);
        }
      }
    }

    clearSelection();
    selectNode(executeNodeId);
    hasUnsavedChanges.value = true;
  }

  return {
    currentWorkflow,
    nodes,
    edges,
    selectedNodeId,
    selectedNodeIds,
    selectedNode,
    selectedNodes,
    executionResult,
    nodeResults,
    agentProgressLogs,
    llmBatchProgressLogs,
    executionHistoryList,
    executionHistoryDetails,
    executionHistoryTotal,
    isHistoryLoading,
    isHistoryDetailLoading,
    fetchExecutionHistoryEntry,
    upsertExecutionHistoryEntry,
    applyExecutionHistoryEntry,
    applyExecutionResultSnapshot,
    isExecuting,
    isSaving,
    hasUnsavedChanges,
    runningNodeId,
    pendingNodeDeletion,
    clipboardNode,
    canUndo,
    canRedo,
    loadWorkflow,
    saveWorkflow,
    addNode,
    updateNode,
    toggleNodeActive,
    toggleSelectedNodesActive,
    prepareNodeDeletion,
    removeNode,
    addEdge,
    removeEdge,
    copyNode,
    cutNode,
    pasteNode,
    generateUniqueNodeLabel,
    selectNode,
    selectNodes,
    suppressVueFlowSelectionEcho,
    setSuppressVueFlowSelectionEcho,
    setExpressionGraphNavigateHandler,
    runExpressionGraphNavigate,
    expressionEvaluateFallbackOpen,
    expressionEvaluateFallbackNodeId,
    openExpressionEvaluateFallbackDialog,
    closeExpressionEvaluateFallbackDialog,
    addToSelection,
    removeFromSelection,
    toggleNodeSelection,
    selectAllNodes,
    clearSelection,
    isNodeSelected,
    removeSelectedNodes,
    updateNodePosition,
    setNodeStatus,
    clearNodeStatuses,
    executeWorkflow,
    stopExecution,
    clearWorkflow,
    clearExecution,
    clearCanvas,
    clearExecutionHistory,
    fetchExecutionHistory,
    propertiesPanelOpen,
    agentMemoryGraphDialogOpen,
    setAgentMemoryGraphDialogOpen,
    propertiesPanelTab,
    openPropertiesPanel,
    timelinePickedNodeResultIndex,
    setTimelinePickedNodeResultIndex,
    evaluateLoopSelection,
    setEvaluateLoopSelection,
    clearEvaluateLoopSelection,
    skipPrimaryExpandOnNextPropertiesOpen,
    clearSkipPrimaryExpandOnNextPropertiesOpen,
    focusField,
    clearFocusField,
    debugPanelHeight,
    setDebugPanelHeight,
    nodeSearchQuery,
    setNodeSearchQuery,
    clearNodeSearchQuery,
    pendingConnectionSource,
    setPendingConnectionSource,
    clearPendingConnectionSource,
    pendingInsertEdge,
    setPendingInsertEdge,
    clearPendingInsertEdge,
    insertNodeBetween,
    shouldTidyUp,
    requestTidyUp,
    clearTidyUp,
    undo,
    redo,
    canTogglePin,
    togglePinnedData,
    runInputText,
    runInputValues,
    runInputJson,
    allInputFields,
    webhookBodyMode,
    buildLegacyExecutionBody,
    resetRunInputJsonFromMode,
    buildExecutionRequestBody,
    validateWorkflow,
    validateExecuteTargetsExist,
    pendingHistoryInputs,
    pendingHistoryNodeResults,
    pendingHistoryExecutionResult,
    loadHistoryInputs,
    duplicateSelectedNodes,
    getExtractInfo,
    replaceNodesWithExecute,
  };
});
