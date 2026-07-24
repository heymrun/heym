/**
 * Compare workflow `updated_at` ISO timestamps without losing sub-millisecond digits.
 *
 * `Date.parse` only keeps milliseconds. Postgres timestamps often include microseconds, so two
 * saves in the same millisecond used to compare equal and skip the stale-run dialog.
 */
export function isRevisionAfter(candidate: string, baseline: string): boolean {
  const candidateMs = Date.parse(candidate);
  const baselineMs = Date.parse(baseline);
  if (
    !Number.isNaN(candidateMs) &&
    !Number.isNaN(baselineMs) &&
    candidateMs !== baselineMs
  ) {
    return candidateMs > baselineMs;
  }
  // Same millisecond (or unparsable): ISO-8601 strings stay ordered when formats match.
  return candidate > baseline;
}

/** Prefer `primary` when equal or newer; otherwise `fallback`. */
export function pickPreferredRevision(
  primary: string | null,
  fallback: string | null,
): string | null {
  if (!primary) return fallback;
  if (!fallback) return primary;
  if (primary === fallback || isRevisionAfter(primary, fallback)) {
    return primary;
  }
  return fallback;
}
