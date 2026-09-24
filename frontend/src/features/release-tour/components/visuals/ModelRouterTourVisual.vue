<script setup lang="ts">
import { computed } from "vue";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: request arrives · 1: the router weighs both options ·
// 2: one option wins · 3: the trace line shows router and model together.
const step = useCycleStep(4, 1700);

interface RouterOption {
  name: string;
  criteria: string;
  model: string;
  wins: boolean;
}

const options = computed<RouterOption[]>(() => [
  {
    name: "Fast",
    criteria: "Short factual questions",
    model: "gpt-4o-mini",
    wins: false,
  },
  {
    name: "Deep reasoning",
    criteria: "Multi-step reasoning, code",
    model: "gpt-5",
    wins: step.value >= 2,
  },
]);

const weighing = computed<boolean>(() => step.value === 1);
const showTrace = computed<boolean>(() => step.value >= 3);
</script>

<template>
  <!-- Fills the tour's fixed frame and draws no border of its own: the frame already
       has one, and a second rounded edge inside it reads as a doubled line. -->
  <div class="flex h-full w-full flex-col rounded-lg bg-card p-3">
    <div class="flex shrink-0 items-center justify-between">
      <span class="text-xs font-medium leading-none text-foreground">Auto Model</span>
      <span class="font-mono text-[10px] leading-none text-muted-foreground">jev-latest</span>
    </div>

    <p class="mt-2 shrink-0 truncate rounded-md bg-background px-2 py-1 text-[11px] text-muted-foreground">
      <span class="text-foreground">request</span>
      &nbsp;"Refactor this module and explain the tradeoffs."
    </p>

    <div class="flex flex-1 flex-col justify-center gap-1.5">
      <div
        v-for="option in options"
        :key="option.name"
        class="flex items-center gap-2 rounded-md border px-2 py-1.5 transition-all duration-500"
        :class="
          option.wins
            ? 'border-primary/60 bg-primary/5'
            : weighing
              ? 'border-border/60 bg-muted/30'
              : 'border-border/40'
        "
      >
        <span class="w-24 shrink-0 truncate text-[11px] font-medium text-foreground">
          {{ option.name }}
        </span>
        <span class="flex-1 truncate text-[10px] text-muted-foreground">
          {{ option.criteria }}
        </span>
        <span
          class="shrink-0 rounded px-1.5 py-0.5 font-mono text-[9px] leading-none transition-colors duration-500"
          :class="option.wins ? 'bg-primary/15 text-primary dark:bg-primary/25 dark:text-brand-primary-soft' : 'bg-muted text-muted-foreground'"
        >
          {{ option.model }}
        </span>
      </div>
    </div>

    <!-- Space is reserved from the first step so the rows above never shift. -->
    <div
      class="flex h-6 shrink-0 items-center gap-2 rounded-md px-2 transition-colors duration-500"
      :class="showTrace ? 'bg-background' : 'bg-transparent'"
    >
      <span
        class="text-[10px] leading-none text-muted-foreground transition-opacity duration-500"
        :class="showTrace ? 'opacity-100' : 'opacity-0'"
      >
        Traces
      </span>
      <span
        class="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] leading-none text-primary transition-opacity duration-500 dark:bg-primary/25 dark:text-brand-primary-soft"
        :class="showTrace ? 'opacity-100' : 'opacity-0'"
      >
        Auto Model / gpt-5
      </span>
    </div>
  </div>
</template>
