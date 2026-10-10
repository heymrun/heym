import { describe, expect, it } from "vitest";

import type { WorkflowNode } from "@/types/workflow";
import { useExpressionCompletion } from "@/composables/useExpressionCompletion";

function node(id: string, type: string): WorkflowNode {
  return { id, type, position: { x: 0, y: 0 }, data: { label: id } } as WorkflowNode;
}

function suggestionLabels(nodes: WorkflowNode[], prefix: string): string[] {
  const completion = useExpressionCompletion({
    nodes,
    nodeResults: [],
    edges: [],
    currentNodeId: nodes[0]?.id ?? null,
  });
  return completion.getNodeSuggestions(prefix).map((suggestion) => suggestion.label);
}

describe("$page.record suggestion", () => {
  it("is offered in a dashboard widget workflow", () => {
    const labels = suggestionLabels([node("rows", "set"), node("chart", "chartOutput")], "pa");

    expect(labels).toContain("$page.record");
  });

  it("is not offered in an ordinary workflow", () => {
    const labels = suggestionLabels([node("rows", "set"), node("result", "output")], "pa");

    expect(labels).not.toContain("$page.record");
  });
});
