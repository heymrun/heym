import { describe, expect, it } from "vitest";

import { clampAssistantInputHeight } from "@/composables/useAssistantInputResize";

describe("clampAssistantInputHeight", () => {
  it("never goes below the default height", () => {
    expect(clampAssistantInputHeight(20, 60, 800, 100)).toBe(60);
  });

  it("keeps the whole input area within 60% of the panel", () => {
    // 60% of 800 is 480; the buttons and padding around the box take 100 of it.
    expect(clampAssistantInputHeight(900, 60, 800, 100)).toBe(380);
  });

  it("keeps a height between the limits as it is", () => {
    expect(clampAssistantInputHeight(200, 60, 800, 100)).toBe(200);
  });

  it("stays at the default when the panel is too small to grow", () => {
    expect(clampAssistantInputHeight(200, 60, 200, 100)).toBe(60);
  });
});
