import { describe, expect, it } from "vitest";

import type { NodeResult, WorkflowNode } from "@/types/workflow";
import type { TimelineEntry } from "@/components/Panels/executionTimeline";
import * as executionTimeline from "@/components/Panels/executionTimeline";
import {
  buildDelegatedSubAgentLabelSet,
  buildSubAgentLabelToParentId,
  buildTimelineEntries,
  buildTimelineModel,
  formatSpanCost,
  isSameSpan,
  formatToolCallArguments,
  isDelegatedSubAgentRow,
  isSpanSettled,
  LIVE_TIMELINE_REFRESH_INTERVAL_MS,
  orderSpansByStart,
  readSpanJsonRepairs,
  readSpanTokenUsage,
  readSpanToolCalls,
  splitSpanOutput,
  summarizeTimelineModel,
} from "@/components/Panels/executionTimeline";

function entry(
  partial: Partial<TimelineEntry> &
    Pick<TimelineEntry, "node_id" | "node_label" | "node_type" | "status">,
): TimelineEntry {
  return {
    output: {},
    execution_time_ms: 0,
    error: null,
    isSubAgent: false,
    ...partial,
  };
}

describe("buildTimelineModel HITL wait spans", () => {
  it("renders explicit hitl_wait metadata as a distinct wait span on the node row", () => {
    const results: TimelineEntry[] = [
      entry({
        node_id: "agent-1",
        node_label: "Agent",
        node_type: "agent",
        status: "success",
        execution_time_ms: 1000,
        metadata: {
          sequence: 1,
          started_at_ms: 1000,
          ended_at_ms: 2000,
          hitl_phase: "pre_review",
        },
      }),
      entry({
        node_id: "agent-1",
        node_label: "Agent",
        node_type: "agent",
        status: "success",
        execution_time_ms: 5000,
        metadata: {
          sequence: 2,
          started_at_ms: 2000,
          ended_at_ms: 7000,
          hitl_wait: true,
        },
      }),
      entry({
        node_id: "agent-1",
        node_label: "Agent",
        node_type: "agent",
        status: "success",
        execution_time_ms: 500,
        metadata: {
          sequence: 3,
          started_at_ms: 7000,
          ended_at_ms: 7500,
        },
      }),
    ];

    const { rows, timeWindow } = buildTimelineModel(results, 6500, new Map());

    expect(timeWindow.totalMs).toBeGreaterThanOrEqual(6500);
    expect(rows).toHaveLength(1);
    expect(rows[0].spans).toHaveLength(3);
    expect(rows[0].spans[1].isHitlWait).toBe(true);
    expect(rows[0].spans[1].durationMs).toBe(5000);
    expect(rows[0].spans[1].startOffsetMs).toBe(1000);
    expect(rows[0].spans[0].isHitlWait).toBe(false);
    expect(rows[0].spans[2].isHitlWait).toBe(false);
    expect(rows[0].spans[0].output).toEqual({});
    expect(rows[0].spans[1].output).toBe(null);
  });

  it("synthesizes a live HITL wait span while an agent node is still pending", () => {
    const results: TimelineEntry[] = [
      entry({
        node_id: "trigger-1",
        node_label: "Trigger",
        node_type: "manual_trigger",
        status: "success",
        execution_time_ms: 10,
        metadata: {
          sequence: 1,
          started_at_ms: 1000,
          ended_at_ms: 1010,
        },
      }),
      entry({
        node_id: "agent-1",
        node_label: "Agent",
        node_type: "agent",
        status: "pending",
        execution_time_ms: 800,
        metadata: {
          sequence: 2,
          started_at_ms: 1010,
          ended_at_ms: 1810,
          hitl: { summary: "Needs review" },
        },
      }),
    ];

    const { rows } = buildTimelineModel(results, 800, new Map(), {
      nowMs: 6810,
    });

    const agentRow = rows.find((row) => row.nodeId === "agent-1");
    expect(agentRow).toBeDefined();
    expect(agentRow!.spans).toHaveLength(2);
    expect(agentRow!.spans[0].isHitlWait).toBe(false);
    expect(agentRow!.spans[1].isHitlWait).toBe(true);
    expect(agentRow!.spans[1].durationMs).toBe(5000);
    expect(agentRow!.spans[1].startOffsetMs).toBe(810);
  });

  it("synthesizes a live Codex follow-up wait span while codex is pending", () => {
    const results: TimelineEntry[] = [
      entry({
        node_id: "codex-1",
        node_label: "Codex",
        node_type: "codex",
        status: "pending",
        execution_time_ms: 200,
        metadata: {
          sequence: 1,
          started_at_ms: 5000,
          ended_at_ms: 5200,
          codex: { kind: "codex" },
        },
      }),
    ];

    const { rows } = buildTimelineModel(results, 200, new Map(), {
      nowMs: 8200,
    });

    expect(rows).toHaveLength(1);
    expect(rows[0].spans).toHaveLength(2);
    expect(rows[0].spans[1].isHitlWait).toBe(true);
    expect(rows[0].spans[1].durationMs).toBe(3000);
  });
});

