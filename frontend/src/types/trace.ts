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
