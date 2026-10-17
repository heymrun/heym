<script setup lang="ts">
import { computed } from "vue";

import type { TraceStatsByModel } from "@/types/trace";

import { useThemeStore } from "@/stores/theme";

interface Props {
  models: TraceStatsByModel[];
  selectedModel: string | null;
}

interface SpeedRow {
  model: string;
  tokensPerSecond: number;
}

interface ApexSelectionConfig {
  dataPointIndex: number;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "select", model: string | null): void;
}>();
const themeStore = useThemeStore();

function fmtSpeed(value: number): string {
  return value >= 100 ? Math.round(value).toLocaleString() : value.toFixed(1);
}

// "Other" mixes models, so the backend leaves its speed empty and it drops out here.
const rows = computed<SpeedRow[]>(() =>
  props.models
    .flatMap((m): SpeedRow[] => {
      const speed = m.output_tokens_per_second;
      return speed != null && speed > 0 ? [{ model: m.model, tokensPerSecond: speed }] : [];
    })
    .sort((a, b) => b.tokensPerSecond - a.tokensPerSecond),
);
const maxSpeed = computed(() => rows.value[0]?.tokensPerSecond ?? 0);
// Keeps each bar near 20px whether one model is listed or eight.
const barHeight = computed(() => `${Math.min(70, Math.round((rows.value.length * 20 * 100) / 190))}%`);

function fmtAxis(value: number): string {
  return maxSpeed.value >= 10 ? Math.round(value).toLocaleString() : value.toFixed(1);
}

function toggle(index: number): void {
  const row = rows.value[index];
  if (!row) return;
  emit("select", row.model === props.selectedModel ? null : row.model);
}

const barColor = computed(() => (themeStore.isDark ? "#3987e5" : "#2a78d6"));

const options = computed(() => ({
  chart: {
    type: "bar" as const,
    fontFamily: "inherit",
    background: "transparent",
    foreColor: themeStore.isDark ? "#94a3b8" : "#64748b",
    // One series stacked so the value prints as a bar total: ApexCharts pins plain
    // start-anchored labels to the axis once they are wider than their bar.
    stacked: true,
    toolbar: { show: false },
    events: {
      dataPointSelection: (_event: unknown, _chart: unknown, config: ApexSelectionConfig): void =>
        toggle(config.dataPointIndex),
    },
  },
  theme: { mode: themeStore.isDark ? ("dark" as const) : ("light" as const) },
  colors: [barColor.value],
  states: { active: { filter: { type: "none" } } },
  plotOptions: {
    bar: {
      horizontal: true,
      barHeight: barHeight.value,
      borderRadius: 4,
      borderRadiusApplication: "end" as const,
      dataLabels: {
        total: {
          enabled: true,
          offsetX: 6,
          formatter: (val?: string): string => fmtSpeed(Number(val)),
          style: {
            color: themeStore.isDark ? "#e5e7eb" : "#111827",
            fontSize: "11px",
            fontWeight: 500,
          },
        },
      },
    },
  },
  dataLabels: { enabled: false },
  xaxis: {
    min: 0,
    // Headroom so the value printed past the longest bar stays inside the plot.
    max: maxSpeed.value * 1.2,
    tickAmount: 4,
    labels: { formatter: (val: string): string => fmtAxis(Number(val)) },
  },
  yaxis: {
    labels: {
      maxWidth: 140,
      style: { colors: themeStore.isDark ? "#e5e7eb" : "#111827" },
    },
  },
  grid: {
    borderColor: themeStore.isDark ? "rgba(148, 163, 184, 0.24)" : "rgba(100, 116, 139, 0.22)",
    xaxis: { lines: { show: true } },
    yaxis: { lines: { show: false } },
  },
  legend: { show: false },
  tooltip: {
    theme: themeStore.isDark ? "dark" : "light",
    y: {
      formatter: (val: number): string => `${fmtSpeed(val)} tok/s`,
      title: { formatter: (): string => "Output" },
    },
  },
}));
const series = computed(() => [
  {
    name: "Output",
    data: rows.value.map((r) => ({
      x: r.model,
      y: r.tokensPerSecond,
      fillColor:
        props.selectedModel && r.model !== props.selectedModel
          ? `${barColor.value}40`
          : barColor.value,
    })),
  },
]);
</script>

<template>
  <div
    v-if="rows.length === 0"
    class="flex items-center justify-center h-[240px] text-xs text-muted-foreground"
  >
    No data
  </div>
  <apexchart
    v-else
    type="bar"
    height="240"
    :options="options"
    :series="series"
  />
</template>

<style scoped>
:deep(.apexcharts-bar-area) {
  cursor: pointer;
}
</style>
