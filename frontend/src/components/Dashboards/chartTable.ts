import type { StatusTone } from "@/types/dashboard";

/** Chip colors per tone; the server resolves each status value to a tone. */
export const STATUS_TONE_CLASSES: Record<StatusTone, string> = {
  success: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  attention: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  failure: "bg-red-500/15 text-red-600 dark:text-red-400",
  waiting: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
  neutral: "bg-muted text-muted-foreground",
};

/** A table widget's row link: which column holds the record, and which one names it. */
export interface TableRowLink {
  recordField: string;
  labelField?: string | null;
}

/** The record a clicked row opens, and the label the detail page shows for it. */
export interface TableRecord {
  record: string;
  label: string;
}

/** A cell as the table shows it, which is also how the server keys status tones. */
export function cellText(cell: unknown): string {
  if (cell === null || cell === undefined) return "";
  if (typeof cell === "object") return JSON.stringify(cell);
  return String(cell);
}

export function statusTone(cell: unknown, tones: Record<string, StatusTone> | undefined): StatusTone {
  return tones?.[cellText(cell)] ?? "neutral";
}

/** The record a row links to, or null when the row has no value in the record column. */
export function tableRowRecord(
  columns: string[],
  row: unknown[],
  link: TableRowLink | null | undefined,
): TableRecord | null {
  if (!link) return null;
  const recordIndex = columns.indexOf(link.recordField);
  if (recordIndex < 0) return null;
  const record = cellText(row[recordIndex]).trim();
  if (!record) return null;
  const labelIndex = link.labelField ? columns.indexOf(link.labelField) : -1;
  const label = labelIndex >= 0 ? cellText(row[labelIndex]).trim() : "";
  return { record, label: label || record };
}
