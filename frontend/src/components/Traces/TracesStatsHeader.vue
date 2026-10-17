<script setup lang="ts">
import { computed } from "vue";

import type { TraceStatsResponse } from "@/types/trace";

import TraceModelDonut from "@/components/Traces/TraceModelDonut.vue";
import TraceModelSpeedChart from "@/components/Traces/TraceModelSpeedChart.vue";
import Card from "@/components/ui/Card.vue";
import { useThemeStore } from "@/stores/theme";

interface Props {
  /** Every model in the window; the model charts offer these to pick from. */
  stats: TraceStatsResponse | null;
  /** Narrowed to the picked model, or the same as `stats` when none is picked. */
  scopedStats: TraceStatsResponse | null;
  loading: boolean;
  selectedModel: string | null;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "configure-pricing", model: string): void;
  (e: "select-model", model: string | null): void;
}>();
const themeStore = useThemeStore();

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

function fmtTokens(value: number): string {
  return `${fmtNum(value)} tokens`;
}

const kpis = computed(() => props.scopedStats?.kpis ?? null);
const models = computed(() => props.stats?.by_model ?? []);
const chartTheme = computed(() => themeStore.isDark ? "dark" : "light");
const chartTextColor = computed(() => themeStore.isDark ? "#e5e7eb" : "#111827");
const chartMutedTextColor = computed(() => themeStore.isDark ? "#94a3b8" : "#64748b");
const chartGridColor = computed(() =>
  themeStore.isDark ? "rgba(148, 163, 184, 0.24)" : "rgba(100, 116, 139, 0.22)",
);

const hasModelData = computed(() => models.value.length > 0);
const hasTimeData = computed(() => (props.scopedStats?.by_time.length ?? 0) > 0);

const tokensByModelSeries = computed(() => models.value.map((m) => m.total_tokens));
const costByModelSeries = computed(() =>
  models.value.map((m) => parseFloat(m.cost_usd) || 0),
);

function selectModel(model: string | null): void {
  emit("select-model", model);
}

