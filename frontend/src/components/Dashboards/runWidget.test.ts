import { describe, expect, it } from "vitest";

import { runWidgetKind, runWidgetOption } from "@/components/Dashboards/runWidget";

describe("runWidgetKind", () => {
  it("says how the widget runs each workflow", () => {
    expect(runWidgetKind({ name: "Invoices", input_fields: [], file_input: { allowed_types: ["application/pdf"] } })).toBe(
      "takes a file",
    );
    expect(runWidgetKind({ name: "Quote", input_fields: [{ key: "vendor" }, { key: "amount" }] })).toBe(
      "asks for vendor, amount",
    );
    expect(runWidgetKind({ name: "Digest", input_fields: [] })).toBe("runs without input");
  });

  it("names the workflow in the option", () => {
    expect(runWidgetOption({ id: "w1", name: "Digest", input_fields: [] })).toEqual({
      value: "w1",
      label: "Digest · runs without input",
    });
  });
});
