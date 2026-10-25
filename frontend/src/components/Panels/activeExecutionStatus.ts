import type { ActiveExecutionItem } from "@/types/workflow";

export interface ActiveExecutionStatusView {
  kind: "running" | "pending" | "queued";
  label: string;
  canOpenLive: boolean;
}

/** How a row in the active section of the history dialogs reads. */
export function activeExecutionStatus(
  item: Pick<ActiveExecutionItem, "status" | "queue_position" | "queue_size">,
): ActiveExecutionStatusView {
  if (item.status === "queued") {
    const position = item.queue_position ?? "?";
    const size = item.queue_size ?? "?";
    return { kind: "queued", label: `Queued ${position}/${size}`, canOpenLive: false };
  }
  if (item.status === "pending") {
    return { kind: "pending", label: "Pending review", canOpenLive: true };
  }
  return { kind: "running", label: "Running", canOpenLive: true };
}
