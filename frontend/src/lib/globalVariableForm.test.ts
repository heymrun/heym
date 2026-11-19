import { describe, expect, it } from "vitest";

import { globalVariableSavePayload } from "./globalVariableForm";

describe("globalVariableSavePayload", () => {
  it("sends Auto as auto, so an edit re-infers the type instead of keeping the old one", () => {
    expect(globalVariableSavePayload(" count ", [1, 2], "auto")).toEqual({
      name: "count",
      value: [1, 2],
      value_type: "auto",
    });
  });

  it("sends an explicit type as chosen", () => {
    expect(globalVariableSavePayload("limit", 5, "number")).toEqual({
      name: "limit",
      value: 5,
      value_type: "number",
    });
  });
});
