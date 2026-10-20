import { describe, expect, it } from "vitest";

import {
  HEYM_ALL_WORKFLOWS,
  heymWorkflowPickerOptions,
  heymWorkflowIdForOperation,
} from "./heymWorkflowPicker";

const WORKFLOWS = [
  { value: "w1", label: "One" },
  { value: "w2", label: "Two" },
];

describe("heymWorkflowPickerOptions", () => {
  it("lists All workflows first for the execution history", () => {
    const options = heymWorkflowPickerOptions("getExecutionHistory", WORKFLOWS);

    expect(options[0]).toEqual({ value: HEYM_ALL_WORKFLOWS, label: "All workflows" });
    expect(options.slice(1)).toEqual(WORKFLOWS);
  });

  it("keeps the empty choice first for the operations that need one workflow", () => {
    expect(heymWorkflowPickerOptions("getWorkflow", WORKFLOWS)).toEqual([
      { value: "", label: "Select a workflow..." },
      ...WORKFLOWS,
    ]);
  });
});

describe("heymWorkflowIdForOperation", () => {
  it("keeps All workflows for the execution history", () => {
    expect(heymWorkflowIdForOperation("getExecutionHistory", HEYM_ALL_WORKFLOWS)).toBe(
      HEYM_ALL_WORKFLOWS,
    );
  });

  it("clears All workflows when the operation cannot read them all", () => {
    expect(heymWorkflowIdForOperation("getWorkflow", HEYM_ALL_WORKFLOWS)).toBe("");
  });

  it("keeps a real workflow id whatever the operation", () => {
    expect(heymWorkflowIdForOperation("getWorkflow", "w1")).toBe("w1");
    expect(heymWorkflowIdForOperation("getExecutionHistory", "w1")).toBe("w1");
  });
});
