<script setup lang="ts">
import { RefreshCw } from "lucide-vue-next";

import AgentSuiteToolAssertions from "@/components/Evals/AgentSuite/AgentSuiteToolAssertions.vue";
import {
  baselineSourceLabel,
  formatCount,
  formatMs,
  formatRunTime,
  formatUsd,
} from "@/components/Evals/AgentSuite/agentSuiteFormat";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import type { AgentBaseline, AgentThresholds, AgentToolUsage, ToolAssertion } from "@/types/evals";

type ThresholdKey = keyof AgentThresholds;

interface Props {
  tools: AgentToolUsage[];
  runCount: number;
  assertions: ToolAssertion[];
  thresholds: AgentThresholds;
  suggested: AgentThresholds;
  baseline: AgentBaseline | null;
  /** The snapshot a saved suite compares against; absent while creating one. */
  savedBaseline?: AgentBaseline | null;
  refreshing?: boolean;
}

const props = withDefaults(defineProps<Props>(), { savedBaseline: null, refreshing: false });

const emit = defineEmits<{
  (e: "update:assertions", value: ToolAssertion[]): void;
  (e: "update:thresholds", value: AgentThresholds): void;
  (e: "refresh-baseline"): void;
}>();

const THRESHOLD_FIELDS: {
  key: ThresholdKey;
  label: string;
  unit: string;
  integer: boolean;
  baselineText: (baseline: AgentBaseline) => string;
}[] = [
  {
    key: "latency_ms",
    label: "Latency",
    unit: "ms",
    integer: true,
    baselineText: (b) => `Baseline p95 ${formatMs(b.latency_p95_ms)}`,
  },
  {
    key: "cost_usd",
    label: "Cost",
    unit: "USD",
    integer: false,
    baselineText: (b) => `Baseline p95 ${formatUsd(b.cost_p95_usd)}`,
  },
  {
    key: "total_tokens",
    label: "Total tokens",
    unit: "tokens",
    integer: true,
    baselineText: (b) => `Baseline p95 ${formatCount(b.tokens_p95)}`,
  },
  {
    key: "tool_calls",
    label: "Tool calls",
    unit: "calls",
    integer: true,
    baselineText: (b) => `Baseline max ${formatCount(b.tool_calls_max)}`,
  },
];

function toggleThreshold(key: ThresholdKey, enabled: boolean): void {
  const fallback = key === "cost_usd" ? 0.01 : 1;
  emit("update:thresholds", {
    ...props.thresholds,
    [key]: enabled ? (props.suggested[key] ?? fallback) : null,
  });
}

function setThreshold(key: ThresholdKey, raw: string, integer: boolean): void {
  const parsed = integer ? parseInt(raw, 10) : parseFloat(raw);
  if (Number.isNaN(parsed) || parsed < 0) return;
  emit("update:thresholds", { ...props.thresholds, [key]: parsed });
}
</script>

<template>
  <div class="space-y-6">
    <AgentSuiteToolAssertions
      :tools="tools"
      :run-count="runCount"
      :assertions="assertions"
      @update:assertions="(value) => emit('update:assertions', value)"
    />

    <section>
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h3 class="text-sm font-medium text-foreground">
          Thresholds
        </h3>
        <div
          v-if="savedBaseline"
          class="flex items-center gap-2 text-xs text-muted-foreground"
        >
          <span v-if="savedBaseline.captured_at">
            Saved baseline: {{ formatRunTime(savedBaseline.captured_at) }} ·
            {{ baselineSourceLabel(savedBaseline) }}
          </span>
          <Button
            variant="outline"
            size="sm"
            class="gap-1.5"
            :loading="refreshing"
            data-testid="agent-suite-refresh-baseline"
            @click="emit('refresh-baseline')"
          >
            <RefreshCw class="h-3.5 w-3.5" />
            Use latest runs as baseline
          </Button>
        </div>
      </div>
      <p class="mb-3 mt-1 text-xs text-muted-foreground">
        Upper bounds per run, suggested 20% above the baseline. A run of an unpriced model skips
        the cost check.
      </p>
      <div class="divide-y divide-border/40 rounded-xl border border-border/60">
        <div
          v-for="field in THRESHOLD_FIELDS"
          :key="field.key"
          class="flex flex-wrap items-center gap-3 px-3 py-2.5"
        >
          <label class="flex w-40 cursor-pointer items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              :checked="thresholds[field.key] !== null"
              :data-testid="`agent-suite-threshold-${field.key}`"
              @change="toggleThreshold(field.key, ($event.target as HTMLInputElement).checked)"
            >
            {{ field.label }}
          </label>
          <div class="flex items-center gap-2">
            <span class="text-xs text-muted-foreground">≤</span>
            <Input
              :model-value="thresholds[field.key] === null ? '' : String(thresholds[field.key])"
              type="number"
              min="0"
              :step="field.integer ? '1' : '0.0001'"
              class="w-32"
              :disabled="thresholds[field.key] === null"
              @update:model-value="(v) => setThreshold(field.key, v, field.integer)"
            />
            <span class="text-xs text-muted-foreground">{{ field.unit }}</span>
          </div>
          <span
            v-if="baseline && baseline.run_count > 0"
            class="ml-auto text-xs text-muted-foreground"
          >
            {{ field.baselineText(baseline) }}
          </span>
        </div>
      </div>
    </section>
  </div>
</template>
