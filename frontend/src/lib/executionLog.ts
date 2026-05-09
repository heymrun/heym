import type { NodeResult } from "@/types/workflow";

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
