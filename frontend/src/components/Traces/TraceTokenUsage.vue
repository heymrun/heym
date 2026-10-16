<script setup lang="ts">
import { computed } from "vue";
import { Coins } from "lucide-vue-next";

import { formatTokenCount } from "@/lib/traceSpans";
import type { TraceSpan } from "@/types/trace";

const props = defineProps<{
  span: TraceSpan;
  /** What clicking the row does, shown last because the native title is off here. */
  hint: string | null;
}>();

/** A long agent run would otherwise grow the tooltip past the screen. */
const MAX_TURN_ROWS = 12;

interface Segment {
  key: "prompt" | "completion" | "router";
  value: number;
}

const SEGMENT_CLASS: Record<Segment["key"], string> = {
  prompt: "bg-sky-500",
  completion: "bg-amber-500",
  router: "bg-violet-500",
};

interface TurnRow {
  turn: number;
  total: number;
  /** Bar length against the heaviest turn, so the biggest spender reads at once. */
  widthPercent: number;
  segments: Segment[];
}

const usage = computed(() => props.span.usage);

/** Input only: a decision model's output is a one-word answer and costs next to nothing. */
const routerInput = computed<number | null>(() => usage.value?.router?.promptTokens ?? null);

/** Null when the model side is unknown, so the tooltip never shows a made-up total. */
const total = computed<number | null>(() => {
  const prompt = usage.value?.promptTokens;
  const completion = usage.value?.completionTokens;
  if (typeof prompt !== "number" || typeof completion !== "number") return null;
  return prompt + completion + (routerInput.value ?? 0);
});

function toSegments(prompt: number, completion: number, router: number): Segment[] {
  const segments: Segment[] = [
    { key: "prompt", value: prompt },
    { key: "completion", value: completion },
    { key: "router", value: router },
  ];
  return segments.filter((segment) => segment.value > 0);
}

const segments = computed<Segment[]>(() =>
  toSegments(
    usage.value?.promptTokens ?? 0,
    usage.value?.completionTokens ?? 0,
    routerInput.value ?? 0,
  ),
);

const turnRows = computed<TurnRow[]>(() => {
  const turns = usage.value?.turns ?? [];
  const totals = turns.map((turn) => (turn.promptTokens ?? 0) + (turn.completionTokens ?? 0));
  const heaviest = Math.max(...totals, 1);
  return turns.slice(0, MAX_TURN_ROWS).map((turn, index) => ({
    turn: turn.turn,
    total: totals[index],
    widthPercent: (totals[index] / heaviest) * 100,
    segments: toSegments(turn.promptTokens ?? 0, turn.completionTokens ?? 0, 0),
  }));
});

const hiddenTurnCount = computed(() => Math.max(0, (usage.value?.turns?.length ?? 0) - MAX_TURN_ROWS));

function segmentStyle(segment: Segment): Record<string, string> {
  // Proportional by weight, with a sliver kept by the class so a tiny share still shows.
  return { flex: `${segment.value} 1 0%` };
}
</script>

<template>
  <div
    class="space-y-2"
    :class="usage?.turns ? 'min-w-[17rem]' : 'min-w-[13rem]'"
  >
    <div class="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      <Coins class="h-3.5 w-3.5" />
      Token usage
    </div>
    <div
      v-if="total"
      class="flex h-1.5 overflow-hidden rounded-full bg-muted"
      role="presentation"
    >
      <div
        v-for="segment in segments"
        :key="segment.key"
        class="min-w-[3px]"
        :class="SEGMENT_CLASS[segment.key]"
        :style="segmentStyle(segment)"
      />
    </div>
    <div class="space-y-1 tabular-nums">
      <div class="flex items-center gap-2">
        <span class="h-2 w-2 shrink-0 rounded-full bg-sky-500" />
        <span class="flex-1 text-muted-foreground">Prompt</span>
        <span class="text-sm font-semibold">{{ formatTokenCount(usage?.promptTokens) }}</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="h-2 w-2 shrink-0 rounded-full bg-amber-500" />
        <span class="flex-1 text-muted-foreground">Completion</span>
        <span class="text-sm font-semibold">{{ formatTokenCount(usage?.completionTokens) }}</span>
      </div>
      <!-- Routing decisions are their own spend, so they show beside the model calls
           rather than disappearing into the prompt and completion lines. -->
      <div
        v-if="routerInput !== null"
        class="flex items-center gap-2"
        data-testid="token-usage-router"
      >
        <span class="h-2 w-2 shrink-0 rounded-full bg-violet-500" />
        <span class="flex-1 text-muted-foreground">Model router</span>
        <span class="text-sm font-semibold">{{ formatTokenCount(routerInput) }}</span>
      </div>
    </div>
    <div
      v-if="total !== null"
      class="flex items-center justify-between border-t border-border/60 pt-1.5 tabular-nums"
    >
      <span class="text-muted-foreground">Total</span>
      <span class="text-sm font-semibold">{{ formatTokenCount(total) }}</span>
    </div>
    <!-- What each model call took in and gave back, as its own call_llm row shows it;
         routing is the Model router line above, not part of a turn. -->
    <div
      v-if="usage?.turns"
      class="space-y-1 border-t border-border/60 pt-2 tabular-nums"
      data-testid="token-usage-turns"
    >
      <div class="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        By turn
      </div>
      <div
        v-for="row in turnRows"
        :key="row.turn"
        class="flex items-center gap-2"
      >
        <span class="w-12 shrink-0 text-muted-foreground">Turn {{ row.turn }}</span>
        <div
          class="h-1.5 flex-1 rounded-full bg-muted"
          role="presentation"
        >
          <div
            class="flex h-full overflow-hidden rounded-full"
            :style="{ width: `${row.widthPercent}%` }"
          >
            <div
              v-for="segment in row.segments"
              :key="segment.key"
              class="min-w-[2px]"
              :class="SEGMENT_CLASS[segment.key]"
              :style="segmentStyle(segment)"
            />
          </div>
        </div>
        <span class="w-14 shrink-0 text-right text-sm font-semibold">
          {{ formatTokenCount(row.total) }}
        </span>
      </div>
      <div
        v-if="hiddenTurnCount > 0"
        class="text-muted-foreground"
      >
        +{{ hiddenTurnCount }} more turns
      </div>
    </div>
    <div
      v-if="hint"
      class="text-[11px] text-muted-foreground"
    >
      {{ hint }}
    </div>
  </div>
</template>
