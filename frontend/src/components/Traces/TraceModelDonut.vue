<script setup lang="ts">
import { computed } from "vue";

import type { TraceStatsByModel } from "@/types/trace";

import { useThemeStore } from "@/stores/theme";

interface Props {
  models: TraceStatsByModel[];
  values: number[];
  formatValue: (value: number) => string;
  selectedModel: string | null;
}

interface ApexDonutTooltipContext {
  series: number[];
  seriesIndex: number;
  w: {
    globals?: {
      labels?: string[];
    };
  };
}

interface ApexSelectionConfig {
  dataPointIndex: number;
}

// ApexCharts' default palette, spelled out so a slice can fade without changing hue.
const PALETTE = ["#008FFB", "#00E396", "#FEB019", "#FF4560", "#775DD0"];

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "select", model: string | null): void;
}>();
const themeStore = useThemeStore();

const htmlEscapeMap: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#39;",
};

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => htmlEscapeMap[char] ?? char);
}

function formatTooltip(context: ApexDonutTooltipContext): string {
  const label = context.w.globals?.labels?.[context.seriesIndex] ?? "Model";
  const value = context.series[context.seriesIndex] ?? 0;
  return `<div class="trace-donut-tooltip">${escapeHtml(label)}: <strong>${escapeHtml(props.formatValue(value))}</strong></div>`;
}

// "Other" folds several models together, so it cannot narrow the view to one.
function toggle(index: number): void {
  const row = props.models[index];
  if (!row || row.is_other) return;
  emit("select", row.model === props.selectedModel ? null : row.model);
}

const options = computed(() => ({
  chart: {
    type: "donut" as const,
    fontFamily: "inherit",
    background: "transparent",
    foreColor: themeStore.isDark ? "#94a3b8" : "#64748b",
    toolbar: { show: false },
    events: {
      dataPointSelection: (_event: unknown, _chart: unknown, config: ApexSelectionConfig): void =>
        toggle(config.dataPointIndex),
      legendClick: (_chart: unknown, seriesIndex: number): void => toggle(seriesIndex),
    },
  },
  labels: props.models.map((m) => m.model),
  colors: props.models.map((m, i) => {
    const color = PALETTE[i % PALETTE.length];
    return props.selectedModel && m.model !== props.selectedModel ? `${color}40` : color;
  }),
  legend: {
    position: "bottom" as const,
    labels: { colors: themeStore.isDark ? "#e5e7eb" : "#111827" },
    onItemClick: { toggleDataSeries: false },
  },
  dataLabels: { enabled: false },
  plotOptions: { pie: { expandOnClick: false } },
  states: { active: { filter: { type: "none" } } },
  theme: { mode: themeStore.isDark ? ("dark" as const) : ("light" as const) },
  tooltip: {
    fillSeriesColor: false,
    custom: formatTooltip,
  },
}));
</script>

<template>
  <apexchart
    type="donut"
    height="240"
    :options="options"
    :series="values"
  />
</template>

<style scoped>
:deep(.apexcharts-pie-area) {
  cursor: pointer;
}

:global(.trace-donut-tooltip) {
  border: 1px solid hsl(var(--border));
  border-radius: 0.5rem;
  background: hsl(var(--popover));
  color: hsl(var(--popover-foreground));
  padding: 0.5rem 0.75rem;
  box-shadow: 0 12px 30px hsl(var(--background) / 0.3);
  font-size: 0.875rem;
  font-weight: 500;
  line-height: 1.4;
}

:global(.trace-donut-tooltip strong) {
  color: hsl(var(--foreground));
  font-weight: 700;
}
</style>
