<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { Background } from "@vue-flow/background";
import { ControlButton, Controls } from "@vue-flow/controls";
import { VueFlow, useVueFlow, SelectionMode } from "@vue-flow/core";
import type { EdgeChange, NodeChange, OnConnectStartParams } from "@vue-flow/core";
import { MiniMap } from "@vue-flow/minimap";
import { FileJson, LayoutGrid } from "lucide-vue-next";
import ShareTemplateModal from "@/features/templates/components/ShareTemplateModal.vue";

import type { NodeType, WorkflowEdge, WorkflowNode } from "@/types/workflow";

import BaseNode from "@/components/Nodes/BaseNode.vue";
import InsertableEdge from "@/components/Canvas/InsertableEdge.vue";
import NodeContextMenu from "@/components/Canvas/NodeContextMenu.vue";
import StickyNoteNode from "@/components/Nodes/StickyNoteNode.vue";
import AgentMemoryGraphDialog from "@/components/Dialogs/AgentMemoryGraphDialog.vue";
import ExtractSubWorkflowDialog from "@/components/Dialogs/ExtractSubWorkflowDialog.vue";
import { buildSubAgentEdges, getSubAgentLabels } from "@/lib/agentCanvasLinks";
import { buildWorkflowNodeFromNodeTemplate } from "@/lib/nodeFromTemplate";
import { generateId, replaceInputRefs } from "@/lib/utils";
import { evalsApi, templatesApi } from "@/services/api";
import { useToast } from "@/composables/useToast";
import { useWorkflowStore } from "@/stores/workflow";

import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import "@vue-flow/controls/dist/style.css";
import "@vue-flow/minimap/dist/style.css";

const workflowStore = useWorkflowStore();
const router = useRouter();
const { showToast } = useToast();
const { onConnect, onConnectStart, onConnectEnd, onNodeDragStop, onPaneClick, onEdgesChange, onNodesChange, fitView, updateNodeInternals, getNodes, getSelectedNodes, getSelectedEdges, addSelectedNodes, removeSelectedNodes, nodesSelectionActive } = useVueFlow();

const pendingConnection = ref<{ nodeId: string; handleId: string | null } | null>(null);
const isDraggingFile = ref(false);

const contextMenuVisible = ref(false);
const contextMenuPosition = ref({ x: 0, y: 0 });
const extractDialogOpen = ref(false);
const agentMemoryDialogOpen = ref(false);
const agentMemoryCanvasNodeId = ref<string | null>(null);

const pendingEdgeRemovals = ref<Set<string>>(new Set());
const pendingNodeRemovals = ref<Set<string>>(new Set());
let processingScheduled = false;

/** DebugPanel uses `duration-200` height transitions; fitView before finish measures the wrong pane. */
const FIT_VIEW_AFTER_LAYOUT_MS = 260;
let fitAfterLayoutTimer: number | null = null;

function scheduleFitViewAfterLayout(): void {
  if (fitAfterLayoutTimer !== null) {
    window.clearTimeout(fitAfterLayoutTimer);
  }
  fitAfterLayoutTimer = window.setTimeout((): void => {
    fitAfterLayoutTimer = null;
    fitView({ padding: 0.2 });
  }, FIT_VIEW_AFTER_LAYOUT_MS);
}

function handleOpenAgentMemory(nodeId: string): void {
  agentMemoryCanvasNodeId.value = nodeId;
  agentMemoryDialogOpen.value = true;
}

function closeAgentMemoryDialog(): void {
  agentMemoryDialogOpen.value = false;
  agentMemoryCanvasNodeId.value = null;
}

watch(
  agentMemoryDialogOpen,
  (open) => {
    workflowStore.setAgentMemoryGraphDialogOpen(open);
  },
  { immediate: true },
);

const subAgentLabels = computed(() => getSubAgentLabels(workflowStore.nodes));

const vueFlowNodes = computed(() =>
  workflowStore.nodes.map((node) => {
    const isSubAgent =
      node.type === "agent" &&
      node.data?.label &&
      subAgentLabels.value.has(node.data.label as string);
    return {
      id: node.id,
      type: "custom",
      position: node.position,
      data: { ...node.data, nodeType: node.type, isSubAgent: !!isSubAgent },
    };
  })
);

const subAgentEdges = computed(() => buildSubAgentEdges(workflowStore.nodes));

const vueFlowEdges = computed(() => [
  ...workflowStore.edges.map((edge) => ({
    id: edge.id,
    type: "insertable",
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle,
    targetHandle: edge.targetHandle,
    animated: true,
  })),
  ...subAgentEdges.value.map((edge) => ({
    id: edge.id,
    type: "insertable",
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle,
    targetHandle: edge.targetHandle,
    animated: true,
  })),
]);

function canConnectAgentToAgent(sourceId: string, targetId: string): boolean {
  const sourceNode = workflowStore.nodes.find((n) => n.id === sourceId);
  const targetNode = workflowStore.nodes.find((n) => n.id === targetId);
  if (!sourceNode || !targetNode) return true;

  if (sourceNode.type !== "agent" || targetNode.type !== "agent") return true;

  return sourceNode.data?.isOrchestrator === true;
}

onConnect((connection) => {
  if (connection.source && connection.target) {
    const allowed = canConnectAgentToAgent(connection.source, connection.target);
    if (!allowed) {
      showToast("This agent is not in orchestrator mode, so it cannot connect to other agent nodes.", "error");
      return;
    }
  }
  const edge: WorkflowEdge = {
    id: `edge_${connection.source}_${connection.target}_${Date.now()}`,
    source: connection.source,
    target: connection.target,
    sourceHandle: connection.sourceHandle || undefined,
    targetHandle: connection.targetHandle || undefined,
  };
  workflowStore.addEdge(edge);
});

let connectionCreated = false;

onConnectStart((params: { event?: MouseEvent | TouchEvent } & OnConnectStartParams) => {
  if (params.nodeId) {
    pendingConnection.value = { nodeId: params.nodeId, handleId: params.handleId ?? null };
  }
  connectionCreated = false;
  workflowStore.clearPendingConnectionSource();
});

onConnect(() => {
  connectionCreated = true;
});

