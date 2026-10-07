import { describe, expect, it } from "vitest";

import { responseDetail } from "@/lib/responseDetail";

function apiError(detail: unknown): unknown {
  return { isAxiosError: true, response: { status: 400, data: { detail } } };
}

describe("responseDetail", () => {
  it("returns the API's detail message", () => {
    expect(responseDetail(apiError("Data table with this name already exists"))).toBe(
      "Data table with this name already exists",
    );
  });

  it("returns null when the detail is missing, blank or not a string", () => {
    expect(responseDetail(apiError(undefined))).toBeNull();
    expect(responseDetail(apiError("   "))).toBeNull();
    expect(responseDetail(apiError([{ loc: ["body"], msg: "field required" }]))).toBeNull();
  });

  it("returns null for errors that did not come from an API request", () => {
    expect(responseDetail(new Error("offline"))).toBeNull();
    expect(responseDetail({ response: { data: { detail: "not axios" } } })).toBeNull();
    expect(responseDetail(null)).toBeNull();
    expect(responseDetail("failed")).toBeNull();
  });
});
