import { describe, expect, it } from "vitest";

import type { NodeType, WorkflowNode } from "@/types/workflow";

import { workflowRunNodeIds } from "./workflowRunScope";

function node(id: string, type: NodeType = "set"): WorkflowNode {
  return { id, type, position: { x: 0, y: 0 }, data: { label: id } };
}

describe("partial run dependencies", () => {
  const nodes = [node("start"), node("loop", "loop"), node("target"), node("sibling"), node("done")];
  const edges = [
    { id: "a", source: "start", target: "loop" },
    { id: "b", source: "loop", target: "target", sourceHandle: "loop" },
    { id: "c", source: "loop", target: "sibling", sourceHandle: "loop" },
    { id: "d", source: "target", target: "loop", targetHandle: "loop" },
    { id: "e", source: "sibling", target: "loop", targetHandle: "loop" },
    { id: "f", source: "loop", target: "done", sourceHandle: "done" },
  ];

  it("excludes sibling loop branches when the target is inside the loop", () => {
    expect(workflowRunNodeIds(nodes, edges, "target")).toEqual(new Set(["start", "loop", "target"]));
  });

  it("includes the whole upstream loop when the target follows it", () => {
    expect(workflowRunNodeIds(nodes, edges, "done")).toEqual(new Set(nodes.map((item) => item.id)));
  });

  it("does not include the body when running the loop node itself", () => {
    expect(workflowRunNodeIds(nodes, edges, "loop")).toEqual(new Set(["start", "loop"]));
  });
});
