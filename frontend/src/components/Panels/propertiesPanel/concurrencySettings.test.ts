import { describe, expect, it } from "vitest";

import {
  parsePositiveInteger,
  toConcurrencyUpdatePayload,
  togglePatch,
} from "@/components/Panels/propertiesPanel/concurrencySettings";

describe("parsePositiveInteger", () => {
  it("returns null for empty, zero, negative and non-numeric input", () => {
    expect(parsePositiveInteger("")).toBeNull();
    expect(parsePositiveInteger("0")).toBeNull();
    expect(parsePositiveInteger("-3")).toBeNull();
    expect(parsePositiveInteger("abc")).toBeNull();
  });

  it("floors positive numbers", () => {
    expect(parsePositiveInteger("2.7")).toBe(2);
  });
});

describe("togglePatch", () => {
  it("turns the limit on at 1 and off at null", () => {
    expect(togglePatch(null)).toEqual({ concurrency_limit: 1 });
    expect(togglePatch(3)).toEqual({ concurrency_limit: null });
  });
});

describe("toConcurrencyUpdatePayload", () => {
  it("sends 0 to clear a field, because the server clears on 0", () => {
    expect(
      toConcurrencyUpdatePayload({ concurrency_limit: null, concurrency_max_queue: 5 }),
    ).toEqual({
      concurrency_limit: 0,
      concurrency_max_queue: 5,
    });
  });

  it("leaves out fields the patch does not touch", () => {
    expect(toConcurrencyUpdatePayload({ concurrency_max_wait_seconds: 30 })).toEqual({
      concurrency_max_wait_seconds: 30,
    });
  });
});
