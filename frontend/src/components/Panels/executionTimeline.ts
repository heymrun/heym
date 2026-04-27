import type { NodeResult, NodeType } from "@/types/workflow";
import { NODE_DEFINITIONS } from "@/types/node";

export interface TimelineEntry extends NodeResult {
  isSubAgent: boolean;
  /** Set by DebugPanel: index in full `node_results` / `workflowStore.nodeResults` (required for span → output mapping). */
  sourceNodeResultsIndex?: number;
  retryFailedAttempts?: number;
  retryFinalAttempt?: number | null;
  retryMaxAttempts?: number | null;
}

export interface TimeWindow {
  startMs: number;
  totalMs: number;
}

export interface BuildTimelineOptions {
  preserveTotalTime?: boolean;
}

/** Payload when selecting a row or span in the execution timeline (debug panel). */
export interface TimelineSelectPayload {
  nodeId: string;
  /** Global index in `node_results`; null = use the latest row for this node (label click). */
  resultListIndex: number | null;
}

export interface SpanItem {
  key: string;
  /** Index into the execution `node_results` array for this span (disambiguates multiple runs of the same node). */
  resultListIndex: number;
  nodeId: string;
  nodeLabel: string;
  nodeType: string;
  traceId: string | null;
  status: string;
  durationMs: number;
  startOffsetMs: number;
  endOffsetMs: number;
  error: string | null;
  leftPct: number;
  widthPct: number;
  colorVar: string;
  occurrence: number;
  occurrenceCount: number;
  retryFailedAttempts: number;
  retryFinalAttempt: number | null;
  retryMaxAttempts: number | null;
  gcPauseMs: number;
  gcPauseCount: number;
  gcPauseSegments: GcPauseSegment[];
}

export interface SpanRow {
  key: string;
  nodeId: string;
  nodeLabel: string;
  depth: number;
  spans: SpanItem[];
}

interface RawSpanItem {
  key: string;
  nodeId: string;
  nodeLabel: string;
  nodeType: string;
  traceId: string | null;
  status: string;
  durationMs: number;
  error: string | null;
  colorVar: string;
  startMs: number;
  endMs: number;
  order: number;
  retryFailedAttempts: number;
  retryFinalAttempt: number | null;
  retryMaxAttempts: number | null;
  gcPauseMs: number;
  gcPauseCount: number;
  gcPauseIntervals: RawGcPauseInterval[];
}

interface SpanAccumulator extends SpanRow {
  rawSpans: RawSpanItem[];
}

interface RawGcPauseInterval {
  startMs: number;
  durationMs: number;
  generation: number | null;
}

export interface GcPauseSegment {
  leftPct: number;
  widthPct: number;
  durationMs: number;
  generation: number | null;
}

/** GC is not shown in the span timeline / tooltip below this total pause (ms). */
const GC_PAUSE_DISPLAY_MIN_MS = 20;

function nodeColorVar(nodeType: string): string {
  const def = NODE_DEFINITIONS[nodeType as NodeType];
  return def?.color ?? "primary";
}

function colorFor(result: TimelineEntry): string {
  return result.status === "error" ? "node-error" : nodeColorVar(result.node_type);
}

