<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import HitlCarousel from "@/components/Dashboards/HitlCarousel.vue";
import MarkdownTextContent from "@/components/Dashboards/MarkdownTextContent.vue";
import { renderChartMarkdown } from "@/lib/markdown";
import { hasTaskItems } from "@/lib/markdownTaskList";
import { useThemeStore } from "@/stores/theme";
import type { ChartPayload } from "@/types/dashboard";

const props = defineProps<{
  payload: ChartPayload | Record<string, unknown> | null;
  markdownTaskSaving?: boolean;
}>();

const emit = defineEmits<{
  (e: "markdown-task-toggle", lineIndex: number): void;
  (e: "markdown-task-update", payload: { lineIndex: number; text: string }): void;
}>();

const themeStore = useThemeStore();

// Palette for pie / proportion segments. All colors are mid/deep tones so a single
// white label color stays readable on every slice (no near-white colors here, and
// white is reserved for text — never used as a slice color).
const PROPORTION_COLORS = [
  "#8b5cf6",
  "#ca8a04",
  "#3b82f6",
  "#b45309",
  "#0ea5e9",
  "#16a34a",
  "#ef4444",
  "#ec4899",
  "#0d9488",
  "#ea580c",
];

const CHART_TYPES = new Set<ChartPayload["type"]>([
  "pie",
  "bar",
  "line",
  "area",
  "table",
  "numeric",
  "gauge",
  "scatter",
  "proportion",
  "barGauge",
  "text",
  "hitl",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isChartPayload(value: unknown): value is ChartPayload {
  if (!isRecord(value) || typeof value.type !== "string") return false;
  return CHART_TYPES.has(value.type as ChartPayload["type"]);
}

function normalizeChartPayload(value: ChartPayload | Record<string, unknown> | null): ChartPayload | null {
  if (isChartPayload(value)) return value;
  if (!isRecord(value)) return null;

  const nestedPayloads = Object.values(value).filter(isChartPayload);
  return nestedPayloads.length === 1 ? nestedPayloads[0] : null;
}

const chartPayload = computed((): ChartPayload | null => normalizeChartPayload(props.payload));

interface ProportionSegment {
  label: string;
  pct: number;
  color: string;
}

const proportionSegments = computed((): ProportionSegment[] => {
  const p = chartPayload.value;
  if (!p || p.type !== "proportion") return [];
  const data = (p.series?.[0]?.data ?? []) as number[];
  const labels = p.labels ?? [];
  const total = data.reduce((sum, v) => sum + (typeof v === "number" ? v : 0), 0);
  if (total <= 0) return [];
  return data.map((value, i) => ({
    label: String(labels[i] ?? `Series ${i + 1}`),
    pct: (Number(value) / total) * 100,
    color: PROPORTION_COLORS[i % PROPORTION_COLORS.length],
  }));
});

// Interpolate the red -> amber -> green scale used by the bar-gauge rows.
function gradientColorAt(t: number): string {
  const stops = [
    [239, 68, 68],
    [245, 158, 11],
    [34, 197, 94],
  ];
  const clamped = Math.max(0, Math.min(1, t));
  const seg = clamped < 0.5 ? 0 : 1;
  const local = clamped < 0.5 ? clamped / 0.5 : (clamped - 0.5) / 0.5;
  const c0 = stops[seg];
  const c1 = stops[seg + 1];
  const r = Math.round(c0[0] + (c1[0] - c0[0]) * local);
  const g = Math.round(c0[1] + (c1[1] - c0[1]) * local);
  const b = Math.round(c0[2] + (c1[2] - c0[2]) * local);
  return `rgb(${r}, ${g}, ${b})`;
}

interface BarGaugeRow {
  label: string;
  value: number;
  pct: number;
  valueColor: string;
  gradientSize: string;
}

const barGaugeRows = computed((): BarGaugeRow[] => {
  const p = chartPayload.value;
  if (!p || p.type !== "barGauge") return [];
  const data = (p.series?.[0]?.data ?? []) as number[];
  const labels = p.labels ?? [];
  const values = data.map((v) => (typeof v === "number" ? v : 0));
  const max =
    typeof p.max === "number" && p.max > 0 ? p.max : Math.max(1, ...values);
  return values.map((value, i) => {
    const pct = Math.max(0, Math.min(100, (value / max) * 100));
    return {
      label: String(labels[i] ?? `Row ${i + 1}`),
      value,
      pct,
      valueColor: gradientColorAt(pct / 100),
      // Scale the gradient so the full red->green spans the whole track; the fill
      // width then reveals only the first `pct` of it (short bar = red, long = green).
      gradientSize: pct > 0 ? `${(100 / pct) * 100}% 100%` : "100% 100%",
    };
  });
});

// ApexCharts pie/radialBar derive their radius from the resolved pixel height.
// height="100%" can resolve to 0 on first mount inside a flex card, leaving the
// chart invisible (the original pie-not-rendering bug). Track the real height and
// pass it as a number instead.
const containerRef = ref<HTMLElement | null>(null);
const chartHeight = ref(220);
const chartWidth = ref(220);
let resizeObserver: ResizeObserver | null = null;

onMounted(() => {
  if (!containerRef.value) return;
  resizeObserver = new ResizeObserver((entries) => {
    const rect = entries[0]?.contentRect;
    if (rect && rect.height > 0) chartHeight.value = Math.round(rect.height);
    if (rect && rect.width > 0) chartWidth.value = Math.round(rect.width);
  });
  resizeObserver.observe(containerRef.value);
});

// Pie / radial charts derive their radius from the smaller dimension, so in a tall,
// narrow widget the chart canvas should stay square and be centered vertically —
// otherwise ApexCharts pins the circle to the top and leaves dead space below.
const radialHeight = computed((): number => {
  return Math.max(120, Math.min(chartHeight.value, chartWidth.value));
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
});

const isEmpty = computed((): boolean => {
  const p = chartPayload.value;
  if (!p) return true;
  if (p.type === "table") return !p.rows || p.rows.length === 0;
  if (p.type === "numeric") return p.value === null || p.value === undefined;
  if (p.type === "gauge") return p.value === null || p.value === undefined;
  if (p.type === "text") return !p.text || p.text.trim().length === 0;
  if (p.type === "hitl") return false;
  return !p.series || p.series.length === 0;
});

// Render the markdown body of a `text` chart to sanitized HTML.
const renderedText = computed((): string => {
  const p = chartPayload.value;
  if (!p || p.type !== "text" || !p.text) return "";
  return renderChartMarkdown(p.text);
});

const usesTaskListRenderer = computed((): boolean => {
  const p = chartPayload.value;
  if (!p || p.type !== "text" || !p.text) return false;
  return hasTaskItems(p.text);
});

function onMarkdownTaskToggle(lineIndex: number): void {
  emit("markdown-task-toggle", lineIndex);
}

function onMarkdownTaskUpdate(payload: { lineIndex: number; text: string }): void {
  emit("markdown-task-update", payload);
}

const numericValue = computed((): string => {
  const p = chartPayload.value;
  if (!p || p.value === null || p.value === undefined) return "—";
  const raw = p.value;
  if (typeof raw === "number" && typeof p.decimals === "number") {
    return raw.toFixed(p.decimals);
  }
  return String(raw);
});

const apexType = computed((): "pie" | "bar" | "line" | "area" | "scatter" | "radialBar" => {
  const t = chartPayload.value?.type;
  if (t === "pie") return "pie";
  if (t === "line") return "line";
  if (t === "area") return "area";
  if (t === "scatter") return "scatter";
  if (t === "gauge") return "radialBar";
  return "bar";
});

// Gauge value as a 0-100 percentage of [min, max].
const gaugePercent = computed((): number => {
  const p = chartPayload.value;
  if (!p || typeof p.value !== "number") return 0;
  const min = typeof p.min === "number" ? p.min : 0;
  const max = typeof p.max === "number" ? p.max : 100;
  if (max <= min) return 0;
  return Math.max(0, Math.min(100, ((p.value - min) / (max - min)) * 100));
});

const apexSeries = computed(() => {
  const p = chartPayload.value;
  if (!p) return [];
  if (p.type === "pie") return p.series?.[0]?.data ?? [];
  if (p.type === "gauge") return [gaugePercent.value];
  return p.series ?? [];
});

const apexOptions = computed((): Record<string, unknown> => {
  const p = chartPayload.value;
  if (!p) return {};
  const base: Record<string, unknown> = {
    chart: {
      toolbar: { show: false },
      animations: { enabled: false },
      background: "transparent",
    },
    theme: { mode: themeStore.isDark ? "dark" : "light" },
    grid: { borderColor: themeStore.isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)" },
  };
  // Only set `title` when there is one. Passing `title: undefined` makes ApexCharts
  // choke (the chart does not render) — this is why title-less pie charts were blank.
  if (p.title) {
    base.title = { text: p.title };
  }

  if (p.type === "pie") {
    const dataLabelOffset = -Math.max(12, Math.min(24, Math.round(radialHeight.value * 0.04)));
    return {
      ...base,
      labels: p.labels ?? [],
      colors: PROPORTION_COLORS,
      plotOptions: {
        pie: {
          dataLabels: {
            offset: dataLabelOffset,
            minAngleToShowLabel: 8,
          },
        },
      },
      legend: {
        position: "bottom",
        labels: { colors: themeStore.isDark ? "#e2e8f0" : "#0f172a" },
      },
      // Slice gaps match the card background so slices read cleanly in dark mode.
      stroke: { colors: [themeStore.isDark ? "#0b1220" : "#ffffff"], width: 2 },
      dataLabels: {
        style: { colors: ["#ffffff"], fontSize: "13px", fontWeight: 700 },
        dropShadow: { enabled: false },
      },
      tooltip: { theme: themeStore.isDark ? "dark" : "light", fillSeriesColor: false },
    };
  }

  if (p.type === "gauge") {
    const raw = typeof p.value === "number" ? p.value : 0;
    const unit = p.unit ?? "";
    // Scale the center value with the chart size so it fits the hollow at any
    // widget size (a fixed size overflows small gauges).
    const valueFontPx = Math.max(13, Math.min(34, Math.round(radialHeight.value * 0.13)));
    const nameFontPx = Math.max(9, Math.min(15, Math.round(radialHeight.value * 0.06)));
    return {
      ...base,
      plotOptions: {
        radialBar: {
          hollow: { size: "58%" },
          dataLabels: {
            name: { show: !!p.title, text: p.title ?? "", fontSize: `${nameFontPx}px` },
            value: {
              offsetY: p.title ? Math.round(valueFontPx * 0.48) : Math.round(valueFontPx * 0.38),
              fontSize: `${valueFontPx}px`,
              fontWeight: 600,
              color: themeStore.isDark ? "#f8fafc" : "#0f172a",
              formatter: (): string => `${raw}${unit}`,
            },
          },
        },
      },
      labels: [p.title ?? ""],
    };
  }

  if (p.type === "scatter") {
    return { ...base, xaxis: { type: "numeric" } };
  }

  if (p.type === "area") {
    return {
      ...base,
      colors: PROPORTION_COLORS,
      xaxis: { categories: p.labels ?? [] },
      stroke: { curve: "smooth", width: 2 },
      fill: { type: "gradient", gradient: { opacityFrom: 0.45, opacityTo: 0.05 } },
      legend: { position: "bottom", labels: { colors: themeStore.isDark ? "#e2e8f0" : "#0f172a" } },
    };
  }

  return {
    ...base,
    colors: PROPORTION_COLORS,
    xaxis: { categories: p.labels ?? [] },
    plotOptions: { bar: { horizontal: p.type === "bar" && p.orientation === "horizontal" } },
  };
});
</script>

<template>
  <div
    ref="containerRef"
    class="h-full w-full text-foreground"
  >
    <div
      v-if="isEmpty"
      class="flex h-full min-h-[120px] items-center justify-center text-sm text-muted-foreground"
    >
      No data
    </div>

    <HitlCarousel
      v-else-if="chartPayload && chartPayload.type === 'hitl'"
      :seed-items="chartPayload.items"
      :seed-total="chartPayload.pending_total"
    />

    <div
      v-else-if="chartPayload && chartPayload.type === 'numeric'"
      class="flex h-full min-h-[120px] flex-col items-center justify-center"
    >
      <div class="text-4xl font-semibold tabular-nums text-foreground">
        {{ numericValue }}
      </div>
      <div
        v-if="chartPayload.unit"
        class="mt-1 text-sm text-muted-foreground"
      >
        {{ chartPayload.unit }}
      </div>
    </div>

    <!-- eslint-disable vue/no-v-html -->
    <MarkdownTextContent
      v-else-if="chartPayload && chartPayload.type === 'text' && usesTaskListRenderer"
      :text="chartPayload.text || ''"
      :interactive="!!chartPayload.text_interactive"
      :saving="markdownTaskSaving"
      @toggle="onMarkdownTaskToggle"
      @update="onMarkdownTaskUpdate"
    />
    <div
      v-else-if="chartPayload && chartPayload.type === 'text'"
      class="chart-markdown h-full overflow-auto break-words px-1 py-1 text-sm text-foreground"
      v-html="renderedText"
    />
    <!-- eslint-enable vue/no-v-html -->

    <div
      v-else-if="chartPayload && chartPayload.type === 'table'"
      class="h-full overflow-auto pb-3"
    >
      <table class="w-full text-sm text-foreground">
        <thead class="sticky top-0 bg-card">
          <tr class="border-b border-border">
            <th
              v-for="col in chartPayload.columns"
              :key="col"
              class="px-2 py-1 text-left font-medium text-muted-foreground"
            >
              {{ col }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, rowIndex) in chartPayload.rows"
            :key="rowIndex"
            class="border-b border-border/50"
          >
            <td
              v-for="(cell, cellIndex) in row"
              :key="cellIndex"
              class="px-2 py-1"
            >
              {{ cell }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-else-if="chartPayload && chartPayload.type === 'proportion'"
      class="flex h-full flex-col justify-center gap-4 px-1"
    >
      <div class="flex h-3 w-full overflow-hidden rounded-full bg-muted">
        <div
          v-for="(seg, i) in proportionSegments"
          :key="i"
          class="h-full first:rounded-l-full last:rounded-r-full"
          :style="{ width: seg.pct + '%', backgroundColor: seg.color }"
          :title="`${seg.label} ${seg.pct.toFixed(2)}%`"
        />
      </div>
      <div class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm text-foreground">
        <div
          v-for="(seg, i) in proportionSegments"
          :key="i"
          class="flex items-center gap-2"
        >
          <span
            class="h-2.5 w-2.5 shrink-0 rounded-full"
            :style="{ backgroundColor: seg.color }"
          />
          <span class="truncate">{{ seg.label }} {{ seg.pct.toFixed(2) }}%</span>
        </div>
      </div>
    </div>

    <div
      v-else-if="chartPayload && chartPayload.type === 'barGauge'"
      class="flex h-full flex-col justify-center gap-2 overflow-auto px-1 py-1"
    >
      <div
        v-for="(row, i) in barGaugeRows"
        :key="i"
        class="flex items-center gap-2 text-sm"
      >
        <span class="w-14 shrink-0 truncate text-muted-foreground">{{ row.label }}</span>
        <div class="relative h-4 flex-1 overflow-hidden rounded bg-muted">
          <div
            class="h-full rounded"
            :style="{
              width: row.pct + '%',
              backgroundImage: 'linear-gradient(to right, #ef4444, #f59e0b, #22c55e)',
              backgroundSize: row.gradientSize,
              backgroundRepeat: 'no-repeat',
            }"
          />
        </div>
        <span
          class="w-20 shrink-0 text-right font-semibold tabular-nums"
          :style="{ color: row.valueColor }"
        >
          {{ row.value }}<span
            v-if="chartPayload.unit"
            class="ml-1 text-xs font-normal text-muted-foreground"
          >{{ chartPayload.unit }}</span>
        </span>
      </div>
    </div>

    <!-- Pie / gauge: keep the canvas square and centered in tall, narrow widgets. -->
    <div
      v-else-if="apexType === 'pie' || apexType === 'radialBar'"
      class="flex h-full w-full items-center justify-center"
    >
      <apexchart
        :key="apexType"
        :type="apexType"
        :height="radialHeight"
        :options="apexOptions"
        :series="apexSeries"
      />
    </div>

    <apexchart
      v-else
      :key="apexType"
      :type="apexType"
      :height="chartHeight"
      :options="apexOptions"
      :series="apexSeries"
    />
  </div>
</template>

<style scoped>
.chart-markdown :deep(p) {
  margin: 0 0 0.5rem;
}

.chart-markdown :deep(p:last-child) {
  margin-bottom: 0;
}

.chart-markdown :deep(h1),
.chart-markdown :deep(h2),
.chart-markdown :deep(h3) {
  margin: 0.5rem 0 0.35rem;
  font-weight: 700;
  line-height: 1.2;
}

.chart-markdown :deep(h1) {
  font-size: 1.5rem;
}

.chart-markdown :deep(h2) {
  font-size: 1.25rem;
}

.chart-markdown :deep(h3) {
  font-size: 1.05rem;
}

.chart-markdown :deep(ul),
.chart-markdown :deep(ol) {
  margin: 0 0 0.5rem;
  padding-left: 1.25rem;
}

.chart-markdown :deep(ul) {
  list-style: disc;
}

.chart-markdown :deep(ol) {
  list-style: decimal;
}

.chart-markdown :deep(a) {
  color: rgb(37 99 235);
  text-decoration: underline;
}

.chart-markdown :deep(code) {
  border-radius: 0.25rem;
  background: rgb(0 0 0 / 0.08);
  padding: 0.1rem 0.3rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 0.85em;
}

.chart-markdown :deep(pre) {
  margin: 0 0 0.5rem;
  overflow-x: auto;
  border-radius: 0.375rem;
  background: rgb(0 0 0 / 0.06);
  padding: 0.5rem 0.75rem;
}

.chart-markdown :deep(pre code) {
  background: transparent;
  padding: 0;
}

.chart-markdown :deep(strong) {
  font-weight: 700;
}

.chart-markdown :deep(em) {
  font-style: italic;
}

.chart-markdown :deep(blockquote) {
  margin: 0 0 0.5rem;
  border-left: 3px solid rgb(0 0 0 / 0.15);
  padding-left: 0.75rem;
  color: hsl(var(--muted-foreground));
}

.chart-markdown :deep(hr) {
  margin: 0.75rem 0;
  border: none;
  border-top: 1px solid hsl(var(--border));
}

:global(.dark) .chart-markdown :deep(a) {
  color: rgb(96 165 250);
}

:global(.dark) .chart-markdown :deep(code),
:global(.dark) .chart-markdown :deep(pre) {
  background: rgb(255 255 255 / 0.1);
}
</style>
