import { describe, expect, it } from "vitest";

import { buildTraceSpans, hasToolCallArguments, summarizeTraceTokens } from "@/lib/traceSpans";
import type { LLMTraceDetail } from "@/types/trace";

function makeTrace(response: Record<string, unknown>, elapsedMs = 10856): LLMTraceDetail {
  return {
    id: "trace-1",
    created_at: "2026-09-23T17:17:56Z",
    source: "dashboard_chat",
    request_type: "chat.completions",
    provider: "Custom",
    model: "qwen3.8-flash",
    credential_id: null,
    credential_name: null,
    workflow_id: null,
    workflow_name: null,
    node_id: null,
    node_label: "Dashboard Chat",
    status: "success",
    elapsed_ms: elapsedMs,
    prompt_tokens: 300,
    completion_tokens: 30,
    total_tokens: 330,
    cost_usd: null,
    is_priced: false,
    request: {},
    response,
    error: null,
  };
}

const chatResponse = {
  text: "Here are your runs.",
  elapsed_ms: 10856,
  turn_timings: [
    { turn: 1, startMs: 402.64, durationMs: 6009, toolCalls: 1 },
    { turn: 2, startMs: 6500, durationMs: 4700, toolCalls: 0 },
  ],
  tool_calls: [
    {
      tool_call_id: "call-1",
      name: "get_recent_executions",
      arguments: { limit: 30 },
      start_ms: 6411,
      elapsed_ms: 80,
    },
  ],
};

const routing = {
  routerLabel: "model-router",
  routerCredentialId: "router-1",
  decisionModel: "jev-latest",
  decisionTotalMs: 402.64,
  calls: [{ turn: 1, model: "qwen3.8-flash", option: "fast-json", decisionMs: 402.64 }],
};

