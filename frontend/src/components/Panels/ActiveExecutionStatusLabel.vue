<script setup lang="ts">
import { computed } from "vue";
import { Clock, Loader2 } from "lucide-vue-next";

import type { ActiveExecutionItem } from "@/types/workflow";
import { activeExecutionStatus } from "@/components/Panels/activeExecutionStatus";

const props = withDefaults(defineProps<{ item: ActiveExecutionItem; size?: "sm" | "md" }>(), {
  size: "sm",
});

const view = computed(() => activeExecutionStatus(props.item));
const iconClass = computed(() => (props.size === "md" ? "w-4 h-4" : "w-3 h-3"));
const textClass = computed(() => (props.size === "md" ? "text-sm" : "text-xs"));
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5"
    :data-testid="`active-execution-status-${item.execution_id}`"
  >
    <Clock
      v-if="view.kind === 'queued'"
      class="text-amber-500 shrink-0"
      :class="iconClass"
    />
    <Loader2
      v-else
      class="text-blue-400 animate-spin shrink-0"
      :class="iconClass"
    />
    <span
      class="font-medium"
      :class="[textClass, view.kind === 'queued' ? 'text-amber-500' : 'text-blue-400']"
    >{{ view.label }}</span>
  </span>
</template>
