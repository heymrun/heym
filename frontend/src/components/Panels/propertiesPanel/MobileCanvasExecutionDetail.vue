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
    @close="workflowStore.closeMobileNodeExecutionDetail"
  />
</template>
