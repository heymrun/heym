import type { LLMTraceDetail } from "@/types/trace";

import {
  formatRoutingCallLabel,
  readTraceModelRouting,
  readTraceTurnTimings,
  type ModelRoutingTrace,
  type ModelRoutingTraceCall,
  type ModelRoutingTurnTiming,
} from "@/lib/traceModelRouting";

export type TraceStepKind =
  | "system"
  | "user"
  | "assistant"
  | "tool"
  | "answer"
  | "request"
  | "response";

export interface TraceStepBadge {
  label: string;
}

export interface TraceStep {
  id: string;
  kind: TraceStepKind;
  icon: TraceStepKind;
  roleLabel: string;
  summary: string;
  detail?: string;
  detailIsMarkdown?: boolean;
  argumentsText?: string;
  resultText?: string;
  json: unknown;
  durationMs?: number;
  tokens?: number;
  isError?: boolean;
  badges?: TraceStepBadge[];
}

interface RawToolCall {
  id?: string;
  type?: string;
  function?: { name?: string; arguments?: string };
}

interface RawMessage {
  role?: string;
  content?: unknown;
  tool_calls?: RawToolCall[];
  tool_call_id?: string;
}

/** One model call of the request, with the routing decision that picked it. */
interface TurnBlock {
  turn: number;
  /** How many tools that call asked for; null when the trace did not record it. */
  toolCalls: number | null;
  steps: TraceStep[];
}

/** Where each turn's steps go among the stored messages. */
interface TurnPlacement {
  /** Steps emitted just before the assistant message at that index. */
  beforeMessage: Map<number, TraceStep[]>;
  /** Steps of the call that produced the answer, and of any call no message holds. */
  beforeAnswer: TraceStep[];
}

interface RawResponseToolCall {
  id?: string;
  tool_call_id?: string;
  name?: string;
  arguments?: unknown;
  result?: unknown;
  elapsed_ms?: number;
  source?: string;
  mcp_server?: string;
  workflow_name?: string;
  status?: string;
}

/**
 * The routing reader fills every field, using null for "not recorded". Those nulls
 * are an artefact of that shape, not facts about the run, so they are dropped before
 * the record reaches the Event JSON panel.
 */
function withoutNulls(value: object): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(value).filter(([, entry]) => entry !== null && entry !== undefined),
  );
}

const SUMMARY_MAX = 140;
const ARGS_SUMMARY_MAX = 80;

function asText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part;
        if (part && typeof part === "object" && "text" in part) {
          const text = (part as { text?: unknown }).text;
          return typeof text === "string" ? text : "";
        }
        return "";
      })
      .join(" ")
      .trim();
  }
  if (content == null) return "";
  return safeStringify(content);
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function safeJsonCompact(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function summarize(text: string, max = SUMMARY_MAX): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  if (collapsed.length <= max) return collapsed;
  return `${collapsed.slice(0, max - 1).trimEnd()}…`;
}

