import { describe, expect, it } from "vitest";

import { buildTraceSteps } from "@/lib/traceSteps";
import type { LLMTraceDetail } from "@/types/trace";

function makeTrace(overrides: Partial<LLMTraceDetail> = {}): LLMTraceDetail {
  return {
    id: "trace-1",
    created_at: "2026-07-24T00:00:00Z",
    source: "workflow",
    request_type: "chat.completions",
    provider: "openai",
    model: "gpt-4o",
    credential_id: null,
    credential_name: null,
    workflow_id: null,
    workflow_name: null,
    node_id: "agent-1",
    node_label: "Agent",
    status: "success",
    elapsed_ms: 120,
    prompt_tokens: 10,
    completion_tokens: 5,
    total_tokens: 15,
    cost_usd: null,
    is_priced: false,
    request: {
      messages: [
        { role: "user", content: "run tools" },
        {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              id: "call-1",
              type: "function",
              function: { name: "lookup", arguments: '{"q":"x"}' },
            },
          ],
        },
        { role: "tool", tool_call_id: "call-1", content: '{"ok":true}' },
      ],
    },
    response: {
      text: "done",
      elapsed_ms: 120,
      tool_calls: [
        {
          tool_call_id: "call-1",
          name: "lookup",
          status: "pending",
          elapsed_ms: 40,
        },
      ],
      tool_metrics: {
        count: 2,
        success: 1,
        error: 0,
        pending: 1,
        timeout: 0,
        cancelled: 0,
        total_duration_ms: 55,
      },
    },
    error: null,
    ...overrides,
  };
}

describe("buildTraceSteps agent tool observability", () => {
  it("adds pending/timeout/cancelled badges on tool steps", () => {
    const pending = buildTraceSteps(makeTrace());
    const pendingTool = pending.find((step) => step.kind === "tool");
    expect(pendingTool?.badges?.some((badge) => badge.label === "Pending review")).toBe(true);
    expect(pendingTool?.isError).toBe(false);

    const timeout = buildTraceSteps(
      makeTrace({
        response: {
          text: "done",
          tool_calls: [{ tool_call_id: "call-1", name: "lookup", status: "timeout", elapsed_ms: 40 }],
        },
      }),
    );
    const timeoutTool = timeout.find((step) => step.kind === "tool");
    expect(timeoutTool?.badges?.some((badge) => badge.label === "Timeout")).toBe(true);
    expect(timeoutTool?.isError).toBe(true);

    const cancelled = buildTraceSteps(
      makeTrace({
        response: {
          text: "done",
          tool_calls: [
            { tool_call_id: "call-1", name: "lookup", status: "cancelled", elapsed_ms: 40 },
          ],
        },
      }),
    );
    const cancelledTool = cancelled.find((step) => step.kind === "tool");
    expect(cancelledTool?.badges?.some((badge) => badge.label === "Cancelled")).toBe(true);
  });

  it("surfaces tool_metrics on the answer step", () => {
    const steps = buildTraceSteps(makeTrace());
    const answer = steps.find((step) => step.kind === "answer");

    expect(answer?.badges?.map((badge) => badge.label)).toEqual(
      expect.arrayContaining(["2 tools", "1 ok", "1 pending", "55ms tools"]),
    );
    expect(answer?.json).toEqual(
      expect.objectContaining({
        tool_metrics: expect.objectContaining({ count: 2, pending: 1 }),
      }),
    );
  });
});

