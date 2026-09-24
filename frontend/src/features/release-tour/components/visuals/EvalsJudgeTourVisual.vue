<script setup lang="ts">
import { computed } from "vue";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: each model answers · 1: the answers arrive · 2: the decision
// model scores them · 3: the run lands in history with its judge.
const step = useCycleStep(4, 1700);

interface ModelRow {
  model: string;
  answer: string;
  score: number;
}

const rows: ModelRow[] = [
  { model: "gpt-4o", answer: "Paris is the capital.", score: 96 },
  { model: "gpt-4o-mini", answer: "Lyon.", score: 4 },
];

const answered = computed<boolean>(() => step.value >= 1);
const scored = computed<boolean>(() => step.value >= 2);
const showHistory = computed<boolean>(() => step.value >= 3);

function scoreClass(score: number): string {
  return score >= 50
    ? "bg-primary/15 text-primary dark:bg-primary/25 dark:text-brand-primary-soft"
    : "bg-destructive/15 text-destructive";
}
</script>

<template>
  <!-- Fills the tour's fixed frame and draws no border of its own: the frame already
       has one, and a second rounded edge inside it reads as a doubled line. -->
  <div class="flex h-full w-full flex-col rounded-lg bg-card p-3">
    <div class="flex shrink-0 items-center justify-between">
      <span class="text-xs font-medium leading-none text-foreground">LLM-as-Judge</span>
      <span class="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] leading-none text-muted-foreground">
        judge &middot; jev-latest
      </span>
    </div>

    <p class="mt-2 shrink-0 truncate rounded-md bg-background px-2 py-1 text-[11px] text-muted-foreground">
      <span class="text-foreground">input</span>
      &nbsp;"Capital of France?"
      <span class="ml-2 text-foreground">expected</span>
      &nbsp;"Paris"
    </p>

    <div class="flex flex-1 flex-col justify-center gap-1.5">
      <div
        v-for="row in rows"
        :key="row.model"
        class="flex items-center gap-2 rounded-md border border-border/40 px-2 py-1.5"
      >
        <span class="w-20 shrink-0 truncate font-mono text-[10px] text-foreground">
          {{ row.model }}
        </span>
        <span
          class="flex-1 truncate text-[11px] text-muted-foreground transition-opacity duration-500"
          :class="answered ? 'opacity-100' : 'opacity-0'"
        >
          {{ row.answer }}
        </span>
        <div class="relative h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-muted">
          <div
            class="absolute inset-y-0 left-0 rounded-full bg-primary transition-all duration-700 ease-out"
            :style="{ width: scored ? `${row.score}%` : '0%' }"
          />
        </div>
        <span
          class="w-10 shrink-0 rounded px-1 py-0.5 text-center font-mono text-[10px] leading-none transition-colors duration-500"
          :class="scored ? scoreClass(row.score) : 'bg-muted text-muted-foreground'"
        >
          {{ scored ? `${row.score}%` : "—" }}
        </span>
      </div>
    </div>

    <!-- Space is reserved from the first step so the rows above never shift. -->
    <div
      class="flex h-6 shrink-0 items-center gap-2 rounded-md px-2 transition-colors duration-500"
      :class="showHistory ? 'bg-background' : 'bg-transparent'"
    >
      <span
        class="text-[10px] leading-none text-muted-foreground transition-opacity duration-500"
        :class="showHistory ? 'opacity-100' : 'opacity-0'"
      >
        History
      </span>
      <span
        class="truncate text-[10px] leading-none text-foreground transition-opacity duration-500"
        :class="showHistory ? 'opacity-100' : 'opacity-0'"
      >
        Run #3 &middot; LLM-as-Judge (jev-latest)
      </span>
      <span
        class="ml-auto shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] leading-none text-primary transition-opacity duration-500 dark:bg-primary/25 dark:text-brand-primary-soft"
        :class="showHistory ? 'opacity-100' : 'opacity-0'"
      >
        Export
      </span>
    </div>
  </div>
</template>
