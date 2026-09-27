<script setup lang="ts">
import { computed } from "vue";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: applied · 1: attempt 1 runs · 2: attempt 1 failed, attempt 2 runs · 3: verified.
const step = useCycleStep(4, 1700);

type MockState = "waiting" | "running" | "done" | "failed";

interface MockRow {
  label: string;
  state: MockState;
}

function attemptState(startsAt: number, fails: boolean): MockState {
  if (step.value < startsAt) return "waiting";
  if (step.value === startsAt) return "running";
  return fails ? "failed" : "done";
}

const rows = computed<MockRow[]>(() => [
  { label: "Applying changes to canvas", state: "done" },
  { label: "Running workflow · attempt 1/5", state: attemptState(1, true) },
  { label: "Running workflow · attempt 2/5", state: attemptState(2, false) },
]);

const verified = computed<boolean>(() => step.value === 3);
</script>

<template>
  <!-- Fills the tour's fixed frame and draws no border of its own. -->
  <div class="flex h-full w-full flex-col gap-1.5 rounded-lg bg-card p-2.5">
    <div class="flex shrink-0 items-center gap-1.5 text-[11px] font-medium leading-none text-foreground">
      <span class="flex h-3 w-3 items-center justify-center rounded-sm bg-primary text-[8px] leading-none text-primary-foreground">&#10003;</span>
      YOLO mode
    </div>
    <div class="flex min-h-0 flex-1 flex-col justify-center gap-1">
      <div
        v-for="row in rows"
        :key="row.label"
        class="flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] leading-none transition-colors duration-500"
        :class="{
          'border-border text-muted-foreground opacity-40': row.state === 'waiting',
          'border-primary/40 text-foreground': row.state === 'running',
          'border-border text-foreground': row.state === 'done',
          'border-destructive/40 text-destructive': row.state === 'failed',
        }"
      >
        <span
          class="h-1.5 w-1.5 shrink-0 rounded-full transition-colors duration-500"
          :class="{
            'bg-muted-foreground': row.state === 'waiting',
            'animate-pulse bg-primary': row.state === 'running',
            'bg-emerald-500': row.state === 'done',
            'bg-destructive': row.state === 'failed',
          }"
        />
        <span class="truncate">{{ row.label }}</span>
      </div>
    </div>
    <!-- One line, two captions crossfading, so the footer never wraps. -->
    <div class="relative h-3 shrink-0 text-[10px] leading-3">
      <span
        class="absolute inset-0 truncate text-muted-foreground transition-opacity duration-500"
        :class="verified ? 'opacity-0' : 'opacity-100'"
      >Runs the workflow, reads the result, fixes it</span>
      <span
        class="absolute inset-0 truncate text-primary transition-opacity duration-500 dark:text-brand-primary-soft"
        :class="verified ? 'opacity-100' : 'opacity-0'"
      >Verified in 2 attempts &rarr;</span>
    </div>
  </div>
</template>