describe("buildTimelineModel running spans", () => {
  it("aligns a client clock ahead by one hour with the server clock", () => {
    const alignNow = (
      executionTimeline as typeof executionTimeline & {
        getServerAlignedNowMs?: (clientNowMs: number, serverClockOffsetMs: number) => number;
      }
    ).getServerAlignedNowMs;

    expect(alignNow?.(3_601_000, -3_600_000)).toBe(1_000);
  });

  it("extends an open running span to the current timeline time", () => {
    const results: TimelineEntry[] = [
      entry({
        node_id: "http-1",
        node_label: "HTTP Request",
        node_type: "http",
        status: "running",
        execution_time_ms: 0,
        metadata: {
          started_at_ms: 1000,
          ended_at_ms: 1000,
        },
      }),
    ];

    const model = buildTimelineModel(results, 0, new Map(), { nowMs: 1050 });
    const span = model.rows[0]?.spans[0];

    expect(LIVE_TIMELINE_REFRESH_INTERVAL_MS).toBe(50);
    expect(model.timeWindow).toEqual({ startMs: 1000, totalMs: 50 });
    expect(span).toMatchObject({
      status: "running",
      durationMs: 50,
      startOffsetMs: 0,
      endOffsetMs: 50,
    });
  });
});

describe("summarizeTimelineModel", () => {
  it("returns a neutral summary for an empty execution", () => {
    const model = buildTimelineModel([], 0, new Map());

    expect(summarizeTimelineModel(model.rows, model.timeWindow)).toEqual({
      totalDurationMs: 1,
      spanCount: 0,
      failedSpanCount: 0,
      retryCount: 0,
    });
  });

  it("summarizes failures and retries across all rows", () => {
    const results: TimelineEntry[] = [
      entry({
        node_id: "llm-1",
        node_label: "LLM",
        node_type: "llm",
        status: "error",
        execution_time_ms: 120,
        retryFailedAttempts: 2,
        retryLastError: "Rate limit exceeded",
        metadata: { started_at_ms: 100, ended_at_ms: 220 },
      }),
      entry({
        node_id: "agent-1",
        node_label: "Agent",
        node_type: "agent",
        status: "success",
        execution_time_ms: 80,
        retryFailedAttempts: 1,
        metadata: { started_at_ms: 220, ended_at_ms: 300 },
      }),
    ];

    const model = buildTimelineModel(results, 200, new Map());
    expect(summarizeTimelineModel(model.rows, model.timeWindow)).toEqual({
      totalDurationMs: 200,
      spanCount: 2,
      failedSpanCount: 1,
      retryCount: 3,
    });
    expect(model.rows[0].spans[0].retryLastError).toBe("Rate limit exceeded");
  });
});

