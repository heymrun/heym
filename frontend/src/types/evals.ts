export interface EvalSuite {
  id: string;
  name: string;
  description: string | null;
  system_prompt: string;
  scoring_method: string;
  created_at: string;
  updated_at: string;
  test_cases?: EvalTestCase[];
}

export type EvalSuiteType = "prompt" | "agent";

export interface EvalSuiteListItem {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  suite_type: EvalSuiteType;
}

export interface EvalTestCase {
  id: string;
  suite_id: string;
  input: string;
  expected_output: string;
  input_mode: string;
  expected_mode: string;
  order_index: number;
  created_at: string;
  updated_at: string;
}

/** The same levels the LLM and Agent nodes offer. */
export type ReasoningEffort = "low" | "medium" | "high" | "xhigh" | "max";

export const REASONING_EFFORTS: ReasoningEffort[] = ["low", "medium", "high", "xhigh", "max"];

export function isReasoningEffort(value: unknown): value is ReasoningEffort {
  return typeof value === "string" && (REASONING_EFFORTS as string[]).includes(value);
}

export interface EvalRun {
  id: string;
  suite_id: string;
  name: string;
  system_prompt_snapshot: string;
  models: string[];
  scoring_method: string;
  temperature: number;
  reasoning_effort?: string | null;
  max_tokens: number | null;
  runs_per_test?: number;
  /** The credential the models ran on; empty for runs made before it was stored. */
  credential_id?: string | null;
  /** The judge that scored an LLM-as-Judge run; empty when each model scored itself. */
  judge_credential_id?: string | null;
  judge_model?: string | null;
  status: string;
  created_at: string;
  completed_at: string | null;
  results: EvalRunResult[];
}

export interface EvalRunResult {
  id: string;
  run_id: string;
  test_case_id: string | null;
  model_id: string;
  input_snapshot: string;
  expected_output_snapshot: string;
  actual_output: string;
  score: string;
  explanation?: string | null;
  latency_ms: number | null;
  tokens_used: number | null;
  error: string | null;
  created_at: string;
}

export interface EvalRunListItem {
  id: string;
  name: string;
  models: string[];
  credential_id?: string | null;
  temperature?: number | null;
  reasoning_effort?: string | null;
  max_tokens?: number | null;
  runs_per_test?: number;
  judge_credential_id?: string | null;
  status: string;
  scoring_method: string;
  judge_model?: string | null;
  created_at: string;
  completed_at: string | null;
  pass_count: number;
  total_count: number;
}

export interface CreateSuiteRequest {
  name: string;
  description?: string | null;
  system_prompt?: string;
  scoring_method?: string;
}

export interface UpdateSuiteRequest {
  name?: string;
  description?: string | null;
  system_prompt?: string;
  scoring_method?: string;
}

export interface CreateTestCaseRequest {
  input?: string;
  expected_output?: string;
  input_mode?: string;
  expected_mode?: string;
  order_index?: number;
}

export interface UpdateTestCaseRequest {
  input?: string;
  expected_output?: string;
  input_mode?: string;
  expected_mode?: string;
  order_index?: number;
}

export interface RunEvalsRequest {
  credential_id: string;
  models: string[];
  scoring_method?: string;
  temperature?: number;
  reasoning_effort?: ReasoningEffort | null;
  max_tokens?: number | null;
  runs_per_test?: number;
  judge_credential_id?: string | null;
  judge_model?: string | null;
}

export interface OptimizePromptRequest {
  credential_id: string;
  model?: string;
  system_prompt?: string;
}

export interface OptimizePromptResponse {
  optimized_prompt: string;
}

export interface GenerateTestDataRequest {
  credential_id: string;
  model?: string;
  count?: number;
}

export interface GenerateTestDataResponse {
  test_cases: CreateTestCaseRequest[];
}

export type ToolExpect = "called" | "not_called";

export type ToolKind = "tool" | "mcp" | "sub_agent" | "sub_workflow" | "skill" | "node" | "review";

/** `name` identifies the call within its kind: a sub-agent's label, a sub-workflow's id. */
export interface ToolAssertion {
  kind: ToolKind;
  name: string;
  label?: string | null;
  expect: ToolExpect;
}

/** Upper bounds per run; null turns that check off. */
export interface AgentThresholds {
  latency_ms: number | null;
  cost_usd: number | null;
  total_tokens: number | null;
  tool_calls: number | null;
}

export type AgentBaselineSourceKind = "latest_runs" | "suite_run" | "manual";

export interface AgentBaseline {
  run_count: number;
  error_count: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  cost_avg_usd: number | null;
  cost_p95_usd: number | null;
  tokens_avg: number | null;
  tokens_p95: number | null;
  tool_calls_avg: number | null;
  tool_calls_max: number | null;
  unpriced_models: string[];
  captured_at: string | null;
  source?: AgentBaselineSourceKind;
  suite_run_id?: string | null;
}

