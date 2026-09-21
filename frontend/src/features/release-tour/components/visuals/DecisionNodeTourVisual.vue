<script setup lang="ts">
import { computed } from "vue";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: questions waiting · 1: noul answered · 2: choice answered ·
// 3: score answered. One line per question so the whole mock fits the tour frame.
const step = useCycleStep(4, 1600);

interface ChoiceSegment {
  label: string;
  share: number;
}

const noulPercent = computed<number>(() => (step.value >= 1 ? 95 : 0));

const choiceSegments = computed<ChoiceSegment[]>(() => {
  const answered = step.value >= 2;
  return [
    { label: "billing", share: answered ? 88 : 0 },
    { label: "technical", share: answered ? 12 : 0 },
  ];
});

/** Levels run 0..2, so the marker sits at 1.05 of 2 once the score lands. */
const scorePercent = computed<number>(() => (step.value >= 3 ? (1.05 / 2) * 100 : 0));
</script>

<template>
  <div class="w-full rounded-lg border border-border bg-card p-3">
    <div class="mb-2 flex items-center justify-between">
      <span class="text-xs font-medium text-foreground">Decision &middot; triage</span>
      <span class="font-mono text-[10px] text-muted-foreground">jev-latest</span>
    </div>

    <p class="mb-2 truncate rounded-md bg-background px-2 py-1 text-[11px] text-muted-foreground">
      <span class="text-foreground">state</span>
      &nbsp;"My card was charged twice and I need this fixed today."
    </p>

    <div class="space-y-1.5">
      <div class="flex items-center gap-2">
        <span class="w-20 shrink-0 truncate text-[11px] text-foreground">is_urgent</span>
        <span class="w-11 shrink-0 rounded bg-muted px-1 text-center text-[9px] text-muted-foreground">
          noul
        </span>
        <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
          <div
            class="h-full rounded-full bg-primary transition-all duration-700 ease-out"
            :style="{ width: `${noulPercent}%` }"
          />
        </div>
        <span class="w-8 shrink-0 text-right font-mono text-[10px] text-muted-foreground">
          {{ step >= 1 ? "0.95" : "—" }}
        </span>
      </div>

      <div class="flex items-center gap-2">
        <span class="w-20 shrink-0 truncate text-[11px] text-foreground">department</span>
        <span class="w-11 shrink-0 rounded bg-muted px-1 text-center text-[9px] text-muted-foreground">
          choice
        </span>
        <div class="flex h-1.5 flex-1 gap-0.5 overflow-hidden rounded-full bg-muted">
          <div
            v-for="segment in choiceSegments"
            :key="segment.label"
            class="h-full rounded-full bg-primary transition-all duration-700 ease-out"
            :class="segment.label === 'billing' ? 'opacity-100' : 'opacity-40'"
            :style="{ width: `${segment.share}%` }"
          />
        </div>
        <span class="w-12 shrink-0 text-right text-[10px] text-muted-foreground">
          {{ step >= 2 ? "billing" : "—" }}
        </span>
      </div>

      <div class="flex items-center gap-2">
        <span class="w-20 shrink-0 truncate text-[11px] text-foreground">frustration</span>
        <span class="w-11 shrink-0 rounded bg-muted px-1 text-center text-[9px] text-muted-foreground">
          score
        </span>
        <div class="relative h-1.5 flex-1 rounded-full bg-muted">
          <div
            class="absolute -top-1 h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-card bg-primary transition-all duration-700 ease-out"
            :style="{ left: `${scorePercent}%` }"
          />
        </div>
        <span class="w-8 shrink-0 text-right font-mono text-[10px] text-muted-foreground">
          {{ step >= 3 ? "1.05" : "—" }}
        </span>
      </div>
    </div>

    <div class="mt-2 flex items-center justify-between text-[10px]">
      <span class="text-muted-foreground">Calm &middot; Frustrated &middot; Very angry</span>
      <span
        class="transition-opacity duration-500"
        :class="step >= 2 ? 'text-primary opacity-100' : 'text-muted-foreground opacity-40'"
      >Switch &rarr; billing</span>
    </div>
  </div>
</template>
