import { describe, expect, it } from "vitest";

import {
  formatRoutingCallLabel,
  readTraceModelRouting,
  type ModelRoutingTraceCall,
} from "./traceModelRouting";

function call(overrides: Partial<ModelRoutingTraceCall> = {}): Record<string, unknown> {
  return {
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
  };
}

function response(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    text: "hi",
    model_routing: {
      routerLabel: "Auto Model",
      routerCredentialId: "router-1",
      decisionModel: "jev-latest",
      decisionTotalMs: 41.5,
      calls: [call()],
      ...overrides,
    },
  };
}

describe("readTraceModelRouting", () => {
  it("reads a routed trace", () => {
    const routing = readTraceModelRouting(response());

    expect(routing?.routerLabel).toBe("Auto Model");
    expect(routing?.decisionModel).toBe("jev-latest");
    expect(routing?.decisionTotalMs).toBe(41.5);
    expect(routing?.calls).toHaveLength(1);
    expect(routing?.calls[0].decisionMs).toBe(41.5);
    expect(routing?.calls[0].decisionTraceId).toBe("decision-1");
  });

  it("returns null when nothing routed", () => {
    expect(readTraceModelRouting({ text: "hi" })).toBeNull();
    expect(readTraceModelRouting(null)).toBeNull();
    expect(readTraceModelRouting(undefined)).toBeNull();
  });

  it("ignores a malformed block rather than rendering half of it", () => {
    expect(readTraceModelRouting({ model_routing: "nope" })).toBeNull();
    expect(readTraceModelRouting({ model_routing: { routerLabel: "Auto Model" } })).toBeNull();
    expect(
      readTraceModelRouting({ model_routing: { routerLabel: "Auto Model", calls: [] } }),
    ).toBeNull();
  });

  it("drops call rows with no model but keeps the rest", () => {
    const routing = readTraceModelRouting(
      response({ calls: [{ turn: 1 }, call({ turn: 2, model: "gpt-5" })] }),
    );

    expect(routing?.calls).toHaveLength(1);
    expect(routing?.calls[0].model).toBe("gpt-5");
  });

  it("falls back to summing the calls when no total was stored", () => {
    const routing = readTraceModelRouting(
      response({
        decisionTotalMs: 0,
        calls: [call({ decisionMs: 10 }), call({ turn: 2, decisionMs: 15 })],
      }),
    );

    expect(routing?.decisionTotalMs).toBe(25);
  });

  it("numbers turns when a trace predates the turn field", () => {
    const routing = readTraceModelRouting(
      response({ calls: [call({ turn: undefined }), call({ turn: undefined, model: "gpt-5" })] }),
    );

    expect(routing?.calls.map((entry) => entry.turn)).toEqual([1, 2]);
  });

  it("keeps a reused turn visible with no cost", () => {
    const routing = readTraceModelRouting(
      response({ calls: [call({ reused: true, decisionMs: 0, decisionTraceId: null })] }),
    );

    expect(routing?.calls[0].reused).toBe(true);
    expect(routing?.calls[0].decisionMs).toBe(0);
  });
});

describe("formatRoutingCallLabel", () => {
  it("names the option and the model it resolved to", () => {
    expect(
      formatRoutingCallLabel(readTraceModelRouting(response())!.calls[0]),
    ).toBe("Fast → gpt-4o-mini");
  });

  it("falls back to the model alone when the option has no name", () => {
    const routing = readTraceModelRouting(response({ calls: [call({ option: null })] }));
    expect(formatRoutingCallLabel(routing!.calls[0])).toBe("gpt-4o-mini");
  });
});

describe("turn timings", () => {
  it("reads the per-turn provider offsets", () => {
    const routing = readTraceModelRouting(
      response({
        turnTimings: [
          { turn: 1, startMs: 1060, durationMs: 4200 },
          { turn: 2, startMs: 6010, durationMs: 3200 },
        ],
      }),
    );

    expect(routing?.turnTimings).toHaveLength(2);
    expect(routing?.turnTimings[1].startMs).toBe(6010);
  });

  it("reads what the turn cost and produced", () => {
    const routing = readTraceModelRouting(
      response({
        turnTimings: [
          {
            turn: 1,
            startMs: 1060,
            durationMs: 4200,
            model: "qwen3.8-flash",
            provider: "Custom",
            promptTokens: 1200,
            completionTokens: 340,
            totalTokens: 1540,
            textChars: 812,
            toolCalls: 2,
          },
        ],
      }),
    );
    const timing = routing!.turnTimings[0];

    expect(timing.model).toBe("qwen3.8-flash");
    expect(timing.provider).toBe("Custom");
    expect(timing.totalTokens).toBe(1540);
    expect(timing.toolCalls).toBe(2);
    expect(timing.error).toBeNull();
  });

  it("leaves absent turn fields null rather than zero", () => {
    const routing = readTraceModelRouting(
      response({ turnTimings: [{ turn: 1, startMs: 0, durationMs: 10 }] }),
    );
    const timing = routing!.turnTimings[0];

    // Zero tool calls and "not recorded" are different facts, so the step can say so.
    expect(timing.toolCalls).toBeNull();
    expect(timing.totalTokens).toBeNull();
    expect(timing.model).toBeNull();
  });

  it("is empty for a trace recorded before offsets existed", () => {
    expect(readTraceModelRouting(response())?.turnTimings).toEqual([]);
  });

  it("reads a call's own start offset", () => {
    const routing = readTraceModelRouting(response({ calls: [call({ startMs: 0 })] }));
    expect(routing?.calls[0].startMs).toBe(0);
  });
});
