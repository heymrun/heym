import { describe, expect, it } from "vitest";

import { getHistoryStatusBadgeClass, HISTORY_STATUS_OPTIONS } from "./executionHistoryStatus";

describe("HISTORY_STATUS_OPTIONS", () => {
  it("starts with the unfiltered entry", () => {
    expect(HISTORY_STATUS_OPTIONS[0]).toEqual({ value: undefined, label: "All Statuses" });
  });

  it("offers success, error, cached and cancelled", () => {
    const values = HISTORY_STATUS_OPTIONS.map((option) => option.value);
    expect(values).toEqual([undefined, "success", "error", "cached", "cancelled"]);
  });

  it("has no duplicate values", () => {
    const values = HISTORY_STATUS_OPTIONS.map((option) => option.value);
    expect(new Set(values).size).toBe(values.length);
  });
});

describe("getHistoryStatusBadgeClass", () => {
  it("returns a badge for statuses the icon does not explain", () => {
    expect(getHistoryStatusBadgeClass("cached")).toContain("sky");
    expect(getHistoryStatusBadgeClass("failed")).toContain("red");
    expect(getHistoryStatusBadgeClass("skipped")).toContain("gray");
  });

  it("badges runs that never executed because of the concurrency limit", () => {
    expect(getHistoryStatusBadgeClass("expired")).toContain("amber");
    expect(getHistoryStatusBadgeClass("queue_full")).toContain("orange");
  });

  it("returns null for statuses without a badge", () => {
    expect(getHistoryStatusBadgeClass("success")).toBeNull();
    expect(getHistoryStatusBadgeClass("unknown")).toBeNull();
  });
});
