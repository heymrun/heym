/** Share this agent node's persistent memory graph with another agent (runtime prompt + optional write extraction). */
export interface AgentMemoryShareEntry {
  /** Workflow that contains the peer agent node (may differ from this node's workflow). */
  peerWorkflowId: string;
  peerCanvasNodeId: string;
  permission: "read" | "write";
}

export type WorkflowAuthType = "anonymous" | "jwt" | "header_auth";
export type WebhookBodyMode = "legacy" | "generic";

export interface SseNodeConfig {
  send_start: boolean;
  start_message: string | null;
}

export interface Workflow {
  id: string;
  name: string;
  description: string | null;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  auth_type: WorkflowAuthType;
  auth_header_key: string | null;
  auth_header_value: string | null;
  webhook_body_mode: WebhookBodyMode;
  allow_anonymous: boolean;
  owner_id: string;
  cache_ttl_seconds: number | null;
  rate_limit_requests: number | null;
  rate_limit_window_seconds: number | null;
  sse_enabled: boolean;
  sse_node_config: Record<string, SseNodeConfig>;
  created_at: string;
  updated_at: string;
}

export interface WorkflowListItem {
  id: string;
  name: string;
  description: string | null;
  folder_id: string | null;
  first_node_type: NodeType | null;
  scheduled_for_deletion: string | null;
  created_at: string;
  updated_at: string;
}

export interface Folder {
  id: string;
  name: string;
  parent_id: string | null;
  owner_id: string;
  created_at: string;
  updated_at: string;
}

export interface FolderWithContents extends Folder {
  children: Folder[];
  workflows: WorkflowListItem[];
}

export interface FolderTree {
  id: string;
  name: string;
  parent_id: string | null;
  children: FolderTree[];
  workflows: WorkflowListItem[];
}

export interface WorkflowNode {
  id: string;
  type: NodeType;
  position: { x: number; y: number };
  data: NodeData;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
}

export interface AgentTool {
  name: string;
  description: string;
  parameters: string;
  code: string;
}

export type MCPTransportType = "stdio" | "sse" | "streamable_http";
export type AgentSkillFileEncoding = "text" | "base64";

export interface AgentMCPConnection {
  id: string;
  transport: MCPTransportType;
  label?: string;
  timeoutSeconds: number;
  command?: string;
  args?: string[] | string;
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string> | string;
}

export interface AgentSkillFile {
  path: string;
  content: string;
  encoding?: AgentSkillFileEncoding;
  mimeType?: string;
}

export interface AgentSkill {
  id: string;
  name: string;
  content: string;
  files?: AgentSkillFile[];
  timeoutSeconds?: number;
}

export type NodeType =
  | "textInput"
  | "cron"
  | "telegramTrigger"
  | "websocketTrigger"
  | "llm"
  | "agent"
  | "condition"
  | "switch"
  | "execute"
  | "output"
  | "wait"
  | "http"
  | "websocketSend"
  | "sticky"
  | "merge"
  | "set"
  | "jsonOutputMapper"
  | "telegram"
  | "slack"
  | "sendEmail"
  | "errorHandler"
  | "variable"
  | "loop"
  | "disableNode"
  | "redis"
  | "rag"
  | "grist"
  | "googleSheets"
  | "bigquery"
  | "throwError"
  | "rabbitmq"
  | "imapTrigger"
  | "crawler"
  | "consoleLog"
  | "playwright"
  | "dataTable"
  | "drive"
  | "slackTrigger";

export type VariableType =
  | "string"
  | "number"
  | "boolean"
  | "object"
  | "array"
  | "auto";

export interface OutputSchemaField {
  key: string;
  value: string;
}

export interface MappingField {
  key: string;
  value: string;
}

export interface InputField {
  key: string;
  defaultValue?: string;
}

export interface ExecuteInputMapping {
  key: string;
  value: string;
}

export type ReasoningEffort = "none" | "low" | "medium" | "high";

export type GuardrailCategory =
  | "violence"
  | "hate_speech"
  | "sexual_content"
  | "nsfw"
  | "self_harm"
  | "harassment"
  | "illegal_activity"
  | "political_extremism"
  | "spam_phishing"
  | "personal_data"
  | "prompt_injection";

export type GuardrailSeverity = "low" | "medium" | "high";

export type LLMOutputType = "text" | "image";

export type RedisOperation = "set" | "get" | "hasKey" | "deleteKey";

export type RagOperation = "insert" | "search";

export type GristOperation =
  | "getRecord"
  | "getRecords"
  | "createRecord"
  | "createRecords"
  | "updateRecord"
  | "updateRecords"
  | "deleteRecord"
  | "listTables"
  | "listColumns";

export type DataTableOperation =
  | "find"
  | "getAll"
  | "getById"
  | "insert"
  | "update"
  | "remove"
  | "upsert";

