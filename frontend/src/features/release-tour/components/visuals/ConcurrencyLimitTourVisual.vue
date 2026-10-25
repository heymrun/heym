<script setup lang="ts">
import { computed } from "vue";
import { CheckCircle2, Clock, Loader2 } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: three runs arrive · 1: one runs, two wait · 2: the first finishes, #1 starts.
const step = useCycleStep(3, 1800);

interface MockRun {
  id: string;
  source: string;
  state: "running" | "queued" | "done";
  position?: number;
}

const runs = computed<MockRun[]>(() => {
  if (step.value < 2) {
    return [
      { id: "a", source: "Webhook", state: "running" },
      { id: "b", source: "Cron", state: "queued", position: 1 },
      { id: "c", source: "MCP", state: "queued", position: 2 },
    ];
  }
  return [
    { id: "a", source: "Webhook", state: "done" },
    { id: "b", source: "Cron", state: "running" },
    { id: "c", source: "MCP", state: "queued", position: 1 },
  ];
});

const caption = computed<string>(() => {
  if (step.value === 0) return "Three runs arrive at once";
  if (step.value === 1) return "Limit 1: the others wait in order";
  return "One finishes, the next one starts";
});

// The 202 a waiting webhook caller gets back, for the last run in line.
const responseLine = computed<string>(() => {
  const position = step.value < 2 ? 2 : 1;
  return `202 · {"status": "queued", "queue": {"position": ${position}}}`;
});
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      Concurrency limit
      <span class="ml-auto rounded border border-primary/50 bg-primary/25 px-1.5 text-[10px] font-medium leading-4 text-foreground">
        1 at a time
      </span>
    </div>

    <div class="space-y-1.5">
      <div
        v-for="run in runs"
        :key="run.id"
        class="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] leading-4 transition-colors duration-500"
        :class="run.state === 'running' ? 'border-primary/50 bg-primary/10' : 'border-border bg-background'"
      >
        <Loader2
          v-if="run.state === 'running'"
          class="h-3 w-3 animate-spin text-primary"
        />
        <CheckCircle2
          v-else-if="run.state === 'done'"
          class="h-3 w-3 text-emerald-500"
        />
        <Clock
          v-else
          class="h-3 w-3 text-amber-500"
        />
        <span class="text-foreground">{{ run.source }}</span>
        <span
          class="ml-auto rounded px-1.5 text-[10px] transition-colors duration-500"
          :class="run.state === 'queued' ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400' : 'text-muted-foreground'"
        >
          {{ run.state === "queued" ? `#${run.position}` : run.state }}
        </span>
      </div>
    </div>

    <div class="mt-auto rounded-md bg-muted/50 px-2.5 py-1.5 font-mono text-[10px] leading-4 text-muted-foreground">
      {{ responseLine }}
    </div>
    <p class="text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
