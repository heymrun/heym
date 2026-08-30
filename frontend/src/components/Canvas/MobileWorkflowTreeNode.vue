<script setup lang="ts">
import { computed } from "vue";
import { GitBranch } from "lucide-vue-next";

import type { MobileWorkflowTreeAccent, MobileWorkflowTreeEntry } from "@/components/Canvas/mobileWorkflowTree";
import { isTileFillingIcon, nodeIconColorClass, nodeIcons } from "@/lib/nodeIcons";
import { NODE_DEFINITIONS } from "@/types/node";
import type { NodeResult, WorkflowNode } from "@/types/workflow";
import { useWorkflowStore } from "@/stores/workflow";

interface Props {
  entry: MobileWorkflowTreeEntry;
  editMode?: boolean;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (event: "idle-node"): void;
  (event: "edit-node"): void;
}>();
const workflowStore = useWorkflowStore();
const result = computed(() => workflowStore.getLatestNodeResult(props.entry.node.id));

function formatDuration(value: number | undefined): string {
  if (!value) return "—";
  return value < 1_000 ? `${Math.round(value)}ms` : `${(value / 1_000).toFixed(1)}s`;
}

function nodeLabel(node: WorkflowNode): string {
  return String(node.data.label || NODE_DEFINITIONS[node.type].label);
}

function nodeSummary(node: WorkflowNode): string {
  const data = node.data as unknown as Record<string, unknown>;
  for (const key of ["url", "path", "operation", "model", "prompt", "message", "code"]) {
    const value = data[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return NODE_DEFINITIONS[node.type].description;
}

function accentClass(accent: MobileWorkflowTreeAccent): string {
  return {
    violet: "bg-violet-300 dark:bg-violet-400",
    emerald: "bg-emerald-400",
    amber: "bg-amber-400",
  }[accent];
}

function statusClass(nodeResult: NodeResult | null): string {
  if (nodeResult?.status === "error") return "bg-destructive";
  if (nodeResult?.status === "success") return "bg-emerald-400";
  if (nodeResult?.status === "running") return "bg-amber-400";
  return "bg-muted-foreground/60";
}

function selectNode(): void {
  workflowStore.selectNode(props.entry.node.id);
  if (props.editMode) {
    emit("edit-node");
    return;
  }
  if (result.value !== null) {
    workflowStore.openMobileNodeExecutionDetail(props.entry.node.id);
    return;
  }
  emit("idle-node");
}
</script>

<template>
  <div class="relative">
    <div
      class="relative"
      :style="{ marginLeft: `${entry.depth * 16}px` }"
    >
      <span
        v-if="entry.depth > 0"
        class="absolute -left-2 top-0 h-[calc(100%+0.5rem)] w-0.5"
        :class="accentClass(entry.accent)"
      />
      <button
        type="button"
        class="mobile-workflow-node"
        :class="{ 'border-primary/60 bg-primary/5': workflowStore.selectedNodeId === entry.node.id }"
        @click="selectNode"
      >
        <div class="flex min-w-0 items-center gap-2">
          <span
            class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-emerald-500/10"
            :class="nodeIconColorClass[entry.node.type]"
          >
            <component
              :is="nodeIcons[entry.node.type]"
              :class="isTileFillingIcon(entry.node.type) ? 'h-full w-full' : 'h-3 w-3'"
            />
          </span>
          <span class="min-w-0 text-left">
            <strong class="block truncate text-[13px]">{{ nodeLabel(entry.node) }}</strong>
            <span class="block truncate text-[11px] text-muted-foreground">{{ nodeSummary(entry.node) }}</span>
          </span>
        </div>
        <span class="flex shrink-0 items-center gap-1.5">
          <template v-if="result">
            <span class="font-mono text-[10px] text-muted-foreground">{{ formatDuration(result?.execution_time_ms) }}</span>
            <span
              class="h-1.5 w-1.5 rounded-full"
              :class="statusClass(result)"
            />
          </template>
        </span>
      </button>
    </div>
    <p
      v-if="entry.parallelChildCount > 0"
      class="relative flex h-4 items-center gap-1.5 pl-1 text-[10px] font-medium text-violet-300"
      :style="{ marginLeft: `${entry.depth * 16}px` }"
    >
      <GitBranch class="h-3 w-3" />{{ entry.parallelChildCount }} branches
    </p>
  </div>
</template>

<style scoped>
.mobile-workflow-node { @apply flex w-full items-center justify-between gap-3 rounded-xl border border-border/80 bg-card p-2.5 text-foreground transition-colors active:border-primary/60 active:bg-primary/5; }
</style>