describe("model router steps", () => {
  function routedTrace(calls: unknown[], messages?: unknown[]): LLMTraceDetail {
    return makeTrace({
      request: {
        messages: messages ?? [
          { role: "user", content: "hello" },
          { role: "assistant", content: "the reply" },
        ],
      },
      response: {
        text: "hi",
        model_routing: {
          routerLabel: "Auto Model",
          routerCredentialId: "router-1",
          decisionModel: "jev-latest",
          decisionTotalMs: 41.5,
          calls,
        },
      },
    });
  }

  const call = (overrides: Record<string, unknown> = {}) => ({
    turn: 1,
    model: "gpt-4o-mini",
    option: "Fast",
    credentialName: "OpenAI prod",
    fallback: false,
    error: null,
    decisionMs: 41.5,
    decisionTraceId: "decision-1",
    reused: false,
    ...overrides,
  });

  it("places the routing decision immediately before the reply it produced", () => {
    const steps = buildTraceSteps(routedTrace([call()]));
    const routerIndex = steps.findIndex((step) => step.id === "model_router_turn_1");

    expect(routerIndex).toBeGreaterThanOrEqual(0);
    expect(steps[routerIndex].roleLabel).toBe("Model Router");
    expect(steps[routerIndex].summary).toBe("Fast → gpt-4o-mini");
    expect(steps[routerIndex].durationMs).toBe(41.5);
    // It sits next to the assistant turn it decided, not in a block at the top.
    expect(steps[routerIndex + 1].kind).toBe("assistant");
  });

  it("puts each turn's decision next to that turn, not stacked together", () => {
    const steps = buildTraceSteps(
      routedTrace([call(), call({ turn: 2, model: "gpt-5", option: "Deep" })], [
        { role: "user", content: "hello" },
        { role: "assistant", content: "first reply" },
        { role: "user", content: "and again" },
        { role: "assistant", content: "second reply" },
      ]),
    );
    const ids = steps.map((step) => step.id);
    const firstRouter = ids.indexOf("model_router_turn_1");
    const secondRouter = ids.indexOf("model_router_turn_2");

    expect(firstRouter).toBeGreaterThanOrEqual(0);
    expect(secondRouter).toBeGreaterThan(firstRouter + 1);
    expect(steps[firstRouter + 1].summary).toBe("first reply");
    expect(steps[secondRouter + 1].summary).toBe("second reply");
    expect(steps[firstRouter].roleLabel).toBe("Model Router · turn 1");
    expect(steps[secondRouter].roleLabel).toBe("Model Router · turn 2");
  });

  it("still shows a decision whose turn left no stored reply", () => {
    const steps = buildTraceSteps(
      routedTrace([call(), call({ turn: 2, model: "gpt-5", option: "Deep" })], [
        { role: "user", content: "hello" },
        { role: "assistant", content: "only reply" },
      ]),
    );

    expect(steps.map((step) => step.id)).toContain("model_router_turn_2");
  });

  it("marks a reused decision and gives it no duration", () => {
    const steps = buildTraceSteps(
      routedTrace([call(), call({ turn: 2, reused: true, decisionMs: 0 })]),
    );
    const reused = steps.find((step) => step.id === "model_router_turn_2");

    expect(reused?.badges?.map((badge) => badge.label)).toContain("reused");
    expect(reused?.durationMs).toBeUndefined();
  });

  it("flags a fallback decision as an error with its reason", () => {
    const steps = buildTraceSteps(
      routedTrace([call({ fallback: true, error: "Decision model timed out" })]),
    );
    const router = steps.find((step) => step.id === "model_router_turn_1");

    expect(router?.isError).toBe(true);
    expect(router?.badges?.map((badge) => badge.label)).toContain("fallback");
    expect(router?.detail).toContain("Decision model timed out");
  });

  it("adds nothing when the request did not route", () => {
    const plain = makeTrace({
      request: { messages: [{ role: "user", content: "hello" }] },
      response: { text: "hi" },
    });

    expect(buildTraceSteps(plain).some((step) => step.id.startsWith("model_router"))).toBe(false);
  });
});

describe("answer placement with routing", () => {
  const call = (overrides: Record<string, unknown> = {}) => ({
    turn: 1,
    model: "gpt-4o-mini",
    option: "fast-json",
    credentialName: "OpenAI prod",
    fallback: false,
    error: null,
    startMs: 0,
    decisionMs: 1050,
    decisionTraceId: "decision-1",
    reused: false,
    ...overrides,
  });

  function orchestratorTrace(): LLMTraceDetail {
    // One assistant turn that only called tools, then a final answer from turn 2.
    return makeTrace({
      request: {
        messages: [
          { role: "system", content: "You are a coordinator." },
          { role: "user", content: "Frankfurt" },
          {
            role: "assistant",
            content: "",
            tool_calls: [
              {
                id: "call-1",
                type: "function",
                function: { name: "call_sub_agent", arguments: '{"a":1}' },
              },
            ],
          },
          { role: "tool", tool_call_id: "call-1", content: "sub agent result" },
        ],
      },
      response: {
        text: "Frankfurt Travel Guide",
        model_routing: {
          routerLabel: "model-router",
          routerCredentialId: "router-1",
          decisionModel: "jev-latest",
          decisionTotalMs: 1694,
          calls: [call(), call({ turn: 2, model: "glm-5.3-flash", option: "creative", decisionMs: 644 })],
          turnTimings: [],
        },
      },
    });
  }

  it("keeps the answer last even when a turn left no stored reply", () => {
    const steps = buildTraceSteps(orchestratorTrace());

    expect(steps[steps.length - 1].kind).toBe("answer");
  });

  it("puts the final turn's decision immediately before the answer", () => {
    const steps = buildTraceSteps(orchestratorTrace());
    const ids = steps.map((step) => step.id);
    const answerIndex = ids.indexOf("answer");

    expect(ids[answerIndex - 1]).toBe("model_router_turn_2");
    expect(ids.indexOf("model_router_turn_1")).toBeLessThan(answerIndex - 1);
  });

  it("carries the decision trace id so the row can link to it", () => {
    const steps = buildTraceSteps(orchestratorTrace());
    const router = steps.find((step) => step.id === "model_router_turn_1");

    expect((router?.json as { decisionTraceId?: string }).decisionTraceId).toBe("decision-1");
  });
});