export type CrawlerMode = "basic" | "extract";
export type WebSocketTriggerEventName = "onMessage" | "onConnected" | "onClosed";

export interface CrawlerSelector {
  name: string;
  selector: string;
  attributes?: string[];
}

export type PlaywrightStepAction =
  | "navigate"
  | "click"
  | "type"
  | "fill"
  | "wait"
  | "screenshot"
  | "getText"
  | "getAttribute"
  | "getHTML"
  | "getVisibleTextOnPage"
  | "hover"
  | "selectOption"
  | "scrollDown"
  | "scrollUp"
  | "aiStep";

export interface PlaywrightStep {
  action: PlaywrightStepAction;
  selector?: string;
  url?: string;
  text?: string;
  value?: string;
  attribute?: string;
  timeout?: number;
  outputKey?: string;
  /** Pixels to scroll (scrollDown/scrollUp). Default 300. */
  amount?: number;
  /** AI step: instructions for LLM to generate actions from page HTML */
  instructions?: string;
  /** AI step: credential for LLM API */
  credentialId?: string;
  /** AI step: model for LLM */
  model?: string;
  /** AI step: log generated steps to console */
  logStepsToConsole?: boolean;
  /** AI step: save generated steps for future usages */
  saveStepsForFuture?: boolean;
  /** AI step: if saved selector fails 2x, ask LLM for text/role-based alternative */
  autoHealMode?: boolean;
  /** AI step: cached steps from previous run (used when saveStepsForFuture, avoids LLM call) */
  savedSteps?: {
    action: string;
    selector?: string;
    text?: string;
    value?: string;
    timeout?: number;
    amount?: number;
  }[];
  /** AI step: send screenshot to LLM (helps with dynamic/visual elements) */
  sendScreenshot?: boolean;
  /** AI step: timeout in ms for LLM API call (default 120000) */
  aiStepTimeout?: number;
}

