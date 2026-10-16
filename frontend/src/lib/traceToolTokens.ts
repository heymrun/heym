import type { LLMTraceDetail, ToolTokenEstimate } from "@/types/trace";

import { readTraceTurnTimings } from "@/lib/traceModelRouting";

interface RawToolCall {
  tool_call_id?: unknown;
  start_ms?: unknown;
  /** Chat traces keep only how much a tool returned, not the result. */
  result_chars?: unknown;
  result?: unknown;
}

interface AskedTool {
  id: string;
  /** How much output the tool produced, which is what it can add to a prompt. */
  weight: number;
}

/** Timings are rounded, so a tool that starts as its turn ends may read a hair early. */
const START_TOLERANCE_MS = 1;

function sizeOf(value: unknown): number {
  if (value === undefined || value === null) return 0;
  if (typeof value === "string") return value.length;
  try {
    return JSON.stringify(value).length;
  } catch {
    return 0;
  }
}

/**
 * What each tool's output cost the turn that read it.
 *
 * A turn's prompt holds everything before it, so the next turn's prompt minus this
 * one's, minus the reply this one added, is the tools' output. Tools asked for by the
 * same turn share that growth in proportion to how much each returned. A tool the
 * last turn asked for has no reader, and a trace that did not record per-turn
 * prompts has nothing to subtract, so neither gets an estimate.
 */
export function estimateToolTokens(trace: LLMTraceDetail): Map<string, ToolTokenEstimate> {
  const estimates = new Map<string, ToolTokenEstimate>();
  const response = trace.response as Record<string, unknown> | null | undefined;
  const timings = [...readTraceTurnTimings(response ?? null)].sort((a, b) => a.turn - b.turn);
  const calls = Array.isArray(response?.tool_calls) ? (response.tool_calls as RawToolCall[]) : [];
  if (timings.length < 2 || calls.length === 0) return estimates;

  const askedByTurn = new Map<number, AskedTool[]>();
  for (const call of calls) {
    if (typeof call.tool_call_id !== "string" || typeof call.start_ms !== "number") continue;
    const startMs = call.start_ms;
    const asker = [...timings].reverse().find((t) => t.startMs <= startMs + START_TOLERANCE_MS);
    if (!asker) continue;
    const tools = askedByTurn.get(asker.turn) ?? [];
    // Only the output grows the next prompt; the call itself is already in the reply.
    const weight = typeof call.result_chars === "number" ? call.result_chars : sizeOf(call.result);
    tools.push({ id: call.tool_call_id, weight });
    askedByTurn.set(asker.turn, tools);
  }

  for (const [turn, tools] of askedByTurn) {
    const index = timings.findIndex((t) => t.turn === turn);
    const asker = timings[index];
    const reader = timings[index + 1];
    if (!reader || asker.promptTokens === null || reader.promptTokens === null) continue;

    const grown = reader.promptTokens - asker.promptTokens - (asker.completionTokens ?? 0);
    // Context that shrank (trimmed history, a cache that is not counted) hides the tools.
    if (grown <= 0) continue;

    const totalWeight = tools.reduce((sum, tool) => sum + tool.weight, 0);
    for (const tool of tools) {
      const share = totalWeight > 0 ? tool.weight / totalWeight : 1 / tools.length;
      const tokens = Math.round(grown * share);
      if (tokens <= 0) continue;
      estimates.set(tool.id, { tokens, readByTurn: reader.turn, sharedBy: tools.length });
    }
  }
  return estimates;
}
