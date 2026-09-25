import { describe, expect, it } from "vitest";

import type { NodeResult, WorkflowEdge } from "@/types/workflow";
import { resolveSpanInput } from "@/components/Panels/executionSpanInput";

function row(
  partial: Partial<NodeResult> & Pick<NodeResult, "node_id" | "node_label" | "node_type">,
): NodeResult {
  return { status: "success", output: {}, execution_time_ms: 1, error: null, ...partial };
}

function edge(source: string, target: string, targetHandle?: string): WorkflowEdge {
  return { id: `${source}-${target}`, source, target, targetHandle };
}

describe("resolveSpanInput", () => {
  it("keys every wired upstream output by its node label", () => {
    const rows = [
      row({ node_id: "start", node_label: "start", node_type: "textInput", output: { text: "hi" } }),
      row({ node_id: "http", node_label: "fetch", node_type: "http", output: { status: 200 } }),
      row({ node_id: "agent", node_label: "writer", node_type: "agent", output: { text: "ok" } }),
    ];
    const edges = [edge("start", "agent"), edge("http", "agent"), edge("tool", "agent", "tool-input")];

    const input = resolveSpanInput(
      { nodeId: "agent", nodeType: "agent", resultListIndex: 2 },
      rows,
      edges,
    );

    expect(input).toEqual({
      value: { start: { text: "hi" }, fetch: { status: 200 } },
      note: null,
    });
  });

  it("picks the upstream output of the same loop iteration and skips failed rows", () => {
    const rows = [
      row({ node_id: "loop", node_label: "loop", node_type: "loop", output: { item: 1 } }),
      row({ node_id: "body", node_label: "body", node_type: "set", output: { n: 1 } }),
      row({ node_id: "loop", node_label: "loop", node_type: "loop", output: { item: 2 } }),
      row({ node_id: "loop", node_label: "loop", node_type: "loop", status: "error" }),
      row({ node_id: "body", node_label: "body", node_type: "set", output: { n: 2 } }),
      row({ node_id: "loop", node_label: "loop", node_type: "loop", output: { item: 3 } }),
    ];

    const input = resolveSpanInput(
      { nodeId: "body", nodeType: "set", resultListIndex: 4 },
      rows,
      [edge("loop", "body")],
    );

    expect(input?.value).toEqual({ loop: { item: 2 } });
  });

  it("explains entry nodes and upstream nodes that produced nothing", () => {
    const rows = [
      row({ node_id: "start", node_label: "start", node_type: "textInput" }),
      row({ node_id: "gate", node_label: "gate", node_type: "set", status: "skipped" }),
      row({ node_id: "out", node_label: "out", node_type: "output" }),
    ];

    expect(
      resolveSpanInput({ nodeId: "start", nodeType: "textInput", resultListIndex: 0 }, rows, []),
    ).toEqual({ value: null, note: "Entry node: it has no upstream input." });
    expect(
      resolveSpanInput(
        { nodeId: "out", nodeType: "output", resultListIndex: 2 },
        rows,
        [edge("gate", "out")],
      ),
    ).toEqual({ value: null, note: "No upstream output reached this node." });
  });

  it("shows the failed node payload an error handler received", () => {
    const failure = { node_label: "fetch", message: "timeout" };
    const rows = [
      row({ node_id: "http", node_label: "fetch", node_type: "http", status: "error" }),
      row({
        node_id: "handler",
        node_label: "onError",
        node_type: "errorHandler",
        output: { error: failure, message: "fetch failed" },
      }),
    ];

    expect(
      resolveSpanInput({ nodeId: "handler", nodeType: "errorHandler", resultListIndex: 1 }, rows, []),
    ).toEqual({ value: { error: failure }, note: null });
  });

  it("shows the orchestrator prompt for a delegated sub-agent run", () => {
    const orchestrator = row({
      node_id: "boss",
      node_label: "boss",
      node_type: "agent",
      output: {
        text: "done",
        tool_calls: [
          { name: "call_sub_agent", arguments: { prompt: "first" }, trace_id: "t-1" },
          { name: "call_sub_agent", arguments: { prompt: "second" }, trace_id: "t-2" },
        ],
      },
    });
    const delegated = row({
      node_id: "helper",
      node_label: "helper",
      node_type: "agent",
      metadata: { invocation: "sub_agent_tool", trace_id: "t-2" },
    });

    expect(
      resolveSpanInput(
        { nodeId: "helper", nodeType: "agent", resultListIndex: 0 },
        [delegated, orchestrator],
        [edge("helper", "boss", "tool-input")],
      ),
    ).toEqual({ value: { text: "second" }, note: "Delegated by boss" });
  });

  it("returns nothing while the input has not arrived yet", () => {
    const rows = [
      row({ node_id: "boss", node_label: "boss", node_type: "agent", status: "running" }),
      row({
        node_id: "helper",
        node_label: "helper",
        node_type: "agent",
        metadata: { invocation: "sub_agent_tool", trace_id: "t-1" },
      }),
      row({ node_id: "next", node_label: "next", node_type: "set", status: "running" }),
    ];

    expect(
      resolveSpanInput({ nodeId: "helper", nodeType: "agent", resultListIndex: 1 }, rows, []),
    ).toBeNull();
    expect(
      resolveSpanInput(
        { nodeId: "next", nodeType: "set", resultListIndex: 2 },
        rows,
        [edge("boss", "next")],
      ),
    ).toBeNull();
  });
});