export interface NodeData {
  label: string;
  value?: string;
  inputFields?: InputField[];
  model?: string;
  temperature?: number;
  maxTokens?: number;
  condition?: string;
  expression?: string;
  cases?: string[];
  executeTargets?: string[];
  executeInput?: string;
  executeWorkflowId?: string;
  executeInputMappings?: ExecuteInputMapping[];
  executeDoNotWait?: boolean;
  targetWorkflowInputFields?: InputField[];
  targetWorkflowName?: string;
  message?: string;
  chatId?: string;
  duration?: number;
  cronExpression?: string;
  pollIntervalMinutes?: number;
  curl?: string;
  websocketUrl?: string;
  websocketHeaders?: string;
  websocketSubprotocols?: string;
  websocketMessage?: string;
  websocketTriggerEvents?: WebSocketTriggerEventName[];
  note?: string;
  status?: string;
  active?: boolean;
  allowDownstream?: boolean;
  outputSchema?: OutputSchemaField[];
  inputCount?: number;
  mappings?: MappingField[];
  pinnedData?: Record<string, unknown> | null;
  credentialId?: string;
  systemInstruction?: string;
  userMessage?: string;
  batchModeEnabled?: boolean;
  imageInputEnabled?: boolean;
  imageInput?: string;
  isReasoningModel?: boolean;
  reasoningEffort?: ReasoningEffort;
  batchRuntimeStatus?: "pending" | "processing" | "completed" | "failed";
  batchRuntimeRawStatus?: string;
  batchRuntimeRequestCounts?: {
    total: number;
    completed: number;
    failed: number;
  };
  jsonOutputEnabled?: boolean;
  jsonOutputSchema?: string;
  hitlEnabled?: boolean;
  hitlSummary?: string;
  outputType?: LLMOutputType;
  tools?: AgentTool[];
  mcpConnections?: AgentMCPConnection[];
  skills?: AgentSkill[];
  isOrchestrator?: boolean;
  subAgentLabels?: string[];
  subWorkflowIds?: string[];
  subWorkflowNames?: Record<string, string>;
  /** When true, agent builds a knowledge graph from runs (async); sub-agents write to their own graph. */
  persistentMemoryEnabled?: boolean;
  /** Other agent nodes that may read (or read/write) this node's memory graph at runtime. */
  memoryShares?: AgentMemoryShareEntry[];
  isSubAgent?: boolean;
  maxToolIterations?: number;
  toolTimeoutSeconds?: number;
  variableName?: string;
  variableValue?: string;
  variableType?: VariableType;
  /** When true, store in Global Variable Store (persistent, $global.name) */
  isGlobal?: boolean;
  arrayExpression?: string;
  to?: string;
  subject?: string;
  emailBody?: string;
  targetNodeLabel?: string;
  redisOperation?: RedisOperation;
  redisKey?: string;
  redisValue?: string;
  redisTtl?: number;
  ragOperation?: RagOperation;
  vectorStoreId?: string;
  documentContent?: string;
  documentMetadata?: string;
  queryText?: string;
  searchLimit?: number;
  metadataFilters?: string;
  enableReranker?: boolean;
  rerankerCredentialId?: string;
  rerankerTopN?: number;
  gristOperation?: GristOperation;
  gristDocId?: string;
  gristTableId?: string;
  gristRecordId?: string;
  gristRecordData?: string;
  gristRecordsData?: string;
  gristFilter?: string;
  gristSort?: string;
  gristLimit?: number;
  gristRecordIds?: string;
  gristRecordDataInputMode?: "raw" | "selective";
  gristFilterInputMode?: "raw" | "selective";
  gristColumns?: Array<{ id: string; name: string; type: string }>;
  errorMessage?: string;
  httpStatusCode?: number;
  retryEnabled?: boolean;
  retryMaxAttempts?: number;
  retryWaitSeconds?: number;
  onErrorEnabled?: boolean;
  retryAttempt?: number;
  rabbitmqOperation?: string;
  rabbitmqExchange?: string;
  rabbitmqRoutingKey?: string;
  rabbitmqQueueName?: string;
  rabbitmqMessageBody?: string;
  rabbitmqDelayMs?: number;
  crawlerUrl?: string;
  crawlerWaitSeconds?: number;
  crawlerMaxTimeout?: number;
  crawlerMode?: CrawlerMode;
  crawlerSelectors?: CrawlerSelector[];
  logMessage?: string;
  playwrightSteps?: PlaywrightStep[];
  playwrightCode?: string;
  playwrightHeadless?: boolean;
  playwrightTimeout?: number;
  playwrightCaptureNetwork?: boolean;
  playwrightAuthEnabled?: boolean;
  playwrightAuthStateExpression?: string;
  playwrightAuthCheckSelector?: string;
  playwrightAuthCheckTimeout?: number;
  playwrightAuthFallbackSteps?: PlaywrightStep[];
  guardrailsEnabled?: boolean;
  guardrailsCategories?: GuardrailCategory[];
  guardrailsSeverity?: GuardrailSeverity;
  guardrailCredentialId?: string;
  guardrailModel?: string;
  fallbackCredentialId?: string;
  fallbackModel?: string;
  dataTableId?: string;
  dataTableOperation?: DataTableOperation;
  dataTableFilter?: string;
  dataTableData?: string;
  dataTableRowId?: string;
  dataTableLimit?: number;
  dataTableSort?: string;
  dataTableInputMode?: "raw" | "selective";
  driveOperation?: "get" | "delete" | "setPassword" | "setTtl" | "setMaxDownloads" | "downloadUrl";
  driveFileId?: string;
  drivePassword?: string;
  driveTtlHours?: number;
  driveMaxDownloads?: number;
  driveIncludeBinary?: boolean;
  driveSourceUrl?: string;
  bqOperation?: string;
  bqProjectId?: string;
  bqQuery?: string;
  bqMaxResults?: string;
  bqDatasetId?: string;
  bqTableId?: string;
  bqRowsInputMode?: "raw" | "selective";
  bqRows?: string;
  bqMappings?: Array<{ key: string; value: string }>;
  gsOperation?: string;
  gsSpreadsheetId?: string;
  gsSheetName?: string;
  gsStartRow?: string;
  /** 1-based sheet row number to update (updateRange only; falls back to gsStartRow if unset). */
  gsUpdateRow?: string;
  gsMaxRows?: string;
  gsHasHeader?: boolean;
  gsRowCount?: string;
  gsKeepHeader?: boolean;
  gsAppendPlacement?: "append" | "prepend";
  gsValuesInputMode?: "raw" | "selective";
  gsValuesSelectiveRows?: string;
  gsValuesSelectiveCols?: string;
  gsValues?: string;
}

export interface WorkflowShare {
  id: string;
  user_id: string;
  email: string;
  name: string;
  shared_at: string;
}

export interface ExecutionToken {
  id: string;
  token: string;
  expires_at: string;
  created_at: string;
  revoked: boolean;
}

export interface ExecutionResult {
  workflow_id: string;
  status: "success" | "error" | "pending";
  outputs: Record<string, unknown>;
  execution_time_ms: number;
  node_results: NodeResult[];
  execution_history_id?: string | null;
}

export interface ExecutionHistoryEntry {
  id: string;
  started_at: string;
  inputs: Record<string, unknown>;
  status: "running" | "success" | "error" | "pending";
  result: ExecutionResult | null;
  trigger_source?: string | null;
}

export interface AllExecutionHistoryEntry {
  id: string;
  workflow_id: string | null;
  workflow_name: string;
  run_type?: "workflow" | "dashboard_chat" | "workflow_assistant";
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  node_results: NodeResult[];
  status: "running" | "success" | "error" | "pending";
  execution_time_ms: number;
  started_at: string;
  trigger_source?: string | null;
}

