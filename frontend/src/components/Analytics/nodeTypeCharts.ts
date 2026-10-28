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
  y: number | null;
}

export interface NodeTypeChartSeries {
  name: string;
  data: NodeTypeChartPoint[];
}

export interface NodeTypeChartModel {
  metric: NodeTypeMetric;
  title: string;
  subtitle: string;
  leader: string | null;
  stacked: boolean;
  series: NodeTypeChartSeries[];
}

interface ChartCopy {
  title: string;
  subtitle: string;
}

const CHART_COPY: Record<NodeTypeMetric, ChartCopy> = {
  duration: {
    title: "Average Node Duration Over Time",
    subtitle: "Top 10 node types by total time",
  },
  errors: { title: "Node Errors Over Time", subtitle: "Top 10 node types by errors" },
  calls: { title: "Node Calls Over Time", subtitle: "Top 10 node types by calls" },
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

function formatCount(value: number, singular: string, plural: string): string {
  const count = new Intl.NumberFormat("en-US").format(Math.round(value));
  return `${count} ${value === 1 ? singular : plural}`;
}

function rankedItems(metric: NodeTypeMetric, analytics: NodeTypeAnalytics): NodeTypeSeriesItem[] {
  if (metric === "duration") return analytics.most_duration;
  if (metric === "errors") return analytics.most_errors;
  return analytics.most_calls;
}

function leaderText(metric: NodeTypeMetric, item: NodeTypeSeriesItem, label: string): string {
  if (metric === "duration") {
    const average = item.average === null ? "" : ` · avg ${formatDurationMs(item.average)}`;
    return `#1 ${label}${average} · ${formatDurationMs(item.total)} total`;
  }
  if (metric === "errors") return `#1 ${label} · ${formatCount(item.total, "error", "errors")}`;
  return `#1 ${label} · ${formatCount(item.total, "call", "calls")}`;
}

/** One chart's series and header; averages are not stacked because they do not add up. */
export function buildNodeTypeChart(
  metric: NodeTypeMetric,
  analytics: NodeTypeAnalytics | null,
  labelFor: (nodeType: string) => string,
): NodeTypeChartModel {
  const items = analytics ? rankedItems(metric, analytics) : [];
  const times = analytics ? analytics.time_buckets.map((bucket) => Date.parse(bucket)) : [];
  const first = items[0];
  return {
    metric,
    ...CHART_COPY[metric],
    leader: first ? leaderText(metric, first, labelFor(first.node_type)) : null,
    stacked: metric !== "duration",
    series: items.map((item) => ({
      name: labelFor(item.node_type),
      data: times.map((x, index) => {
        const value = item.values[index] ?? null;
        return { x, y: value === null ? null : Math.round(value) };
      }),
    })),
  };
}
