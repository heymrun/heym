import { describe, expect, it } from "vitest";

import type { NodeTemplate, WorkflowTemplate } from "../types/template.types";
import { nodeTemplateMatches, workflowTemplateMatches } from "./templateSearch";

const workflow = {
  name: "Lead sync",
  description: "Copies new leads",
  tags: ["crm", "Zürich"],
  nodes: [{ id: "a", type: "hubspot" }, { id: "b" }],
} as unknown as WorkflowTemplate;

const node = {
  name: "Tuned writer",
  description: null,
  tags: ["copy"],
  node_type: "llm",
} as unknown as NodeTemplate;

describe("template search", () => {
  it("matches a workflow template by name, description, tag or node type", () => {
    for (const query of ["lead", "NEW LEADS", "crm", "zürich", "HubSpot"]) {
      expect(workflowTemplateMatches(workflow, query)).toBe(true);
    }
    expect(workflowTemplateMatches(workflow, "llm")).toBe(false);
  });

  it("matches a node template by its node type as well", () => {
    expect(nodeTemplateMatches(node, "LLM")).toBe(true);
    expect(nodeTemplateMatches(node, "copy")).toBe(true);
    expect(nodeTemplateMatches(node, "hubspot")).toBe(false);
  });

  it("keeps everything for an empty search", () => {
    expect(workflowTemplateMatches(workflow, "  ")).toBe(true);
    expect(nodeTemplateMatches(node, "")).toBe(true);
  });
});
