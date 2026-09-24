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

const created = computed<boolean>(() => step.value >= 3);
</script>

<template>
  <!-- Fills the tour's fixed frame and draws no border of its own: the frame already
       has one, and a second rounded edge inside it reads as a doubled line. The option
       row may wrap, so the form takes whatever height is left instead of a fixed share. -->
  <div class="flex h-full w-full flex-col gap-1.5 rounded-lg bg-card p-2.5">
    <div class="shrink-0 rounded-md bg-background px-2 py-1.5">
      <p class="truncate text-[11px] font-medium leading-tight text-foreground">
        Which GitHub credential should I use?
      </p>
      <div class="mt-1 flex flex-wrap gap-1">
        <span
          v-for="option in options"
          :key="option.label"
          class="whitespace-nowrap rounded-full border px-1.5 py-0.5 text-[10px] leading-none transition-colors duration-500"
          :class="option.active ? 'border-primary bg-primary text-primary-foreground' : 'border-border text-muted-foreground'"
        >{{ option.label }}</span>
      </div>
    </div>

    <div
      class="flex min-h-0 flex-1 flex-col justify-center gap-1 rounded-md border border-border px-2 py-1 transition-opacity duration-500"
      :class="step >= 2 ? 'opacity-100' : 'opacity-30'"
    >
      <div class="flex items-center justify-between">
        <span class="text-[11px] font-medium leading-none text-foreground">New credential</span>
        <span class="rounded bg-muted px-1 py-0.5 text-[9px] leading-none text-muted-foreground">GitHub</span>
      </div>
      <div class="grid grid-cols-2 gap-2 text-[10px] leading-none">
        <div class="flex min-w-0 items-center gap-1.5">
          <span class="shrink-0 text-muted-foreground">Name</span>
          <span class="min-w-0 flex-1 truncate rounded bg-background px-1.5 py-1 font-mono text-foreground">github-personal</span>
        </div>
        <div class="flex min-w-0 items-center gap-1.5">
          <span class="shrink-0 text-muted-foreground">Token</span>
          <span class="h-[18px] min-w-0 flex-1 truncate rounded bg-background px-1.5 py-1 font-mono text-foreground">{{ step >= 2 ? "••••••••••••" : "" }}</span>
        </div>
      </div>
    </div>

    <!-- One line, two captions crossfading, so the footer never wraps into the form. -->
    <div class="relative h-3 shrink-0 text-[10px] leading-3">
      <span
        class="absolute inset-0 truncate text-muted-foreground transition-opacity duration-500"
        :class="created ? 'opacity-0' : 'opacity-100'"
      >The model sees the name, not the token</span>
      <span
        class="absolute inset-0 truncate text-primary transition-opacity duration-500 dark:text-brand-primary-soft"
        :class="created ? 'opacity-100' : 'opacity-0'"
      >Added github-personal, continuing &rarr;</span>
    </div>
  </div>
</template>