/** Lightweight list item without inputs/outputs/node_results. */
export interface AllExecutionHistoryEntryLight {
  id: string;
  workflow_id: string | null;
  workflow_name: string;
  run_type: "workflow" | "dashboard_chat" | "workflow_assistant";
  started_at: string;
  status: string;
  execution_time_ms: number;
  trigger_source?: string | null;
}

export interface HistoryListResponse<T = AllExecutionHistoryEntryLight> {
  total: number;
  items: T[];
}

export interface ActiveExecutionItem {
  execution_id: string;
  workflow_id: string;
  workflow_name: string;
  started_at: string;
}

export interface ServerExecutionHistory {
  id: string;
  workflow_id: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  node_results: NodeResult[];
  status: string;
  execution_time_ms: number;
  started_at: string;
  trigger_source?: string | null;
}

export interface NodeResult {
  node_id: string;
  node_label: string;
  node_type: string;
  status: "success" | "error" | "pending" | "running" | "skipped";
  output: Record<string, unknown>;
  execution_time_ms: number;
  error: string | null;
  /** e.g. `{ invocation: "sub_agent_tool" }` for orchestrator-delegated agent runs */
  metadata?: Record<string, unknown>;
}

export interface ExpressionEvaluateCanvasResult {
  node_id: string;
  label: string;
  output: unknown;
}

export interface ExpressionEvaluateRequest {
  expression: string;
  workflow_id: string;
  current_node_id: string;
  field_name?: string;
  input_body?: unknown;
  selected_loop_iteration_index?: number | null;
  node_results: ExpressionEvaluateCanvasResult[];
}

export interface ExpressionEvaluateResponse {
  result: unknown;
  result_type: "string" | "number" | "boolean" | "array" | "object" | "null";
  preserved_type: boolean;
  error: string | null;
  selected_loop_total?: number | null;
}

export interface AgentProgressEntry {
  name: string;
  arguments: Record<string, unknown>;
  result: unknown;
  elapsed_ms?: number;
  source?: string;
  mcp_server?: string;
  phase?: "start" | "end" | "result";
  tool_call_id?: string | null;
  timestamp?: number;
  /** Set for call_sub_workflow when the workflow display name is known */
  workflow_name?: string;
}

export interface AgentProgressEvent {
  type: "agent_progress";
  node_id: string;
  node_label: string;
  entry: AgentProgressEntry;
}

export interface LLMBatchProgressEntry {
  batchId: string;
  status: "pending" | "processing" | "completed" | "failed";
  rawStatus: string;
  provider: string;
  model: string;
  requestCounts: {
    total: number;
    completed: number;
    failed: number;
  };
  total: number;
  completed: number;
  failed: number;
  timestamp: number;
  batchStatus?: string;
}

export interface LLMBatchProgressEvent {
  type: "llm_batch_progress";
  node_id: string;
  node_label: string;
  entry: LLMBatchProgressEntry;
}

export interface HITLReview {
  request_id: string;
  workflow_name: string;
  agent_label: string;
  summary: string;
  original_draft_text: string;
  status: string;
  decision?: string | null;
  edited_text?: string | null;
  refusal_reason?: string | null;
  resolved_output: Record<string, unknown>;
  expires_at: string;
  resolved_at?: string | null;
}

export interface HITLDecisionPayload {
  action: "accept" | "edit" | "refuse";
  edited_text?: string;
  refusal_reason?: string;
}

export interface WorkflowVersion {
  id: string;
  workflow_id: string;
  version_number: number;
  name: string;
  description: string | null;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  auth_type: WorkflowAuthType;
  auth_header_key: string | null;
  auth_header_value: string | null;
  webhook_body_mode: WebhookBodyMode;
  cache_ttl_seconds: number | null;
  rate_limit_requests: number | null;
  rate_limit_window_seconds: number | null;
  created_by_id: string;
  created_at: string;
}

export interface VersionChange {
  type: string;
  field: string;
  old_value: Record<string, unknown> | unknown[] | string | number | null;
  new_value: Record<string, unknown> | unknown[] | string | number | null;
}

export interface NodeChange {
  node_id: string;
  change_type: "added" | "removed" | "modified";
  old_node: WorkflowNode | null;
  new_node: WorkflowNode | null;
  changes: VersionChange[];
}

export interface EdgeChange {
  edge_id: string | null;
  change_type: "added" | "removed" | "modified";
  old_edge: WorkflowEdge | null;
  new_edge: WorkflowEdge | null;
}

export interface WorkflowVersionDiff {
  version_id: string;
  version_number: number;
  compared_to_version_id: string | null;
  compared_to_version_number: number | null;
  node_changes: NodeChange[];
  edge_changes: EdgeChange[];
  config_changes: VersionChange[];
}