onConnectEnd((event: MouseEvent | TouchEvent | undefined) => {
  const source = pendingConnection.value;
  pendingConnection.value = null;

  if (!event || !source || connectionCreated) return;

  let clientX: number;
  let clientY: number;

  if (event instanceof MouseEvent) {
    clientX = event.clientX;
    clientY = event.clientY;
  } else if (event instanceof TouchEvent && event.changedTouches.length > 0) {
    clientX = event.changedTouches[0].clientX;
    clientY = event.changedTouches[0].clientY;
  } else {
    return;
  }

  const targetElement = document.elementFromPoint(clientX, clientY);
  if (!targetElement) {
    lastDropTime = Date.now();
    workflowStore.setPendingConnectionSource(source);
    workflowStore.clearNodeSearchQuery();
    return;
  }

  const nodeElement = targetElement.closest(".vue-flow__node");
  if (!nodeElement) {
    lastDropTime = Date.now();
    workflowStore.setPendingConnectionSource(source);
    workflowStore.clearNodeSearchQuery();
    return;
  }

  const nodeId = nodeElement.getAttribute("data-id");
  if (!nodeId || nodeId === source.nodeId) return;

  const nodes = getNodes.value;
  const targetNode = nodes.find(n => n.id === nodeId);
  if (!targetNode) return;

  const nodeType = targetNode.data?.nodeType as NodeType;
  const noInputTypes: NodeType[] = ["textInput", "cron", "sticky", "merge", "errorHandler", "telegramTrigger", "websocketTrigger", "slackTrigger", "imapTrigger"];
  if (noInputTypes.includes(nodeType)) return;

  const existingEdge = workflowStore.edges.find(
    e => e.source === source.nodeId && e.target === nodeId && e.sourceHandle === source.handleId
  );
  if (existingEdge) return;

  if (!canConnectAgentToAgent(source.nodeId, nodeId)) {
    showToast("This agent is not in orchestrator mode, so it cannot connect to other agent nodes.", "error");
    return;
  }

  const edge: WorkflowEdge = {
    id: `edge_${source.nodeId}_${nodeId}_${Date.now()}`,
    source: source.nodeId,
    target: nodeId,
    sourceHandle: source.handleId || undefined,
    targetHandle: "input",
  };
  workflowStore.addEdge(edge);
});

function processPendingChanges(): void {
  if (pendingNodeRemovals.value.size > 0) {
    pendingNodeRemovals.value.forEach((nodeId) => {
      workflowStore.prepareNodeDeletion(nodeId);
    });
    pendingNodeRemovals.value.forEach((nodeId) => {
      workflowStore.removeNode(nodeId);
    });
    pendingNodeRemovals.value.clear();
  }

  pendingEdgeRemovals.value.forEach((edgeId) => {
    const edge = workflowStore.edges.find(e => e.id === edgeId);
    if (edge) {
      workflowStore.removeEdge(edgeId);
    }
  });
  pendingEdgeRemovals.value.clear();
  processingScheduled = false;
}

function schedulePendingChanges(): void {
  if (!processingScheduled) {
    processingScheduled = true;
    queueMicrotask(processPendingChanges);
  }
}

onEdgesChange((changes: EdgeChange[]) => {
  changes.forEach((change) => {
    if (change.type === "remove") {
      const edge = workflowStore.edges.find(e => e.id === change.id);
      if (!edge) return;
      pendingEdgeRemovals.value.add(change.id);
    }
  });
  schedulePendingChanges();
});

onNodesChange((changes: NodeChange[]) => {
  changes.forEach((change) => {
    if (change.type === "remove") {
      pendingNodeRemovals.value.add(change.id);
      pendingEdgeRemovals.value.forEach((edgeId) => {
        const edge = workflowStore.edges.find(e => e.id === edgeId);
        if (edge && (edge.source === change.id || edge.target === change.id)) {
          pendingEdgeRemovals.value.delete(edgeId);
        }
      });
    }
  });
  schedulePendingChanges();
});

onNodeDragStop((event) => {
  if (event.nodes && event.nodes.length > 1) {
    event.nodes.forEach((n) => {
      workflowStore.updateNodePosition(n.id, n.position);
    });
  } else {
    workflowStore.updateNodePosition(event.node.id, event.node.position);
  }
});

let lastDropTime = 0;

let skipNextSelectionSync = false;

/** True while applying Pinia selection onto Vue Flow to avoid vue→store overwriting programmatic picks. */
let isApplyingStoreSelection = false;

onPaneClick(() => {
  if (Date.now() - lastDropTime > 100) {
    workflowStore.clearPendingConnectionSource();
    workflowStore.clearPendingInsertEdge();
  }
  closeContextMenu();
});

watch(getSelectedNodes, (selectedNodes) => {
  if (skipNextSelectionSync) {
    skipNextSelectionSync = false;
    return;
  }
  if (isApplyingStoreSelection) {
    return;
  }
  if (workflowStore.suppressVueFlowSelectionEcho) {
    return;
  }
  const selectedIds = selectedNodes.map((n) => n.id);
  workflowStore.selectNodes(selectedIds);
}, { deep: true });

watch(
  () => Array.from(workflowStore.selectedNodeIds).sort().join(","),
  () => {
    const ids = Array.from(workflowStore.selectedNodeIds);
    const vueNodes = getSelectedNodes.value;
    const vueIds = vueNodes
      .map((n) => n.id)
      .sort()
      .join(",");
    const targetIds = [...ids].sort().join(",");
    if (vueIds === targetIds) {
      return;
    }

    isApplyingStoreSelection = true;
    removeSelectedNodes(vueNodes);
    const toAdd = ids
      .map((id) => getNodes.value.find((n) => n.id === id))
      .filter((n): n is NonNullable<(typeof getNodes.value)[number]> => !!n);
    if (toAdd.length > 0) {
      addSelectedNodes(toAdd);
    }
    void nextTick(() => {
      isApplyingStoreSelection = false;
    });
  },
  { flush: "post" },
);

function closeContextMenu(): void {
  contextMenuVisible.value = false;
}

function handleNodeClick(event: { node: { id: string } }): void {
  closeContextMenu();
  workflowStore.selectNode(event.node.id);
}

