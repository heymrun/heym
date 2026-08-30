<script setup lang="ts">
import { computed, watch } from "vue";

import MobileNodeExecutionDetail from "@/components/Panels/propertiesPanel/MobileNodeExecutionDetail.vue";
import { useWorkflowStore } from "@/stores/workflow";
import type { NodeResult } from "@/types/workflow";

const workflowStore = useWorkflowStore();

const nodeId = computed(() => workflowStore.mobileNodeExecutionDetailNodeId);
const node = computed(() => workflowStore.nodes.find((item) => item.id === nodeId.value) ?? null);
const result = computed<NodeResult | null>(() => {
  if (!nodeId.value) return null;
  return workflowStore.getLatestNodeResult(nodeId.value);
});
const isOpen = computed(() => nodeId.value !== null && result.value !== null);
const orderedResults = computed<NodeResult[]>(() =>
  workflowStore.executionResult?.node_results ?? workflowStore.nodeResults,
);
const resultIndex = computed(() => orderedResults.value.findIndex((item) => item.node_id === nodeId.value));
const previousResult = computed(() =>
  resultIndex.value > 0 ? orderedResults.value[resultIndex.value - 1] : null,
);
const nextResult = computed(() => {
  const nextIndex = resultIndex.value + 1;
  return resultIndex.value >= 0 && nextIndex < orderedResults.value.length
    ? orderedResults.value[nextIndex]
    : null;
});

function openNodeProperties(): void {
  workflowStore.propertiesPanelTab = "properties";
  workflowStore.mobileEditorTab = "properties";
  workflowStore.closeMobileNodeExecutionDetail();
}

function showAdjacentNode(offset: -1 | 1): void {
  const target = offset < 0 ? previousResult.value : nextResult.value;
  if (!target) return;
  workflowStore.selectNode(target.node_id);
  workflowStore.openMobileNodeExecutionDetail(target.node_id);
}

watch(result, (value) => {
  if (nodeId.value !== null && value === null) {
    workflowStore.closeMobileNodeExecutionDetail();
  }
});
</script>

<template>
  <MobileNodeExecutionDetail
    :open="isOpen"
    :result="result"
    :node="node"
    :output="result?.output ?? null"
    :workflow-name="workflowStore.currentWorkflow?.name ?? 'Workflow'"
    :previous-node-label="previousResult?.node_label ?? null"
    :next-node-label="nextResult?.node_label ?? null"
    @close="workflowStore.closeMobileNodeExecutionDetail"
    @previous="showAdjacentNode(-1)"
    @next="showAdjacentNode(1)"
    @properties="openNodeProperties"
  />
</template>