describe("per-turn LLM steps", () => {
  const call = (overrides: Record<string, unknown> = {}) => ({
    turn: 1,
    model: "qwen3.8-flash",
    option: "fast-json",
    credentialName: "opencode",
    fallback: false,
    error: null,
    startMs: 0,
    decisionMs: 1064,
    decisionTraceId: "decision-1",
    reused: false,
    ...overrides,
  });

  function orchestratorTrace(): LLMTraceDetail {
    return makeTrace({
      request: {
        messages: [
          { role: "system", content: "You are a coordinator." },
          { role: "user", content: "Frankfurt" },
          {
            role: "assistant",
            content: "",
            tool_calls: [
              {
                id: "call-1",
                type: "function",
                function: { name: "call_sub_agent", arguments: '{"a":1}' },
              },
            ],
          },
          { role: "tool", tool_call_id: "call-1", content: "sub agent result" },
        ],
      },
      response: {
        text: "Your Frankfurt Trip Guide",
        model_routing: {
          routerLabel: "model-router",
          routerCredentialId: "router-1",
          decisionModel: "jev-1.13.0",
          decisionTotalMs: 2143,
          calls: [
            call(),
            call({ turn: 2, model: "glm-5.3-flash", option: "creative", decisionMs: 1079 }),
          ],
          turnTimings: [
            { turn: 1, startMs: 1064, durationMs: 6753 },
            { turn: 2, startMs: 50000, durationMs: 27717 },
          ],
        },
      },
    });
  }

  it("shows the model call right after the decision that picked it", () => {
    const ids = buildTraceSteps(orchestratorTrace()).map((step) => step.id);

    expect(ids.indexOf("call_llm_turn_1")).toBe(ids.indexOf("model_router_turn_1") + 1);
    expect(ids.indexOf("call_llm_turn_2")).toBe(ids.indexOf("model_router_turn_2") + 1);
  });

  it("puts turn 1's model call before the tools that call produced", () => {
    const ids = buildTraceSteps(orchestratorTrace()).map((step) => step.id);
    const firstTool = ids.findIndex((id) => id.startsWith("tool-"));

    expect(firstTool).toBeGreaterThan(ids.indexOf("call_llm_turn_1"));
  });

  it("keeps the answer last with the final turn's call just before it", () => {
    const steps = buildTraceSteps(orchestratorTrace());
    const ids = steps.map((step) => step.id);

    expect(steps[steps.length - 1].kind).toBe("answer");
    expect(ids[ids.indexOf("answer") - 1]).toBe("call_llm_turn_2");
  });

  it("names the model and how long it ran", () => {
    const steps = buildTraceSteps(orchestratorTrace());
    const llm = steps.find((step) => step.id === "call_llm_turn_1");

    expect(llm?.roleLabel).toBe("LLM · turn 1");
    expect(llm?.summary).toBe("qwen3.8-flash");
    expect(llm?.durationMs).toBe(6753);
    expect(llm?.detail).toContain("opencode");
  });

  it("adds no model-call step when the trace has no turn timings", () => {
    const trace = orchestratorTrace();
    (trace.response as Record<string, unknown>).model_routing = {
      ...((trace.response as Record<string, unknown>).model_routing as object),
      turnTimings: [],
    };

    expect(
      buildTraceSteps(trace).some((step) => step.id.startsWith("call_llm_turn_")),
    ).toBe(false);
  });
});