function handleNodeContextMenu(event: { event: MouseEvent | TouchEvent; node: { id: string } }): void {
  event.event.preventDefault();
  event.event.stopPropagation();

  const vueFlowSelectedNodes = getSelectedNodes.value;
  const vueFlowSelectedIds = new Set(vueFlowSelectedNodes.map((n) => n.id));
  const isInVueFlowSelection = vueFlowSelectedIds.has(event.node.id);

  if (isInVueFlowSelection && vueFlowSelectedIds.size > 1) {
    skipNextSelectionSync = true;
    workflowStore.selectNodes(Array.from(vueFlowSelectedIds));
  } else if (!workflowStore.selectedNodeIds.has(event.node.id)) {
    workflowStore.selectNode(event.node.id);
  }

  let x = 0;
  let y = 0;

  if (event.event instanceof MouseEvent) {
    x = event.event.clientX;
    y = event.event.clientY;
  } else if (event.event instanceof TouchEvent && event.event.touches.length > 0) {
    x = event.event.touches[0].clientX;
    y = event.event.touches[0].clientY;
  }

  contextMenuPosition.value = { x, y };
  contextMenuVisible.value = true;
}

function handleContextMenuExtract(): void {
  closeContextMenu();
  extractDialogOpen.value = true;
}

function handleContextMenuDisable(): void {
  closeContextMenu();
  workflowStore.toggleSelectedNodesActive();
}

function handleContextMenuDuplicate(): void {
  closeContextMenu();
  workflowStore.duplicateSelectedNodes();
}

function handleContextMenuDelete(): void {
  closeContextMenu();
  workflowStore.removeSelectedNodes();
}

function handleExtracted(_workflowId: string): void {
  extractDialogOpen.value = false;
}

const contextMenuSelectedCount = computed(() => workflowStore.selectedNodeIds.size);

const contextMenuHasDisabledNodes = computed(() => {
  return workflowStore.selectedNodes.some((n) => n.data.active === false);
});

const contextMenuAllDisabled = computed(() => {
  if (workflowStore.selectedNodes.length === 0) return false;
  return workflowStore.selectedNodes.every((n) => n.data.active === false);
});

const shareNodeTemplateOpen = ref(false);
const shareNodeTemplateData = ref<{ type: string; data: Record<string, unknown> } | null>(null);

function handleContextMenuShareAsTemplate(): void {
  if (workflowStore.selectedNodeIds.size !== 1) return;
  const node = workflowStore.selectedNodes[0];
  if (!node) return;
  shareNodeTemplateData.value = {
    type: node.type ?? "unknown",
    data: node.data as Record<string, unknown>,
  };
  shareNodeTemplateOpen.value = true;
}

const contextMenuEvalNode = computed(() => {
  if (workflowStore.selectedNodeIds.size !== 1) return null;
  const node = workflowStore.selectedNodes[0];
  if (!node || (node.type !== "llm" && node.type !== "agent")) return null;
  return {
    id: node.id,
    type: node.type,
    data: {
      label: node.data.label ?? "node",
      systemInstruction: node.data.systemInstruction,
      temperature: node.data.temperature,
    },
  };
});

async function handleContextMenuEvalAgent(): Promise<void> {
  const node = contextMenuEvalNode.value;
  if (!node) return;
  closeContextMenu();
  const workflowName = workflowStore.currentWorkflow?.name ?? "Workflow";
  const nodeLabel = node.data.label ?? "node";
  const suiteName = `${workflowName} - ${nodeLabel}`;
  try {
    const suite = await evalsApi.createSuite({
      name: suiteName,
      system_prompt: node.data.systemInstruction ?? "",
      scoring_method: "exact_match",
    });
    router.push({
      path: "/evals",
      query: {
        suite: suite.id,
        temperature: String(node.data.temperature ?? 0.7),
      },
    });
  } catch (e) {
    console.error("Failed to create eval suite:", e);
  }
}

function handleNodeDoubleClick(event: { node: { id: string; data?: { nodeType?: NodeType; ragOperation?: string } } }): void {
  workflowStore.selectNode(event.node.id);
  if (event.node.data?.nodeType === "sticky") return;
  const nodeType = event.node.data?.nodeType;
  let fieldToFocus: string | undefined;
  if (nodeType === "llm") {
    fieldToFocus = "userMessage";
  } else if (nodeType === "slack") {
    fieldToFocus = "message";
  } else if (nodeType === "redis") {
    fieldToFocus = "redisKey";
  } else if (nodeType === "rag") {
    const ragOperation = event.node.data?.ragOperation;
    if (ragOperation === "insert") {
      fieldToFocus = "documentContent";
    } else if (ragOperation === "search") {
      fieldToFocus = "queryText";
    }
  } else if (nodeType === "throwError") {
    fieldToFocus = "errorMessage";
  } else if (nodeType === "crawler") {
    fieldToFocus = "crawlerUrl";
  } else if (nodeType === "playwright") {
    fieldToFocus = "playwrightSteps";
  }
  workflowStore.openPropertiesPanel(fieldToFocus);
}

function handleEdgeDoubleClick(event: { edge: { id: string } }): void {
  workflowStore.removeEdge(event.edge.id);
}

