import type { TraceSpan } from "@/components/Traces/TraceDurationChart.vue";
import type { LLMTraceDetail } from "@/types/trace";

import {
  formatRoutingCallLabel,
  readTraceModelRouting,
  readTraceTurnTimings,
  type ModelRoutingTrace,
  type ModelRoutingTurnTiming,
} from "@/lib/traceModelRouting";

export interface ToolCallEntry {
  name: string;
  arguments: Record<string, unknown>;
  result: unknown;
  tool_call_id?: string;
  elapsed_ms?: number;
  /** Offset from the start of the request, for the waterfall layout. */
  start_ms?: number;
  /** Set when the tool ran work of its own, such as a sub-agent, and traced it. */
  trace_id?: string;
  source?: string;
  mcp_server?: string;
  workflow_name?: string;
  status?: string;
}

export function getToolCallsFromResponse(
  response: Record<string, unknown> | null,
): ToolCallEntry[] | undefined {
  const arr = response?.tool_calls;
  return Array.isArray(arr) ? (arr as ToolCallEntry[]) : undefined;
}

/** False for a call made with no arguments, so the panel can show `{}` for any empty form. */
export function hasToolCallArguments(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim() !== "" && value.trim() !== "{}";
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

function computeInvocationTotalMs(children: TraceSpan[]): number {
  if (children.length === 0) return 0;
  const llmSpan = children.find((s) => s.id === "call_llm" || s.label === "call_llm");
  const subAgentSpans = children.filter((s) => s.label === "call_sub_agent");
  const otherSpans = children.filter(
    (s) =>
      s.id !== "call_llm" &&
      s.label !== "call_llm" &&
      s.label !== "call_sub_agent"
  );
  let total = 0;
  if (llmSpan) total += llmSpan.durationMs;
  if (subAgentSpans.length > 0) {
    total += Math.max(...subAgentSpans.map((s) => s.durationMs));
  }
  total += otherSpans.reduce((acc, s) => acc + s.durationMs, 0);
  return total > 0 ? total : 0;
}

/**
 * Per-turn rows, ordered by when each one actually started: a routing decision where
 * one was made, and every model call of the request.
 */
function buildTurnSpans(
  routing: ModelRoutingTrace | null,
  timings: ModelRoutingTurnTiming[],
): TraceSpan[] {
  const spans: TraceSpan[] = [];

  for (const call of routing?.calls ?? []) {
    if (routing === null || call.decisionMs <= 0) continue;
    spans.push({
      id: `model_router_turn_${call.turn}`,
      label:
        routing.calls.length > 1
          ? `model_router · turn ${call.turn} (${formatRoutingCallLabel(call)})`
          : `model_router (${routing.routerLabel}${routing.decisionModel ? ` · ${routing.decisionModel}` : ""})`,
      durationMs: call.decisionMs,
      startMs: call.startMs,
      icon: "router",
      // The decision wrote its own trace row; the label opens it.
      traceId: call.decisionTraceId,
    });
  }

  for (const timing of timings) {
    if (timing.durationMs <= 0) continue;
    spans.push({
      id: `call_llm_turn_${timing.turn}`,
      label: timings.length > 1 ? `call_llm · turn ${timing.turn}` : "call_llm",
      durationMs: timing.durationMs,
      startMs: timing.startMs,
      icon: "llm",
      // Part of this trace, so there is nothing to open; the row opens its step.
      stepId: `call_llm_turn_${timing.turn}`,
    });
  }

  return spans.sort((a, b) => (a.startMs ?? 0) - (b.startMs ?? 0));
}

/** The Duration Breakdown rows for a trace, led by the whole invocation. */
export function buildTraceSpans(trace: LLMTraceDetail): TraceSpan[] {
  const response = trace.response as Record<string, unknown> | null | undefined;
  const timingBreakdown = response?.timing_breakdown as
    | { llm_ms?: number; tools_ms?: number; mcp_list_ms?: number }
    | undefined;

  const children: TraceSpan[] = [];

  if (timingBreakdown && typeof timingBreakdown === "object") {
    if (timingBreakdown.llm_ms != null && timingBreakdown.llm_ms > 0) {
      children.push({
        id: "call_llm",
        label: "call_llm",
        durationMs: timingBreakdown.llm_ms,
        icon: "llm",
      });
    }
    if (timingBreakdown.tools_ms != null && timingBreakdown.tools_ms > 0) {
      children.push({
        id: "tools",
        label: "tools",
        durationMs: timingBreakdown.tools_ms,
        icon: "tool",
      });
    }
    if (timingBreakdown.mcp_list_ms != null && timingBreakdown.mcp_list_ms > 0) {
      children.push({
        id: "mcp_list",
        label: "mcp_list",
        durationMs: timingBreakdown.mcp_list_ms,
        icon: "agent",
      });
    }
  } else {
    const responseElapsed = response?.elapsed_ms;
    if (
      typeof responseElapsed === "number" &&
      !Number.isNaN(responseElapsed) &&
      responseElapsed > 0
    ) {
      children.push({
        id: "call_llm",
        label: "call_llm",
        durationMs: responseElapsed,
        icon: "llm",
      });
    }

    const toolCalls = getToolCallsFromResponse(response ?? null);
    if (toolCalls?.length) {
      for (let i = 0; i < toolCalls.length; i++) {
        const tc = toolCalls[i];
        const ms = tc.elapsed_ms;
        if (typeof ms === "number" && !Number.isNaN(ms) && ms > 0) {
          children.push({
            id: `tool_${i}`,
            label: tc.name,
            durationMs: ms,
            // Parallel tools overlap on the track; that overlap is the run's shape.
            startMs: typeof tc.start_ms === "number" ? tc.start_ms : undefined,
            icon: "tool",
            // A sub-agent or sub-workflow wrote its own trace; the row opens it.
            traceId: typeof tc.trace_id === "string" ? tc.trace_id : null,
            // Otherwise the row jumps to the tool's own step in this trace.
            stepId: typeof tc.tool_call_id === "string" ? `tool-${tc.tool_call_id}` : null,
          });
        }
      }
    }
  }

  const routing = readTraceModelRouting(response ?? null);
  // Real offsets exist only when the backend recorded turn timings; otherwise keep
  // the aggregate view rather than inventing a layout.
  const timings = readTraceTurnTimings(response ?? null);
  const turnSpans = timings.length > 0 ? buildTurnSpans(routing, timings) : [];

  if (turnSpans.length > 0) {
    const totalMs = Math.max(
      ...turnSpans.map((span) => (span.startMs ?? 0) + span.durationMs),
      ...children.map((span) => (span.startMs ?? 0) + span.durationMs),
      trace.elapsed_ms ?? 0,
    );
    // The per-turn rows replace the aggregate llm row; everything else keeps its place
    // in the same timeline, ordered by when it started.
    const nonLlmChildren = children.filter((span) => span.id !== "call_llm");
    const laidOut = [...turnSpans, ...nonLlmChildren].sort(
      (a, b) => (a.startMs ?? 0) - (b.startMs ?? 0),
    );
    return [
      {
        id: "invocation",
        label: "invocation",
        durationMs: totalMs,
        startMs: 0,
        icon: "invocation",
      },
      ...laidOut,
    ];
  }

  const routingTotalMs = routing?.decisionTotalMs ?? 0;
  const totalMs =
    (computeInvocationTotalMs(children) || (trace.elapsed_ms ?? 0)) + routingTotalMs;

  if (totalMs <= 0 || Number.isNaN(totalMs)) {
    return [];
  }

  const routingSpan: TraceSpan[] =
    routing !== null && routingTotalMs > 0
      ? [
          {
            id: "model_router",
            label: `model_router (${routing.routerLabel}${routing.decisionModel ? ` · ${routing.decisionModel}` : ""})`,
            durationMs: routingTotalMs,
            icon: "router",
            traceId: routing.calls.length === 1 ? routing.calls[0].decisionTraceId : null,
          },
        ]
      : [];

  return [
    {
      id: "invocation",
      label: "invocation",
      durationMs: totalMs,
      icon: "invocation",
    },
    // Routing happens before the model call, so it leads the children.
    ...routingSpan,
    ...children,
  ];
}
