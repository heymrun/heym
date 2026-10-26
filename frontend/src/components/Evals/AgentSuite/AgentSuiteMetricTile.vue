<script setup lang="ts">
import { computed } from "vue";

import { formatDeltaPct } from "@/components/Evals/AgentSuite/agentSuiteFormat";

interface Props {
  label: string;
  value: string;
  sub?: string;
  /** Change against the baseline; a rise reads as worse for every metric here. */
  deltaPct?: number | null;
  testId?: string;
}

const props = withDefaults(defineProps<Props>(), {
  sub: undefined,
  deltaPct: null,
  testId: undefined,
});

const deltaClass = computed((): string => {
  if (props.deltaPct === null || props.deltaPct === undefined || props.deltaPct === 0) {
    return "text-muted-foreground";
  }
  return props.deltaPct > 0 ? "text-destructive" : "text-emerald-600 dark:text-emerald-400";
});
</script>

<template>
  <div
    class="rounded-xl border border-border/60 bg-card px-4 py-3"
    :data-testid="testId"
  >
    <p class="text-xs font-medium text-muted-foreground">
      {{ label }}
    </p>
    <div class="mt-1 flex items-baseline gap-2">
      <span class="text-xl font-semibold tabular-nums text-foreground">{{ value }}</span>
      <span
        v-if="deltaPct !== null && deltaPct !== undefined"
        class="text-xs font-medium tabular-nums"
        :class="deltaClass"
      >
        {{ formatDeltaPct(deltaPct) }}
      </span>
    </div>
    <p
      v-if="sub"
      class="mt-0.5 truncate text-xs text-muted-foreground"
    >
      {{ sub }}
    </p>
  </div>
</template>
