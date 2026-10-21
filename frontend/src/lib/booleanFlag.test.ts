import { describe, expect, it } from "vitest";

import { isFlagOn } from "@/lib/booleanFlag";

describe("isFlagOn", () => {
  it.each([true, "true", " TRUE ", "1", "yes", "on", 1])("treats %j as on", (value) => {
    expect(isFlagOn(value)).toBe(true);
  });

  it.each([false, "false", "0", "no", "off", "", "maybe", 0, null, undefined])(
    "treats %j as off",
    (value) => {
      expect(isFlagOn(value)).toBe(false);
    },
  );
});
