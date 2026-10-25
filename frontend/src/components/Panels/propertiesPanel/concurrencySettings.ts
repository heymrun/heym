import type { WorkflowConcurrencyPatch } from "@/types/workflow";

/** A positive whole number, or null for empty and invalid input. */
export function parsePositiveInteger(raw: string): number | null {
  if (raw.trim() === "") return null;
  const parsed = Math.floor(Number(raw));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/** Switching on starts at one run at a time; switching off clears the limit. */
export function togglePatch(currentLimit: number | null): WorkflowConcurrencyPatch {
  return { concurrency_limit: currentLimit === null ? 1 : null };
}

/** The PUT body: the server clears a field on 0, not on null. */
export function toConcurrencyUpdatePayload(
  patch: WorkflowConcurrencyPatch,
): WorkflowConcurrencyPatch {
  const payload: WorkflowConcurrencyPatch = {};
  if (patch.concurrency_limit !== undefined) {
    payload.concurrency_limit = patch.concurrency_limit ?? 0;
  }
  if (patch.concurrency_max_queue !== undefined) {
    payload.concurrency_max_queue = patch.concurrency_max_queue ?? 0;
  }
  if (patch.concurrency_max_wait_seconds !== undefined) {
    payload.concurrency_max_wait_seconds = patch.concurrency_max_wait_seconds ?? 0;
  }
  return payload;
}