function handleDrop(event: DragEvent): void {
  event.preventDefault();
  isDraggingFile.value = false;
  lastDropTime = Date.now();
  const files = event.dataTransfer?.files;
  if (files && files.length > 0) {
    const file = files[0];
    const isJson = file.type === "application/json" || file.name.endsWith(".json");
    if (!isJson) return;
    const reader = new FileReader();
    reader.onload = () => {
      const content = typeof reader.result === "string" ? reader.result : "";
      try {
        const parsed = JSON.parse(content) as { nodes?: WorkflowNode[]; edges?: WorkflowEdge[] };
        if (!parsed.nodes || !Array.isArray(parsed.nodes)) {
          alert("Invalid workflow file.");
          return;
        }
        const hasExisting = workflowStore.nodes.length > 0 || workflowStore.edges.length > 0;
        if (hasExisting && !confirm("Replace the current workflow with the imported one?")) {
          return;
        }
        workflowStore.nodes.splice(0, workflowStore.nodes.length, ...parsed.nodes);
        workflowStore.edges.splice(0, workflowStore.edges.length, ...(parsed.edges || []));
        workflowStore.hasUnsavedChanges = true;
        setTimeout(() => fitView({ padding: 0.2 }), 100);
      } catch {
        alert("Invalid workflow file.");
      }
    };
    reader.readAsText(file);
    return;
  }

  const templateId = event.dataTransfer?.getData("application/heym-node-template");
  if (templateId) {
    const canvas = document.querySelector(".vue-flow");
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const position = {
      x: event.clientX - rect.left - 90,
      y: event.clientY - rect.top - 30,
    };
    void (async () => {
      try {
        const template = await templatesApi.getNode(templateId);
        const pendingSource = workflowStore.pendingConnectionSource;
        const sourceNode = pendingSource
          ? workflowStore.nodes.find((n) => n.id === pendingSource.nodeId)
          : null;
        const newNode = buildWorkflowNodeFromNodeTemplate(
          template,
          position,
          sourceNode ? { label: String(sourceNode.data.label), type: sourceNode.type } : null,
        );
        workflowStore.addNode(newNode);
        if (pendingSource) {
          const noInputTypes: NodeType[] = ["textInput", "cron", "sticky", "merge", "errorHandler", "telegramTrigger", "websocketTrigger", "slackTrigger", "imapTrigger"];
          const nodeType = template.node_type as NodeType;
          if (!noInputTypes.includes(nodeType)) {
            const edge: WorkflowEdge = {
              id: `edge_${pendingSource.nodeId}_${newNode.id}_${Date.now()}`,
              source: pendingSource.nodeId,
              target: newNode.id,
              sourceHandle: pendingSource.handleId || undefined,
              targetHandle: "input",
            };
            workflowStore.addEdge(edge);
            workflowStore.clearNodeSearchQuery();
            workflowStore.requestTidyUp();
          }
          workflowStore.clearPendingConnectionSource();
        }
        void templatesApi.useNode(templateId).catch(() => {
          // best-effort use count
        });
      } catch {
        showToast("The node template could not be loaded.", "error");
      }
    })();
    return;
  }

  const nodeType = event.dataTransfer?.getData("application/heym-node") as NodeType;
  if (!nodeType) return;

  const canvas = document.querySelector(".vue-flow");
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  const position = {
    x: event.clientX - rect.left - 90,
    y: event.clientY - rect.top - 30,
  };

  let defaultData = getDefaultNodeData(nodeType);

  const pendingSource = workflowStore.pendingConnectionSource;
  if (pendingSource) {
    const sourceNode = workflowStore.nodes.find((n) => n.id === pendingSource.nodeId);
    if (sourceNode) {
      defaultData = replaceInputRefs(defaultData, {
        label: sourceNode.data.label,
        type: sourceNode.type,
      });
    }
  }

  const newNode: WorkflowNode = {
    id: generateId(),
    type: nodeType,
    position,
    data: defaultData,
  };

  workflowStore.addNode(newNode);

  if (pendingSource) {
    const noInputTypes: NodeType[] = ["textInput", "cron", "sticky", "merge", "errorHandler", "telegramTrigger", "websocketTrigger", "slackTrigger", "imapTrigger"];
    if (!noInputTypes.includes(nodeType)) {
      const edge: WorkflowEdge = {
        id: `edge_${pendingSource.nodeId}_${newNode.id}_${Date.now()}`,
        source: pendingSource.nodeId,
        target: newNode.id,
        sourceHandle: pendingSource.handleId || undefined,
        targetHandle: "input",
      };
      workflowStore.addEdge(edge);
      workflowStore.clearNodeSearchQuery();
      workflowStore.requestTidyUp();
    }
    workflowStore.clearPendingConnectionSource();
  }
}

function handleDragOver(event: DragEvent): void {
  event.preventDefault();
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = "move";
    const items = event.dataTransfer.items;
    if (items && items.length > 0 && items[0].kind === "file") {
      isDraggingFile.value = true;
    }
  }
}

function handleDragLeave(event: DragEvent): void {
  const relatedTarget = event.relatedTarget as HTMLElement;
  if (!relatedTarget || !event.currentTarget || !(event.currentTarget as HTMLElement).contains(relatedTarget)) {
    isDraggingFile.value = false;
  }
}

