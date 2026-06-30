export type SentryExpressionFieldKey =
  | "sentryOrganizationSlug"
  | "sentryProjectSlug"
  | "sentryTeamSlug"
  | "sentryIssueId"
  | "sentryEventId"
  | "sentryReleaseVersion"
  | "sentryName"
  | "sentrySlug"
  | "sentryPlatform"
  | "sentryStatus"
  | "sentryAssignedTo"
  | "sentryQuery"
  | "sentryStatsPeriod"
  | "sentryLimit"
  | "sentryReleaseProjects"
  | "sentryReleaseRefs";

export interface SentryExpressionField {
  key: SentryExpressionFieldKey;
  label: string;
}

const organizationOperations = new Set([
  "listProjects",
  "createProject",
  "listTeams",
  "createTeam",
  "listIssues",
  "listEvents",
  "getEvent",
  "listReleases",
  "getRelease",
  "createRelease",
]);

const limitedOperations = new Set([
  "listOrganizations",
  "listProjects",
  "listTeams",
  "listIssues",
  "listEvents",
  "listReleases",
]);

function appendOrganizationSlug(fields: SentryExpressionField[], operation: string): void {
  if (organizationOperations.has(operation)) {
    fields.push({ key: "sentryOrganizationSlug", label: "Organization Slug" });
  }
}

function appendLimit(fields: SentryExpressionField[], operation: string): void {
  if (limitedOperations.has(operation)) {
    fields.push({ key: "sentryLimit", label: "Limit" });
  }
}

/** Returns ordered expression-evaluate dialog slots for the given Sentry operation. */
export function getSentryExpressionFields(operation: string): SentryExpressionField[] {
  const op = operation || "listIssues";
  const fields: SentryExpressionField[] = [];

  appendOrganizationSlug(fields, op);

  switch (op) {
    case "listOrganizations":
      appendLimit(fields, op);
      break;
    case "listProjects":
    case "listTeams":
    case "listReleases":
      appendLimit(fields, op);
      break;
    case "createProject":
      fields.push({ key: "sentryTeamSlug", label: "Team Slug" });
      fields.push({ key: "sentryName", label: "Name" });
      fields.push({ key: "sentrySlug", label: "Slug" });
      fields.push({ key: "sentryPlatform", label: "Platform" });
      break;
    case "createTeam":
      fields.push({ key: "sentryName", label: "Name" });
      fields.push({ key: "sentrySlug", label: "Slug" });
      break;
    case "listIssues":
      fields.push({ key: "sentryProjectSlug", label: "Project Slug" });
      fields.push({ key: "sentryQuery", label: "Query" });
      fields.push({ key: "sentryStatsPeriod", label: "Stats Period" });
      appendLimit(fields, op);
      break;
    case "getIssue":
      fields.push({ key: "sentryIssueId", label: "Issue ID" });
      break;
    case "updateIssue":
      fields.push({ key: "sentryIssueId", label: "Issue ID" });
      fields.push({ key: "sentryStatus", label: "Status" });
      fields.push({ key: "sentryAssignedTo", label: "Assigned To" });
      break;
    case "listEvents":
      fields.push({ key: "sentryProjectSlug", label: "Project Slug" });
      fields.push({ key: "sentryQuery", label: "Query" });
      appendLimit(fields, op);
      break;
    case "getEvent":
      fields.push({ key: "sentryProjectSlug", label: "Project Slug" });
      fields.push({ key: "sentryEventId", label: "Event ID" });
      break;
    case "getRelease":
      fields.push({ key: "sentryReleaseVersion", label: "Release Version" });
      break;
    case "createRelease":
      fields.push({ key: "sentryReleaseVersion", label: "Release Version" });
      fields.push({ key: "sentryReleaseProjects", label: "Projects (JSON Array)" });
      fields.push({ key: "sentryReleaseRefs", label: "Refs (JSON Array)" });
      break;
    default:
      break;
  }

  return fields;
}
