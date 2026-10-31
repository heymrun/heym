import { describe, expect, it } from "vitest";

import { streamingWorkflowProgress, workflowDraftMessage } from "@/lib/workflowDraftProgress";

const DSL = JSON.stringify(
  {
    name: "Lead intake",
    nodes: [
      { id: "a", type: "textInput", data: { label: "start", inputFields: [{ key: "text", label: "Text" }] } },
      { id: "b", type: "agent", data: { label: "Qualify" } },
      { id: "c", type: "dataTable", data: { label: "Save lead" } },
      { id: "d", type: "output", data: { label: "result" } },
    ],
    edges: [],
  },
  null,
  2,
);

describe("workflowDraftMessage", () => {
  it("names the workflow and its latest nodes", () => {
    expect(workflowDraftMessage(DSL)).toBe('Writing "Lead intake" · 4 nodes (…, Qualify, Save lead, result)');
  });

  it("counts a node whose label is not written yet, and skips field labels", () => {
    const cut = DSL.indexOf('"Qualify"') + 4;
    expect(workflowDraftMessage(DSL.slice(0, cut))).toBe('Writing "Lead intake" · 2 nodes (start)');
  });

  it("reads a workflow cut anywhere", () => {
    for (let end = 0; end < DSL.length; end += 7) {
      expect(workflowDraftMessage(DSL.slice(0, end))).toMatch(/^Writing/);
    }
  });
});

describe("streamingWorkflowProgress", () => {
  it("waits for the workflow JSON block", () => {
    expect(streamingWorkflowProgress("I will add a Slack step.")).toBeNull();
    expect(streamingWorkflowProgress(`Here:\n\`\`\`json\n${DSL.slice(0, 120)}`)).toBe(
      'Writing "Lead intake" · 1 node',
    );
  });
});
