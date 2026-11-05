<script setup lang="ts">
import { computed } from "vue";
import { KanbanSquare } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: a plain card · 1: assigned · 2: urgent and due today · 3: moved to Review.
// It fits the tour's 208px frame: the badges sit on two fixed rows, so the card never grows,
// and badges that fade in come last in their row, so nothing leaves a gap in front of them.
const step = useCycleStep(4, 1500);
const inReview = computed<boolean>(() => step.value === 3);

const caption = computed<string>(
  () =>
    [
      "A task on the team board",
      "Assign it to anyone on the board",
      "Set its priority and due date",
      "Move it: Heym, Work, Chat and MCP see it",
    ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      <KanbanSquare class="h-3 w-3" />
      Legal team · Contracts
    </div>

    <div class="grid min-h-0 flex-1 grid-cols-2 gap-2.5">
      <div
        v-for="column in ['In progress', 'Review']"
        :key="column"
        class="flex min-h-0 flex-col gap-1.5 rounded-md border border-border bg-muted/40 p-2"
      >
        <div class="text-[11px] font-semibold leading-4 text-muted-foreground">
          {{ column }}
        </div>
        <div
          v-if="(column === 'Review') === inReview"
          class="rounded-md border border-border bg-background p-2 shadow-sm"
        >
          <div class="truncate text-xs font-medium leading-4 text-foreground">
            NDA for Acme
          </div>
          <div class="mt-1.5 flex flex-col gap-1 text-[10px] leading-3">
            <div class="flex gap-1">
              <span
                class="whitespace-nowrap rounded-full border px-1.5 py-0.5 transition-colors duration-500"
                :class="step >= 2 ? 'border-destructive/40 bg-destructive/10 text-destructive' : 'border-border text-muted-foreground'"
              >
                {{ step >= 2 ? "Urgent" : "Medium" }}
              </span>
              <span
                class="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-border px-1.5 py-0.5 text-foreground transition-opacity duration-500"
                :class="step >= 1 ? 'opacity-100' : 'opacity-0'"
              >
                <span class="h-2 w-2 rounded-full bg-primary/50" />
                Ada
              </span>
            </div>
            <div class="flex gap-1">
              <span class="whitespace-nowrap rounded-full border border-transparent bg-primary/10 px-1.5 py-0.5 text-primary">
                Acme
              </span>
              <span
                class="whitespace-nowrap rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-amber-600 transition-opacity duration-500 dark:text-amber-400"
                :class="step >= 2 ? 'opacity-100' : 'opacity-0'"
              >
                Due today
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <p class="shrink-0 truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
