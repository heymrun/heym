export interface TraceJsonContent {
  isJson: boolean;
  rawText: string;
  treeValue: unknown;
}

function isJsonContainer(value: unknown): value is Record<string, unknown> | unknown[] {
  return value !== null && typeof value === "object";
}

function parseJsonContainerString(value: string): unknown | null {
  const trimmed = value.trim();
  if (
    !((trimmed.startsWith("{") && trimmed.endsWith("}")) ||
      (trimmed.startsWith("[") && trimmed.endsWith("]")))
  ) {
    return null;
  }

  try {
    const parsed: unknown = JSON.parse(trimmed);
    return isJsonContainer(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Parse JSON stored as either a trace payload or a JSON-encoded string inside one.
 * Nested JSON strings are normalized only for the tree view; raw mode always keeps
 * the original event payload so malformed or intentionally textual data is not lost.
 */
function normalizeEmbeddedJson(value: unknown): unknown {
  if (typeof value === "string") {
    const parsed = parseJsonContainerString(value);
    return parsed === null ? value : normalizeEmbeddedJson(parsed);
  }
  if (Array.isArray(value)) {
    return value.map((item) => normalizeEmbeddedJson(item));
  }
  if (isJsonContainer(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, normalizeEmbeddedJson(item)]),
    );
  }
  return value;
}

/** Detect and prepare trace event JSON without throwing on malformed content. */
export function getTraceJsonContent(value: unknown): TraceJsonContent {
  if (typeof value === "string") {
    const parsed = parseJsonContainerString(value);
    return {
      isJson: parsed !== null,
      rawText: value,
      treeValue: parsed === null ? value : normalizeEmbeddedJson(parsed),
    };
  }

  if (isJsonContainer(value)) {
    try {
      const serialized = JSON.stringify(value, null, 2);
      return {
        isJson: true,
        rawText: serialized,
        treeValue: normalizeEmbeddedJson(value),
      };
    } catch {
      return {
        isJson: false,
        rawText: String(value),
        treeValue: value,
      };
    }
  }

  return {
    isJson: false,
    rawText: String(value ?? ""),
    treeValue: value,
  };
}

export function isTraceJsonContent(value: unknown): boolean {
  return getTraceJsonContent(value).isJson;
}
