export interface LLMPricingRow {
  id: string;
  provider: string | null;
  model: string;
  operator: "equals" | "startsWith" | "includes";
  input_per_1m_usd: string;
  output_per_1m_usd: string;
  source: string;
  is_override: boolean;
  is_custom: boolean;
  override_id: string | null;
  updated_at: string;
}

export interface LLMPricingSyncStatus {
  last_synced_at: string | null;
  total_rows: number;
  override_rows: number;
}

export interface LLMPricingPatchPayload {
  input_per_1m_usd: string;
  output_per_1m_usd: string;
  note?: string | null;
}

export interface LLMPricingCustomPayload {
  model: string;
  input_per_1m_usd: string;
  output_per_1m_usd: string;
  note?: string | null;
}