describe("model routing on spans", () => {
  function routingEntry(metadata: Record<string, unknown>): TimelineEntry {
    return entry({
      node_id: "n1",
      node_label: "Agent",
      node_type: "agent",
      status: "success",
      output: { text: "done" },
      execution_time_ms: 120,
      metadata,
    });
  }

  it("carries the routing summary from node metadata onto the span", () => {
    const model = buildTimelineModel(
      [
        routingEntry({
          model_routing: {
            routerLabel: "Auto Model",
            routerCredentialId: "cred-1",
            calls: [
              { model: "gpt-4o-mini", option: "Fast", credentialName: "OpenAI", fallback: false, error: null },
              { model: "gpt-5", option: "Deep", credentialName: "OpenAI", fallback: false, error: null },
            ],
          },
        }),
      ],
      500,
      new Map(),
    );

    const span = model.rows[0].spans[0];
    expect(span.modelRouting?.routerLabel).toBe("Auto Model");
    expect(span.modelRouting?.calls).toHaveLength(2);
  });

  it("leaves modelRouting null when a node did not route", () => {
    const model = buildTimelineModel([routingEntry({})], 500, new Map());
    expect(model.rows[0].spans[0].modelRouting).toBeNull();
  });

  it("ignores a malformed routing blob rather than rendering half of it", () => {
    const model = buildTimelineModel(
      [routingEntry({ model_routing: { routerLabel: "Auto" } })],
      500,
      new Map(),
    );
    expect(model.rows[0].spans[0].modelRouting).toBeNull();
  });
});

describe("formatModelRoutingLabel", () => {
  it("shows router and model for a single model", () => {
    expect(
      executionTimeline.formatModelRoutingLabel({
        routerLabel: "Auto Model",
        routerCredentialId: "c",
        calls: [{ model: "gpt-5", option: "Deep", credentialName: "OpenAI", fallback: false, error: null }],
      }),
    ).toBe("Auto Model / gpt-5");
  });

  it("marks extra distinct models with a count", () => {
    expect(
      executionTimeline.formatModelRoutingLabel({
        routerLabel: "Auto Model",
        routerCredentialId: "c",
        calls: [
          { model: "gpt-4o-mini", option: "Fast", credentialName: "OpenAI", fallback: false, error: null },
          { model: "gpt-5", option: "Deep", credentialName: "OpenAI", fallback: false, error: null },
          { model: "gpt-5", option: "Deep", credentialName: "OpenAI", fallback: false, error: null },
        ],
      }),
    ).toBe("Auto Model / gpt-5 +1");
  });

  it("returns null with no calls", () => {
    expect(
      executionTimeline.formatModelRoutingLabel({
        routerLabel: "Auto Model",
        routerCredentialId: "c",
        calls: [],
      }),
    ).toBeNull();
  });

  it("returns null when nothing routed", () => {
    expect(executionTimeline.formatModelRoutingLabel(null)).toBeNull();
  });
});

describe("span token usage", () => {
  const usage = { prompt_tokens: 800, completion_tokens: 434, total_tokens: 1234 };

  it("reads usage from metadata before the output, and derives a missing total", () => {
    expect(readSpanTokenUsage({ output: { usage }, metadata: {} })).toEqual({
      total: 1234,
      prompt: 800,
      completion: 434,
    });
    expect(
      readSpanTokenUsage({
        output: { answer: "ok" },
        metadata: { usage: { prompt_tokens: 3, completion_tokens: 2 } },
      }),
    ).toEqual({ total: 5, prompt: 3, completion: 2 });
    expect(readSpanTokenUsage({ output: { usage: "n/a" } })).toBeNull();
    expect(readSpanTokenUsage({ output: { text: "no llm" } })).toBeNull();
  });

  it("only reports tokens once the node finished", () => {
    const results = [
      entry({
        node_id: "llm-1",
        node_label: "Writer",
        node_type: "llm",
        status: "success",
        output: { text: "done", usage },
        metadata: { started_at_ms: 1000, ended_at_ms: 2000 },
      }),
      entry({
        node_id: "llm-2",
        node_label: "Reviewer",
        node_type: "llm",
        status: "running",
        output: { usage },
        metadata: { started_at_ms: 2000, ended_at_ms: 2000 },
      }),
    ];

    const { rows } = buildTimelineModel(results, 1000, new Map(), { nowMs: 2500 });

    expect(rows[0].spans[0].tokenUsage?.total).toBe(1234);
    expect(isSpanSettled(rows[0].spans[0])).toBe(true);
    expect(rows[1].spans[0].tokenUsage).toBeNull();
    expect(isSpanSettled(rows[1].spans[0])).toBe(false);
  });
});

