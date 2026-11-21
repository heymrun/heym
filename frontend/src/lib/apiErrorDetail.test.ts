import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import { apiErrorDetail } from "@/lib/apiErrorDetail";

function refused(status: number, data: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", config, null, {
    status,
    statusText: "",
    headers: {},
    config,
    data,
  });
}

describe("apiErrorDetail", () => {
  it("shows why the server refused the change", () => {
    const err = refused(400, {
      detail: "Cannot make 'sku' unique: more than one row has the value A-1",
    });

    expect(apiErrorDetail(err, "Failed to update columns")).toBe(
      "Cannot make 'sku' unique: more than one row has the value A-1",
    );
  });

  it("falls back when there is no message to show", () => {
    expect(apiErrorDetail(refused(422, { detail: [{ msg: "field required" }] }), "Failed")).toBe(
      "Failed",
    );
    expect(apiErrorDetail(new Error("Network Error"), "Failed")).toBe("Failed");
  });
});
