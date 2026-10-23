import { describe, expect, it } from "vitest";

import type { HitlSource } from "@/types/dashboard";
import {
  ALL_CHOICE,
  MISSING_STEP_LABEL,
  UNKNOWN_WORKFLOW_LABEL,
  chooseStep,
  chooseWorkflow,
  openableWorkflowId,
  sameFilter,
  stepChoices,
  stepValue,
  workflowChoices,
  workflowValue,
} from "@/components/Dashboards/hitlFilter";

const invoices: HitlSource = {
  workflow_id: "wf-invoices",
  workflow_name: "Invoices",
  steps: [
    { node_id: "approver", label: "Approver", kind: "agent" },
    { node_id: "finance", label: "Ask finance", kind: "slack" },
  ],
};
const hiring: HitlSource = {
  workflow_id: "wf-hiring",
  workflow_name: "Hiring",
  steps: [{ node_id: "screen", label: "Screener", kind: "agent" }],
};
const sources = [invoices, hiring];

describe("workflowChoices", () => {
  it("offers every workflow after All workflows", () => {
    expect(workflowChoices(sources, null)).toEqual([
      { value: ALL_CHOICE, label: "All workflows" },
      { value: "wf-invoices", label: "Invoices" },
      { value: "wf-hiring", label: "Hiring" },
    ]);
  });

  it("keeps a stored workflow the editor cannot see, without naming it", () => {
    const choices = workflowChoices(sources, { workflow_id: "wf-other", node_id: null });
    expect(choices.at(-1)).toEqual({ value: "wf-other", label: UNKNOWN_WORKFLOW_LABEL });
  });
});

describe("stepChoices", () => {
  it("offers nothing until a workflow is chosen", () => {
    expect(stepChoices(sources, null)).toEqual([]);
  });

  it("leads several steps with All agents and marks Slack steps", () => {
    expect(stepChoices(sources, { workflow_id: "wf-invoices", node_id: null })).toEqual([
      { value: ALL_CHOICE, label: "All agents" },
      { value: "approver", label: "Approver" },
      { value: "finance", label: "Ask finance (Slack)" },
    ]);
  });

  it("offers a single chosen step alone", () => {
    expect(stepChoices(sources, { workflow_id: "wf-hiring", node_id: "screen" })).toEqual([
      { value: "screen", label: "Screener" },
    ]);
  });

  it("keeps a removed step so it can be changed", () => {
    const choices = stepChoices(sources, { workflow_id: "wf-hiring", node_id: "gone" });
    expect(choices.at(-1)).toEqual({ value: "gone", label: MISSING_STEP_LABEL });
  });

  it("hides the steps of a workflow the editor cannot see", () => {
    expect(stepChoices(sources, { workflow_id: "wf-other", node_id: "x" })).toEqual([]);
  });
});

describe("choosing", () => {
  it("picks the only step of a workflow with one", () => {
    expect(chooseWorkflow(sources, null, "wf-hiring")).toEqual({
      workflow_id: "wf-hiring",
      node_id: "screen",
    });
  });

  it("shows every step of a workflow with several", () => {
    expect(chooseWorkflow(sources, null, "wf-invoices")).toEqual({
      workflow_id: "wf-invoices",
      node_id: null,
    });
  });

  it("goes back to every review with All workflows", () => {
    const current = { workflow_id: "wf-hiring", node_id: "screen" };
    expect(chooseWorkflow(sources, current, ALL_CHOICE)).toBeNull();
    expect(chooseWorkflow(sources, current, undefined)).toBeNull();
  });

  it("keeps the step when the same workflow is picked again", () => {
    const current = { workflow_id: "wf-invoices", node_id: "finance" };
    expect(chooseWorkflow(sources, current, "wf-invoices")).toBe(current);
  });

  it("narrows to a step and widens back with All agents", () => {
    const current = { workflow_id: "wf-invoices", node_id: null };
    const narrowed = chooseStep(current, "finance");
    expect(narrowed).toEqual({ workflow_id: "wf-invoices", node_id: "finance" });
    expect(chooseStep(narrowed, ALL_CHOICE)).toEqual(current);
  });

  it("reads the selects' values from the filter", () => {
    expect(workflowValue(null)).toBe(ALL_CHOICE);
    expect(stepValue({ workflow_id: "wf-invoices", node_id: null })).toBe(ALL_CHOICE);
    expect(stepValue({ workflow_id: "wf-invoices", node_id: "finance" })).toBe("finance");
  });
});

describe("openableWorkflowId", () => {
  it("links only a chosen workflow the editor can open", () => {
    expect(openableWorkflowId(sources, null)).toBeNull();
    expect(openableWorkflowId(sources, { workflow_id: "wf-hiring", node_id: null })).toBe("wf-hiring");
    expect(openableWorkflowId(sources, { workflow_id: "wf-other", node_id: null })).toBeNull();
  });
});

describe("sameFilter", () => {
  it("compares workflow and step", () => {
    expect(sameFilter(null, null)).toBe(true);
    expect(sameFilter({ workflow_id: "a", node_id: null }, { workflow_id: "a", node_id: null })).toBe(true);
    expect(sameFilter({ workflow_id: "a", node_id: "x" }, { workflow_id: "a", node_id: null })).toBe(false);
    expect(sameFilter({ workflow_id: "a", node_id: null }, null)).toBe(false);
  });
});
