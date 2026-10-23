<script setup lang="ts">
import { computed } from "vue";

import type { HitlFilter } from "@/types/dashboard";
import HitlFilterFields from "@/components/Dashboards/HitlFilterFields.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode, updateNodeData } = usePropertiesPanelContext();

// The node keeps the choice as hitlWorkflowId / hitlNodeId; the fields edit it as one filter.
const filter = computed<HitlFilter | null>(() => {
  const data = (selectedNode.value?.data ?? {}) as Record<string, unknown>;
  const workflowId = typeof data.hitlWorkflowId === "string" ? data.hitlWorkflowId.trim() : "";
  if (!workflowId) return null;
  const nodeId = typeof data.hitlNodeId === "string" ? data.hitlNodeId.trim() : "";
  return { workflow_id: workflowId, node_id: nodeId || null };
});

function onChange(value: HitlFilter | null): void {
  updateNodeData("hitlWorkflowId", value?.workflow_id ?? undefined);
  updateNodeData("hitlNodeId", value?.node_id ?? undefined);
}
</script>

<template>
  <HitlFilterFields
    :model-value="filter"
    @update:model-value="onChange"
  />
</template>
