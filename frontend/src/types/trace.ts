export interface TraceSpan {
  id: string;
  label: string;
  durationMs: number;
  icon: "invocation" | "agent" | "llm" | "tool" | "router";
  /** Offset from the start of the request; where the bar begins on the track. */
  startMs?: number;
  /** When set, the row opens that trace in a new tab. */
  traceId?: string | null;
  /** When there is no separate trace, the row jumps to this step instead. */
  stepId?: string | null;
  /** Tokens one model call used; set on per-turn model rows so a hover can show them. */
  usage?: TraceSpanUsage;
  /** What a tool's output added to the next turn's prompt; set on tool rows. */
  toolTokens?: ToolTokenEstimate;
}

/**
 * A tool spends no tokens itself; its output is read by the next turn. This is how
 * much that turn's prompt grew because of it, so it is an estimate, not a meter.
 */
export interface ToolTokenEstimate {
  tokens: number;
  /** The turn that read the output. */
  readByTurn: number;
  /** Tools asked for by the same turn, this one included; they share the growth. */
  sharedBy: number;
}

export interface TraceSpanTokens {
  promptTokens: number | null;
  completionTokens: number | null;
}

export interface TraceSpanUsage extends TraceSpanTokens {
  /** On the invocation row: what routing decisions spent, kept apart from the model calls. */
  router?: TraceSpanTokens;
  /** On the invocation row of a multi-turn request: what each turn used. */
  turns?: TraceSpanTurnUsage[];
}

export interface TraceSpanTurnUsage extends TraceSpanTokens {
  turn: number;
}

export interface LLMTraceListItem {
  id: string;
  created_at: string;
  source: string;
  request_type: string;
  provider: string | null;
  model: string | null;
  credential_id: string | null;
  credential_name: string | null;
  /** Set when a Model Router chose the model; `model` above is what actually ran. */
  router_credential_id?: string | null;
  router_label?: string | null;
  workflow_id: string | null;
  workflow_name: string | null;
  node_id: string | null;
  node_label: string | null;
  status: string;
  elapsed_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cost_usd: string | null;
  is_priced: boolean;
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
