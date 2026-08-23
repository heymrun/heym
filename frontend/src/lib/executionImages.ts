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
  const shot = out.screenshot;
  if (typeof shot === "string" && shot.length > 100) {
    const dataUrl = `data:image/png;base64,${shot}`;
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
  return srcs;
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
