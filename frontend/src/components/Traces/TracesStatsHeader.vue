<script setup lang="ts">
import { computed } from "vue";

import type { TraceStatsResponse } from "@/types/trace";

import Card from "@/components/ui/Card.vue";

interface Props {
  stats: TraceStatsResponse | null;
  loading: boolean;
}

const props = defineProps<Props>();

function fmtNum(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return value.toLocaleString();
}

function fmtCost(value: string | number): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (!Number.isFinite(n) || n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function fmtMs(value: number): string {
  if (!Number.isFinite(value) || value === 0) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  return `${Math.round(value)} ms`;
}

const kpis = computed(() => props.stats?.kpis ?? null);

const hasModelData = computed(() => (props.stats?.by_model.length ?? 0) > 0);
const hasTimeData = computed(() => (props.stats?.by_time.length ?? 0) > 0);

const tokensByModelOptions = computed(() => ({
  chart: { type: "donut" as const, fontFamily: "inherit", toolbar: { show: false } },
  labels: (props.stats?.by_model ?? []).map((m) => m.model),
  legend: { position: "bottom" as const, labels: { colors: "var(--foreground)" } },
  dataLabels: { enabled: false },
  tooltip: {
    y: { formatter: (val: number) => `${fmtNum(val)} tokens` },
  },
}));
const tokensByModelSeries = computed(() =>
  (props.stats?.by_model ?? []).map((m) => m.total_tokens),
);

const costByModelOptions = computed(() => ({
  chart: { type: "donut" as const, fontFamily: "inherit", toolbar: { show: false } },
  labels: (props.stats?.by_model ?? []).map((m) => m.model),
  legend: { position: "bottom" as const, labels: { colors: "var(--foreground)" } },
  dataLabels: { enabled: false },
  tooltip: {
    y: { formatter: (val: number) => fmtCost(val) },
  },
}));
const costByModelSeries = computed(() =>
  (props.stats?.by_model ?? []).map((m) => parseFloat(m.cost_usd) || 0),
);

const callsOverTimeOptions = computed(() => ({
  chart: {
    type: "area" as const,
    stacked: true,
    fontFamily: "inherit",
    toolbar: { show: false },
  },
  xaxis: {
    type: "datetime" as const,
    labels: { style: { colors: "var(--muted-foreground)" } },
  },
  yaxis: {
    labels: {
      style: { colors: "var(--muted-foreground)" },
      formatter: (val: number) => fmtNum(val),
    },
  },
  colors: ["#10b981", "#ef4444"],
  stroke: { curve: "smooth" as const, width: 2 },
  fill: { opacity: 0.3 },
  legend: { position: "bottom" as const, labels: { colors: "var(--foreground)" } },
  dataLabels: { enabled: false },
}));
const callsOverTimeSeries = computed(() => {
  const buckets = props.stats?.by_time ?? [];
  return [
    {
      name: "Success",
      data: buckets.map((b) => [new Date(b.bucket_start).getTime(), b.success]),
    },
    {
      name: "Error",
      data: buckets.map((b) => [new Date(b.bucket_start).getTime(), b.error]),
    },
  ];
});

const hasCostData = computed(() => costByModelSeries.value.some((v) => v > 0));
const showUnpriced = computed(() => (kpis.value?.unpriced_models?.length ?? 0) > 0);
</script>

<template>
  <div class="space-y-4">
    <div class="grid gap-3 grid-cols-2 md:grid-cols-5">
      <Card
        variant="flat"
        :hover="false"
        class="p-3"
      >
        <div class="text-xs text-muted-foreground">
          Calls
        </div>
        <div class="mt-1 text-xl font-semibold">
          {{ loading ? "…" : fmtNum(kpis?.total_calls ?? 0) }}
        </div>
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="p-3"
      >
        <div class="text-xs text-muted-foreground">
          Tokens
        </div>
        <div class="mt-1 text-xl font-semibold">
          {{ loading ? "…" : fmtNum(kpis?.total_tokens ?? 0) }}
        </div>
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="p-3"
      >
        <div class="text-xs text-muted-foreground">
          Cost
        </div>
        <div class="mt-1 text-xl font-semibold">
          {{ loading ? "…" : fmtCost(kpis?.total_cost_usd ?? "0") }}
        </div>
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="p-3"
      >
        <div class="text-xs text-muted-foreground">
          Avg Latency
        </div>
        <div class="mt-1 text-xl font-semibold">
          {{ loading ? "…" : fmtMs(kpis?.avg_latency_ms ?? 0) }}
        </div>
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="p-3"
      >
        <div class="text-xs text-muted-foreground">
          Error %
        </div>
        <div class="mt-1 text-xl font-semibold">
          {{ loading ? "…" : `${(kpis?.error_pct ?? 0).toFixed(1)}%` }}
        </div>
      </Card>
    </div>

    <div class="grid gap-4 md:grid-cols-3">
      <Card
        variant="flat"
        :hover="false"
        class="p-3"
      >
        <div class="text-sm font-medium mb-2">
          Tokens by Model
        </div>
        <div
          v-if="!hasModelData"
          class="flex items-center justify-center h-[240px] text-xs text-muted-foreground"
        >
          No data
        </div>
        <apexchart
          v-else
          type="donut"
          height="240"
          :options="tokensByModelOptions"
          :series="tokensByModelSeries"
        />
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="p-3"
      >
        <div class="text-sm font-medium mb-2">
          Cost by Model
        </div>
        <div
          v-if="!hasModelData || !hasCostData"
          class="flex items-center justify-center h-[240px] text-xs text-muted-foreground"
        >
          {{ !hasModelData ? "No data" : "No pricing configured" }}
        </div>
        <apexchart
          v-else
          type="donut"
          height="240"
          :options="costByModelOptions"
          :series="costByModelSeries"
        />
        <div
          v-if="showUnpriced"
          class="mt-2 text-[11px] text-muted-foreground break-words"
        >
          {{ kpis?.unpriced_models.length }} model(s) without pricing:
          <span class="font-mono">{{ kpis?.unpriced_models.join(", ") }}</span>
        </div>
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="p-3"
      >
        <div class="text-sm font-medium mb-2">
          Calls Over Time
        </div>
        <div
          v-if="!hasTimeData"
          class="flex items-center justify-center h-[240px] text-xs text-muted-foreground"
        >
          No data
        </div>
        <apexchart
          v-else
          type="area"
          height="240"
          :options="callsOverTimeOptions"
          :series="callsOverTimeSeries"
        />
      </Card>
    </div>
  </div>
</template>