function getMetadataNumber(result: TimelineEntry, key: string): number | null {
  const value = result.metadata?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function getMetadataInteger(result: TimelineEntry, key: string): number | null {
  const value = getMetadataNumber(result, key);
  return value !== null && Number.isInteger(value) ? value : null;
}

function getGcPauseIntervals(result: TimelineEntry): RawGcPauseInterval[] {
  const rawIntervals = result.metadata?.gc_pause_intervals;
  if (!Array.isArray(rawIntervals)) {
    return [];
  }

  return rawIntervals.flatMap((rawInterval) => {
    if (typeof rawInterval !== "object" || rawInterval === null) {
      return [];
    }

    const startMs =
      typeof rawInterval.start_ms === "number" && Number.isFinite(rawInterval.start_ms)
        ? rawInterval.start_ms
        : null;
    const durationMs =
      typeof rawInterval.duration_ms === "number" && Number.isFinite(rawInterval.duration_ms)
        ? rawInterval.duration_ms
        : null;
    const generation =
      typeof rawInterval.generation === "number" && Number.isInteger(rawInterval.generation)
        ? rawInterval.generation
        : null;

    if (startMs === null || durationMs === null || durationMs <= 0) {
      return [];
    }

    return [{ startMs, durationMs, generation }];
  });
}

function getTraceId(result: TimelineEntry): string | null {
  const traceId = result.metadata?.trace_id;
  return typeof traceId === "string" && traceId.trim() !== "" ? traceId : null;
}

function getTimingBounds(result: TimelineEntry): { startMs: number; endMs: number } | null {
  const startMs = getMetadataNumber(result, "started_at_ms");
  const endMs = getMetadataNumber(result, "ended_at_ms");
  if (startMs === null || endMs === null || endMs < startMs) {
    return null;
  }
  return { startMs, endMs };
}

function hasRecordedTiming(nodeResults: TimelineEntry[]): boolean {
  return nodeResults.length > 0 && nodeResults.every((result) => getTimingBounds(result) !== null);
}

export function formatTimelineMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

export function getTimelineRowKey(
  result: TimelineEntry,
  subAgentLabelToParentId: Map<string, string>,
): string {
  const parentId = result.isSubAgent
    ? subAgentLabelToParentId.get(result.node_label) ?? "__orphan__"
    : null;
  const depth = result.isSubAgent && parentId !== "__orphan__" ? 1 : 0;
  return depth === 1
    ? `child:${parentId}:${result.node_id}`
    : `top:${parentId ?? "root"}:${result.node_id}`;
}

export function buildTimelineModel(
  nodeResults: TimelineEntry[],
  totalTimeMs: number,
  subAgentLabelToParentId: Map<string, string>,
  options: BuildTimelineOptions = {},
): { rows: SpanRow[]; timeWindow: TimeWindow } {
  const preserveTotalTime = options.preserveTotalTime ?? true;
  const recordedTiming = hasRecordedTiming(nodeResults);

  let timeWindow: TimeWindow;
  if (nodeResults.length === 0) {
    timeWindow = { startMs: 0, totalMs: Math.max(totalTimeMs, 1) };
  } else if (!recordedTiming) {
    const syntheticTotal =
      preserveTotalTime && totalTimeMs > 0
        ? totalTimeMs
        : nodeResults.reduce((sum, result) => sum + result.execution_time_ms, 0);
    timeWindow = { startMs: 0, totalMs: Math.max(syntheticTotal, 1) };
  } else {
    let minStartMs = Number.POSITIVE_INFINITY;
    let maxEndMs = 0;
    for (const result of nodeResults) {
      const bounds = getTimingBounds(result);
      if (!bounds) continue;
      minStartMs = Math.min(minStartMs, bounds.startMs);
      maxEndMs = Math.max(maxEndMs, bounds.endMs);
    }
    const recordedTotal = Math.max(maxEndMs - minStartMs, 1);
    timeWindow = {
      startMs: Number.isFinite(minStartMs) ? minStartMs : 0,
      totalMs: preserveTotalTime && totalTimeMs > 0 ? Math.max(totalTimeMs, recordedTotal) : recordedTotal,
    };
  }

  const rowMap = new Map<string, SpanAccumulator>();
  const topLevelRowOrder: string[] = [];
  const childRowOrderByParent = new Map<string, string[]>();
  const orphanRowOrder: string[] = [];
  let syntheticCursorMs = 0;

  for (let index = 0; index < nodeResults.length; index++) {
    const result = nodeResults[index];
    const parentId = result.isSubAgent
      ? subAgentLabelToParentId.get(result.node_label) ?? "__orphan__"
      : null;
    const depth = result.isSubAgent && parentId !== "__orphan__" ? 1 : 0;
    const rowKey = getTimelineRowKey(result, subAgentLabelToParentId);

    let row = rowMap.get(rowKey);
    if (!row) {
      row = {
        key: rowKey,
        nodeId: result.node_id,
        nodeLabel: result.node_label,
        depth,
        spans: [],
        rawSpans: [],
      };
      rowMap.set(rowKey, row);

      if (depth === 1 && parentId) {
        const childKeys = childRowOrderByParent.get(parentId) ?? [];
        childKeys.push(rowKey);
        childRowOrderByParent.set(parentId, childKeys);
      } else if (result.isSubAgent) {
        orphanRowOrder.push(rowKey);
      } else {
        topLevelRowOrder.push(rowKey);
      }
    }

    const bounds = recordedTiming ? getTimingBounds(result) : null;
    const startMs = bounds?.startMs ?? syntheticCursorMs;
    const endMs = bounds?.endMs ?? (syntheticCursorMs + Math.max(result.execution_time_ms, 0));

    if (!bounds) {
      syntheticCursorMs = endMs;
    }

    const sourceListIndex = result.sourceNodeResultsIndex ?? index;
    const gcPauseIntervals = getGcPauseIntervals(result);
    const gcPauseMs =
      getMetadataNumber(result, "gc_pause_ms") ??
      gcPauseIntervals.reduce((sum, interval) => sum + interval.durationMs, 0);
    const gcPauseCount = getMetadataInteger(result, "gc_pause_count") ?? gcPauseIntervals.length;
    row.rawSpans.push({
      key: `${rowKey}:${index}`,
      nodeId: result.node_id,
      nodeLabel: result.node_label,
      nodeType: result.node_type,
      traceId: getTraceId(result),
      status: result.status,
      durationMs: Math.max(endMs - startMs, result.execution_time_ms, 0),
      error: result.error,
      colorVar: colorFor(result),
      startMs,
      endMs,
      order: sourceListIndex,
      retryFailedAttempts: result.retryFailedAttempts ?? 0,
      retryFinalAttempt: result.retryFinalAttempt ?? null,
      retryMaxAttempts: result.retryMaxAttempts ?? null,
      gcPauseMs,
      gcPauseCount,
      gcPauseIntervals,
    });
  }

  const orderedRowKeys: string[] = [];
  for (const rowKey of topLevelRowOrder) {
    orderedRowKeys.push(rowKey);
    const parentNodeId = rowMap.get(rowKey)?.nodeId;
    if (!parentNodeId) continue;
    orderedRowKeys.push(...(childRowOrderByParent.get(parentNodeId) ?? []));
  }

  const seenRowKeys = new Set(orderedRowKeys);
  for (const childKeys of childRowOrderByParent.values()) {
    for (const childKey of childKeys) {
      if (seenRowKeys.has(childKey)) continue;
      orderedRowKeys.push(childKey);
      seenRowKeys.add(childKey);
    }
  }
  for (const orphanRowKey of orphanRowOrder) {
    if (seenRowKeys.has(orphanRowKey)) continue;
    orderedRowKeys.push(orphanRowKey);
    seenRowKeys.add(orphanRowKey);
  }

  const rows = orderedRowKeys
    .map((rowKey) => rowMap.get(rowKey))
    .filter((row): row is SpanAccumulator => row !== undefined)
    .map((row) => {
      const orderedSpans = [...row.rawSpans].sort(
        (left, right) =>
          left.startMs - right.startMs || left.endMs - right.endMs || left.order - right.order,
      );
      const occurrenceCount = orderedSpans.length;

      return {
        key: row.key,
        nodeId: row.nodeId,
        nodeLabel: row.nodeLabel,
        depth: row.depth,
        spans: orderedSpans.map((span, spanIndex) => {
          const leftPct = Math.min(
            Math.max(((span.startMs - timeWindow.startMs) / timeWindow.totalMs) * 100, 0),
            99.5,
          );
          const widthPct = Math.max(
            Math.min((span.durationMs / timeWindow.totalMs) * 100, 100 - leftPct),
            0.5,
          );
          const gcPauseSegments =
            span.durationMs > 0 && span.gcPauseMs >= GC_PAUSE_DISPLAY_MIN_MS
              ? span.gcPauseIntervals.map((interval) => {
                  const segmentLeftPct = Math.min(
                    Math.max((interval.startMs / span.durationMs) * 100, 0),
                    99.5,
                  );
                  const segmentWidthPct = Math.max(
                    Math.min(
                      (interval.durationMs / span.durationMs) * 100,
                      100 - segmentLeftPct,
                    ),
                    0.5,
                  );

                  return {
                    leftPct: segmentLeftPct,
                    widthPct: segmentWidthPct,
                    durationMs: interval.durationMs,
                    generation: interval.generation,
                  };
                })
              : [];

          const showGcPause = span.gcPauseMs >= GC_PAUSE_DISPLAY_MIN_MS;

          return {
            key: span.key,
            resultListIndex: span.order,
            nodeId: span.nodeId,
            nodeLabel: span.nodeLabel,
            nodeType: span.nodeType,
            traceId: span.traceId,
            status: span.status,
            durationMs: span.durationMs,
            startOffsetMs: Math.max(span.startMs - timeWindow.startMs, 0),
            endOffsetMs: Math.max(span.endMs - timeWindow.startMs, 0),
            error: span.error,
            leftPct,
            widthPct,
            colorVar: span.colorVar,
            occurrence: spanIndex + 1,
            occurrenceCount,
            retryFailedAttempts: span.retryFailedAttempts,
            retryFinalAttempt: span.retryFinalAttempt,
            retryMaxAttempts: span.retryMaxAttempts,
            gcPauseMs: showGcPause ? span.gcPauseMs : 0,
            gcPauseCount: showGcPause ? span.gcPauseCount : 0,
            gcPauseSegments,
          };
        }),
      };
    });

  return { rows, timeWindow };
}
