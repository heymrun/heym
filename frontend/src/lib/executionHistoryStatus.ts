export interface HistoryStatusOption {
  value: string | undefined;
  label: string;
}

/**
 * Statuses offered by the history filter. `undefined` is the "no filter" entry, so
 * the list always reads as All Statuses first. "error" also matches runs a restart
 * recovery marked "failed" (the backend groups them); pending and skipped are rare
 * and left to All Statuses.
 */
export const HISTORY_STATUS_OPTIONS: readonly HistoryStatusOption[] = [
  { value: undefined, label: "All Statuses" },
  { value: "success", label: "Success" },
  { value: "error", label: "Error" },
  { value: "cached", label: "Cached" },
  { value: "cancelled", label: "Cancelled" },
];

/** Statuses that get a text badge in the run list; success is already the icon. */
const BADGE_CLASSES: Readonly<Record<string, string>> = {
  skipped: "bg-gray-500/20 text-gray-400",
  failed: "bg-red-500/20 text-red-400",
  cached: "bg-sky-500/20 text-sky-400",
  cancelled: "bg-gray-500/20 text-gray-400",
  expired: "bg-amber-500/20 text-amber-500",
  queue_full: "bg-orange-500/20 text-orange-500",
};

/** Returns the badge classes for a status, or null when it needs no badge. */
export function getHistoryStatusBadgeClass(status: string): string | null {
  return BADGE_CLASSES[status] ?? null;
}
