import type { NodeResult } from "@/types/workflow";

/** All image srcs from a node output: image gen (output.image) or Playwright screenshots. */
export function getOutputImageSrcs(output: unknown): string[] {
  const out = output as Record<string, unknown> | undefined;
  if (!out) return [];
  const srcs: string[] = [];
  const img = out.image;
  if (typeof img === "string" && (img.startsWith("data:image/") || img.startsWith("http"))) {
    srcs.push(img);
  }
  const base64 = out.file_base64;
  const mimeType = out.mime_type;
  if (
    typeof base64 === "string" &&
    base64.length > 0 &&
    typeof mimeType === "string" &&
    mimeType.startsWith("image/")
  ) {
    const dataUrl = `data:${mimeType};base64,${base64}`;
    if (!srcs.includes(dataUrl)) srcs.push(dataUrl);
  }
  const results = out.results as Record<string, unknown> | undefined;
  if (results && typeof results === "object") {
    for (const v of Object.values(results)) {
      if (typeof v === "string" && v.length > 100 && /^[A-Za-z0-9+/=]+$/.test(v)) {
        const dataUrl = `data:image/png;base64,${v}`;
        if (!srcs.includes(dataUrl)) srcs.push(dataUrl);
      }
    }
  }
  // Playwright repeats its last step screenshot here; after `results` it dedupes in step order.
  const shot = out.screenshot;
  if (typeof shot === "string" && shot.length > 100) {
    const dataUrl = `data:image/png;base64,${shot}`;
    if (!srcs.includes(dataUrl)) srcs.push(dataUrl);
  }
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