const callsOverTimeOptions = computed(() => ({
  chart: {
    type: "area" as const,
    stacked: true,
    fontFamily: "inherit",
    background: "transparent",
    foreColor: chartMutedTextColor.value,
    toolbar: { show: false },
  },
  theme: { mode: chartTheme.value },
  xaxis: {
    type: "datetime" as const,
    labels: { style: { colors: chartMutedTextColor.value } },
  },
  yaxis: {
    labels: {
      style: { colors: chartMutedTextColor.value },
      formatter: (val: number) => fmtNum(val),
    },
  },
  grid: { borderColor: chartGridColor.value },
  colors: ["#10b981", "#ef4444"],
  stroke: { curve: "smooth" as const, width: 2 },
  fill: { opacity: 0.3 },
  legend: { position: "bottom" as const, labels: { colors: chartTextColor.value } },
  dataLabels: { enabled: false },
  tooltip: { theme: chartTheme.value },
}));
const callsOverTimeSeries = computed(() => {
  const buckets = props.scopedStats?.by_time ?? [];
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
const unpricedModels = computed(() => props.stats?.kpis.unpriced_models ?? []);
const showUnpriced = computed(() => unpricedModels.value.length > 0);
</script>

<template>
  <div class="space-y-4">
    <div class="grid grid-cols-5 gap-2 md:gap-3">
      <Card
        variant="flat"
        :hover="false"
        class="px-3 py-2.5 md:p-3 min-w-0"
      >
        <div class="text-[10px] md:text-xs text-muted-foreground truncate">
          Calls
        </div>
        <div class="mt-1 text-sm md:text-xl font-semibold truncate">
          {{ loading ? "…" : fmtNum(kpis?.total_calls ?? 0) }}
        </div>
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="px-3 py-2.5 md:p-3 min-w-0"
      >
        <div class="text-[10px] md:text-xs text-muted-foreground truncate">
          Tokens
        </div>
        <div class="mt-1 text-sm md:text-xl font-semibold truncate">
          {{ loading ? "…" : fmtNum(kpis?.total_tokens ?? 0) }}
        </div>
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="px-3 py-2.5 md:p-3 min-w-0"
      >
        <div class="text-[10px] md:text-xs text-muted-foreground truncate">
          Cost
        </div>
        <div class="mt-1 text-sm md:text-xl font-semibold truncate">
          {{ loading ? "…" : fmtCost(kpis?.total_cost_usd ?? "0") }}
        </div>
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="px-3 py-2.5 md:p-3 min-w-0"
      >
        <div class="text-[10px] md:text-xs text-muted-foreground truncate">
          <span class="md:hidden">Lat.</span>
          <span class="hidden md:inline">Avg Latency</span>
        </div>
        <div class="mt-1 text-sm md:text-xl font-semibold truncate">
          {{ loading ? "…" : fmtMs(kpis?.avg_latency_ms ?? 0) }}
        </div>
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="px-3 py-2.5 md:p-3 min-w-0"
      >
        <div class="text-[10px] md:text-xs text-muted-foreground truncate">
          <span class="md:hidden">Err%</span>
          <span class="hidden md:inline">Error %</span>
        </div>
        <div class="mt-1 text-sm md:text-xl font-semibold truncate">
          {{ loading ? "…" : `${(kpis?.error_pct ?? 0).toFixed(1)}%` }}
        </div>
      </Card>
    </div>

    <div class="grid gap-4 md:grid-cols-2">
      <Card
        variant="flat"
        :hover="false"
        class="trace-chart-card p-3"
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
        <TraceModelDonut
          v-else
          :models="models"
          :values="tokensByModelSeries"
          :format-value="fmtTokens"
          :selected-model="selectedModel"
          @select="selectModel"
        />
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="trace-chart-card p-3"
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
        <TraceModelDonut
          v-else
          :models="models"
          :values="costByModelSeries"
          :format-value="fmtCost"
          :selected-model="selectedModel"
          @select="selectModel"
        />
        <div
          v-if="showUnpriced"
          class="unpriced-models-notice mt-2 max-w-full text-[11px] text-muted-foreground break-words"
        >
          {{ unpricedModels.length }} model(s) without pricing:
          <template
            v-for="(model, index) in unpricedModels"
            :key="model"
          >
            <a
              href="#"
              class="font-mono underline decoration-muted-foreground/60 underline-offset-2 transition-colors hover:text-primary hover:decoration-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2 rounded-sm"
              @click.prevent="emit('configure-pricing', model)"
            >{{ model }}</a><span v-if="index < unpricedModels.length - 1">, </span>
          </template>
        </div>
      </Card>
      <Card
        variant="flat"
        :hover="false"
        class="trace-chart-card p-3"
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
      <Card
        variant="flat"
        :hover="false"
        class="trace-chart-card p-3"
      >
        <div class="flex items-baseline justify-between gap-2 mb-2">
          <div class="text-sm font-medium truncate">
            Tokens/sec by Model
          </div>
          <div
            class="text-[11px] text-muted-foreground shrink-0"
            title="Output tokens divided by the time spent waiting on the model, network and first token included. Successful calls only; tool time is excluded."
          >
            output, end to end
          </div>
        </div>
        <TraceModelSpeedChart
          :models="models"
          :selected-model="selectedModel"
          @select="selectModel"
        />
      </Card>
    </div>
  </div>
</template>

<style scoped>
.trace-chart-card :deep(.apexcharts-canvas),
.trace-chart-card :deep(.apexcharts-canvas svg) {
  background: transparent !important;
}

.trace-chart-card :deep(.apexcharts-tooltip) {
  background: hsl(var(--popover)) !important;
  border-color: hsl(var(--border)) !important;
  color: hsl(var(--popover-foreground)) !important;
  box-shadow: 0 12px 30px hsl(var(--background) / 0.3) !important;
}

.unpriced-models-notice {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.trace-chart-card :deep(.apexcharts-tooltip-title) {
  background: hsl(var(--muted)) !important;
  border-color: hsl(var(--border)) !important;
  color: hsl(var(--foreground)) !important;
}

.trace-chart-card :deep(.apexcharts-tooltip-text),
.trace-chart-card :deep(.apexcharts-tooltip-y-group),
.trace-chart-card :deep(.apexcharts-xaxistooltip) {
  color: hsl(var(--foreground)) !important;
}

.trace-chart-card :deep(.apexcharts-xaxistooltip) {
  background: hsl(var(--popover)) !important;
  border-color: hsl(var(--border)) !important;
}
</style>
