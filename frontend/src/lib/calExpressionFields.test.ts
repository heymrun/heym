import { describe, expect, it } from "vitest";

import { getCalExpressionFields } from "@/lib/calExpressionFields";

describe("getCalExpressionFields", () => {
  it("returns no dynamic fields for list", () => {
    expect(getCalExpressionFields("listWebhooks")).toEqual([]);
  });

  it("returns body for create", () => {
    expect(getCalExpressionFields("createWebhook")).toEqual([
      { key: "calWebhook", label: "Webhook Data" },
    ]);
  });

  it("returns id and body in navigation order for update", () => {
    expect(getCalExpressionFields("updateWebhook").map((field) => field.key)).toEqual([
      "calWebhookId",
      "calWebhook",
    ]);
  });

  it("returns id for delete", () => {
    expect(getCalExpressionFields("deleteWebhook")).toEqual([
      { key: "calWebhookId", label: "Webhook ID" },
    ]);
  });
});
