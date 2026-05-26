export interface LLMTraceListItem {
  id: string;
  created_at: string;
  source: string;
  request_type: string;
  provider: string | null;
  model: string | null;
  credential_id: string | null;
  credential_name: string | null;
  workflow_id: string | null;
  workflow_name: string | null;
  node_id: string | null;
  node_label: string | null;
  status: string;
  elapsed_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
}

export interface LLMTraceDetail extends LLMTraceListItem {
  request: Record<string, unknown>;
  response: Record<string, unknown>;
  error: string | null;
}

export interface LLMTraceListResponse {
  items: LLMTraceListItem[];
  total: number;
  limit: number;
  offset: number;
}

export type TraceTimeRange = "1h" | "24h" | "7d" | "30d" | "all";

export interface TraceStatsRangeMeta {
  start: string | null;
  end: string;
  bucket_seconds: number;
}

export interface TraceStatsKpis {
  total_calls: number;
  success_calls: number;
  error_calls: number;
  error_pct: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  total_cost_usd: string;
  avg_latency_ms: number;
  unpriced_models: string[];
}

export interface TraceStatsByModel {
  model: string;
  provider: string | null;
  calls: number;
  total_tokens: number;
  cost_usd: string;
  is_priced: boolean;
  is_other?: boolean;
}

export interface TraceStatsByTime {
  bucket_start: string;
  calls: number;
  success: number;
  error: number;
  total_tokens: number;
  cost_usd: string;
}

export interface TraceStatsResponse {
  range: TraceStatsRangeMeta;
  kpis: TraceStatsKpis;
  by_model: TraceStatsByModel[];
  by_time: TraceStatsByTime[];
}
