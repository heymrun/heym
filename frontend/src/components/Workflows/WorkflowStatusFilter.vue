<script setup lang="ts">
import { computed } from "vue";
import { Check, ChevronDown, Filter } from "lucide-vue-next";
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuTrigger,
} from "radix-vue";

import type { WorkflowRowStatus } from "@/types/workflow";

export type WorkflowStatusFilterValue = WorkflowRowStatus | "all";

interface Props {
  modelValue: WorkflowStatusFilterValue;
  /** How many workflows each status currently matches, for the counts in the menu. */
  counts?: Partial<Record<WorkflowStatusFilterValue, number>>;
}

const props = withDefaults(defineProps<Props>(), { counts: () => ({}) });

const emit = defineEmits<{
  "update:modelValue": [value: WorkflowStatusFilterValue];
}>();

const OPTIONS: { value: WorkflowStatusFilterValue; label: string }[] = [
  { value: "all", label: "All" },
  { value: "running", label: "Running" },
  { value: "scheduled", label: "Scheduled" },
  { value: "listening", label: "Listening" },
  { value: "paused", label: "Paused" },
  { value: "manual", label: "Manual" },
  { value: "api", label: "API" },
  { value: "subWorkflow", label: "SubWorker" },
  { value: "portal", label: "Portal" },
  { value: "web", label: "WEB" },
  { value: "removeScheduled", label: "Remove Scheduled" },
];

const activeLabel = computed((): string => {
  return OPTIONS.find((option) => option.value === props.modelValue)?.label ?? "All";
});
</script>

<template>
  <DropdownMenuRoot>
    <DropdownMenuTrigger
      class="inline-flex h-11 min-h-[44px] items-center gap-2 rounded-xl border border-border bg-background px-3 text-sm shadow-sm transition-all duration-200 hover:border-border/80 focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/15 md:h-9 md:min-h-0"
      data-testid="workflow-status-filter"
      :aria-label="`Filter by status: ${activeLabel}`"
    >
      <Filter class="h-3.5 w-3.5 text-muted-foreground" />
      <span class="whitespace-nowrap">Status: {{ activeLabel }}</span>
      <ChevronDown class="h-3 w-3 text-muted-foreground" />
    </DropdownMenuTrigger>

    <DropdownMenuPortal>
      <DropdownMenuContent
        :side-offset="6"
        :collision-padding="12"
        align="end"
        class="z-[200] min-w-[13rem] overflow-hidden rounded-xl border border-border/70 bg-popover/95 p-1 text-popover-foreground shadow-xl backdrop-blur-xl"
      >
        <DropdownMenuItem
          v-for="option in OPTIONS"
          :key="option.value"
          :data-testid="`workflow-status-filter-${option.value}`"
          class="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm outline-none transition-colors data-[highlighted]:bg-muted/70"
          @select="emit('update:modelValue', option.value)"
        >
          <Check
            class="h-3.5 w-3.5 shrink-0"
            :class="modelValue === option.value ? 'text-primary' : 'text-transparent'"
          />
          <span class="flex-1">{{ option.label }}</span>
          <span
            v-if="counts[option.value] !== undefined"
            class="text-xs tabular-nums text-muted-foreground"
          >
            {{ counts[option.value] }}
          </span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenuRoot>
</template>
