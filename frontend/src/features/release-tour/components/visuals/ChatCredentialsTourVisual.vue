<script setup lang="ts">
import { computed } from "vue";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: the question · 1: create picked · 2: the form · 3: created, continuing.
const step = useCycleStep(4, 1700);

interface MockOption {
  label: string;
  active: boolean;
}

const options = computed<MockOption[]>(() => [
  { label: "github-work", active: false },
  { label: "Create a new credential", active: step.value >= 1 },
  { label: "Continue without", active: false },
]);
</script>

<template>
  <div class="w-full space-y-2 rounded-lg border border-border bg-card p-3">
    <div class="rounded-md bg-background px-2 py-1.5">
      <p class="text-[11px] font-medium text-foreground">
        Which GitHub credential should I use?
      </p>
      <div class="mt-1.5 flex flex-wrap gap-1">
        <span
          v-for="option in options"
          :key="option.label"
          class="rounded-full border px-2 py-0.5 text-[10px] transition-colors duration-500"
          :class="option.active ? 'border-primary bg-primary text-primary-foreground' : 'border-border text-muted-foreground'"
        >{{ option.label }}</span>
      </div>
    </div>

    <div
      class="rounded-md border border-border px-2 py-1.5 transition-opacity duration-500"
      :class="step >= 2 ? 'opacity-100' : 'opacity-30'"
    >
      <div class="mb-1 flex items-center justify-between">
        <span class="text-[11px] font-medium text-foreground">New credential</span>
        <span class="rounded bg-muted px-1 text-[9px] text-muted-foreground">GitHub</span>
      </div>
      <div class="space-y-1 text-[10px]">
        <div class="flex items-center gap-2">
          <span class="w-10 shrink-0 text-muted-foreground">Name</span>
          <span class="flex-1 truncate rounded bg-background px-1.5 py-0.5 font-mono text-foreground">github-personal</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="w-10 shrink-0 text-muted-foreground">Token</span>
          <span class="h-4 flex-1 rounded bg-background px-1.5 py-0.5 font-mono text-foreground">{{ step >= 2 ? "••••••••••••" : "" }}</span>
        </div>
      </div>
    </div>

    <div class="flex items-center justify-between text-[10px]">
      <span class="text-muted-foreground">The model sees the name, not the token</span>
      <span
        class="transition-opacity duration-500"
        :class="step >= 3 ? 'text-primary opacity-100' : 'text-muted-foreground opacity-40'"
      >Added github-personal, continuing &rarr;</span>
    </div>
  </div>
</template>
