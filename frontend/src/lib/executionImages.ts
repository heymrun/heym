import type { NodeResult } from "@/types/workflow";

const BASE64 = /^[A-Za-z0-9+/=]+$/;
const IMAGE_MIME = /^image\/[a-z0-9.+-]+$/i;
const MAX_DEPTH = 8;

/** The image type raw base64 holds, read from its first bytes. */
function sniffImageType(base64: string): string | null {
  let head: string;
  try {
    head = atob(base64.slice(0, 16));
  } catch {
    return null;
  }
  if (head.startsWith("\x89PNG")) return "image/png";
  if (head.startsWith("\xff\xd8\xff")) return "image/jpeg";
  if (head.startsWith("GIF8")) return "image/gif";
  if (head.startsWith("RIFF") && head.slice(8, 12) === "WEBP") return "image/webp";
  return null;
}

function imageSrc(key: string, value: string, siblingMime: string | null): string | null {
  if (value.startsWith("data:image/")) return value;
  if (key === "image" && /^https?:\/\//.test(value)) return value;
  if (value.length <= 100 || !BASE64.test(value)) return null;
  const type = sniffImageType(value) ?? siblingMime;
  return type ? `data:${type};base64,${value}` : null;
}

function collectImageSrcs(value: unknown, srcs: string[], depth: number): void {
  if (depth > MAX_DEPTH || typeof value !== "object" || value === null) return;
  const entries: [string, unknown][] = Array.isArray(value)
    ? value.map((item, index) => [String(index), item])
    : Object.entries(value);
  // `{ "type": "image/svg+xml", "data": "<base64>" }`: a format the bytes alone do not reveal.
  const mimeEntry = entries.find(
    (entry): entry is [string, string] => typeof entry[1] === "string" && IMAGE_MIME.test(entry[1]),
  );
  const siblingMime = mimeEntry ? mimeEntry[1] : null;
  for (const [key, item] of entries) {
    if (typeof item !== "string") {
      collectImageSrcs(item, srcs, depth + 1);
      continue;
    }
    const src = imageSrc(key, item, siblingMime);
    if (src && !srcs.includes(src)) srcs.push(src);
  }
}

/** Every image in a node output, wherever it sits: data URLs, base64 images, `image` URLs. */
export function getOutputImageSrcs(output: unknown): string[] {
  const srcs: string[] = [];
  collectImageSrcs(output, srcs, 0);
  return srcs;
}

/** Output with inline image data shortened so JSON views stay readable. */
export function maskImageDataForDisplay(data: unknown): unknown {
  if (typeof data === "string") {
    if (data.startsWith("data:image")) {
      return data.slice(0, 150) + "...";
    }
    if (data.length > 100 && /^[A-Za-z0-9+/=]+$/.test(data)) {
      return "[Base64 data]";
    }
  }
  if (typeof data === "object" && data !== null) {
    if (Array.isArray(data)) {
      return data.map(maskImageDataForDisplay);
    }
    const result: Record<string, unknown> = {};
    for (const key in data) {
      if (Object.prototype.hasOwnProperty.call(data, key)) {
        result[key] = maskImageDataForDisplay((data as Record<string, unknown>)[key]);
      }
    }
    return result;
  }
  return data;
}

/** Every screenshot produced by a run, in execution order. */
export function collectRunImageSrcs(results: readonly NodeResult[]): string[] {
  const srcs: string[] = [];
  for (const result of results) {
    if (
      result.node_type === "condition" ||
      result.node_type === "sticky" ||
      result.status === "skipped"
    ) {
      continue;
    }
    srcs.push(...getOutputImageSrcs(result.output));
  }
  return srcs;
}
