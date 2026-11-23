<script setup lang="ts">
import { useCycleStep } from "@/features/release-tour/useCycleStep";

const step = useCycleStep(3, 2100);
const operations = ["Get Board", "Get Board Column", "Get Board Card by ID"];
const pickedNames = ["Product", "Planning", "Review onboarding"];
const results = [
  { title: "Columns", rows: ["Backlog", "Planning", "Done"] },
  { title: "Cards in Planning", rows: ["Review onboarding", "Draft launch notes", "Verify checklist"] },
  { title: "Card details", rows: ["Review onboarding", "Column · Planning", "/b/…/cards/…"] },
];
</script>

<template>
  <div class="grid w-full grid-cols-2 gap-2 rounded-lg bg-card p-3 text-xs">
    <div class="min-w-0 space-y-1.5 rounded-md border border-border p-2">
      <p class="font-semibold text-foreground">
        Heym
      </p>
      <div
        v-for="(operation, index) in operations"
        :key="operation"
        class="rounded px-1.5 py-1 transition-colors duration-300 motion-reduce:transition-none"
        :class="index === step ? 'bg-primary/15 text-foreground' : 'text-muted-foreground'"
      >
        {{ operation }}
      </div>
      <div class="rounded border border-border bg-background px-1.5 py-1 text-muted-foreground">
        {{ pickedNames[step] }}
      </div>
    </div>
    <div class="flex min-w-0 flex-col gap-1.5 rounded-md border border-border p-2">
      <p class="font-semibold text-foreground">
        {{ results[step].title }}
      </p>
      <div class="grid flex-1 grid-rows-3 gap-1.5">
        <div
          v-for="(row, index) in results[step].rows"
          :key="index"
          class="flex items-center rounded border px-1.5 py-1 transition-colors duration-300 motion-reduce:transition-none"
          :class="[
            step === 2 && index === 0 ? 'border-primary bg-primary/10' : 'border-border bg-muted/40',
            { 'font-mono text-[10px] text-muted-foreground': step === 2 && index === 2 },
          ]"
        >
          {{ row }}
        </div>
      </div>
    </div>
  </div>
</template>
