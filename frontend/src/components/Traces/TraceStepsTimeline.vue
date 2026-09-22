<script setup lang="ts">
import { nextTick, ref, watch } from "vue";

import type { TraceStep } from "@/lib/traceSteps";

import TraceStepCard from "@/components/Traces/TraceStepCard.vue";

const props = defineProps<{
  steps: TraceStep[];
}>();

const openIds = ref<Set<string>>(new Set());

function toggle(id: string): void {
  const next = new Set(openIds.value);
  if (next.has(id)) {
    next.delete(id);
  } else {
    next.add(id);
  }
  openIds.value = next;
}

/** Open a step and bring it into view; used when a duration row points at it. */
async function focusStep(id: string): Promise<void> {
  if (!openIds.value.has(id)) {
    openIds.value = new Set(openIds.value).add(id);
  }
  await nextTick();
  const card = document.querySelector(`[data-testid="trace-step-${id}"]`);
  card?.scrollIntoView({ behavior: "smooth", block: "center" });
}

defineExpose({ focusStep });

// Collapse everything when the step set changes (navigating between traces).
watch(
  () => props.steps,
  () => {
    openIds.value = new Set();
  },
);
</script>

<template>
  <div class="space-y-2">
    <div class="text-sm font-medium">
      Steps
    </div>
    <div class="space-y-2">
      <TraceStepCard
        v-for="step in steps"
        :key="step.id"
        :step="step"
        :open="openIds.has(step.id)"
        @toggle="toggle(step.id)"
      />
    </div>
  </div>
</template>