function getDefaultNodeData(type: NodeType): WorkflowNode["data"] {
  const defaults: Record<NodeType, WorkflowNode["data"]> = {
    textInput: { label: "start", value: "", inputFields: [{ key: "text" }] },
    cron: { label: "cron", cronExpression: "0 * * * *" },
    websocketTrigger: {
      label: "websocketTrigger",
      websocketUrl: "",
      websocketHeaders: "",
      websocketSubprotocols: "",
      websocketTriggerEvents: ["onMessage"],
      retryEnabled: true,
      retryWaitSeconds: 5,
    },
    llm: {
      label: "llm",
      model: "",
      temperature: 0.7,
      systemInstruction: "",
      userMessage: "$input.text",
      batchModeEnabled: false,
      jsonOutputEnabled: false,
      jsonOutputSchema: "",
    },
    agent: {
      label: "agent",
      model: "",
      temperature: 0.7,
      systemInstruction: "",
      userMessage: "$input.text",
      tools: [],
      mcpConnections: [],
      toolTimeoutSeconds: 30,
      maxToolIterations: 30,
      isOrchestrator: false,
      subAgentLabels: [],
      hitlEnabled: false,
      hitlSummary: "",
    },
    condition: { label: "condition", condition: "$input.text.length > 0" },
    switch: { label: "switch", expression: "$input.text", cases: ["case1", "case2"] },
    execute: { label: "execute", executeTargets: [], executeInput: "$input.text", executeWorkflowId: "" },
    output: { label: "output", message: "$input.text", allowDownstream: false },
    wait: { label: "wait", duration: 1000 },
    http: { label: "httpRequest", curl: "curl -X GET https://api.example.com" },
    websocketSend: {
      label: "websocketSend",
      websocketUrl: "",
      websocketHeaders: "",
      websocketSubprotocols: "",
      websocketMessage: "$input",
    },
    sticky: { label: "stickyNote", note: "Double click to edit" },
    merge: { label: "merge", inputCount: 2 },
    set: { label: "set", mappings: [{ key: "text", value: "$input.text" }] },
    jsonOutputMapper: {
      label: "jsonResponse",
      mappings: [{ key: "message", value: "$input.text" }],
    },
    telegramTrigger: { label: "telegramTrigger", credentialId: "" },
    slack: { label: "slack", credentialId: "", message: "$input.text" },
    telegram: { label: "telegram", credentialId: "", chatId: "", message: "$input.text" },
    sendEmail: { label: "sendEmail", credentialId: "", to: "", subject: "", emailBody: "$input.text" },
    errorHandler: { label: "errorHandler", message: "$error.message" },
    variable: { label: "variable", variableName: "myVariable", variableValue: "$input.text", variableType: "auto", isGlobal: false },
    loop: { label: "loop", arrayExpression: "$input.items" },
    disableNode: { label: "disableNode", targetNodeLabel: "" },
    redis: { label: "redis", credentialId: "", redisOperation: undefined, redisKey: "$input.text", redisValue: "$input.text" },
    rag: { label: "rag", vectorStoreId: "", ragOperation: undefined, documentContent: "$input.text", documentMetadata: "{}", queryText: "$input.text", searchLimit: 5, metadataFilters: "{}" },
    grist: { label: "grist", credentialId: "", gristOperation: undefined, gristDocId: "", gristTableId: "", gristRecordId: "", gristRecordData: "{}", gristRecordsData: "[]", gristFilter: "{}", gristSort: "", gristLimit: 100, gristRecordIds: "[]" },
    googleSheets: { label: "googleSheets", credentialId: "", gsOperation: undefined, gsSpreadsheetId: "", gsSheetName: "Sheet1", gsStartRow: "1", gsUpdateRow: "1", gsMaxRows: "0", gsHasHeader: true, gsRowCount: "1", gsKeepHeader: false, gsAppendPlacement: "append", gsValuesInputMode: "raw", gsValuesSelectiveRows: "1", gsValuesSelectiveCols: "3", gsValues: "[]" },
    bigquery: { label: "bigquery", credentialId: "", bqOperation: undefined, bqProjectId: "", bqQuery: "", bqMaxResults: "1000", bqDatasetId: "", bqTableId: "", bqRowsInputMode: "raw", bqRows: "[]", bqMappings: [{ key: "field", value: "$input.text" }] },
    throwError: { label: "throwError", errorMessage: "$input.text", httpStatusCode: 400 },
    rabbitmq: { label: "rabbitmq", credentialId: "", rabbitmqOperation: undefined, rabbitmqExchange: "", rabbitmqRoutingKey: "", rabbitmqQueueName: "", rabbitmqMessageBody: "$input", rabbitmqDelayMs: undefined },
    imapTrigger: { label: "imapTrigger", credentialId: "", pollIntervalMinutes: 5 },
    crawler: { label: "crawler", credentialId: "", crawlerUrl: "$input.text", crawlerWaitSeconds: 0, crawlerMaxTimeout: 60000, crawlerMode: "basic", crawlerSelectors: [] },
    consoleLog: { label: "consoleLog", logMessage: "$input" },
    playwright: {
      label: "playwright",
      playwrightSteps: [],
      playwrightCode: "",
      playwrightHeadless: true,
      playwrightTimeout: 30000,
      playwrightCaptureNetwork: false,
      playwrightAuthEnabled: false,
      playwrightAuthStateExpression: "",
      playwrightAuthCheckSelector: "",
      playwrightAuthCheckTimeout: 5000,
      playwrightAuthFallbackSteps: [],
    },
    dataTable: { label: "dataTable", dataTableId: "", dataTableOperation: undefined, dataTableFilter: "{}", dataTableData: "{}", dataTableRowId: "", dataTableLimit: 100, dataTableSort: "" },
    drive: { label: "drive", driveOperation: undefined, driveFileId: "" },
    slackTrigger: { label: "slackTrigger", credentialId: "" },
  };
  return defaults[type];
}