function buildToolStep(
  msgIndex: number,
  tcIndex: number,
  rawCall: RawToolCall,
  enriched: RawResponseToolCall | undefined,
  toolResultById: Map<string, RawMessage>,
  workflowNames: Record<string, string>,
): TraceStep {
  const name = rawCall.function?.name ?? "tool";
  const argsRaw = rawCall.function?.arguments;

  let argsObj: unknown;
  if (typeof argsRaw === "string" && argsRaw.length > 0) {
    try {
      argsObj = JSON.parse(argsRaw);
    } catch {
      argsObj = argsRaw;
    }
  } else if (enriched?.arguments !== undefined) {
    argsObj = enriched.arguments;
  }

  // Resolve the executed workflow (for workflow-execution tools), so the step
  // can show the workflow's name rather than just an opaque id.
  let workflowId: string | undefined;
  if (argsObj && typeof argsObj === "object" && !Array.isArray(argsObj)) {
    const wid = (argsObj as Record<string, unknown>).workflow_id;
    if (typeof wid === "string" && wid.trim()) {
      workflowId = wid.trim();
    }
  }
  const workflowName =
    (typeof enriched?.workflow_name === "string" && enriched.workflow_name.trim()
      ? enriched.workflow_name.trim()
      : undefined) ?? (workflowId ? workflowNames[workflowId] : undefined);

  let resultValue: unknown;
  const id = rawCall.id;
  if (id && toolResultById.has(id)) {
    resultValue = toolResultById.get(id)?.content;
  } else if (enriched?.result !== undefined) {
    resultValue = enriched.result;
  }

  const badges: TraceStepBadge[] = [];
  if (enriched?.source === "mcp") {
    badges.push({ label: enriched.mcp_server ? `MCP: ${enriched.mcp_server}` : "MCP" });
  } else if (enriched?.source === "skill") {
    badges.push({ label: "Skill" });
  }
  if (workflowName) {
    badges.push({ label: `Workflow: ${workflowName}` });
  } else if (workflowId) {
    badges.push({ label: `Workflow: ${workflowId.slice(0, 8)}…` });
  }
  if (enriched?.status === "pending") {
    badges.push({ label: "Pending review" });
  } else if (enriched?.status === "timeout") {
    badges.push({ label: "Timeout" });
  } else if (enriched?.status === "cancelled") {
    badges.push({ label: "Cancelled" });
  }

  const argsCompact =
    argsObj === undefined ? "" : typeof argsObj === "string" ? argsObj : safeJsonCompact(argsObj);
  const argumentsText =
    argsObj === undefined
      ? undefined
      : typeof argsObj === "string"
        ? argsObj
        : safeStringify(argsObj);
  const resultText =
    resultValue === undefined
      ? undefined
      : typeof resultValue === "string"
        ? resultValue
        : safeStringify(resultValue);

  return {
    id: id ? `tool-${id}` : `tool-${msgIndex}-${tcIndex}`,
    kind: "tool",
    icon: "tool",
    roleLabel: `Tool · ${name}`,
    summary: argsCompact ? `${name}(${summarize(argsCompact, ARGS_SUMMARY_MAX)})` : `${name}()`,
    argumentsText,
    resultText,
    json: {
      ...(rawCall as Record<string, unknown>),
      ...(enriched ? { _response: enriched } : {}),
      ...(resultValue !== undefined ? { result: resultValue } : {}),
    },
    durationMs: typeof enriched?.elapsed_ms === "number" ? enriched.elapsed_ms : undefined,
    isError: enriched?.status === "error" || enriched?.status === "timeout",
    badges: badges.length > 0 ? badges : undefined,
  };
}

/**
 * Put each turn right before the reply it produced.
 *
 * When the trace records how many tools each call asked for, the run's tool-calling
 * replies are the last ones stored, so turns are matched from the end and earlier
 * conversation history stays untouched. Older traces fall back to one stored reply
 * per turn, in order. The call that answered sits just before the answer.
 */
function placeTurnBlocks(messages: RawMessage[], blocks: TurnBlock[]): TurnPlacement {
  const beforeMessage = new Map<number, TraceStep[]>();
  const assistantIndexes = messages.flatMap((msg, index) =>
    msg.role === "assistant" ? [index] : [],
  );

  if (blocks.some((block) => block.toolCalls !== null)) {
    const toolBlocks = blocks.filter((block) => (block.toolCalls ?? 0) > 0);
    const answerSteps = blocks
      .filter((block) => (block.toolCalls ?? 0) === 0)
      .flatMap((block) => block.steps);
    const toolMessages = assistantIndexes.filter(
      (index) => (messages[index].tool_calls?.length ?? 0) > 0,
    );
    const matched = Math.min(toolBlocks.length, toolMessages.length);
    // Calls whose reply is no longer stored still ran first, so they lead.
    const unmatchedSteps = toolBlocks
      .slice(0, toolBlocks.length - matched)
      .flatMap((block) => block.steps);
    toolBlocks.slice(toolBlocks.length - matched).forEach((block, i) => {
      const index = toolMessages[toolMessages.length - matched + i];
      beforeMessage.set(index, i === 0 ? [...unmatchedSteps, ...block.steps] : block.steps);
    });
    return {
      beforeMessage,
      beforeAnswer: matched === 0 ? [...unmatchedSteps, ...answerSteps] : answerSteps,
    };
  }

  blocks.slice(0, assistantIndexes.length).forEach((block, i) => {
    beforeMessage.set(assistantIndexes[i], block.steps);
  });
  return {
    beforeMessage,
    beforeAnswer: blocks.slice(assistantIndexes.length).flatMap((block) => block.steps),
  };
}

