export type AlertType =
  | "error_threshold"
  | "workflow_duration"
  | "token_cost"
  | "execution_count";
export type AlertScope = "workflow" | "system";
export type AlertState = "ok" | "triggered";
export type RenotifyMode = "on_recovery" | "cooldown";
export type DurationAggregation = "max" | "avg" | "p95";
export type CostMetric = "total_tokens" | "usd";
export type AlertEventTimeRange = "24h" | "7d" | "30d" | "all";

export interface ErrorThresholdConfig {
  window_minutes: number;
  threshold_count: number;
}

export interface WorkflowDurationConfig {
  window_minutes: number;
  threshold_ms: number;
  aggregation: DurationAggregation;
  min_samples: number;
}

export interface TokenCostConfig {
  window_minutes: number;
  metric: CostMetric;
  threshold: number;
}

export interface ExecutionCountConfig {
  window_minutes: number;
  threshold_count: number;
}

export type AlertConfig =
  | ErrorThresholdConfig
  | WorkflowDurationConfig
  | TokenCostConfig
  | ExecutionCountConfig;

export interface Alert {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  alert_type: AlertType;
  scope: AlertScope;
  workflow_id: string | null;
  workflow_name: string | null;
  config: AlertConfig;
  condition_summary: string;
  enabled: boolean;
  notify_workflow_id: string | null;
  notify_workflow_name: string | null;
  state: AlertState;
  renotify_mode: RenotifyMode;
  cooldown_minutes: number | null;
  check_interval_seconds: number;
  last_evaluated_at: string | null;
  last_triggered_at: string | null;
  last_observed_value: number | null;
  /** Firings not yet acknowledged. Zero on a triggered alert means "seen". */
  unacknowledged_count: number;
  is_owner: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface AlertListResponse {
  items: Alert[];
  total: number;
}

export interface AlertEvent {
  id: string;
  alert_id: string;
  alert_name: string;
  alert_type: AlertType;
  triggered_at: string;
  observed_value: number;
  threshold_value: number;
  window_start: string;
  window_end: string;
  context: Record<string, unknown>;
  acknowledged_at: string | null;
  notify_execution_id: string | null;
  notify_status: string | null;
}

export interface AlertEventListResponse {
  items: AlertEvent[];
  total: number;
  unacknowledged: number;
}

export interface AlertPreview {
  observed_value: number;
  threshold_value: number;
  would_fire_now: boolean;
  window_start: string;
  window_end: string;
  context: Record<string, unknown>;
  backtest_fire_count: number;
  backtest_max_observed: number;
  lookback_hours: number;
}

export interface AlertPreviewRequest {
  alert_type: AlertType;
  scope: AlertScope;
  workflow_id?: string | null;
  config: AlertConfig;
  lookback_hours?: number;
}

/**
 * Every field is optional: the AI returns whatever the request supported and the
 * wizard fills the rest. See parse_draft_response in the backend's ai_draft.py.
 */
export interface AlertDraft {
  name?: string | null;
  description?: string | null;
  alert_type?: AlertType | null;
  scope?: AlertScope | null;
  workflow_id?: string | null;
  config?: AlertConfig | null;
  renotify_mode?: RenotifyMode | null;
  cooldown_minutes?: number | null;
  notify_workflow_id?: string | null;
  /** null/absent = the AI did not say, so the wizard keeps its own default. */
  create_notify_workflow?: boolean | null;
  filled_fields: string[];
}

export interface AlertDraftResponse {
  draft: AlertDraft | null;
  clarification: string | null;
}

export interface AlertDraftRequest {
  prompt: string;
  credential_id: string;
  model: string;
}

export interface AlertPayload {
  name: string;
  description?: string | null;
  alert_type: AlertType;
  scope: AlertScope;
  workflow_id?: string | null;
  config: AlertConfig;
  enabled?: boolean;
  notify_workflow_id?: string | null;
  /** Asks the API to create an empty workflow named after the alert and link it. */
  create_notify_workflow?: boolean;
  renotify_mode: RenotifyMode;
  cooldown_minutes?: number | null;
  check_interval_seconds?: number;
}

export type AlertUpdatePayload = Partial<AlertPayload>;

export interface AlertListFilters {
  enabled?: boolean;
  alert_type?: AlertType;
  workflow_id?: string;
  state?: AlertState;
  limit?: number;
  offset?: number;
}

export interface AlertShareEntry {
  id: string;
  user_id: string;
  user_email: string;
}

export interface AlertTeamShareEntry {
  id: string;
  team_id: string;
  team_name: string;
}

export interface AlertTypeMeta {
  type: AlertType;
  label: string;
  question: string;
}

/** Card copy for the wizard's type step, in the order they are presented. */
export const ALERT_TYPE_META: readonly AlertTypeMeta[] = [
  {
    type: "error_threshold",
    label: "Error threshold",
    question: "Did this fail more than N times in the window?",
  },
  {
    type: "workflow_duration",
    label: "Workflow duration",
    question: "Did runs get slower than expected in the window?",
  },
  {
    type: "token_cost",
    label: "Token / USD cost",
    question: "Did spend cross a budget in the window?",
  },
  {
    type: "execution_count",
    label: "Execution count",
    question: "Did this run far more often than it should have?",
  },
] as const;

export const ALERT_TYPE_LABELS: Record<AlertType, string> = {
  error_threshold: "Error threshold",
  workflow_duration: "Workflow duration",
  token_cost: "Token / USD cost",
  execution_count: "Execution count",
};

/**
 * How the Response step supplies the notify workflow. "create" is the wizard's
 * default so a new alert leaves you with somewhere to add notification nodes;
 * the backend creates the workflow and links it in the same request.
 */
export type NotifyWorkflowMode = "create" | "existing" | "none";

/** Default config per type, used when the wizard first lands on the condition step. */
export function defaultConfigForType(type: AlertType): AlertConfig {
  switch (type) {
    case "error_threshold":
      return { window_minutes: 15, threshold_count: 5 };
    case "workflow_duration":
      return {
        window_minutes: 30,
        threshold_ms: 60000,
        aggregation: "max",
        min_samples: 3,
      };
    case "token_cost":
      return { window_minutes: 1440, metric: "usd", threshold: 25 };
    case "execution_count":
      return { window_minutes: 60, threshold_count: 100 };
  }
}
