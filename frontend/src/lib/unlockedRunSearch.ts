import type { AllExecutionHistoryEntryLight } from "@/types/workflow";

/**
 * History search runs on the server, which only sees an encrypted run's placeholders.
 * Runs the viewer has already unlocked (and that unlock was audited) are matched here,
 * in the browser, against their decrypted data.
 */
export interface UnlockedRunCandidate {
  item: AllExecutionHistoryEntryLight;
  data: unknown[];
}

export interface UnlockedRunFilters {
  status?: string;
  triggerSource?: string;
  instanceId?: string;
}

/** Whether any of a run's values contains the search text, case-insensitively. */
export function unlockedRunMatches(query: string, data: unknown[]): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return false;
  return data.some((value) => {
    try {
      return JSON.stringify(value ?? null).toLowerCase().includes(needle);
    } catch {
      return false;
    }
  });
}

function statusMatches(status: string, filter: string): boolean {
  // The server's Error filter also returns runs recovery recorded as "failed".
  return filter === "error" ? status === "error" || status === "failed" : status === filter;
}

/** The server's results plus unlocked runs that match the search, newest first. */
export function withUnlockedMatches(
  listed: AllExecutionHistoryEntryLight[],
  query: string,
  candidates: UnlockedRunCandidate[],
  filters: UnlockedRunFilters = {},
): AllExecutionHistoryEntryLight[] {
  if (!query.trim() || candidates.length === 0) return listed;
  const listedIds = new Set(listed.map((item) => item.id));
  const extra = candidates
    .filter(({ item }) => !listedIds.has(item.id))
    .filter(({ item }) => !filters.triggerSource || item.trigger_source === filters.triggerSource)
    .filter(({ item }) => !filters.status || statusMatches(item.status, filters.status))
    .filter(({ item }) => !filters.instanceId || item.executed_by_instance_id === filters.instanceId)
    .filter(({ data }) => unlockedRunMatches(query, data))
    .map(({ item }) => item);
  if (extra.length === 0) return listed;
  return [...listed, ...extra].sort((left, right) => right.started_at.localeCompare(left.started_at));
}
