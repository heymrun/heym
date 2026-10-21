const TRUE_STRINGS = new Set(["true", "1", "yes", "on"]);

/** Reads a stored toggle the way the backend's `_coerce_boolean` does, defaulting to false. */
export function isFlagOn(value: unknown): boolean {
  if (typeof value === "string") {
    return TRUE_STRINGS.has(value.trim().toLowerCase());
  }
  if (value === null || value === undefined) {
    return false;
  }
  return Boolean(value);
}
