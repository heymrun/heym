export interface AnalyticsStats {
  total_executions: number;
  success_count: number;
  error_count: number;
  success_rate: number;
  error_rate: number;
  avg_latency_ms: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  total_executions_24h: number;
  success_count_24h: number;
  error_count_24h: number;
  avg_latency_24h_ms: number;
}

export interface TimeSeriesMetrics {
  time_buckets: string[];
  executions: number[];
  successes: number[];
  errors: number[];
  avg_latency_ms: number[];
}

export type TimeRange = "24h" | "7d" | "30d" | "all";
export type BucketSize = "1h" | "6h" | "1d";

export interface AnalyticsDateRange {
  startAt: string;
  endAt: string;
}

export interface AnalyticsQueryOptions {
  timeRange?: TimeRange;
  bucketSize?: BucketSize;
  dateRange?: AnalyticsDateRange | null;
}

export interface WorkflowBreakdownItem {
  workflow_id: string;
  workflow_name: string;
  execution_count: number;
  success_count: number;
  error_count: number;
  success_rate: number;
  error_rate: number;
  avg_latency_ms: number;
}

export interface WorkflowBreakdownResponse {
  items: WorkflowBreakdownItem[];
}