describe("span navigation", () => {
  it("orders spans by start time across rows, ties top to bottom", () => {
    const results = [
      entry({
        node_id: "loop",
        node_label: "Loop",
        node_type: "loop",
        status: "success",
        metadata: { started_at_ms: 0, ended_at_ms: 10 },
      }),
      entry({
        node_id: "body",
        node_label: "Body",
        node_type: "set",
        status: "success",
        metadata: { started_at_ms: 10, ended_at_ms: 20 },
      }),
      entry({
        node_id: "loop",
        node_label: "Loop",
        node_type: "loop",
        status: "success",
        metadata: { started_at_ms: 20, ended_at_ms: 30 },
      }),
      entry({
        node_id: "side",
        node_label: "Side",
        node_type: "set",
        status: "success",
        metadata: { started_at_ms: 20, ended_at_ms: 25 },
      }),
    ];

    const { rows } = buildTimelineModel(results, 30, new Map());
    const ordered = orderSpansByStart(rows);

    expect(ordered.map((span) => `${span.nodeId}#${span.resultListIndex}`)).toEqual([
      "loop#0",
      "body#1",
      "loop#2",
      "side#3",
    ]);
  });

  it("recognises the same span after a rebuild shifts its key", () => {
    const results = [
      entry({ node_id: "a", node_label: "A", node_type: "set", status: "success", sourceNodeResultsIndex: 0 }),
      entry({ node_id: "b", node_label: "B", node_type: "set", status: "success", sourceNodeResultsIndex: 1 }),
    ];

    const full = buildTimelineModel(results, 10, new Map()).rows[1].spans[0];
    const withoutA = buildTimelineModel([results[1]], 10, new Map()).rows[0].spans[0];

    expect(withoutA.key).not.toBe(full.key);
    expect(isSameSpan(withoutA, full)).toBe(true);
  });
});

describe("formatSpanCost", () => {
  it("prints sub-cent costs with four decimals like the Traces tab", () => {
    expect(formatSpanCost("0.004213")).toBe("$0.0042");
    expect(formatSpanCost("1.5")).toBe("$1.50");
    expect(formatSpanCost("0")).toBe("$0.00");
  });
});

describe("splitSpanOutput", () => {
  it("reads an LLM reply as the message and keeps the other fields as JSON", () => {
    const usage = { prompt_tokens: 107, completion_tokens: 5534, total_tokens: 5641 };
    expect(splitSpanOutput({ text: "Hi Akash", model: "glm-5.3-flash", usage })).toEqual({
      message: "Hi Akash",
      details: { model: "glm-5.3-flash", usage },
    });
    expect(splitSpanOutput({ text: "only text" })).toEqual({ message: "only text", details: null });
    expect(splitSpanOutput("plain reply")).toEqual({ message: "plain reply", details: null });
  });

  it("leaves outputs without a text reply entirely as JSON", () => {
    expect(splitSpanOutput({ status: 200, body: { ok: true } })).toEqual({
      message: null,
      details: { status: 200, body: { ok: true } },
    });
    expect(splitSpanOutput({ text: 42 })).toEqual({ message: null, details: { text: 42 } });
    expect(splitSpanOutput(null)).toEqual({ message: null, details: null });
  });
});


