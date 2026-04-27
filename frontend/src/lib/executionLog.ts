import type { NodeResult } from "@/types/workflow";

export interface DisplayNodeResult extends NodeResult {
  displayKey: string;
  isRetryAttempt: boolean;
  retryAttempt: number | null;
  retryMaxAttempts: number | null;
  retryWaitSeconds: number | null;
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