function buildConversationSteps(
  messages: RawMessage[],
  response: Record<string, unknown>,
  trace: LLMTraceDetail,
  workflowNames: Record<string, string>,
  turnBlocks: TurnBlock[] = [],
): TraceStep[] {
  const steps: TraceStep[] = [];
  const placement = placeTurnBlocks(messages, turnBlocks);

  const toolResultById = new Map<string, RawMessage>();
  for (const msg of messages) {
    if (msg.role === "tool" && typeof msg.tool_call_id === "string") {
      toolResultById.set(msg.tool_call_id, msg);
    }
  }

  const pool = Array.isArray(response.tool_calls)
    ? (response.tool_calls as RawResponseToolCall[]).map((tc) => ({ tc, used: false }))
    : [];

  function matchResponseToolCall(
    name: string,
    id: string | undefined,
  ): RawResponseToolCall | undefined {
    if (id) {
      const byId = pool.find((e) => !e.used && (e.tc.id === id || e.tc.tool_call_id === id));
      if (byId) {
        byId.used = true;
        return byId.tc;
      }
    }
    const byName = pool.find((e) => !e.used && e.tc.name === name);
    if (byName) {
      byName.used = true;
      return byName.tc;
    }
    const next = pool.find((e) => !e.used);
    if (next) {
      next.used = true;
      return next.tc;
    }
    return undefined;
  }

  messages.forEach((msg, index) => {
    if (msg.role === "system") {
      const text = asText(msg.content);
      steps.push({
        id: `msg-${index}`,
        kind: "system",
        icon: "system",
        roleLabel: "System",
        summary: summarize(text) || "System instructions",
        detail: text,
        detailIsMarkdown: true,
        json: msg,
      });
    } else if (msg.role === "user") {
      const text = asText(msg.content);
      steps.push({
        id: `msg-${index}`,
        kind: "user",
        icon: "user",
        roleLabel: "User",
        summary: summarize(text),
        detail: text,
        json: msg,
      });
    } else if (msg.role === "assistant") {
      steps.push(...(placement.beforeMessage.get(index) ?? []));
      const text = asText(msg.content);
      if (text) {
        steps.push({
          id: `msg-${index}`,
          kind: "assistant",
          icon: "assistant",
          roleLabel: "Assistant",
          summary: summarize(text),
          detail: text,
          detailIsMarkdown: true,
          json: { role: msg.role, content: msg.content },
        });
      }
      const toolCalls = Array.isArray(msg.tool_calls) ? msg.tool_calls : [];
      toolCalls.forEach((tc, tcIndex) => {
        const enriched = matchResponseToolCall(tc.function?.name ?? "tool", tc.id);
        steps.push(buildToolStep(index, tcIndex, tc, enriched, toolResultById, workflowNames));
      });
    }
    // msg.role === "tool" is consumed as a tool step's result above.
  });

  // Chat rows recorded before a chat turn became one trace kept the reply in `content`.
  const text =
    typeof response.text === "string"
      ? response.text
      : typeof response.content === "string"
        ? response.content
        : "";
  const error =
    (typeof response.error === "string" && response.error ? response.error : null) ?? trace.error;
  if (text || error) {
    const usage = response.usage as { total_tokens?: number } | undefined;
    const elapsed = typeof response.elapsed_ms === "number" ? response.elapsed_ms : undefined;
    const metrics = response.tool_metrics as
      | {
          count?: number;
          success?: number;
          error?: number;
          pending?: number;
          timeout?: number;
          cancelled?: number;
          total_duration_ms?: number;
        }
      | undefined;
    const answerBadges: TraceStepBadge[] = [];
    if (metrics && typeof metrics.count === "number" && metrics.count > 0) {
      answerBadges.push({ label: `${metrics.count} tools` });
      if (typeof metrics.success === "number" && metrics.success > 0) {
        answerBadges.push({ label: `${metrics.success} ok` });
      }
      if (typeof metrics.error === "number" && metrics.error > 0) {
        answerBadges.push({ label: `${metrics.error} error` });
      }
      if (typeof metrics.timeout === "number" && metrics.timeout > 0) {
        answerBadges.push({ label: `${metrics.timeout} timeout` });
      }
      if (typeof metrics.cancelled === "number" && metrics.cancelled > 0) {
        answerBadges.push({ label: `${metrics.cancelled} cancelled` });
      }
      if (typeof metrics.pending === "number" && metrics.pending > 0) {
        answerBadges.push({ label: `${metrics.pending} pending` });
      }
      if (typeof metrics.total_duration_ms === "number" && metrics.total_duration_ms > 0) {
        answerBadges.push({ label: `${Math.round(metrics.total_duration_ms)}ms tools` });
      }
    }
    steps.push(...placement.beforeAnswer);
    steps.push({
      id: "answer",
      kind: "answer",
      icon: "answer",
      roleLabel: "Answer",
      summary: error ? summarize(`Error: ${error}`) : summarize(text),
      detail: error ? error : text,
      detailIsMarkdown: !error,
      durationMs: elapsed,
      tokens: typeof usage?.total_tokens === "number" ? usage.total_tokens : undefined,
      isError: Boolean(error),
      badges: answerBadges.length > 0 ? answerBadges : undefined,
      json: {
        text,
        model: response.model,
        usage: response.usage,
        elapsed_ms: response.elapsed_ms,
        ...(metrics ? { tool_metrics: metrics } : {}),
        ...(error ? { error } : {}),
      },
    });
  }

  return steps;
}

