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

export interface EvalSuiteListItem {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
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

export type ReasoningEffort = "low" | "medium" | "high";

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
  status: string;
  scoring_method: string;
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
