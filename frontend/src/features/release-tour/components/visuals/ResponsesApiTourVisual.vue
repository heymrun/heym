<script setup lang="ts">
import { computed } from "vue";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: checkbox off, reasoning restarts each turn ·
// 1: checkbox on · 2: reasoning carried into the next turn · 3: final answer.
const step = useCycleStep(4, 1800);

const enabled = computed<boolean>(() => step.value >= 1);

interface MockTurn {
  label: string;
  detail: string;
  state: "done" | "active" | "idle";
}

const turns = computed<MockTurn[]>(() => [
  {
    label: "Tool call",
    detail: "search(\"q3 refunds\")",
    state: step.value >= 1 ? "done" : "active",
  },
  {
    label: "Reasoning",
    detail: enabled.value ? "carried to the next turn" : "dropped after the tool result",
    state: step.value >= 2 ? "done" : step.value === 1 ? "active" : "idle",
  },
  {
    label: "Final answer",
    detail: enabled.value ? "built on the same chain of thought" : "re-derived from scratch",
    state: step.value === 3 ? "active" : "idle",
  },
]);

const capabilityMessage = computed<string>(() =>
  enabled.value
    ? "The Responses API is available for this credential."
    : "Off by default. Chat Completions is used.",
);
</script>

<template>
  <!-- Fills the tour's fixed frame and draws no border of its own: the frame already
       has one, and a second rounded edge inside it reads as a doubled line. -->
  <div class="flex h-full w-full flex-col gap-1.5 rounded-lg bg-card p-2.5">
    <div class="flex shrink-0 items-center justify-between">
      <span class="text-xs font-medium leading-none text-foreground">Agent &middot; Model</span>
      <span class="font-mono text-[10px] leading-none text-muted-foreground">gpt-5</span>
    </div>

    <div class="shrink-0 rounded-md border border-border bg-background px-2 py-1">
      <div class="flex items-center gap-1.5">
        <span
          class="flex h-3.5 w-3.5 items-center justify-center rounded border transition-colors duration-500"
          :class="enabled
            ? 'border-primary bg-primary text-primary-foreground'
            : 'border-input bg-background'"
        >
          <svg
            v-if="enabled"
            viewBox="0 0 16 16"
            class="h-2.5 w-2.5"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
          >
            <path
              d="M3 8.5l3.2 3.2L13 5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </span>
        <span class="text-[11px] leading-none text-foreground">Use Responses API</span>
      </div>
      <p
        class="mt-1 truncate text-[10px] leading-tight transition-colors duration-500"
        :class="enabled ? 'text-success' : 'text-muted-foreground'"
      >
        {{ capabilityMessage }}
      </p>
    </div>

    <div class="flex min-h-0 flex-1 flex-col justify-center gap-1">
      <div
        v-for="turn in turns"
        :key="turn.label"
        class="flex items-center gap-2 rounded-md border bg-background px-2 py-1 transition-all duration-500"
        :class="{
          'border-border opacity-100': turn.state === 'done',
          'border-primary/60 opacity-100': turn.state === 'active',
          'border-border opacity-40': turn.state === 'idle',
        }"
      >
        <span class="w-20 shrink-0 text-[10px] leading-none text-muted-foreground">{{ turn.label }}</span>
        <span class="flex-1 truncate text-[11px] leading-none text-foreground">{{ turn.detail }}</span>
        <span
          v-if="turn.label === 'Reasoning' && enabled"
          class="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-[9px] leading-none text-primary dark:bg-primary/25 dark:text-brand-primary-soft"
        >encrypted</span>
      </div>
    </div>
  </div>
</template>
