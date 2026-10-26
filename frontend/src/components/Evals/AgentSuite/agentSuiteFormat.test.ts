import { describe, expect, it } from "vitest";

import type { Workflow } from "@/types/workflow";
import { baselineSourceLabel, nodeToolLabels } from "@/components/Evals/AgentSuite/agentSuiteFormat";

describe("nodeToolLabels", () => {
  it("lists the nodes on the agent's tool input, the way the agent can call them", () => {
    const workflow = {
      nodes: [
        { id: "agent", type: "agent", data: { label: "chatbotAgent" } },
        { id: "rag", type: "rag", data: { label: "imperumKnowledge" } },
        { id: "http", type: "http", data: {} },
        { id: "map", type: "jsonOutputMapper", data: { label: "payload" } },
        { id: "start", type: "textInput", data: { label: "start" } },
      ],
      edges: [
        { id: "e1", source: "rag", target: "agent", targetHandle: "tool-input" },
        { id: "e2", source: "http", target: "agent", targetHandle: "tool-input" },
        { id: "e3", source: "map", target: "agent", targetHandle: "tool-input" },
        { id: "e4", source: "start", target: "agent" },
        { id: "e5", source: "gone", target: "agent", targetHandle: "tool-input" },
      ],
    } as unknown as Workflow;

    expect(nodeToolLabels(workflow, "agent")).toEqual(["imperumKnowledge", "http"]);
    expect(nodeToolLabels(workflow, "rag")).toEqual([]);
  });
});

describe("baselineSourceLabel", () => {
  it("names each source", () => {
    expect(baselineSourceLabel({ source: "manual" })).toBe("entered manually");
    expect(baselineSourceLabel({ source: "suite_run" })).toBe("from a suite run");
    expect(baselineSourceLabel({ source: "latest_runs" })).toBe("from the latest runs");
  });

  it("reads a baseline saved before sources existed as the latest runs", () => {
    expect(baselineSourceLabel({})).toBe("from the latest runs");
  });
});
