/**
 * Helpers for picking nested paths from expression preview output.
 */

const SINGLE_DOLLAR_REF =
  /^\$[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*|\[\d+\]|\[\s*"(?:[^"\\]|\\.)*"\s*\]|\[\s*'(?:[^'\\]|\\.)*'\s*\])*$/;

/**
 * True when the trimmed text is a single $-root reference chain (no ternary, calls, or operators).
 */
export function isSingleDollarReferenceExpression(text: string): boolean {
  const t = text.trim();
  if (!t.startsWith("$")) {
    return false;
  }
  if (!SINGLE_DOLLAR_REF.test(t)) {
    return false;
  }
  const rest = t.slice(1);
  if (rest.includes("?") || rest.includes(":")) {
    return false;
  }
  return true;
}

function appendSegment(base: string, segment: string | number): string {
  if (typeof segment === "number" || /^\d+$/.test(String(segment))) {
    const n = typeof segment === "number" ? segment : Number(segment);
    return `${base}[${n}]`;
  }
  const s = String(segment);
  if (/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(s)) {
    return `${base}.${s}`;
  }
  const escaped = s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  return `${base}["${escaped}"]`;
}

/**
 * Append path segments to a dollar expression (e.g. `$input.body` + `['user']` -> `$input.body.user`).
 */
export function extendDollarExpression(
  base: string,
  segments: readonly (string | number)[],
): string {
  let out = base.trim();
  for (const seg of segments) {
    out = appendSegment(out, seg);
  }
  return out;
}