function tidyUp(): void {
  const nodes = workflowStore.nodes;
  const edges = workflowStore.edges;

  if (nodes.length === 0) return;

  const stickyNodeIds = new Set(nodes.filter((n) => n.type === "sticky").map((n) => n.id));
  const layoutNodes = nodes.filter((n) => !stickyNodeIds.has(n.id));
  const layoutEdges = edges.filter(
    (e) => !stickyNodeIds.has(e.source) && !stickyNodeIds.has(e.target),
  );

  if (layoutNodes.length === 0) return;

  const subAgentNodeIds = new Set<string>();
  const orchestratorToSubAgents = new Map<string, string[]>();
  layoutNodes.forEach((n) => {
    if (
      n.type === "agent" &&
      n.data?.isOrchestrator &&
      (n.data?.subAgentLabels as string[] | undefined)?.length
    ) {
      const labels = n.data.subAgentLabels as string[];
      const subIds: string[] = [];
      labels.forEach((label) => {
        const subNode = layoutNodes.find(
          (n2) => n2.type === "agent" && n2.data?.label === label
        );
        if (subNode) {
          subAgentNodeIds.add(subNode.id);
          subIds.push(subNode.id);
        }
      });
      orchestratorToSubAgents.set(n.id, subIds);
    }
  });

  const inDegree = new Map<string, number>();
  const outEdges = new Map<string, { target: string; sourceHandle?: string }[]>();

  layoutNodes.forEach(n => {
    inDegree.set(n.id, 0);
    outEdges.set(n.id, []);
  });

  const forwardEdges = layoutEdges.filter(e => e.targetHandle !== "loop");

  forwardEdges.forEach(e => {
    inDegree.set(e.target, (inDegree.get(e.target) || 0) + 1);
    outEdges.get(e.source)?.push({ target: e.target, sourceHandle: e.sourceHandle });
  });

  const levels: string[][] = [];
  const visited = new Set<string>();
  // Track which sourceHandle was used to reach each node
  const nodeSourceHandle = new Map<string, string | undefined>();

  let currentLevel = layoutNodes.filter(n => inDegree.get(n.id) === 0).map(n => n.id);

  while (currentLevel.length > 0) {
    levels.push(currentLevel);
    currentLevel.forEach(id => visited.add(id));

    const nextLevel: string[] = [];
    currentLevel.forEach(nodeId => {
      outEdges.get(nodeId)?.forEach(({ target: targetId, sourceHandle }) => {
        if (!visited.has(targetId) && !nextLevel.includes(targetId)) {
          const allInputsVisited = forwardEdges
            .filter(e => e.target === targetId)
            .every(e => visited.has(e.source));
          if (allInputsVisited) {
            nextLevel.push(targetId);
            nodeSourceHandle.set(targetId, sourceHandle);
          }
        }
      });
    });

    nextLevel.sort((a, b) => {
      const handleA = nodeSourceHandle.get(a);
      const handleB = nodeSourceHandle.get(b);

      const getOrder = (handle: string | undefined): number => {
        if (!handle) return 0;
        if (handle === "output") return 0;
        if (handle === "batchStatus") return 1;
        if (handle === "true") return 0;
        if (handle === "false") return 1;
        if (handle === "hitl") return 1;
        if (handle === "error") return 2;
        if (handle === "loop") return 0;
        if (handle === "done") return 1;
        if (handle === "default") return 999;
        if (handle.startsWith("case-")) {
          const index = parseInt(handle.split("-")[1] || "", 10);
          if (!Number.isNaN(index)) return index;
        }
        return 100;
      };

      return getOrder(handleA) - getOrder(handleB);
    });

    currentLevel = nextLevel;
  }

  layoutNodes.filter(n => !visited.has(n.id)).forEach(n => {
    levels.push([n.id]);
    visited.add(n.id);
  });

  const NODE_WIDTH = 200;
  const NODE_HEIGHT = 80;
  const HORIZONTAL_GAP = 100;
  const VERTICAL_GAP = 60;
  const LOOP_BRANCH_OFFSET = 200;
  const DONE_BRANCH_OFFSET = 50;
  /** Extra horizontal pitch after a column that contains a batch-mode LLM (OUT + STATUS breathing room). */
  const BATCH_LLM_INTER_COLUMN_EXTRA = 80;
  const START_X = 50;
  const START_Y = 200;
  const STRIDE = NODE_HEIGHT + VERTICAL_GAP;

  const loopBranchNodes = new Set<string>();
  const doneBranchNodes = new Set<string>();
  const loopNodes = layoutNodes.filter(n => n.type === "loop").map(n => n.id);

  loopNodes.forEach(loopId => {
    const loopOutEdges = forwardEdges.filter(e => e.source === loopId && e.sourceHandle === "loop");
    const toVisit = loopOutEdges.map(e => e.target);

    while (toVisit.length > 0) {
      const nodeId = toVisit.shift()!;
      if (loopBranchNodes.has(nodeId) || nodeId === loopId) continue;
      loopBranchNodes.add(nodeId);

      const childEdges = forwardEdges.filter(e => e.source === nodeId);
      childEdges.forEach(e => {
        if (!loopBranchNodes.has(e.target) && e.target !== loopId) {
          toVisit.push(e.target);
        }
      });
    }

    const doneOutEdges = forwardEdges.filter(e => e.source === loopId && e.sourceHandle === "done");
    const doneToVisit = doneOutEdges.map(e => e.target);

    while (doneToVisit.length > 0) {
      const nodeId = doneToVisit.shift()!;
      if (doneBranchNodes.has(nodeId) || loopBranchNodes.has(nodeId)) continue;
      doneBranchNodes.add(nodeId);

      const childEdges = forwardEdges.filter(e => e.source === nodeId);
      childEdges.forEach(e => {
        if (!doneBranchNodes.has(e.target) && !loopBranchNodes.has(e.target)) {
          doneToVisit.push(e.target);
        }
      });
    }
  });

  const nodePositions = new Map<string, { x: number; y: number }>();

  const columnX: number[] = [START_X];
  for (let k = 1; k < levels.length; k++) {
    const prevHasBatchLlm = levels[k - 1].some((id) => {
      const n = layoutNodes.find((nn) => nn.id === id);
      return n?.type === "llm" && n.data?.batchModeEnabled === true;
    });
    const extra = prevHasBatchLlm ? BATCH_LLM_INTER_COLUMN_EXTRA : 0;
    columnX.push(columnX[k - 1] + NODE_WIDTH + HORIZONTAL_GAP + extra);
  }

  levels.forEach((level, levelIndex) => {
    const mainNodes = level.filter(
      id => !loopBranchNodes.has(id) && !doneBranchNodes.has(id) && !subAgentNodeIds.has(id)
    );
    const loopNodes = level.filter(id => loopBranchNodes.has(id) && !subAgentNodeIds.has(id));
    const doneNodes = level.filter(id => doneBranchNodes.has(id) && !subAgentNodeIds.has(id));

    const x = columnX[levelIndex] ?? START_X;
    const firstMainY = START_Y;

    loopNodes.forEach((nodeId, nodeIndex) => {
      const y = START_Y - LOOP_BRANCH_OFFSET + nodeIndex * STRIDE;
      nodePositions.set(nodeId, { x, y });
      workflowStore.updateNodePosition(nodeId, { x, y });
    });

    mainNodes.forEach((nodeId, nodeIndex) => {
      const y = firstMainY + nodeIndex * STRIDE;
      nodePositions.set(nodeId, { x, y });
      workflowStore.updateNodePosition(nodeId, { x, y });
    });

    doneNodes.forEach((nodeId, nodeIndex) => {
      const y = START_Y + DONE_BRANCH_OFFSET + nodeIndex * STRIDE;
      nodePositions.set(nodeId, { x, y });
      workflowStore.updateNodePosition(nodeId, { x, y });
    });
  });

  /** Batch LLM only: vertically center between OUT / STATUS (or single branch + virtual row). */
  layoutNodes.forEach((node) => {
    const nodeId = node.id;
    if (subAgentNodeIds.has(nodeId)) return;
    if (node.type !== "llm" || !node.data?.batchModeEnabled) return;

    const childTargets = [
      ...new Set(forwardEdges.filter((e) => e.source === nodeId).map((e) => e.target)),
    ];
    if (childTargets.length < 1) return;

    const ys: number[] = [];
    for (const cid of childTargets) {
      const p = nodePositions.get(cid);
      if (p !== undefined) ys.push(p.y);
    }
    if (childTargets.length === 1 && ys.length === 1) {
      ys.push(ys[0] + STRIDE);
    }
    if (ys.length < 2) return;

    const newY = (Math.min(...ys) + Math.max(...ys)) / 2;
    const pos = nodePositions.get(nodeId);
    if (pos === undefined) return;
    pos.y = newY;
    workflowStore.updateNodePosition(nodeId, { x: pos.x, y: newY });
  });

  orchestratorToSubAgents.forEach((subIds, orchId) => {
    const pos = nodePositions.get(orchId);
    if (!pos) return;
    const subY = pos.y + STRIDE;
    const orchCenterX = pos.x + NODE_WIDTH / 2;
    const totalSubWidth =
      subIds.length * NODE_WIDTH + (subIds.length - 1) * HORIZONTAL_GAP;
    const startX = orchCenterX - totalSubWidth / 2;
    subIds.forEach((subId, index) => {
      const x = startX + index * (NODE_WIDTH + HORIZONTAL_GAP);
      workflowStore.updateNodePosition(subId, { x, y: subY });
    });
  });

  void nextTick(() => {
    updateNodeInternals(nodes.map((n) => n.id));
    setTimeout(() => fitView({ padding: 0.2 }), 100);
  });
}

