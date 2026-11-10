<script setup lang="ts">
import { computed } from "vue";
import { Scale, Search } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: vector search order · 1: the decision model scores each finding · 2: reranked.
const step = useCycleStep(3, 2400);

interface Finding {
  id: string;
  text: string;
  similarity: number;
  relevance: number;
}

const findings: Finding[] = [
  { id: "a", text: "VPN client release notes, version 4.2", similarity: 0.82, relevance: 0.1 },
  { id: "b", text: "Office network map and VPN gateways", similarity: 0.79, relevance: 0.3 },
  { id: "c", text: "Reset your VPN token from the IT portal", similarity: 0.74, relevance: 0.95 },
  { id: "d", text: "Lost laptop? Revoke its VPN access", similarity: 0.71, relevance: 0.55 },
];

const TOP_N = 2;

const ordered = computed<Finding[]>(() =>
  step.value === 2 ? [...findings].sort((a, b) => b.relevance - a.relevance) : findings,
);

const caption = computed<string>(
  () =>
    [
      "Vector search returns the closest findings",
      "The decision model scores every finding against the question",
      "Results come back in order of relevance_score",
    ][step.value],
);

function rowClass(index: number): string {
  if (step.value !== 2) return "border-border bg-background";
  return index < TOP_N
    ? "border-emerald-500/40 bg-emerald-500/10"
    : "border-border bg-background opacity-50";
}
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      <Search class="h-3 w-3" />
      RAG · Search
      <span
        class="ml-auto flex items-center gap-1 transition-opacity duration-500"
        :class="step > 0 ? 'opacity-100' : 'opacity-0'"
      >
        <Scale class="h-3 w-3 text-primary" />
        Reranker: Decision Model
      </span>
    </div>

    <div class="shrink-0 rounded-md border border-border bg-background px-2.5 py-1 text-[11px] leading-4 text-foreground">
      How do I reset my VPN token?
    </div>

    <TransitionGroup
      tag="div"
      move-class="transition-transform duration-500"
      class="flex min-h-0 flex-1 flex-col gap-1"
    >
      <div
        v-for="(finding, index) in ordered"
        :key="finding.id"
        class="flex min-h-0 flex-1 items-center gap-2 rounded-md border px-2.5 text-[11px] leading-4 transition-colors duration-500"
        :class="rowClass(index)"
      >
        <span class="w-3 shrink-0 font-mono text-[10px] text-muted-foreground">{{ index + 1 }}</span>
        <span class="min-w-0 flex-1 truncate text-foreground">{{ finding.text }}</span>
        <span
          v-if="step === 0"
          class="shrink-0 font-mono text-[10px] text-muted-foreground"
        >{{ finding.similarity.toFixed(2) }}</span>
        <span
          v-else
          class="flex shrink-0 items-center gap-1"
        >
          <span class="h-1.5 w-10 overflow-hidden rounded-full bg-muted">
            <span
              class="block h-full rounded-full bg-primary transition-all duration-700"
              :style="{ width: `${finding.relevance * 100}%` }"
            />
          </span>
          <span class="w-7 text-right font-mono text-[10px] text-foreground">
            {{ finding.relevance.toFixed(2) }}
          </span>
        </span>
      </div>
    </TransitionGroup>

    <p class="shrink-0 text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
