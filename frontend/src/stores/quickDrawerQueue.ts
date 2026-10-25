import type { QuickDrawerRunState } from "@/types/quickDrawer";
import type { QueuedRunEvent } from "@/types/workflow";

/** The waiting line shown while a run sits in its workflow's concurrency queue. */
export function queueLabel(event: QueuedRunEvent): string {
  return `Waiting in queue (${event.position}/${event.size})`;
}

/** Statuses a queued run can end in that the drawer has no state for read as errors. */
export function normalizeRunStatus(status: string): QuickDrawerRunState["status"] {
  if (status === "awaiting_file_upload") return "pending";
  if (status === "success" || status === "error" || status === "pending") return status;
  return "error";
}
