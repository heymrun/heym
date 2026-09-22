/**
 * Reads the routing block a Model Router writes onto the routed request's own trace.
 *
 * The decision model also writes its own trace row, but that row lives elsewhere in
 * the list. This block is what lets the routed request's detail show, in one place,
 * how long routing cost and which model each turn went to.
 */

export interface ModelRoutingTraceCall {
  turn: number;
  model: string;
  option: string | null;
  credentialName: string | null;
  fallback: boolean;
  error: string | null;
  decisionMs: number;
  decisionTraceId: string | null;
  reused: boolean;
  /** Offset from the start of the request, for the waterfall layout. */
  startMs: number;
}

export interface ModelRoutingTurnTiming {
  turn: number;
  startMs: number;
  durationMs: number;
  model: string | null;
  provider: string | null;
  promptTokens: number | null;
  completionTokens: number | null;
  totalTokens: number | null;
  textChars: number | null;
  toolCalls: number | null;
  error: string | null;
}

export interface ModelRoutingTrace {
  routerLabel: string;
  routerCredentialId: string;
  decisionModel: string | null;
  decisionTotalMs: number;
  calls: ModelRoutingTraceCall[];
  /** Real provider-call offsets, so the breakdown can lay out a waterfall. */
  turnTimings: ModelRoutingTurnTiming[];
}

function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function asNullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asNullableText(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function readCall(raw: unknown, index: number): ModelRoutingTraceCall | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  const model = asNullableText(value.model);
  if (model === null) return null;
  return {
    turn: typeof value.turn === "number" ? value.turn : index + 1,
    model,
    option: asNullableText(value.option),
    credentialName: asNullableText(value.credentialName),
    fallback: value.fallback === true,
    error: asNullableText(value.error),
    startMs: asNumber(value.startMs),
    decisionMs: asNumber(value.decisionMs),
    decisionTraceId: asNullableText(value.decisionTraceId),
    reused: value.reused === true,
  };
}

function readTurnTimings(raw: unknown): ModelRoutingTurnTiming[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((entry, index) => {
      if (!entry || typeof entry !== "object") return null;
      const value = entry as Record<string, unknown>;
      return {
        turn: typeof value.turn === "number" ? value.turn : index + 1,
        startMs: asNumber(value.startMs),
        durationMs: asNumber(value.durationMs),
        model: asNullableText(value.model),
        provider: asNullableText(value.provider),
        promptTokens: asNullableNumber(value.promptTokens),
        completionTokens: asNullableNumber(value.completionTokens),
        totalTokens: asNullableNumber(value.totalTokens),
        textChars: asNullableNumber(value.textChars),
        toolCalls: asNullableNumber(value.toolCalls),
        error: asNullableText(value.error),
      };
    })
    .filter((entry): entry is ModelRoutingTurnTiming => entry !== null);
}

/** Pull the routing block off a trace response, or null when nothing routed. */
export function readTraceModelRouting(
  response: Record<string, unknown> | null | undefined,
): ModelRoutingTrace | null {
  const raw = response?.model_routing;
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  const routerLabel = asNullableText(value.routerLabel);
  if (routerLabel === null || !Array.isArray(value.calls)) return null;

  const calls = value.calls
    .map((call, index) => readCall(call, index))
    .filter((call): call is ModelRoutingTraceCall => call !== null);
  if (calls.length === 0) return null;

  return {
    routerLabel,
    routerCredentialId: String(value.routerCredentialId ?? ""),
    decisionModel: asNullableText(value.decisionModel),
    // Trust the stored total, but fall back to the sum so an older trace still adds up.
    decisionTotalMs:
      asNumber(value.decisionTotalMs) ||
      calls.reduce((total, call) => total + call.decisionMs, 0),
    calls,
    turnTimings: readTurnTimings(value.turnTimings),
  };
}

/** `Fast → gpt-4o-mini`, or just the model when the option has no name. */
export function formatRoutingCallLabel(call: ModelRoutingTraceCall): string {
  return call.option ? `${call.option} → ${call.model}` : call.model;
}
