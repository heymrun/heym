import { describe, expect, it } from "vitest";

import { getSentryExpressionFields } from "@/lib/sentryExpressionFields";

describe("getSentryExpressionFields", () => {
  it("includes filters and pagination for listIssues", () => {
    const keys = getSentryExpressionFields("listIssues").map((field) => field.key);

    expect(keys).toEqual([
      "sentryOrganizationSlug",
      "sentryProjectSlug",
      "sentryQuery",
      "sentryStatsPeriod",
      "sentryLimit",
    ]);
  });

  it("includes project creation fields", () => {
    const keys = getSentryExpressionFields("createProject").map((field) => field.key);

    expect(keys).toEqual([
      "sentryOrganizationSlug",
      "sentryTeamSlug",
      "sentryName",
      "sentrySlug",
      "sentryPlatform",
    ]);
  });

  it("includes issue update fields", () => {
    const keys = getSentryExpressionFields("updateIssue").map((field) => field.key);

    expect(keys).toEqual([
      "sentryIssueId",
      "sentryStatus",
      "sentryAssignedTo",
    ]);
  });

  it("includes release payload fields", () => {
    const keys = getSentryExpressionFields("createRelease").map((field) => field.key);

    expect(keys).toEqual([
      "sentryOrganizationSlug",
      "sentryReleaseVersion",
      "sentryReleaseProjects",
      "sentryReleaseRefs",
    ]);
  });
});
