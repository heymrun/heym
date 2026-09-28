<script setup lang="ts">
import { computed } from "vue";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: the question · 1: new table picked · 2: created · 3: the node uses it.
const step = useCycleStep(4, 1700);

interface MockOption {
  label: string;
  active: boolean;
}

const options = computed<MockOption[]>(() => [
  { label: "leads_2025", active: step.value === 0 },
  { label: "Create a new table", active: step.value >= 1 },
]);

const columns = computed<string[]>(() =>
  step.value === 0
    ? ["email · string", "name · string", "source · string"]
    : ["email · string · unique", "name · string", "status · string"],
);

const created = computed<boolean>(() => step.value >= 2);
</script>

<template>
  <!-- Fills the tour's fixed frame and draws no border of its own, like the other visuals. -->
  <div class="flex h-full w-full flex-col gap-1.5 rounded-lg bg-card p-2.5">
    <div class="shrink-0 rounded-md bg-background px-2 py-1.5">
      <p class="truncate text-[11px] font-medium leading-tight text-foreground">
        Which table should the leads go to?
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

    <div class="flex min-h-0 flex-1 flex-col justify-center gap-1 rounded-md border border-border px-2 py-1">
      <div class="flex items-center justify-between">
        <span class="text-[11px] font-medium leading-none text-foreground">{{ step === 0 ? "leads_2025" : "New table: leads" }}</span>
        <span class="rounded bg-muted px-1 py-0.5 text-[9px] leading-none text-muted-foreground">{{ step === 0 ? "3 columns" : "Proposed" }}</span>
      </div>
      <div class="flex flex-wrap gap-1">
        <span
          v-for="column in columns"
          :key="column"
          class="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[9px] leading-none text-foreground"
        >{{ column }}</span>
      </div>
    </div>

    <div
      class="flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] leading-none transition-opacity duration-500"
      :class="step >= 3 ? 'border-primary opacity-100' : 'border-border opacity-30'"
    >
      <span class="rounded bg-muted px-1 py-0.5 text-[9px] text-muted-foreground">DataTable</span>
      <span class="truncate font-mono leading-snug text-foreground">saveLead · insert → leads</span>
    </div>

    <!-- One line, two captions crossfading, so the footer never wraps. -->
    <div class="relative h-3 shrink-0 text-[10px] leading-3">
      <span
        class="absolute inset-0 truncate text-muted-foreground transition-opacity duration-500"
        :class="created ? 'opacity-0' : 'opacity-100'"
      >The model sees names and columns, never rows</span>
      <span
        class="absolute inset-0 truncate text-primary transition-opacity duration-500 dark:text-brand-primary-soft"
        :class="created ? 'opacity-100' : 'opacity-0'"
      >Created data table leads, continuing &rarr;</span>
    </div>
  </div>
</template>