describe("per-turn LLM step detail", () => {
  function tracedTurn(timing: Record<string, unknown>): LLMTraceDetail {
    return makeTrace({
      request: {
        messages: [
          { role: "user", content: "hello" },
          { role: "assistant", content: "the reply" },
        ],
      },
      response: {
        text: "the reply",
        model_routing: {
          routerLabel: "model-router",
          routerCredentialId: "router-1",
          decisionModel: "jev-1.13.0",
          decisionTotalMs: 1064,
          calls: [
            {
              turn: 1,
              model: "qwen3.8-flash",
              option: "fast-json",
              credentialName: "opencode",
              fallback: false,
              error: null,
              startMs: 0,
              decisionMs: 1064,
              decisionTraceId: "decision-1",
              reused: false,
            },
          ],
          turnTimings: [timing],
        },
      },
    });
  }

  function llmStep(timing: Record<string, unknown>) {
    return buildTraceSteps(tracedTurn(timing)).find((step) => step.id === "call_llm_turn_1");
  }

  it("reports tokens, provider, tools and offset", () => {
    const step = llmStep({
      turn: 1,
      startMs: 1921.73,
      durationMs: 6103,
      model: "qwen3.8-flash",
      provider: "Custom",
      promptTokens: 1200,
      completionTokens: 340,
      totalTokens: 1540,
      textChars: 812,
      toolCalls: 2,
    });

    expect(step?.tokens).toBe(1540);
    expect(step?.detail).toContain("1200 in / 340 out");
    expect(step?.detail).toContain("Requested 2 tool calls");
    expect(step?.detail).toContain("Returned 812 characters");
    expect(step?.detail).toContain("1922 ms into the request");
    expect(step?.badges?.map((badge) => badge.label)).toEqual(["Custom", "2 tools"]);
  });

  it("says plainly when a turn requested no tools", () => {
    const step = llmStep({ turn: 1, startMs: 0, durationMs: 10, toolCalls: 0 });

    expect(step?.detail).toContain("Requested no tools");
    expect(step?.badges).toBeUndefined();
  });

  it("marks a failed turn with its reason", () => {
    const step = llmStep({
      turn: 1,
      startMs: 0,
      durationMs: 10,
      error: "provider returned 500",
    });

    expect(step?.isError).toBe(true);
    expect(step?.detail).toContain("provider returned 500");
  });
});

describe("event json hides unrecorded fields", () => {
  function tracedTurn(timing: Record<string, unknown>): LLMTraceDetail {
    return makeTrace({
      request: {
        messages: [
          { role: "user", content: "hello" },
          { role: "assistant", content: "the reply" },
        ],
      },
      response: {
        text: "the reply",
        model_routing: {
          routerLabel: "model-router",
          routerCredentialId: "router-1",
          decisionModel: "jev-1.13.0",
          decisionTotalMs: 1064,
          calls: [
            {
              turn: 1,
              model: "qwen3.8-flash",
              option: "fast-json",
              credentialName: null,
              fallback: false,
              error: null,
              startMs: 0,
              decisionMs: 1064,
              decisionTraceId: null,
              reused: false,
            },
          ],
          turnTimings: [timing],
        },
      },
    });
  }

  it("drops null fields from a model call record", () => {
    const steps = buildTraceSteps(
      tracedTurn({ turn: 1, startMs: 0, durationMs: 6103, model: "qwen3.8-flash" }),
    );
    const json = steps.find((step) => step.id === "call_llm_turn_1")?.json as Record<
      string,
      unknown
    >;

    expect(Object.keys(json)).toEqual(["turn", "startMs", "durationMs", "model"]);
    expect(json).not.toHaveProperty("provider");
    expect(json).not.toHaveProperty("totalTokens");
  });

  it("drops null fields from a routing record but keeps the false ones", () => {
    const steps = buildTraceSteps(
      tracedTurn({ turn: 1, startMs: 0, durationMs: 10 }),
    );
    const json = steps.find((step) => step.id === "model_router_turn_1")?.json as Record<
      string,
      unknown
    >;

    expect(json).not.toHaveProperty("credentialName");
    expect(json).not.toHaveProperty("decisionTraceId");
    // `false` is a recorded fact, unlike `null`, so it stays.
    expect(json.fallback).toBe(false);
    expect(json.reused).toBe(false);
  });
});
