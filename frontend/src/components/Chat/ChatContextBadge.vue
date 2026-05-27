<script setup lang="ts">
import { computed, ref } from "vue";

import type { ContextUsage } from "@/types/chat";

interface Props {
  contextUsage: ContextUsage | null;
  draftTokens?: number;
}

const props = withDefaults(defineProps<Props>(), { draftTokens: 0 });

const usedTotal = computed(() =>
  props.contextUsage ? props.contextUsage.used + (props.draftTokens ?? 0) : 0,
);

const pct = computed(() => {
  if (!props.contextUsage || props.contextUsage.limit <= 0) return 0;
  return Math.min(100, Math.round((usedTotal.value / props.contextUsage.limit) * 100));
});

const ringColor = computed(() => {
  if (pct.value >= 95) return "hsl(var(--destructive))";
  if (pct.value >= 80) return "hsl(40 95% 55%)";
  return "hsl(var(--primary))";
});

const ringStyle = computed(() => ({
  background: `conic-gradient(${ringColor.value} ${pct.value * 3.6}deg, hsl(var(--muted)) 0)`,
}));

const usedDisplay = computed(() => {
  const k = usedTotal.value / 1000;
  return k >= 10 ? `${Math.round(k)}k` : `${k.toFixed(1)}k`;
});

const isOpen = ref(false);

function formatK(n: number): string {
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return `${n}`;
}
</script>

<template>
  <div
    v-if="contextUsage"
    class="relative inline-flex"
    @mouseenter="isOpen = true"
    @mouseleave="isOpen = false"
  >
    <button
      type="button"
      class="inline-flex items-center gap-1.5 rounded-full bg-muted/50 hover:bg-muted/70 border border-border/40 px-2 py-0.5 text-[11px] text-muted-foreground transition-colors"
      :aria-label="`Context usage ${pct}%`"
      @click="isOpen = !isOpen"
    >
      <span
        class="w-3.5 h-3.5 rounded-full"
        :style="ringStyle"
      />
      <span class="tabular-nums">{{ pct }}% · ~{{ usedDisplay }}</span>
    </button>
    <div
      v-if="isOpen"
      class="absolute bottom-full left-0 mb-2 w-60 rounded-lg border border-border/60 bg-popover text-popover-foreground shadow-md p-3 text-xs space-y-1 z-10"
      role="tooltip"
    >
      <p class="text-[10px] uppercase tracking-wide text-muted-foreground/70 mb-1">
        Context usage
      </p>
      <div class="flex justify-between">
        <span>System prompt</span><span class="tabular-nums">{{ formatK(contextUsage.breakdown.system) }}</span>
      </div>
      <div class="flex justify-between">
        <span>AGENTS.md</span><span class="tabular-nums">{{ formatK(contextUsage.breakdown.agents_md) }}</span>
      </div>
      <div class="flex justify-between">
        <span>Workflows</span><span class="tabular-nums">{{ formatK(contextUsage.breakdown.workflows) }}</span>
      </div>
      <div class="flex justify-between">
        <span>User rules</span><span class="tabular-nums">{{ formatK(contextUsage.breakdown.user_rules) }}</span>
      </div>
      <div class="flex justify-between">
        <span>History</span><span class="tabular-nums">{{ formatK(contextUsage.breakdown.history) }}</span>
      </div>
      <div
        v-if="draftTokens && draftTokens > 0"
        class="flex justify-between"
      >
        <span>Draft</span><span class="tabular-nums">{{ formatK(draftTokens) }}</span>
      </div>
      <div class="flex justify-between border-t border-border/40 mt-1 pt-1 font-medium text-foreground">
        <span>Total</span><span class="tabular-nums">{{ formatK(usedTotal) }} / {{ formatK(contextUsage.limit) }} ({{ pct }}%)</span>
      </div>
    </div>
  </div>
</template>