function buildFallbackSteps(
  trace: LLMTraceDetail,
  request: Record<string, unknown>,
  response: Record<string, unknown>,
): TraceStep[] {
  const hasRequest = Object.keys(request).length > 0;
  const hasResponse = Object.keys(response).length > 0;
  if (!hasRequest && !hasResponse) return [];

  const steps: TraceStep[] = [];
  if (hasRequest) {
    steps.push({
      id: "request",
      kind: "request",
      icon: "request",
      roleLabel: "Request",
      summary: summarize(trace.request_type || "Request"),
      json: request,
    });
  }
  if (hasResponse) {
    const error =
      (typeof response.error === "string" && response.error ? response.error : null) ?? trace.error;
    const text = typeof response.text === "string" ? response.text : "";
    const elapsed = typeof response.elapsed_ms === "number" ? response.elapsed_ms : undefined;
    steps.push({
      id: "response",
      kind: "response",
      icon: "response",
      roleLabel: "Response",
      summary: error ? summarize(`Error: ${error}`) : text ? summarize(text) : trace.status,
      detail: text || undefined,
      detailIsMarkdown: Boolean(text) && !error,
      durationMs: elapsed,
      isError: Boolean(error),
      json: response,
    });
  }
  return steps;
}

export interface BuildTraceStepsOptions {
  /** Map of workflow id → display name, used to label workflow-execution tools. */
  workflowNames?: Record<string, string>;
}

function buildRouterStep(routing: ModelRoutingTrace, call: ModelRoutingTraceCall): TraceStep {
  const badges: TraceStepBadge[] = [{ label: routing.routerLabel }];
  if (call.reused) badges.push({ label: "reused" });
  if (call.fallback) badges.push({ label: "fallback" });

  const detailParts = [`Routed to ${call.model}`];
  if (call.credentialName) detailParts.push(`on ${call.credentialName}`);
  if (call.reused) {
    detailParts.push("Reused the previous decision: the routing input had not changed.");
  }
  if (call.error) detailParts.push(`Routing failed: ${call.error}`);

  return {
    id: `model_router_turn_${call.turn}`,
    kind: "request",
    icon: "request",
    roleLabel: routing.calls.length > 1 ? `Model Router · turn ${call.turn}` : "Model Router",
    summary: formatRoutingCallLabel(call),
    detail: detailParts.join(" · "),
    json: withoutNulls(call),
    durationMs: call.decisionMs > 0 ? call.decisionMs : undefined,
    isError: call.fallback,
    badges,
  };
}