export interface AgentBaselineValues {
  latency_p50_ms?: number | null;
  latency_p95_ms?: number | null;
  cost_avg_usd?: number | null;
  cost_p95_usd?: number | null;
  tokens_avg?: number | null;
  tokens_p95?: number | null;
  tool_calls_avg?: number | null;
  tool_calls_max?: number | null;
}

export interface AgentBaselineSourceRequest {
  source: AgentBaselineSourceKind;
  run_id?: string | null;
  values?: AgentBaselineValues | null;
}

export interface AgentToolCall {
  kind: ToolKind;
  name: string;
  label: string;
  status: string;
  elapsed_ms: number | null;
  server: string | null;
}

export interface AgentRun {
  trace_id: string;
  created_at: string;
  model: string | null;
  latency_ms: number;
  model_ms: number;
  tool_ms: number;
  cost_usd: number | null;
  total_tokens: number;
  tool_count: number;
  tool_calls: AgentToolCall[];
  error: string | null;
}

export interface AgentToolUsage {
  kind: ToolKind;
  name: string;
  label: string;
  server: string | null;
  configured: boolean;
  runs_called: number;
  call_count: number;
  error_count: number;
  avg_ms: number | null;
}

/** An agent node to pick; one without runs has nothing to read yet. */
export interface AgentCandidate {
  workflow_id: string;
  workflow_name: string;
  node_id: string;
  node_label: string;
  run_count: number;
  last_run_at: string | null;
}

export interface AgentMetrics {
  workflow_id: string;
  workflow_name: string;
  node_id: string;
  node_label: string;
  runs: AgentRun[];
  baseline: AgentBaseline;
  tools: AgentToolUsage[];
  suggested_thresholds: AgentThresholds;
}

export interface AgentSuite {
  id: string;
  name: string;
  workflow_id: string;
  workflow_name: string;
  node_id: string;
  node_label: string;
  tool_assertions: ToolAssertion[];
  thresholds: AgentThresholds;
  baseline: AgentBaseline;
  created_at: string;
  updated_at: string;
}

export interface CreateAgentSuiteRequest {
  name: string;
  workflow_id: string;
  node_id: string;
  tool_assertions: ToolAssertion[];
  thresholds: AgentThresholds;
  baseline?: AgentBaselineSourceRequest;
}

export interface UpdateAgentSuiteRequest {
  name?: string;
  tool_assertions?: ToolAssertion[];
  thresholds?: AgentThresholds;
  refresh_baseline?: boolean;
  baseline?: AgentBaselineSourceRequest;
}

export type AgentCheckKind = "run" | "assertion" | "threshold";
export type AgentCheckStatus = "pass" | "fail" | "skip";

export interface AgentCheckResult {
  key: string;
  label: string;
  kind: AgentCheckKind;
  status: AgentCheckStatus;
  detail: string | null;
}

export interface AgentRunEvaluation extends AgentRun {
  passed: boolean;
  checks: AgentCheckResult[];
}

export interface AgentCheckSummary {
  key: string;
  label: string;
  kind: AgentCheckKind;
  passed: number;
  failed: number;
  skipped: number;
}

export type AgentDeltaMetric = "latency_p95_ms" | "cost_avg_usd" | "tokens_avg" | "tool_calls_avg";

export interface AgentMetricDelta {
  metric: AgentDeltaMetric;
  baseline: number | null;
  current: number | null;
  delta_pct: number | null;
}

export interface AgentSuiteReport {
  suite_id: string;
  run_count: number;
  passed_count: number;
  pass_rate: number | null;
  checks: AgentCheckSummary[];
  current: AgentBaseline;
  baseline: AgentBaseline;
  deltas: AgentMetricDelta[];
  runs: AgentRunEvaluation[];
}

export interface AgentSuiteRunInputs {
  fields: string[];
  previous_inputs: Record<string, unknown> | null;
  previous_run_at: string | null;
}

export interface CreateAgentSuiteRunRequest {
  count: number;
  inputs: Record<string, unknown>;
  generate_inputs: boolean;
  credential_id?: string | null;
  model?: string | null;
  inputs_list?: Record<string, unknown>[] | null;
}

export interface AgentSuiteRunResult {
  execution_id: string | null;
  status: string;
  trace_ids: string[];
  error: string | null;
}

export type AgentSuiteRunStatus = "running" | "completed" | "failed" | "cancelled";

/** One suite run in the suite's history, without its inputs and results. */
export interface AgentSuiteRunSummary {
  id: string;
  status: AgentSuiteRunStatus;
  requested_count: number;
  finished_count: number;
  generate_inputs: boolean;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface AgentSuiteRun {
  id: string;
  suite_id: string;
  status: AgentSuiteRunStatus;
  requested_count: number;
  generate_inputs: boolean;
  inputs: Record<string, unknown>[];
  results: AgentSuiteRunResult[];
  error: string | null;
  created_at: string;
  completed_at: string | null;
}
