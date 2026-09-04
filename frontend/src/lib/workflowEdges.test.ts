import { describe, expect, it } from "vitest";

import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

import { resolveRenderedSourceHandle } from "./workflowEdges";

describe("workflowEdges", () => {
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
