<script setup lang="ts">
import { computed } from "vue";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// 0: plain card, 1: assigned, 2: urgent and due today, 3: moved to Review.
const step = useCycleStep(4, 1500);
const inReview = computed<boolean>(() => step.value === 3);
</script>

<template>
  <div class="flex h-full flex-col justify-center gap-3 rounded-lg bg-card p-5 text-foreground">
    <div class="text-sm font-semibold">
      Legal team · Contracts
    </div>
    <div class="grid grid-cols-2 gap-3 text-xs">
      <div
        v-for="column in ['In progress', 'Review']"
        :key="column"
        class="flex min-h-[9rem] flex-col gap-2 rounded-lg border border-border bg-muted/40 p-2"
      >
        <div class="font-semibold text-muted-foreground">
          {{ column }}
        </div>
        <div
          v-if="(column === 'Review') === inReview"
          class="rounded-md border border-border bg-background p-2 shadow-sm transition-all duration-500"
        >
          <div class="font-medium">
            NDA for Acme
          </div>
          <div class="mt-2 flex flex-wrap gap-1">
            <span
              class="inline-flex items-center gap-1 rounded-full border border-border px-1.5 py-0.5 transition-opacity duration-500"
              :class="step >= 1 ? 'opacity-100' : 'opacity-0'"
            >
              <span class="h-3 w-3 rounded-full bg-primary/30" />
              Ada
            </span>
            <span
              class="rounded-full border px-1.5 py-0.5 transition-colors duration-500"
              :class="step >= 2 ? 'border-destructive/40 bg-destructive/10 text-destructive' : 'border-border text-muted-foreground'"
            >
              {{ step >= 2 ? 'Urgent' : 'Medium' }}
            </span>
            <span
              class="rounded-full border px-1.5 py-0.5 transition-opacity duration-500"
              :class="step >= 2 ? 'border-primary/40 bg-primary/10 text-primary opacity-100' : 'opacity-0'"
            >
              Due today
            </span>
            <span class="rounded-full bg-primary/10 px-1.5 py-0.5 text-primary">
              Acme
            </span>
          </div>
        </div>
      </div>
    </div>
    <div class="text-xs text-muted-foreground">
      The same card in Heym, Heym Work, Chat and any MCP client
    </div>
  </div>
</template>
