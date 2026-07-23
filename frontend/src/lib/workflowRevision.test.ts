import { describe, expect, it } from "vitest";

import { isRevisionAfter, pickPreferredRevision } from "@/lib/workflowRevision";

describe("workflowRevision", () => {
  it("orders timestamps that only differ in sub-milliseconds", () => {
    const earlier = "2026-07-23T18:49:20.123456+00:00";
    const later = "2026-07-23T18:49:20.123789+00:00";

    expect(Date.parse(earlier)).toBe(Date.parse(later));
    expect(isRevisionAfter(later, earlier)).toBe(true);
    expect(isRevisionAfter(earlier, later)).toBe(false);
    expect(isRevisionAfter(earlier, earlier)).toBe(false);
  });

  it("orders timestamps across different milliseconds", () => {
    expect(
      isRevisionAfter(
        "2026-07-23T18:49:21.000Z",
        "2026-07-23T18:49:20.999Z",
      ),
    ).toBe(true);
  });

  it("prefers the primary revision when equal or newer", () => {
    const earlier = "2026-07-23T18:49:20.123456+00:00";
    const later = "2026-07-23T18:49:20.123789+00:00";

    expect(pickPreferredRevision(later, earlier)).toBe(later);
    expect(pickPreferredRevision(earlier, later)).toBe(later);
    expect(pickPreferredRevision(earlier, earlier)).toBe(earlier);
    expect(pickPreferredRevision(null, earlier)).toBe(earlier);
    expect(pickPreferredRevision(later, null)).toBe(later);
  });
});
