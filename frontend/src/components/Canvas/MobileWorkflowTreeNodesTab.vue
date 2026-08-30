<script setup lang="ts">
import { computed, ref } from "vue";

import MobileWorkflowTreeConnectionSheet from "@/components/Canvas/MobileWorkflowTreeConnectionSheet.vue";
import MobileWorkflowTreeEditor from "@/components/Canvas/MobileWorkflowTreeEditor.vue";
import MobileWorkflowTreeNode from "@/components/Canvas/MobileWorkflowTreeNode.vue";
import { buildMobileWorkflowTree } from "@/components/Canvas/mobileWorkflowTree";
import {
  connectMobileWorkflowNode,
  type MobileWorkflowConnectionMode,
} from "@/components/Canvas/mobileWorkflowTreeConnections";
import { TOOL_INPUT_HANDLE, isNoRegularInputNodeType } from "@/lib/canvasConnectionRules";
import { generateId } from "@/lib/utils";
import { NODE_DEFINITIONS } from "@/types/node";
import type { NodeType, WorkflowNode } from "@/types/workflow";
import { useWorkflowStore } from "@/stores/workflow";

const emit = defineEmits<{ (event: "open-properties"): void }>();

const workflowStore = useWorkflowStore();
const isEditing = ref(false);
const connectionSheetOpen = ref(false);
const connectionInitialAnchorId = ref<string | null>(null);
const connectionInitialMode = ref<MobileWorkflowConnectionMode>("after");
const treeEntries = computed(() => buildMobileWorkflowTree(workflowStore.nodes, workflowStore.edges));
const selectedNode = computed(() => workflowStore.selectedNode);
const selectedLabel = computed(() => {
  if (!selectedNode.value) return null;
  return String(selectedNode.value.data.label || NODE_DEFINITIONS[selectedNode.value.type].label);
});
const canConnectSelectedNode = computed(
  () => selectedNode.value !== null && !isNoRegularInputNodeType(selectedNode.value.type),
);
function setEditMode(value: boolean): void {
  isEditing.value = value;
}

function addNode(nodeType: NodeType): void {
  const sourceNode = workflowStore.selectedNode;
  const bottomPosition = Math.max(0, ...workflowStore.nodes.map((node) => node.position.y));
  const node: WorkflowNode = {
    id: generateId(),
    type: nodeType,
    position: sourceNode
      ? { x: sourceNode.position.x, y: sourceNode.position.y + 160 }
      : { x: 0, y: bottomPosition + 160 },
    data: { ...NODE_DEFINITIONS[nodeType].defaultData },
  };
  workflowStore.addNode(node);
  workflowStore.selectNode(node.id);

  if (isNoRegularInputNodeType(node.type)) {
    emit("open-properties");
    return;
  }
  connectionInitialAnchorId.value = sourceNode?.id ?? null;
  connectionInitialMode.value = "after";
  connectionSheetOpen.value = true;
}

function openConnectionSheet(): void {
  if (!canConnectSelectedNode.value) return;
  const binding = currentBinding(selectedNode.value);
  connectionInitialAnchorId.value = binding?.anchorId ?? null;
  connectionInitialMode.value = binding?.mode ?? "after";
  connectionSheetOpen.value = true;
}

function currentBinding(node: WorkflowNode | null): {
  anchorId: string;
  mode: MobileWorkflowConnectionMode;
} | null {
  if (!node) return null;
  const regularEdges = workflowStore.edges.filter((edge) => edge.targetHandle !== TOOL_INPUT_HANDLE);
  const incoming = regularEdges.filter((edge) => edge.target === node.id);
  if (incoming.length > 0) {
    const anchorId = incoming[0].source;
    const outgoingCount = regularEdges.filter((edge) => edge.source === anchorId).length;
    return { anchorId, mode: outgoingCount > 1 ? "parallel" : "after" };
  }
  const outgoing = regularEdges.find((edge) => edge.source === node.id);
  return outgoing ? { anchorId: outgoing.target, mode: "before" } : null;
}

function connectSelectedNode(payload: { anchorId: string; mode: MobileWorkflowConnectionMode }): void {
  const node = workflowStore.selectedNode;
  const anchor = workflowStore.nodes.find((item) => item.id === payload.anchorId);
  if (!node || !anchor) return;
  connectMobileWorkflowNode({
    node,
    anchor,
    mode: payload.mode,
    edges: workflowStore.edges,
    addEdge: workflowStore.addEdge,
    removeEdge: workflowStore.removeEdge,
    updateNodePosition: workflowStore.updateNodePosition,
  });
  connectionSheetOpen.value = false;
}

function removeSelectedNode(): void {
  const node = workflowStore.selectedNode;
  if (!node || !window.confirm(`Remove ${node.data.label || NODE_DEFINITIONS[node.type].label}?`)) return;
  workflowStore.removeNode(node.id);
}
</script>

<template>
  <div class="space-y-1">
    <MobileWorkflowTreeEditor
      :node-count="treeEntries.length"
      :selected-label="selectedLabel"
      @add="addNode"
      @edit-mode="setEditMode"
      @remove="removeSelectedNode"
    />
    <p
      v-if="treeEntries.length === 0"
      class="rounded-xl border border-dashed border-border p-4 text-center text-xs text-muted-foreground"
    >
      Add nodes to start building this workflow.
    </p>
    <MobileWorkflowTreeNode
      v-for="entry in treeEntries"
      :key="entry.node.id"
      :entry="entry"
      :edit-mode="isEditing"
      @edit-node="openConnectionSheet"
      @idle-node="emit('open-properties')"
    />
  </div>

  <MobileWorkflowTreeConnectionSheet
    :open="connectionSheetOpen"
    :node="selectedNode"
    :nodes="workflowStore.nodes"
    :initial-anchor-id="connectionInitialAnchorId"
    :initial-mode="connectionInitialMode"
    @close="connectionSheetOpen = false"
    @connect="connectSelectedNode"
  />
</template>
