import type { ExecutionResult, NodeResult } from "@/types/workflow";

const TOOL_CALL_ARGUMENT_PREVIEW_MAX_LENGTH = 180;

export interface DisplayNodeResult extends NodeResult {
  displayKey: string;
  isRetryAttempt: boolean;
  retryAttempt: number | null;
  retryMaxAttempts: number | null;
  retryWaitSeconds: number | null;
}

interface ExecutionLogToolCallTitleInput {
  name: string;
  arguments?: Record<string, unknown>;
  workflow_name?: string;
}

function stringifyExecutionLogValue(value: unknown): string {
  try {
    const stringified = JSON.stringify(value);
    return stringified ?? String(value);
  } catch {
    return String(value);
  }
}

function trimExecutionLogPreview(text: string, maxLength: number): string {
  if (text.length <= maxLength) {
    return text;
  }

  const suffix = "...";
  return `${text.slice(0, Math.max(0, maxLength - suffix.length))}${suffix}`;
}

function getMetadataNumber(result: NodeResult, key: string): number | null {
  const value = result.metadata?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function getMetadataInteger(result: NodeResult, key: string): number | null {
  const value = getMetadataNumber(result, key);
  return value !== null && Number.isInteger(value) ? value : null;
}

export function isHitlWaitNodeResult(result: NodeResult): boolean {
  return result.metadata?.hitl_wait === true;
}

export function isRetryAttemptNodeResult(result: NodeResult): boolean {
  return result.metadata?.retry_stage === "attempt_failed";
}

export function getNodeResultDisplayKey(result: NodeResult, index: number): string {
  const sequence = getMetadataInteger(result, "sequence");
  if (sequence !== null) {
    return `${result.node_id}:${sequence}`;
  }

  const retryAttempt = getMetadataInteger(result, "retry_attempt");
  return `${result.node_id}:${result.status}:${retryAttempt ?? "base"}:${index}`;
}

export function buildDisplayNodeResults(results: NodeResult[]): DisplayNodeResult[] {
  return results.map((result, index) => ({
    ...result,
    displayKey: getNodeResultDisplayKey(result, index),
    isRetryAttempt: isRetryAttemptNodeResult(result),
    retryAttempt: getMetadataInteger(result, "retry_attempt"),
    retryMaxAttempts: getMetadataInteger(result, "retry_max_attempts"),
    retryWaitSeconds: getMetadataNumber(result, "retry_wait_seconds"),
  }));
}

export function getLatestNodeResultForNode(
  results: readonly NodeResult[],
  nodeId: string,
): NodeResult | null {
  let latestRetry: NodeResult | null = null;

  for (let index = results.length - 1; index >= 0; index -= 1) {
    const result = results[index];
    if (result.node_id !== nodeId) {
      continue;
    }

    if (latestRetry === null) {
      latestRetry = result;
    }

    if (!isRetryAttemptNodeResult(result)) {
      return result;
    }
  }

  return latestRetry;
}

export interface ExecutionLogNodeResult {
  node_id: string;
  node_label: string;
  node_type: string;
  status: NodeResult["status"];
  execution_time_ms: number;
  output: Record<string, unknown>;
  error: string | null;
  metadata?: Record<string, unknown>;
}

export interface ExecutionLogForAssistant {
  execution_status: ExecutionResult["status"] | "running";
  execution_time_ms: number | null;
  final_outputs: Record<string, unknown> | null;
  node_results: ExecutionLogNodeResult[];
}

const EXECUTION_LOG_HIDDEN_NODE_TYPES = new Set(["condition", "sticky"]);

function normalizeExecutionLogOutput(result: NodeResult): Record<string, unknown> {
  if (result.node_type !== "consoleLog") {
    return result.output;
  }

  const output = result.output;
  if (
    output &&
    typeof output === "object" &&
    Object.prototype.hasOwnProperty.call(output, "logMessage")
  ) {
    return output as Record<string, unknown>;
  }

  return result.output;
}

function filterExecutionLogNodeResults(results: readonly NodeResult[]): NodeResult[] {
  return results.filter(
    (result) =>
      !EXECUTION_LOG_HIDDEN_NODE_TYPES.has(result.node_type) &&
      result.status !== "skipped" &&
      !isRetryAttemptNodeResult(result),
  );
}

function mapExecutionLogNodeResult(result: NodeResult): ExecutionLogNodeResult {
  return {
    node_id: result.node_id,
    node_label: result.node_label,
    node_type: result.node_type,
    status: result.status,
    execution_time_ms: result.execution_time_ms,
    output: normalizeExecutionLogOutput(result),
    error: result.error,
    metadata: result.metadata,
  };
}

export function buildExecutionLogForAssistant(
  nodeResults: readonly NodeResult[],
  executionResult?: ExecutionResult | null,
): ExecutionLogForAssistant | null {
  const filtered = filterExecutionLogNodeResults(nodeResults);
  if (filtered.length === 0) {
    return null;
  }

  return {
    execution_status: executionResult?.status ?? "running",
    execution_time_ms: executionResult?.execution_time_ms ?? null,
    final_outputs: executionResult?.outputs ?? null,
    node_results: filtered.map(mapExecutionLogNodeResult),
  };
}

export function formatExecutionLogToolCallTitle(
  toolCall: ExecutionLogToolCallTitleInput,
): string {
  if (toolCall.name === "_context_compression") {
    const compressed = toolCall.arguments?.messages_compressed;
    return typeof compressed === "number"
      ? `Context compressed (${compressed} messages -> summary)`
      : "Context compressed";
  }

  if (toolCall.name === "call_sub_workflow") {
    const workflowName = toolCall.workflow_name;
    const workflowId =
      typeof toolCall.arguments?.workflow_id === "string" ? toolCall.arguments.workflow_id : "";
    if (workflowName && workflowId) {
      return `call_sub_workflow(${workflowName}, ${workflowId})`;
    }
    if (workflowName) {
      return `call_sub_workflow(${workflowName})`;
    }
  }

  const argumentPreview = trimExecutionLogPreview(
    stringifyExecutionLogValue(toolCall.arguments ?? {}),
    TOOL_CALL_ARGUMENT_PREVIEW_MAX_LENGTH,
  );
  return `${toolCall.name}(${argumentPreview})`;
}
