<script setup lang="ts">
import { computed } from "vue";
import { MessageSquare, RefreshCw, Sparkles, Undo2 } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: the widget as it was · 1: Chat changed it, and the card offers Revert
// previous · 2: reverted, the widget is back.
const step = useCycleStep(3, 2400);

const bars = [40, 72, 55, 88, 64];
const changed = computed<boolean>(() => step.value === 1);

const caption = computed<string>(
  () =>
    [
      "Ask Chat to change a widget on your dashboard",
      "The changed card offers Revert previous",
      "One click puts the widget back as it was",
    ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 rounded-md border bg-background px-2.5 py-1.5 text-[11px] leading-4">
      <MessageSquare class="h-3 w-3 shrink-0 text-muted-foreground" />
      <span class="truncate text-foreground">Make Open tickets a line chart</span>
      <Sparkles
        class="ml-auto h-3 w-3 shrink-0 text-primary transition-opacity duration-500"
        :class="step === 0 ? 'opacity-0' : 'opacity-100'"
      />
    </div>
    <div class="flex min-h-0 flex-1 flex-col rounded-md border bg-background">
      <div class="flex items-center gap-1.5 border-b px-2.5 py-1.5 text-[11px] font-medium leading-4">
        <span class="truncate text-foreground">Open tickets</span>
        <span
          class="ml-auto flex items-center gap-1 rounded px-1 py-0.5 text-[10px] transition-all duration-500"
          :class="changed ? 'bg-primary/10 text-primary opacity-100' : 'opacity-0'"
        >
          <Undo2 class="h-3 w-3" />
          Revert previous
        </span>
        <RefreshCw class="h-3 w-3 shrink-0 text-muted-foreground" />
      </div>
      <div class="relative min-h-0 flex-1 px-3 pb-2 pt-3">
        <div
          class="absolute inset-x-3 bottom-2 top-3 flex items-end gap-1.5 transition-opacity duration-500"
          :class="changed ? 'opacity-0' : 'opacity-100'"
        >
          <div
            v-for="(height, index) in bars"
            :key="index"
            class="flex-1 rounded-t bg-primary/70"
            :style="{ height: `${height}%` }"
          />
        </div>
        <svg
          class="absolute inset-x-3 bottom-2 top-3 h-[calc(100%-1.25rem)] w-[calc(100%-1.5rem)] text-primary transition-opacity duration-500"
          :class="changed ? 'opacity-100' : 'opacity-0'"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
        >
          <polyline
            points="0,60 25,28 50,45 75,12 100,36"
            fill="none"
            stroke="currentColor"
            stroke-width="3"
            vector-effect="non-scaling-stroke"
          />
        </svg>
      </div>
    </div>
    <p class="shrink-0 text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
