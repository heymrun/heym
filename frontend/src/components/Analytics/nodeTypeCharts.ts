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

export interface NodeTypeChartMarker {
  seriesIndex: number;
  dataPointIndex: number;
  fillColor: string;
  strokeColor: string;
  size: number;
}

export interface NodeTypeChartModel {
  metric: NodeTypeMetric;
  title: string;
  subtitle: string;
  stacked: boolean;
  series: NodeTypeChartSeries[];
  markers: NodeTypeChartMarker[];
}

interface ChartCopy {
  title: string;
  subtitle: string;
}

// Named like the workflow tables below them: Most Used and Most Failed Workflows.
const CHART_COPY: Record<NodeTypeMetric, ChartCopy> = {
  duration: { title: "Most Time-Consuming Node Types", subtitle: "Average duration per call" },
  errors: { title: "Most Failed Node Types", subtitle: "Errors over time" },
  calls: { title: "Most Called Node Types", subtitle: "Calls over time" },
};

export function formatDurationMs(ms: number): string {
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

function hasValue(point: NodeTypeChartPoint | undefined): boolean {
  return point !== undefined && !point.empty && point.y > 0;
}

/** Dots for points with no neighbor to draw a line to: an area chart leaves them invisible. */
export function isolatedPointMarkers(series: NodeTypeChartSeries[]): NodeTypeChartMarker[] {
  const markers: NodeTypeChartMarker[] = [];
  series.forEach((item, seriesIndex) => {
    const color = NODE_TYPE_CHART_COLORS[seriesIndex % NODE_TYPE_CHART_COLORS.length];
    item.data.forEach((point, dataPointIndex) => {
      if (!hasValue(point)) return;
      if (hasValue(item.data[dataPointIndex - 1]) || hasValue(item.data[dataPointIndex + 1])) return;
      markers.push({ seriesIndex, dataPointIndex, fillColor: color, strokeColor: color, size: 4 });
    });
  });
  return markers;
}

/** One chart's series; averages are not stacked because they do not add up. */
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
      return { x, y: value === null ? 0 : Math.round(value), empty: value === null };
    }),
  }));
  return {
    metric,
    ...CHART_COPY[metric],
    stacked: metric !== "duration",
    series,
    markers: isolatedPointMarkers(series),
  };
}
