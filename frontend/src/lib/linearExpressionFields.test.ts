import { describe, expect, it } from "vitest";

import { getLinearExpressionFields } from "@/lib/linearExpressionFields";

describe("getLinearExpressionFields", () => {
  it("includes pagination and filter fields for listIssues", () => {
    const keys = getLinearExpressionFields("listIssues", { returnAll: false }).map(
      (field) => field.key,
    );

    expect(keys).toEqual([
      "linearLimit",
      "linearAfter",
      "linearTeamId",
      "linearProjectId",
    ]);
  });

  it("omits pagination fields when returnAll is enabled", () => {
    const keys = getLinearExpressionFields("listIssues", { returnAll: true }).map(
      (field) => field.key,
    );

    expect(keys).toEqual(["linearTeamId", "linearProjectId"]);
  });

  it("includes issue mutation fields for createIssue", () => {
    const keys = getLinearExpressionFields("createIssue").map((field) => field.key);

    expect(keys).toEqual([
      "linearTeamId",
      "linearProjectId",
      "linearTitle",
      "linearDescription",
      "linearStateId",
      "linearAssigneeId",
      "linearPriority",
    ]);
  });

  it("includes comment fields for createComment", () => {
    const keys = getLinearExpressionFields("createComment").map((field) => field.key);

    expect(keys).toEqual([
      "linearIssueId",
      "linearCommentBody",
      "linearParentCommentId",
    ]);
  });
});
