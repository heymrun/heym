import { describe, expect, it } from "vitest";

import { buildTraceSpans } from "@/lib/traceSpans";
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
