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

/**
 * Where a link cell opens: an http(s) URL, or a path inside this app. Cells can come from
 * upstream data, so anything else (javascript:, data:, //host) is not a link.
 */
export function tableLinkHref(cell: unknown): string | null {
  const raw = cellText(cell).trim();
  if (!raw) return null;
  if (/^\/(?![/\\])\S*$/.test(raw)) return raw;
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export type TableSortDirection = "asc" | "desc";

/** Which column a table widget is sorted by, and which way. */
export interface TableSort {
  column: number;
  direction: TableSortDirection;
}

/**
 * Orders rows by one column. Numbers compare numerically, everything else by text.
 * Empty cells stay last either way, and equal values keep their original order.
 */
export function sortTableRows(
  rows: unknown[][],
  column: number,
  direction: TableSortDirection,
): unknown[][] {
  const factor = direction === "asc" ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const leftEmpty = cellText(left.row[column]).trim() === "";
      const rightEmpty = cellText(right.row[column]).trim() === "";
      if (leftEmpty || rightEmpty) {
        if (leftEmpty && rightEmpty) return left.index - right.index;
        return leftEmpty ? 1 : -1;
      }
      const byValue = compareCells(left.row[column], right.row[column]);
      if (byValue === 0) return left.index - right.index;
      return byValue * factor;
    })
    .map((entry) => entry.row);
}

function compareCells(left: unknown, right: unknown): number {
  const a = cellText(left).trim();
  const b = cellText(right).trim();
  const aNumber = Number(a);
  const bNumber = Number(b);
  if (Number.isFinite(aNumber) && Number.isFinite(bNumber)) return aNumber - bNumber;
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
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