describe("span tool calls", () => {
  const outline = [
    {
      name: "call_sub_workflow",
      status: "success",
      elapsed_ms: 848.09,
      arguments: { inputs: { text: "https://talanoa.email" }, workflow_id: "9606db51-f5e9-4a96-84bb-9e38f58513b7" },
    },
    { name: "lookup", status: "error", elapsed_ms: 12, arguments: { q: "a" } },
  ];

  it("reads the outline JSON output keeps in metadata", () => {
    expect(readSpanToolCalls({ output: { answer: "ok" }, metadata: { tool_calls: outline } })).toEqual([
      {
        name: "call_sub_workflow",
        status: "success",
        elapsedMs: 848.09,
        arguments: outline[0].arguments,
      },
      { name: "lookup", status: "error", elapsedMs: 12, arguments: { q: "a" } },
    ]);
  });

  it("falls back to the tool_calls of a plain agent output", () => {
    const calls = readSpanToolCalls({
      output: { text: "done", tool_calls: [...outline, { name: "_context_compression" }] },
    });
    expect(calls?.map((call) => call.name)).toEqual(["call_sub_workflow", "lookup"]);
  });

  it("is null when nothing was called or the data is malformed", () => {
    expect(readSpanToolCalls({ output: { text: "no tools" } })).toBeNull();
    expect(readSpanToolCalls({ output: {}, metadata: { tool_calls: [] } })).toBeNull();
    expect(readSpanToolCalls({ output: {}, metadata: { tool_calls: [null, 3, {}] } })).toBeNull();
  });

  it("carries tool calls onto the span, once the node settled", () => {
    const results = [
      entry({
        node_id: "agent-1",
        node_label: "extractData",
        node_type: "agent",
        status: "success",
        output: { email: "a@b.c" },
        metadata: { started_at_ms: 1000, ended_at_ms: 2000, tool_calls: outline },
      }),
    ];
    const { rows } = buildTimelineModel(results, 1000, new Map());
    expect(rows[0].spans[0].toolCalls?.length).toBe(2);
  });
});

describe("formatToolCallArguments", () => {
  it("flattens nested objects into key=value pairs", () => {
    expect(formatToolCallArguments({ inputs: { text: "https://talanoa.email" }, workflow_id: "9606db51-f5e9-4a96-84bb-9e38f58513b7" })).toBe(
      "inputs.text=https://talanoa.email, workflow_id=9606db51…",
    );
  });

  it("keeps numbers, booleans and null readable", () => {
    expect(formatToolCallArguments({ n: 3, ok: true, none: null })).toBe("n=3, ok=true, none=null");
  });

  it("shortens long strings and caps the whole line", () => {
    const long = formatToolCallArguments({ code: "x".repeat(200) });
    expect(long.length).toBeLessThanOrEqual(90);
    expect(long.endsWith("…")).toBe(true);
  });

  it("summarises arrays by length and tolerates empty arguments", () => {
    expect(formatToolCallArguments({ items: [1, 2, 3] })).toBe("items=[3]");
    expect(formatToolCallArguments(undefined)).toBe("");
    expect(formatToolCallArguments({})).toBe("");
    expect(formatToolCallArguments("raw text")).toBe("raw text");
  });
});


describe("span json repairs", () => {
  it("reads the rejection reasons JSON output keeps in metadata", () => {
    expect(
      readSpanJsonRepairs({ metadata: { json_repairs: ["'name' is a required property"] } }),
    ).toEqual(["'name' is a required property"]);
  });

  it("is null when the reply needed no repair or the data is malformed", () => {
    expect(readSpanJsonRepairs({ metadata: {} })).toBeNull();
    expect(readSpanJsonRepairs({ metadata: { json_repairs: [] } })).toBeNull();
    expect(readSpanJsonRepairs({ metadata: { json_repairs: [3, null, ""] } })).toBeNull();
    expect(readSpanJsonRepairs({})).toBeNull();
  });

  it("carries the repairs onto the settled span", () => {
    const results = [
      entry({
        node_id: "agent-1",
        node_label: "extractData",
        node_type: "agent",
        status: "success",
        output: { email: "a@b.c" },
        metadata: { started_at_ms: 1000, ended_at_ms: 2000, json_repairs: ["not valid JSON"] },
      }),
    ];
    const { rows } = buildTimelineModel(results, 1000, new Map());
    expect(rows[0].spans[0].jsonRepairs).toEqual(["not valid JSON"]);
  });
});

