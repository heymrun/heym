import { describe, expect, it } from "vitest";

import { getSentryExpressionFields } from "@/lib/sentryExpressionFields";
import {
  getSentryOperationGroups,
  sentryOperationMetadata,
} from "@/lib/sentryExpressionFields";

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
      "sentryOrganizationSlug",
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

  it("includes update payload fields", () => {
    const projectKeys = getSentryExpressionFields("updateProject").map((field) => field.key);
    const releaseKeys = getSentryExpressionFields("updateRelease").map((field) => field.key);

    expect(projectKeys).toEqual([
      "sentryOrganizationSlug",
      "sentryProjectSlug",
      "sentryPayload",
    ]);
    expect(releaseKeys).toEqual([
      "sentryOrganizationSlug",
      "sentryReleaseVersion",
      "sentryPayload",
    ]);
  });

  it("groups every operation exactly once", () => {
    const groupedOperations = getSentryOperationGroups().flatMap((group) =>
      group.options.map((option) => option.value),
    );
    const metadataOperations = sentryOperationMetadata.map((metadata) => metadata.value);

    expect(new Set(groupedOperations).size).toBe(groupedOperations.length);
    expect(groupedOperations.toSorted()).toEqual(metadataOperations.toSorted());
  });

  it("keeps required fields visible for every operation", () => {
    sentryOperationMetadata.forEach((metadata) => {
      const visibleFields = new Set(metadata.fields.map((field) => field.key));

      metadata.requiredFields.forEach((fieldKey) => {
        expect(visibleFields.has(fieldKey)).toBe(true);
      });
    });
  });
});