function handleKeyDown(event: KeyboardEvent): void {
  if (agentMemoryDialogOpen.value) {
    return;
  }
  const target = event.target as HTMLElement;
  if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable) {
    return;
  }

  if (event.key === "Escape") {
    workflowStore.clearNodeSearchQuery();
    workflowStore.clearPendingConnectionSource();
    workflowStore.clearPendingInsertEdge();
    removeSelectedNodes(getSelectedNodes.value);
    nodesSelectionActive.value = false;
    return;
  }

  if ((event.ctrlKey || event.metaKey) && event.key === "a") {
    event.preventDefault();
    workflowStore.selectAllNodes();
    addSelectedNodes(getNodes.value);
    nodesSelectionActive.value = true;
    return;
  }

  if (event.key === "Delete" || event.key === "Backspace") {
    const selectedEdges = getSelectedEdges.value;
    const hasSelectedNodes = workflowStore.selectedNodeIds.size > 0;
    const hasSelectedEdges = selectedEdges.length > 0;

    if (hasSelectedNodes || hasSelectedEdges) {
      event.preventDefault();

      if (hasSelectedEdges) {
        selectedEdges.forEach((edge) => {
          workflowStore.removeEdge(edge.id);
        });
      }

      if (hasSelectedNodes) {
        workflowStore.removeSelectedNodes();
      }
      workflowStore.clearNodeSearchQuery();
      return;
    }

    if (event.key === "Backspace") {
      const currentQuery = workflowStore.nodeSearchQuery;
      if (currentQuery.length > 0) {
        workflowStore.setNodeSearchQuery(currentQuery.slice(0, -1));
      }
      return;
    }
  }

  if (event.key === "d" || event.key === "D") {
    if (!workflowStore.nodeSearchQuery) {
      if (workflowStore.selectedNodeIds.size > 1) {
        workflowStore.toggleSelectedNodesActive();
        return;
      } else if (workflowStore.selectedNodeId) {
        workflowStore.toggleNodeActive(workflowStore.selectedNodeId);
        return;
      }
    }
  }

  if (event.key === "p" || event.key === "P") {
    if (workflowStore.selectedNodeId && !workflowStore.nodeSearchQuery) {
      if (workflowStore.canTogglePin(workflowStore.selectedNodeId)) {
        workflowStore.togglePinnedData(workflowStore.selectedNodeId);
        return;
      }
    }
  }

  if ((event.ctrlKey || event.metaKey) && event.key === "c") {
    if (workflowStore.selectedNodeIds.size > 0) {
      event.preventDefault();
      workflowStore.copyNode();
    }
    return;
  }

  if ((event.ctrlKey || event.metaKey) && event.key === "x") {
    if (workflowStore.selectedNodeIds.size > 0) {
      event.preventDefault();
      workflowStore.cutNode();
    }
    return;
  }

  if ((event.ctrlKey || event.metaKey) && event.key === "v") {
    event.preventDefault();
    void workflowStore.pasteNode();
    return;
  }

  if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
    event.preventDefault();
    workflowStore.setNodeSearchQuery(workflowStore.nodeSearchQuery + event.key);
  }
}

const isShiftHeld = ref(false);

function handleGlobalKeyDown(event: KeyboardEvent): void {
  if (event.key === "Shift") {
    isShiftHeld.value = true;
  }
}

function handleGlobalKeyUp(event: KeyboardEvent): void {
  if (event.key === "Shift") {
    isShiftHeld.value = false;
  }
}

function preventTextSelection(event: Event): void {
  if (isShiftHeld.value) {
    event.preventDefault();
  }
}

function handleSelectionRectContextMenu(event: MouseEvent): void {
  const target = event.target as HTMLElement;
  if (!target?.classList?.contains("vue-flow__nodesselection-rect")) {
    return;
  }

  if (workflowStore.selectedNodeIds.size === 0) {
    return;
  }

  event.preventDefault();
  event.stopPropagation();

  contextMenuPosition.value = { x: event.clientX, y: event.clientY };
  contextMenuVisible.value = true;
}

onMounted(() => {
  setTimeout(() => fitView({ padding: 0.2 }), 100);
  window.addEventListener("keydown", handleKeyDown);
  window.addEventListener("keydown", handleGlobalKeyDown);
  window.addEventListener("keyup", handleGlobalKeyUp);
  document.addEventListener("selectstart", preventTextSelection);
  document.addEventListener("contextmenu", handleSelectionRectContextMenu, true);
});

onUnmounted(() => {
  if (fitAfterLayoutTimer !== null) {
    window.clearTimeout(fitAfterLayoutTimer);
    fitAfterLayoutTimer = null;
  }
  workflowStore.setAgentMemoryGraphDialogOpen(false);
  window.removeEventListener("keydown", handleKeyDown);
  window.removeEventListener("keydown", handleGlobalKeyDown);
  window.removeEventListener("keyup", handleGlobalKeyUp);
  document.removeEventListener("selectstart", preventTextSelection);
  document.removeEventListener("contextmenu", handleSelectionRectContextMenu, true);
});

watch(
  () => workflowStore.nodes.length,
  () => {
    setTimeout(() => fitView({ padding: 0.2 }), 100);
  }
);

