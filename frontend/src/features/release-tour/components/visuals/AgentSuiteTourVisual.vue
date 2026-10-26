<script setup lang="ts">
import { computed } from "vue";
import { CheckCircle2, XCircle } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: baseline from the last runs · 1: tool checks · 2: each run scored.
const step = useCycleStep(3, 2200);

interface MockRow {
  id: string;
  label: string;
  value: string;
  state?: "pass" | "fail";
}

const badge = computed<string>(() => ["Last 10 runs", "3 checks", "9/10 passed"][step.value]);

const rows = computed<MockRow[]>(() => {
  if (step.value === 0) {
    return [
      { id: "latency", label: "Latency p95", value: "2.4 s" },
      { id: "cost", label: "Cost per run", value: "$0.0031" },
      { id: "tools", label: "Tool calls per run", value: "2.6" },
    ];
  }
  if (step.value === 1) {
    return [
      { id: "search", label: "search_docs", value: "Must call" },
      { id: "email", label: "send_email", value: "Must not call" },
      { id: "bound", label: "Latency", value: "≤ 2.9 s" },
    ];
  }
  return [
    { id: "r1", label: "10:42 · 2.1 s · $0.0029", value: "passed", state: "pass" },
    { id: "r2", label: "10:38 · called send_email", value: "failed", state: "fail" },
    { id: "r3", label: "10:31 · 2.3 s · $0.0033", value: "passed", state: "pass" },
  ];
});

const caption = computed<string>(() => {
  if (step.value === 0) return "Baseline from the agent's real runs";
  if (step.value === 1) return "Pick the tools it must and must not call";
  return "Every run scored, with the reason it failed";
});
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      Agent suite · Support Agent
      <span class="ml-auto rounded border border-primary/50 bg-primary/25 px-1.5 text-[10px] font-medium leading-4 text-foreground transition-all duration-500">
        {{ badge }}
      </span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1.5">
      <div
        v-for="row in rows"
        :key="row.id"
        class="flex flex-1 items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] leading-4 transition-colors duration-500"
        :class="row.state === 'fail' ? 'border-destructive/40 bg-destructive/10' : 'border-border bg-background'"
      >
        <CheckCircle2
          v-if="row.state === 'pass'"
          class="h-3 w-3 text-emerald-500"
        />
        <XCircle
          v-else-if="row.state === 'fail'"
          class="h-3 w-3 text-destructive"
        />
        <span
          class="truncate text-foreground"
          :class="step === 1 && row.id !== 'bound' ? 'font-mono' : ''"
        >{{ row.label }}</span>
        <span class="ml-auto shrink-0 rounded bg-muted px-1.5 text-[10px] tabular-nums text-muted-foreground">
          {{ row.value }}
        </span>
      </div>
    </div>

    <p class="text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
