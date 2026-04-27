/** Helpers for Google Sheets node values in the properties panel (selective single row). */

export const GS_VALUES_MAX_COLS = 26;

/** Column index 0 → "A", … 25 → "Z" (matches Sheets columns A–Z for this node). */
export function colLetter(colIndex: number): string {
  if (colIndex < 0 || colIndex > 25) {
    return String(colIndex + 1);
  }
  return String.fromCharCode(65 + colIndex);
}

export function clampIntString(s: string, min: number, max: number): number {
  const n = parseInt(s || String(min), 10);
  if (Number.isNaN(n)) {
    return min;
  }
  return Math.min(max, Math.max(min, n));
}

export function parse2d(value: string): unknown[][] {
  try {
    const parsed = JSON.parse(value || "[]") as unknown;
    if (!Array.isArray(parsed)) {
      return [[""]];
    }
    return parsed.map((row) =>
      Array.isArray(row) ? [...row] : [String(row)],
    ) as unknown[][];
  } catch {
    return [[""]];
  }
}

export function matrixToJson(rows: string[][]): string {
  return JSON.stringify(rows);
}