// Auto-center canvas when debug panel height changes (after CSS height transition + layout)
watch(
  () => workflowStore.debugPanelHeight,
  () => {
    scheduleFitViewAfterLayout();
  }
);

watch(
  () => workflowStore.isExecuting,
  (executing) => {
    if (executing) {
      scheduleFitViewAfterLayout();
    }
  }
);

// Watch for tidy up request from other components
watch(
  () => workflowStore.shouldTidyUp,
  (shouldTidy) => {
    if (shouldTidy) {
      setTimeout(() => {
        tidyUp();
        workflowStore.clearTidyUp();
      }, 50);
    }
  }
);

// Watch for output node allowDownstream changes to update handles and remove edges
watch(
  () => workflowStore.nodes.map((n) => n.type === "output" ? n.data.allowDownstream : null),
  (newVal, oldVal) => {
    if (oldVal && newVal) {
      workflowStore.nodes.forEach((node, index) => {
        if (node.type === "output") {
          const wasEnabled = oldVal[index] === true;
          const isEnabled = newVal[index] === true;

          if (wasEnabled !== isEnabled) {
            updateNodeInternals([node.id]);

            if (wasEnabled && !isEnabled) {
              const outgoingEdges = workflowStore.edges.filter((e) => e.source === node.id);
              outgoingEdges.forEach((edge) => {
                workflowStore.removeEdge(edge.id);
              });
            }
          }
        }
      });
    }
  },
  { deep: true }
);

watch(
  () => workflowStore.nodes.map((n) => (n.type === "llm" ? n.data.batchModeEnabled : null)),
  (newVal, oldVal) => {
    if (oldVal && newVal) {
      workflowStore.nodes.forEach((node, index) => {
        if (node.type !== "llm") return;

        const wasEnabled = oldVal[index] === true;
        const isEnabled = newVal[index] === true;
        if (wasEnabled === isEnabled) return;

        updateNodeInternals([node.id]);
        if (wasEnabled && !isEnabled) {
          const outgoingEdges = workflowStore.edges.filter(
            (edge) => edge.source === node.id && edge.sourceHandle === "batchStatus",
          );
          outgoingEdges.forEach((edge) => {
            workflowStore.removeEdge(edge.id);
          });
        }
      });
    }
  },
  { deep: true },
);
</script>

<template>
  <div
    class="w-full h-full select-none relative overflow-x-hidden"
    @drop="handleDrop"
    @dragover="handleDragOver"
    @dragleave="handleDragLeave"
  >
    <Transition
      enter-active-class="transition-opacity duration-200"
      leave-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
    >
      <div
        v-if="isDraggingFile"
        class="absolute inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm border-2 border-dashed border-primary rounded-lg pointer-events-none"
      >
        <div class="flex flex-col items-center gap-3 text-primary">
          <FileJson class="w-16 h-16" />
          <span class="text-lg font-medium">Drop JSON to import workflow</span>
        </div>
      </div>
    </Transition>
    <VueFlow
      :nodes="vueFlowNodes"
      :edges="vueFlowEdges"
      :default-viewport="{ zoom: 1 }"
      :min-zoom="0.2"
      :max-zoom="2"
      :snap-to-grid="true"
      :snap-grid="[15, 15]"
      :connection-radius="50"
      :selection-key-code="'Shift'"
      :multi-selection-key-code="['Meta', 'Control']"
      :delete-key-code="null"
      :selection-mode="SelectionMode.Partial"
      :edges-updatable="true"
      fit-view-on-init
      @node-click="handleNodeClick"
      @node-double-click="handleNodeDoubleClick"
      @node-context-menu="handleNodeContextMenu"
      @edge-double-click="handleEdgeDoubleClick"
    >
      <template #node-custom="{ id, data, selected }">
        <StickyNoteNode
          v-if="data.nodeType === 'sticky'"
          :id="id"
          :data="data"
          :selected="selected"
        />
        <BaseNode
          v-else
          :id="id"
          :type="data.nodeType"
          :data="data"
          :selected="selected"
          @open-agent-memory="handleOpenAgentMemory"
        />
      </template>

      <template #edge-insertable="props">
        <InsertableEdge v-bind="props" />
      </template>

      <Background
        pattern-color="hsl(var(--muted-foreground) / 0.1)"
        :gap="20"
      />
      <Controls position="bottom-left">
        <ControlButton
          title="Tidy Up - Auto arrange nodes"
          @click="tidyUp"
        >
          <LayoutGrid class="w-3.5 h-3.5" />
        </ControlButton>
      </Controls>

      <MiniMap
        position="bottom-right"
        :pannable="true"
        :zoomable="true"
        :node-color="() => 'hsl(var(--primary))'"
        class="hidden md:block"
      />
    </VueFlow>

    <NodeContextMenu
      :visible="contextMenuVisible"
      :position="contextMenuPosition"
      :selected-count="contextMenuSelectedCount"
      :has-disabled-nodes="contextMenuHasDisabledNodes"
      :all-disabled="contextMenuAllDisabled"
      :eval-node="contextMenuEvalNode"
      @extract="handleContextMenuExtract"
      @eval-agent="handleContextMenuEvalAgent"
      @disable="handleContextMenuDisable"
      @duplicate="handleContextMenuDuplicate"
      @delete="handleContextMenuDelete"
      @share-as-template="handleContextMenuShareAsTemplate"
      @close="closeContextMenu"
    />

    <ShareTemplateModal
      v-if="shareNodeTemplateOpen && shareNodeTemplateData"
      kind="node"
      :node-type="shareNodeTemplateData.type"
      :node-data="shareNodeTemplateData.data"
      @close="shareNodeTemplateOpen = false"
      @shared="shareNodeTemplateOpen = false"
    />

    <ExtractSubWorkflowDialog
      :open="extractDialogOpen"
      @close="extractDialogOpen = false"
      @extracted="handleExtracted"
    />

    <AgentMemoryGraphDialog
      :open="agentMemoryDialogOpen"
      :workflow-id="workflowStore.currentWorkflow?.id"
      :canvas-node-id="agentMemoryCanvasNodeId ?? undefined"
      @close="closeAgentMemoryDialog"
    />
  </div>
</template>
