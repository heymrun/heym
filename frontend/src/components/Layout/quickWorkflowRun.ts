import type { FileRunResult, QuickDrawerRunState } from "@/types/quickDrawer";
import type { NodeResult } from "@/types/workflow";

/** Classes for the run status badge. */
export function resultToneClasses(status: QuickDrawerRunState["status"]): string {
  if (status === "success") {
    return "border-success/30 bg-success/10 text-success";
  }
  if (status === "pending") {
    return "border-warning/30 bg-warning/10 text-foreground";
  }
  if (status === "error") {
    return "border-destructive/30 bg-destructive/10 text-destructive";
  }
  return "border-border/60 bg-muted/30 text-muted-foreground";
}

/** The latest result of each step, in run order, leaving out skipped steps. */
export function latestNodeResults(nodeResults: NodeResult[]): NodeResult[] {
  const dedupedResults: NodeResult[] = [];
  const seenNodeIds = new Set<string>();

  for (let index = nodeResults.length - 1; index >= 0; index -= 1) {
    const nodeResult = nodeResults[index];
    if (nodeResult.status === "skipped") {
      continue;
    }
    if (seenNodeIds.has(nodeResult.node_id)) {
      continue;
    }
    seenNodeIds.add(nodeResult.node_id);
    dedupedResults.unshift(nodeResult);
  }

  return dedupedResults;
}

export function formatExecutionTime(executionTimeMs: number | null): string {
  if (executionTimeMs === null) return "Pending";
  if (executionTimeMs < 1000) return `${executionTimeMs.toFixed(0)} ms`;
  return `${(executionTimeMs / 1000).toFixed(2)} s`;
}

export function formatJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function normalizeImage(value: string): string | null {
  if (value.startsWith("data:image/") || value.startsWith("http")) {
    return value;
  }
  if (value.length > 100 && /^[A-Za-z0-9+/=]+$/.test(value)) {
    return `data:image/png;base64,${value}`;
  }
  return null;
}

function extractImagesFromObject(obj: Record<string, unknown>): string[] {
  const images: string[] = [];

  const directImage = typeof obj.image === "string" ? normalizeImage(obj.image) : null;
  if (directImage) {
    images.push(directImage);
  }

  const screenshot =
    typeof obj.screenshot === "string" ? normalizeImage(obj.screenshot) : null;
  if (screenshot) {
    images.push(screenshot);
  }

  if (obj.results && typeof obj.results === "object") {
    for (const value of Object.values(obj.results as Record<string, unknown>)) {
      if (typeof value !== "string") continue;
      const image = normalizeImage(value);
      if (image) {
        images.push(image);
      }
    }
  }

  return images;
}

/** Images in the final outputs, then in step outputs, each once. */
export function extractImages(
  outputs: Record<string, unknown> | null,
  nodeResults: NodeResult[],
): string[] {
  const seen = new Set<string>();
  const images: string[] = [];

  if (outputs) {
    for (const value of Object.values(outputs)) {
      if (typeof value !== "object" || value === null) continue;
      for (const image of extractImagesFromObject(value as Record<string, unknown>)) {
        if (seen.has(image)) continue;
        seen.add(image);
        images.push(image);
      }
    }
  }

  for (const nodeResult of nodeResults) {
    if (typeof nodeResult.output !== "object" || nodeResult.output === null) continue;
    for (const image of extractImagesFromObject(nodeResult.output as Record<string, unknown>)) {
      if (seen.has(image)) continue;
      seen.add(image);
      images.push(image);
    }
  }

  return images;
}

/** The reason a run's outputs give for failing, if they give one. */
export function extractErrorMessage(outputs: Record<string, unknown> | null): string | null {
  if (!outputs) return null;
  for (const key of ["detail", "error", "message"]) {
    const value = outputs[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

/** The run state for a finished file upload run (the upload response has no step list). */
export function fileRunState(
  // A run widget run has no file and may have no history row.
  result: Pick<FileRunResult, "status" | "output"> & { run_id: string | null; file?: FileRunResult["file"] },
  startedAt: number,
  finishedAt: number = Date.now(),
): QuickDrawerRunState {
  const status: QuickDrawerRunState["status"] =
    result.status === "success" || result.status === "pending" ? result.status : "error";
  return {
    status,
    executionId: null,
    outputs: result.output,
    executionTimeMs: finishedAt - startedAt,
    executionHistoryId: result.run_id,
    errorMessage:
      status === "error" ? extractErrorMessage(result.output) ?? "Workflow execution failed" : null,
    nodeResults: [],
    startedAt,
  };
}
