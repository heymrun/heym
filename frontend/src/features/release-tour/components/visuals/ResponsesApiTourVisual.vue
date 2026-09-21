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
  <div class="w-full rounded-lg border border-border bg-card p-4">
    <div class="mb-3 flex items-center justify-between">
      <span class="text-sm font-medium text-foreground">Agent &middot; Model</span>
      <span class="font-mono text-xs text-muted-foreground">gpt-5</span>
    </div>

    <div class="mb-3 rounded-md border border-border bg-background px-3 py-2">
      <div class="flex items-center gap-2">
        <span
          class="flex h-4 w-4 items-center justify-center rounded border transition-colors duration-500"
          :class="enabled
            ? 'border-primary bg-primary text-primary-foreground'
            : 'border-input bg-background'"
        >
          <svg
            v-if="enabled"
            viewBox="0 0 16 16"
            class="h-3 w-3"
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
        <span class="text-sm text-foreground">Use Responses API</span>
      </div>
      <p
        class="mt-1.5 text-xs transition-colors duration-500"
        :class="enabled ? 'text-success' : 'text-muted-foreground'"
      >
        {{ capabilityMessage }}
      </p>
    </div>

    <div class="space-y-1.5">
      <div
        v-for="turn in turns"
        :key="turn.label"
        class="flex items-center gap-3 rounded-md border bg-background px-3 py-2 transition-all duration-500"
        :class="{
          'border-border opacity-100': turn.state === 'done',
          'border-primary/60 opacity-100': turn.state === 'active',
          'border-border opacity-40': turn.state === 'idle',
        }"
      >
        <span class="w-24 shrink-0 text-xs text-muted-foreground">{{ turn.label }}</span>
        <span class="flex-1 truncate text-sm text-foreground">{{ turn.detail }}</span>
        <span
          v-if="turn.label === 'Reasoning' && enabled"
          class="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] text-primary"
        >encrypted</span>
      </div>
    </div>

    <p class="mt-3 text-xs text-muted-foreground">
      The conversation stays in Heym. Only the reasoning travels back to the model, as an
      encrypted blob, so the agent picks up where it left off.
    </p>
  </div>
</template>
