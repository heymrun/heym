import { describe, expect, it } from "vitest";

import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

import { chartActionValidationError, getChartActionResultIds, resolveRenderedSourceHandle } from "./workflowEdges";

describe("workflowEdges", () => {
  it("finds HTML action results through every switch case and treats them as terminal", () => {
    const chart = (id: string, chartType: "html" | "table"): WorkflowNode => ({
      id, type: "chartOutput", position: { x: 0, y: 0 }, data: { label: id, chartType },
    });
    const nodes: WorkflowNode[] = [
      chart("card", "html"),
      { id: "choose", type: "switch", position: { x: 0, y: 0 }, data: { label: "choose" } },
      chart("reply", "html"),
      chart("redraw", "html"),
      chart("table", "table"),
    ];
    const edges: WorkflowEdge[] = [
      { id: "action", source: "card", target: "choose", sourceHandle: "action" },
      { id: "first", source: "choose", target: "reply", sourceHandle: "case-0" },
      { id: "second", source: "choose", target: "redraw", sourceHandle: "case-1" },
    ];
    expect(getChartActionResultIds(nodes, edges)).toEqual(new Set(["reply", "redraw"]));
    expect(chartActionValidationError(nodes, edges)).toBeNull();
    expect(chartActionValidationError(nodes, [
      ...edges, { id: "table", source: "choose", target: "table", sourceHandle: "default" },
    ])).toBe("Action results must use the HTML chart type.");
    expect(chartActionValidationError(nodes, [
      ...edges, { id: "nested", source: "reply", target: "redraw", sourceHandle: "action" },
    ])).toContain("Action results end the branch.");
  });
  describe("resolveRenderedSourceHandle with unknown source node types", () => {
    it("does not throw when source node type is unknown and no sourceHandle is provided", () => {
      const nodes: WorkflowNode[] = [
        {
          id: "source-unknown",
          type: "unknownNodeType" as never,
          position: { x: 0, y: 0 },
          data: { label: "Unknown source" },
        },
        {
          id: "target",
          type: "llm",
          position: { x: 100, y: 0 },
          data: { label: "LLM node" },
        },
      ];

      const edge: WorkflowEdge = {
        id: "edge-1",
        source: "source-unknown",
        target: "target",
      };

      // Should not throw. Unknown node types are assumed to have outputs, so the
      // function resolves the primary output handle "output" rather than undefined.
      const result = resolveRenderedSourceHandle(edge, nodes);
      expect(result).toBe("output");
    });

    it("returns undefined when source node is not found", () => {
      const nodes: WorkflowNode[] = [
        {
          id: "target",
          type: "llm",
          position: { x: 100, y: 0 },
          data: { label: "LLM node" },
        },
      ];

      const edge: WorkflowEdge = {
        id: "edge-1",
        source: "missing-source",
        target: "target",
      };

      const result = resolveRenderedSourceHandle(edge, nodes);
      expect(result).toBeUndefined();
    });

    it("preserves existing behavior for known source node types", () => {
      const nodes: WorkflowNode[] = [
        {
          id: "source-llm",
          type: "llm",
          position: { x: 0, y: 0 },
          data: { label: "LLM node" },
        },
        {
          id: "target",
          type: "llm",
          position: { x: 100, y: 0 },
          data: { label: "Another LLM node" },
        },
      ];

      const edge: WorkflowEdge = {
        id: "edge-1",
        source: "source-llm",
        target: "target",
      };

      // LLM has a primary output handle, so the function resolves to "output".
      const result = resolveRenderedSourceHandle(edge, nodes);
      expect(result).toBe("output");
    });

    it("uses sourceHandle when explicitly provided, even if source node type is unknown", () => {
      const nodes: WorkflowNode[] = [
        {
          id: "source-unknown",
          type: "unknownNodeType" as never,
          position: { x: 0, y: 0 },
          data: { label: "Unknown source" },
        },
        {
          id: "target",
          type: "llm",
          position: { x: 100, y: 0 },
          data: { label: "LLM node" },
        },
      ];

      const edge: WorkflowEdge = {
        id: "edge-1",
        source: "source-unknown",
        target: "target",
        sourceHandle: "custom-output",
      };

      const result = resolveRenderedSourceHandle(edge, nodes);
      expect(result).toBe("custom-output");
    });

    it("returns 'tool-output' for tool-input edges regardless of source node type", () => {
      const nodes: WorkflowNode[] = [
        {
          id: "source-unknown",
          type: "unknownNodeType" as never,
          position: { x: 0, y: 0 },
          data: { label: "Unknown source" },
        },
        {
          id: "target",
          type: "agent",
          position: { x: 100, y: 0 },
          data: { label: "Agent node" },
        },
      ];

      const edge: WorkflowEdge = {
        id: "edge-1",
        source: "source-unknown",
        target: "target",
        targetHandle: "tool-input",
      };

      const result = resolveRenderedSourceHandle(edge, nodes);
      expect(result).toBe("tool-output");
    });
  });
});
