import type { NodeTypeAnalytics, NodeTypeSeriesItem } from "@/types/analytics";

export type NodeTypeMetric = "duration" | "errors" | "calls";

export const NODE_TYPE_METRICS: NodeTypeMetric[] = ["duration", "errors", "calls"];

export const NODE_TYPE_EMPTY_MESSAGE =
  "No node data for this period yet. Node analytics are recorded for runs after this update.";

/** Ten distinct series colors that read on both light and dark cards. */
export const NODE_TYPE_CHART_COLORS: string[] = [
  "#3b82f6",
  "#f59e0b",
  "#10b981",
  "#ef4444",
  "#8b5cf6",
  "#06b6d4",
  "#ec4899",
  "#84cc16",
  "#f97316",
  "#64748b",
];

export interface ChartBaseOptions {
  chart: Record<string, unknown>;
  tooltip: Record<string, unknown>;
  yaxis: Record<string, unknown>;
  [key: string]: unknown;
}

export interface NodeTypeChartPoint {
  x: number;
  y: number;
  /** No calls in this bucket. ApexCharts cannot draw a lone point between gaps, so the
   * duration chart draws 0 here and its tooltip says "No calls" instead. */
  empty: boolean;
}

export interface NodeTypeChartSeries {
  name: string;
  data: NodeTypeChartPoint[];
}

export interface NodeTypeChartModel {
  metric: NodeTypeMetric;
  title: string;
  subtitle: string;
  series: NodeTypeChartSeries[];
}

interface ChartCopy {
  title: string;
  subtitle: string;
}

// Named like the workflow tables below them: Most Used and Most Failed Workflows.
const CHART_COPY: Record<NodeTypeMetric, ChartCopy> = {
  duration: { title: "Most Time Taken Nodes", subtitle: "Average duration per call" },
  errors: { title: "Most Failed Node Types", subtitle: "Errors over time" },
  calls: { title: "Most Called Node Types", subtitle: "Calls over time" },
};

// A type whose highest point is under this share of the chart's highest point draws as a
// flat line on the axis, so its legend entry would name a line nobody can see.
const VISIBLE_SHARE = 0.01;

export function formatDurationMs(ms: number): string {
  if (ms < 10) return `${Number(ms.toFixed(1))}ms`;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const totalMinutes = Math.floor(seconds / 60);
  if (totalMinutes < 60) return `${totalMinutes}m ${Math.floor(seconds % 60)}s`;
  const hours = Math.floor(totalMinutes / 60);
  return `${hours.toLocaleString("en-US")}h ${totalMinutes % 60}m`;
}

function rankedItems(metric: NodeTypeMetric, analytics: NodeTypeAnalytics): NodeTypeSeriesItem[] {
  if (metric === "duration") return analytics.most_duration;
  if (metric === "errors") return analytics.most_errors;
  return analytics.most_calls;
}

/** The y axis is split into this many steps; axisMax picks a top that divides evenly. */
export const AXIS_TICKS = 5;

const NICE_LEADS = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 8, 10];

function niceCeil(value: number, wholeSteps: boolean): number {
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const lead of NICE_LEADS) {
    const top = lead * magnitude;
    if (top >= value && (!wholeSteps || Number.isInteger(top / AXIS_TICKS))) return top;
  }
  return 10 * magnitude;
}

/** The y-axis top: a round value 10% or more above the highest visible one. */
export function axisMax(metric: NodeTypeMetric, visibleMax: number): number {
  const padded = visibleMax * 1.1;
  if (padded <= 0) return metric === "duration" ? 1 : AXIS_TICKS;
  if (metric === "duration") return niceCeil(padded, false);
  return niceCeil(Math.max(padded, AXIS_TICKS), true);
}

// Counts are whole; durations under 10ms keep a tenth so 2.5ms does not draw as 3.
function roundValue(metric: NodeTypeMetric, value: number): number {
  if (metric === "duration" && value < 10) return Math.round(value * 10) / 10;
  return Math.round(value);
}

function highest(series: NodeTypeChartSeries): number {
  return series.data.reduce((top, point) => Math.max(top, point.y), 0);
}

/** One chart's series, each at its own value, without types too small to see. */
export function buildNodeTypeChart(
  metric: NodeTypeMetric,
  analytics: NodeTypeAnalytics | null,
  labelFor: (nodeType: string) => string,
): NodeTypeChartModel {
  const items = analytics ? rankedItems(metric, analytics) : [];
  const times = analytics ? analytics.time_buckets.map((bucket) => Date.parse(bucket)) : [];
  const series = items.map((item) => ({
    name: labelFor(item.node_type),
    data: times.map((x, index) => {
      const value = item.values[index] ?? null;
      return { x, y: value === null ? 0 : roundValue(metric, value), empty: value === null };
    }),
  }));
  const chartTop = series.reduce((top, item) => Math.max(top, highest(item)), 0);
  const visible = series.filter((item) => chartTop > 0 && highest(item) >= chartTop * VISIBLE_SHARE);
  return { metric, ...CHART_COPY[metric], series: visible };
}
