<script setup lang="ts">
import { computed } from "vue";

import ExecutionTimeline from "@/components/Panels/ExecutionTimeline.vue";
import {
  buildDelegatedSubAgentLabelSet,
  buildSubAgentLabelToParentId,
  buildTimelineEntries,
  isDelegatedSubAgentRow,
  type TimelineEntry,
} from "@/components/Panels/executionTimeline";
import type { NodeResult, WorkflowEdge, WorkflowNode } from "@/types/workflow";

interface Props {
  /** Full `node_results` of the history entry. */
  nodeResults: NodeResult[];
  totalTimeMs: number;
  /** The run's workflow graph: sub-agent rows come from its nodes, span inputs from its edges. */
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

const props = defineProps<Props>();

const delegatedSubAgentLabels = computed(() => buildDelegatedSubAgentLabelSet(props.nodes));
const subAgentLabelToParentId = computed(() => buildSubAgentLabelToParentId(props.nodes));
const timelineEntries = computed((): TimelineEntry[] =>
  buildTimelineEntries(props.nodeResults, (row) =>
    isDelegatedSubAgentRow(row, delegatedSubAgentLabels.value),
  ),
);
</script>

<template>
  <div
    v-if="timelineEntries.length > 0"
    class="flex max-h-[26rem] min-h-0 flex-col overflow-hidden rounded-md border"
    data-testid="execution-history-timeline"
  >
    <ExecutionTimeline
      class="flex-1 min-h-0"
      :node-results="timelineEntries"
      :execution-rows="nodeResults"
      :edges="edges"
      :total-time-ms="totalTimeMs"
      :sub-agent-label-to-parent-id="subAgentLabelToParentId"
    />
  </div>
  <div
    v-else
    class="rounded-md border py-6 text-center text-xs text-muted-foreground"
  >
    No node spans recorded for this run.
  </div>
</template>
