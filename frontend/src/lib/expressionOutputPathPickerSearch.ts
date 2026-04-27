export interface SearchHit {
  segments: (string | number)[];
  value: unknown;
}

export interface SearchEntry {
  segment: string | number;
  val: unknown;
}

export function formatPathDisplay(segments: readonly (string | number)[]): string {
  if (segments.length === 0) {
    return "(root)";
  }
  let s = "";
  for (const seg of segments) {
    if (typeof seg === "number") {
      s += `[${seg}]`;
    } else if (/^[a-zA-Z_][\w]*$/.test(seg)) {
      s += (s ? "." : "") + seg;
    } else {
      const esc = String(seg).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
      s += `["${esc}"]`;
    }
  }
  return s;
}

export function directValueSearchText(val: unknown): string {
  if (val === null) {
    return "null";
  }
  if (val === undefined) {
    return "undefined";
  }
  if (typeof val === "string") {
    return val;
  }
  if (typeof val === "number" || typeof val === "boolean" || typeof val === "bigint") {
    return String(val);
  }
  return "";
}

export function matchesSearchHit(hit: SearchHit, queryLower: string): boolean {
  if (!queryLower) {
    return false;
  }
  const lastSeg = hit.segments[hit.segments.length - 1];
  const keyStr =
    typeof lastSeg === "number" ? `[${lastSeg}]` : String(lastSeg ?? "");
  const valueStr = directValueSearchText(hit.value).toLowerCase();
  return keyStr.toLowerCase().includes(queryLower) || valueStr.includes(queryLower);
}

export function flattenSearchHits(
  value: unknown,
  prefix: readonly (string | number)[],
  currentDepth: number,
  maxDepth: number,
  entriesForValue: (v: unknown) => SearchEntry[],
  isExpandable: (v: unknown) => boolean,
  out: SearchHit[],
): void {
  if (currentDepth >= maxDepth) {
    return;
  }
  if (!isExpandable(value)) {
    out.push({ segments: [...prefix], value });
    return;
  }
  for (const { segment, val } of entriesForValue(value)) {
    const p = [...prefix, segment];
    out.push({ segments: p, value: val });
    if (isExpandable(val)) {
      flattenSearchHits(
        val,
        p,
        currentDepth + 1,
        maxDepth,
        entriesForValue,
        isExpandable,
        out,
      );
    }
  }
}