describe("timeline entries from node results", () => {
  function row(
    partial: Partial<NodeResult> & Pick<NodeResult, "node_id" | "node_label" | "node_type" | "status">,
  ): NodeResult {
    return { output: {}, execution_time_ms: 0, error: null, ...partial };
  }

  function agentNode(id: string, label: string, subAgentLabels?: string[]): WorkflowNode {
    return {
      id,
      type: "agent",
      position: { x: 0, y: 0 },
      data: { label, ...(subAgentLabels ? { subAgentLabels } : {}) },
    } as WorkflowNode;
  }

  it("drops condition, sticky, skipped and retry attempt rows and keeps the source index", () => {
    const rows = [
      row({ node_id: "in", node_label: "input", node_type: "textInput", status: "success" }),
      row({ node_id: "c", node_label: "check", node_type: "condition", status: "success" }),
      row({ node_id: "s", node_label: "note", node_type: "sticky", status: "success" }),
      row({ node_id: "x", node_label: "skipped", node_type: "llm", status: "skipped" }),
      row({ node_id: "out", node_label: "output", node_type: "output", status: "success" }),
    ];

    const entries = buildTimelineEntries(rows, () => false);

    expect(entries.map((e) => [e.node_id, e.sourceNodeResultsIndex])).toEqual([
      ["in", 0],
      ["out", 4],
    ]);
    expect(entries[0]).toMatchObject({
      isSubAgent: false,
      retryFailedAttempts: 0,
      retryFinalAttempt: null,
      retryMaxAttempts: null,
      retryLastError: null,
    });
  });

  it("folds failed retry attempts into the final row", () => {
    const rows = [
      row({
        node_id: "http",
        node_label: "fetch",
        node_type: "http",
        status: "error",
        error: "timeout 1",
        metadata: { retry_stage: "attempt_failed", retry_attempt: 1, retry_max_attempts: 3 },
      }),
      row({
        node_id: "http",
        node_label: "fetch",
        node_type: "http",
        status: "error",
        error: "timeout 2",
        metadata: { retry_stage: "attempt_failed", retry_attempt: 2, retry_max_attempts: 3 },
      }),
      row({ node_id: "http", node_label: "fetch", node_type: "http", status: "success" }),
    ];

    const entries = buildTimelineEntries(rows, () => false);

    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      sourceNodeResultsIndex: 2,
      retryFailedAttempts: 2,
      retryFinalAttempt: 3,
      retryMaxAttempts: 3,
      retryLastError: "timeout 2",
    });
  });

  it("marks rows the predicate calls sub-agent runs", () => {
    const rows = [
      row({ node_id: "a", node_label: "orchestrator", node_type: "agent", status: "success" }),
      row({ node_id: "b", node_label: "researcher", node_type: "agent", status: "success" }),
    ];

    const entries = buildTimelineEntries(rows, (r) => r.node_label === "researcher");

    expect(entries.map((e) => e.isSubAgent)).toEqual([false, true]);
  });

  it("derives delegated sub-agent labels and their parents from canvas nodes", () => {
    const nodes = [
      agentNode("orch", "orchestrator", ["researcher", 7 as unknown as string]),
      agentNode("res", "researcher"),
      { id: "llm", type: "llm", position: { x: 0, y: 0 }, data: { label: "llm", subAgentLabels: ["x"] } } as WorkflowNode,
    ];

    expect([...buildDelegatedSubAgentLabelSet(nodes)]).toEqual(["researcher"]);
    expect([...buildSubAgentLabelToParentId(nodes)]).toEqual([["researcher", "orch"]]);
  });

  it("treats delegated rows as sub-agent runs, including old history without metadata", () => {
    const labels = new Set(["researcher"]);
    const tool = row({
      node_id: "t",
      node_label: "any",
      node_type: "agent",
      status: "success",
      metadata: { invocation: "sub_agent_tool" },
    });

    expect(isDelegatedSubAgentRow(tool, new Set())).toBe(true);
    expect(
      isDelegatedSubAgentRow(
        row({ node_id: "r", node_label: "researcher", node_type: "agent", status: "success" }),
        labels,
      ),
    ).toBe(true);
    expect(
      isDelegatedSubAgentRow(
        row({ node_id: "r", node_label: "researcher", node_type: "llm", status: "success" }),
        labels,
      ),
    ).toBe(false);
    expect(
      isDelegatedSubAgentRow(
        row({ node_id: "o", node_label: "orchestrator", node_type: "agent", status: "success" }),
        labels,
      ),
    ).toBe(false);
  });
});