function buildLlmStep(
  timing: ModelRoutingTurnTiming,
  call: ModelRoutingTraceCall | undefined,
  multiTurn: boolean,
): TraceStep {
  const model = timing.model ?? call?.model ?? "model";
  const detailParts = [
    call?.credentialName ? `Called ${model} on ${call.credentialName}` : `Called ${model}`,
  ];
  if (timing.provider) detailParts.push(`Provider: ${timing.provider}`);
  if (timing.promptTokens !== null || timing.completionTokens !== null) {
    detailParts.push(
      `Tokens: ${timing.promptTokens ?? 0} in / ${timing.completionTokens ?? 0} out`,
    );
  }
  if (timing.toolCalls !== null) {
    detailParts.push(
      timing.toolCalls === 0
        ? "Requested no tools"
        : `Requested ${timing.toolCalls} tool call${timing.toolCalls === 1 ? "" : "s"}`,
    );
  }
  if (timing.textChars !== null) detailParts.push(`Returned ${timing.textChars} characters`);
  detailParts.push(`Started ${Math.round(timing.startMs)} ms into the request`);
  if (timing.error) detailParts.push(`Failed: ${timing.error}`);

  const badges: TraceStepBadge[] = [];
  if (timing.provider) badges.push({ label: timing.provider });
  if (timing.toolCalls) {
    badges.push({ label: `${timing.toolCalls} tool${timing.toolCalls === 1 ? "" : "s"}` });
  }

  return {
    id: `call_llm_turn_${timing.turn}`,
    kind: "response",
    icon: "response",
    roleLabel: multiTurn ? `LLM · turn ${timing.turn}` : "LLM",
    summary: model,
    detail: detailParts.join(" · "),
    json: withoutNulls(timing),
    durationMs: timing.durationMs,
    tokens: timing.totalTokens ?? undefined,
    isError: Boolean(timing.error),
    badges: badges.length > 0 ? badges : undefined,
  };
}

/**
 * One block per model call: the routing decision for that turn, if any, then the
 * call itself, so a turn reads as "decided this, then called it".
 */
function buildTurnBlocks(
  routing: ModelRoutingTrace | null,
  timings: ModelRoutingTurnTiming[],
): TurnBlock[] {
  const calls = routing?.calls ?? [];
  const turns = [...new Set([...calls.map((call) => call.turn), ...timings.map((t) => t.turn)])];
  turns.sort((a, b) => a - b);

  return turns
    .map((turn) => {
      const steps: TraceStep[] = [];
      const call = calls.find((entry) => entry.turn === turn);
      if (routing !== null && call) steps.push(buildRouterStep(routing, call));
      const timing = timings.find((entry) => entry.turn === turn);
      if (timing && timing.durationMs > 0) {
        // A turn without a decision of its own ran on the latest one before it.
        const inForce = calls
          .filter((entry) => entry.turn <= turn)
          .reduce<ModelRoutingTraceCall | undefined>(
            (latest, entry) => (latest && latest.turn > entry.turn ? latest : entry),
            undefined,
          );
        steps.push(buildLlmStep(timing, inForce, timings.length > 1));
      }
      return { turn, toolCalls: timing?.toolCalls ?? null, steps };
    })
    .filter((block) => block.steps.length > 0);
}

/** Turn a trace into an ordered list of readable steps for the timeline view. */
export function buildTraceSteps(
  trace: LLMTraceDetail,
  options: BuildTraceStepsOptions = {},
): TraceStep[] {
  const request = (trace.request ?? {}) as Record<string, unknown>;
  const response = (trace.response ?? {}) as Record<string, unknown>;
  const messages = request.messages;
  const workflowNames = options.workflowNames ?? {};

  const turnBlocks = buildTurnBlocks(
    readTraceModelRouting(response),
    readTraceTurnTimings(response),
  );
  const turnSteps = turnBlocks.flatMap((block) => block.steps);

  if (Array.isArray(messages) && messages.length > 0) {
    const steps = buildConversationSteps(
      messages as RawMessage[],
      response,
      trace,
      workflowNames,
      turnBlocks,
    );
    // A turn whose reply is not stored, in a trace with no answer, would otherwise
    // vanish. It belongs before the answer, which always closes the list.
    const placed = new Set(steps.map((step) => step.id));
    const unplaced = turnSteps.filter((step) => !placed.has(step.id));
    if (unplaced.length === 0) return steps;

    const answerIndex = steps.findIndex((step) => step.kind === "answer");
    if (answerIndex === -1) return [...steps, ...unplaced];
    return [
      ...steps.slice(0, answerIndex),
      ...unplaced,
      ...steps.slice(answerIndex),
    ];
  }
  return [...turnSteps, ...buildFallbackSteps(trace, request, response)];
}