describe("buildTraceSpans for a chat turn", () => {
  it("lays routing, each model call and the tool out in the order they ran", () => {
    const spans = buildTraceSpans(makeTrace({ ...chatResponse, model_routing: routing }));

    expect(spans.map((span) => span.id)).toEqual([
      "invocation",
      "model_router_turn_1",
      "call_llm_turn_1",
      "tool_0",
      "call_llm_turn_2",
    ]);
    expect(spans[0].durationMs).toBe(11200);
  });

  it("shows the model calls around the tool when nothing routed", () => {
    const spans = buildTraceSpans(makeTrace(chatResponse));

    expect(spans.map((span) => span.id)).toEqual([
      "invocation",
      "call_llm_turn_1",
      "tool_0",
      "call_llm_turn_2",
    ]);
    expect(spans.find((span) => span.id === "tool_0")?.stepId).toBe("tool-call-1");
  });

  it("carries each model call's tokens so the row can show them on hover", () => {
    const spans = buildTraceSpans(
      makeTrace({
        ...chatResponse,
        turn_timings: [
          { turn: 1, startMs: 402.64, durationMs: 6009, promptTokens: 41083, completionTokens: 1541 },
          { turn: 2, startMs: 6500, durationMs: 4700 },
        ],
      }),
    );

    expect(spans.find((span) => span.id === "call_llm_turn_1")?.usage).toEqual({
      promptTokens: 41083,
      completionTokens: 1541,
    });
    expect(spans.find((span) => span.id === "call_llm_turn_2")?.usage).toBeUndefined();
  });

  it("shows what the whole invocation and each routing decision spent", () => {
    const spans = buildTraceSpans(
      makeTrace({
        ...chatResponse,
        model_routing: {
          ...routing,
          calls: [
            {
              ...routing.calls[0],
              decisionPromptTokens: 412,
              decisionCompletionTokens: 9,
            },
          ],
        },
      }),
    );

    // The trace's own 300 in / 30 out, with the 412 in / 9 out the router spent beside it.
    expect(spans.find((span) => span.id === "invocation")?.usage).toEqual({
      promptTokens: 300,
      completionTokens: 30,
      router: { promptTokens: 412, completionTokens: 9 },
    });
    expect(spans.find((span) => span.id === "model_router_turn_1")?.usage).toEqual({
      promptTokens: 412,
      completionTokens: 9,
    });
  });

  it("lists what each model call used on the invocation row of a multi-turn request", () => {
    const spans = buildTraceSpans(
      makeTrace({
        ...chatResponse,
        turn_timings: [
          { turn: 1, startMs: 402.64, durationMs: 6009, promptTokens: 20593, completionTokens: 269 },
          { turn: 2, startMs: 6500, durationMs: 4700, promptTokens: 20490, completionTokens: 1272 },
        ],
      }),
    );

    expect(spans.find((span) => span.id === "invocation")?.usage?.turns).toEqual([
      { turn: 1, promptTokens: 20593, completionTokens: 269 },
      { turn: 2, promptTokens: 20490, completionTokens: 1272 },
    ]);
  });

  it("keeps routing out of the turn rows, which show only what each model call took and gave", () => {
    const spans = buildTraceSpans(
      makeTrace({
        ...chatResponse,
        turn_timings: [
          { turn: 1, startMs: 402.64, durationMs: 6009, promptTokens: 20593, completionTokens: 269 },
          { turn: 2, startMs: 6500, durationMs: 4700, promptTokens: 20490, completionTokens: 1272 },
        ],
        model_routing: {
          ...routing,
          calls: [
            { ...routing.calls[0], decisionPromptTokens: 412, decisionCompletionTokens: 9 },
          ],
        },
      }),
    );

    // The router's 412 in is on the invocation row, not in any turn.
    expect(spans.find((span) => span.id === "invocation")?.usage?.turns).toEqual([
      { turn: 1, promptTokens: 20593, completionTokens: 269 },
      { turn: 2, promptTokens: 20490, completionTokens: 1272 },
    ]);
  });

  it("skips the per-turn list when there is only one model call to show", () => {
    const spans = buildTraceSpans(
      makeTrace({
        ...chatResponse,
        turn_timings: [
          { turn: 1, startMs: 402.64, durationMs: 6009, promptTokens: 20593, completionTokens: 269 },
          { turn: 2, startMs: 6500, durationMs: 4700 },
        ],
      }),
    );

    expect(spans.find((span) => span.id === "invocation")?.usage?.turns).toBeUndefined();
  });

  it("leaves a routing row without usage when the decision model reported none", () => {
    const spans = buildTraceSpans(makeTrace({ ...chatResponse, model_routing: routing }));

    expect(spans.find((span) => span.id === "model_router_turn_1")?.usage).toBeUndefined();
  });

  it("sums the decisions into one routing row when there are no turn timings", () => {
    const spans = buildTraceSpans(
      makeTrace(
        {
          text: "done",
          elapsed_ms: 120,
          model_routing: {
            ...routing,
            calls: [
              { turn: 1, model: "a", decisionMs: 20, decisionPromptTokens: 100, decisionCompletionTokens: 4 },
              { turn: 2, model: "b", decisionMs: 15, decisionPromptTokens: 80 },
            ],
          },
        },
        120,
      ),
    );

    expect(spans.find((span) => span.id === "model_router")?.usage).toEqual({
      promptTokens: 180,
      completionTokens: 4,
    });
    // Routing is counted on the invocation row even with no model tokens of its own.
    expect(spans.find((span) => span.id === "invocation")?.usage?.router).toEqual({
      promptTokens: 180,
      completionTokens: 4,
    });
  });

  it("keeps the aggregate rows for a trace without turn timings", () => {
    const spans = buildTraceSpans(
      makeTrace({
        text: "done",
        elapsed_ms: 120,
        tool_calls: [{ tool_call_id: "call-1", name: "lookup", arguments: {}, elapsed_ms: 40 }],
      }, 120),
    );

    expect(spans.map((span) => span.id)).toEqual(["invocation", "call_llm", "tool_0"]);
  });
});

describe("summarizeTraceTokens", () => {
  it("counts the input of routing decisions in the total and the input side", () => {
    const summary = summarizeTraceTokens(
      makeTrace({
        ...chatResponse,
        model_routing: {
          ...routing,
          calls: [
            { ...routing.calls[0], decisionPromptTokens: 412, decisionCompletionTokens: 9 },
          ],
        },
      }),
    );

    // 300 in / 30 out / 330 total on the trace, plus the router's 412 in; its 9 out is free.
    expect(summary).toEqual({
      total: 742,
      promptTokens: 712,
      completionTokens: 30,
      routerPromptTokens: 412,
    });
  });

  it("leaves the trace's own figures alone when nothing routed", () => {
    expect(summarizeTraceTokens(makeTrace(chatResponse))).toEqual({
      total: 330,
      promptTokens: 300,
      completionTokens: 30,
      routerPromptTokens: 0,
    });
  });

  it("keeps an unreported figure unreported", () => {
    const trace = { ...makeTrace(chatResponse), total_tokens: null, prompt_tokens: null };

    expect(summarizeTraceTokens(trace)).toMatchObject({ total: null, promptTokens: null });
  });
});

describe("hasToolCallArguments", () => {
  it("treats a call made with nothing as having no arguments", () => {
    for (const empty of [undefined, null, {}, [], "", "  ", "{}"]) {
      expect(hasToolCallArguments(empty)).toBe(false);
    }
  });

  it("keeps any recorded argument, falsy values included", () => {
    for (const value of [{ limit: 30 }, { flag: false }, ["a"], '{"limit":30}', 0]) {
      expect(hasToolCallArguments(value)).toBe(true);
    }
  });
});
