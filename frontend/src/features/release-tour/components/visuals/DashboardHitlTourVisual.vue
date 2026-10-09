<script setup lang="ts">
import { computed } from "vue";
import { ChevronLeft, ChevronRight, History } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. Alternates two pending reviews; the header keeps the count.
const step = useCycleStep(2, 1600);
const buttonStep = useCycleStep(3, 1400);

function sheenClass(index: number): string {
  const base =
    "pointer-events-none absolute inset-y-0 left-0 w-1/2 bg-gradient-to-r from-transparent via-white/20 to-transparent";
  return buttonStep.value === index
    ? `${base} translate-x-[220%] transition-transform duration-700 ease-in-out`
    : `${base} -translate-x-full transition-none`;
}

const review = computed(() =>
  step.value === 0
    ? {
        title: "Lead intake · Qualifier",
        body: "Thanks for reaching out. I can share pricing tomorrow.",
        label: "1/2 pending",
      }
    : {
        title: "Invoice OCR · Extractor",
        body: "Invoice 1042 from Northwind, total $1,280.",
        label: "2/2 pending",
      },
);
</script>

<template>
  <div class="flex h-full w-full flex-col rounded-lg border bg-card">
    <div class="flex items-center justify-between gap-2 border-b px-3 py-2">
      <span class="truncate text-[11px] font-medium text-foreground">Reviews</span>
      <History class="h-3 w-3 shrink-0 text-muted-foreground" />
    </div>
    <div class="flex min-h-0 flex-1 flex-col px-3 pb-3 pt-2">
      <div class="flex items-center justify-between text-[10px] text-muted-foreground">
        <ChevronLeft class="h-3 w-3" />
        <span class="tabular-nums">{{ review.label }}</span>
        <ChevronRight class="h-3 w-3" />
      </div>
      <span class="mt-4 flex items-center gap-1 truncate text-[11px] font-medium text-foreground">
        <span class="text-primary">↗</span>
        {{ review.title }}
      </span>
      <p class="mt-2 line-clamp-3 text-[10px] leading-snug text-muted-foreground">
        {{ review.body }}
      </p>
      <div class="mt-auto flex flex-nowrap items-center gap-1.5 pt-2">
        <span class="relative overflow-hidden rounded-full bg-primary px-2 py-0.5 text-[9px] text-primary-foreground dark:bg-primary-solid dark:text-primary-solid-foreground">
          <span :class="sheenClass(0)" />
          <span class="relative">Approve</span>
        </span>
        <span class="relative overflow-hidden rounded-full border border-border bg-card px-2 py-0.5 text-[9px] text-foreground">
          <span :class="sheenClass(1)" />
          <span class="relative">Request changes</span>
        </span>
        <span class="relative overflow-hidden rounded-full border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-[9px] text-destructive">
          <span :class="sheenClass(2)" />
          <span class="relative">Reject</span>
        </span>
      </div>
    </div>
  </div>
</template>
