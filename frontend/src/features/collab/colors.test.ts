import { describe, expect, it } from "vitest";

import { COLLAB_COLORS, collabColor, collabTextColor } from "@/features/collab/colors";

describe("collabColor", () => {
  it("gives a user the same palette color every time", () => {
    expect(collabColor("user-1")).toBe(collabColor("user-1"));
    expect(COLLAB_COLORS).toContain(collabColor("user-1"));
  });

  it("keeps label text readable on light and dark colors", () => {
    expect(collabTextColor("#EAB308")).toBe("#111827");
    expect(collabTextColor("#84CC16")).toBe("#111827");
    expect(collabTextColor("#6366F1")).toBe("#FFFFFF");
    expect(collabTextColor("#EF4444")).toBe("#FFFFFF");
  });

  it("spreads users across the palette", () => {
    const used = new Set(Array.from({ length: 200 }, (_, index) => collabColor(`user-${index}`)));
    expect(used.size).toBeGreaterThanOrEqual(10);
  });
});
