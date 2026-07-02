import type { NodeData } from "@/types/workflow";

export type SentryOperation = NonNullable<NodeData["sentryOperation"]>;

export type SentryFieldKey =
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
  | "sentryReleaseRefs"
  | "sentryPayload";

export interface SentryFieldMetadata {
  key: SentryFieldKey;
  label: string;
}

export type SentryExpressionFieldKey = SentryFieldKey;
export type SentryExpressionField = SentryFieldMetadata;

export interface SentryOperationMetadata {
  value: SentryOperation;
  label: string;
  fields: SentryFieldMetadata[];
  requiredFields: SentryFieldKey[];
}

export interface SentryOperationOption {
  value: SentryOperation;
  label: string;
}

export interface SentryOperationOptionGroup {
  label: string;
  options: SentryOperationOption[];
}

export const sentryOperationMetadata: SentryOperationMetadata[] = [
  {
    value: "listOrganizations",
    label: "List Organizations",
    fields: [{ key: "sentryLimit", label: "Limit" }],
    requiredFields: [],
  },
  {
    value: "updateOrganization",
    label: "Update Organization",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryPayload", label: "Payload JSON" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryPayload"],
  },
  {
    value: "listProjects",
    label: "List Projects",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryLimit", label: "Limit" },
    ],
    requiredFields: ["sentryOrganizationSlug"],
  },
  {
    value: "createProject",
    label: "Create Project",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryTeamSlug", label: "Team Slug" },
      { key: "sentryName", label: "Name" },
      { key: "sentrySlug", label: "Slug" },
      { key: "sentryPlatform", label: "Platform" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryTeamSlug", "sentryName"],
  },
  {
    value: "getProject",
    label: "Get Project",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryProjectSlug", label: "Project Slug" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryProjectSlug"],
  },
  {
    value: "updateProject",
    label: "Update Project",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryProjectSlug", label: "Project Slug" },
      { key: "sentryPayload", label: "Payload JSON" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryProjectSlug", "sentryPayload"],
  },
  {
    value: "deleteProject",
    label: "Delete Project",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryProjectSlug", label: "Project Slug" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryProjectSlug"],
  },
  {
    value: "listTeams",
    label: "List Teams",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryLimit", label: "Limit" },
    ],
    requiredFields: ["sentryOrganizationSlug"],
  },
  {
    value: "createTeam",
    label: "Create Team",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryName", label: "Name" },
      { key: "sentrySlug", label: "Slug" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryName"],
  },
  {
    value: "updateTeam",
    label: "Update Team",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryTeamSlug", label: "Team Slug" },
      { key: "sentryPayload", label: "Payload JSON" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryTeamSlug", "sentryPayload"],
  },
  {
    value: "deleteTeam",
    label: "Delete Team",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryTeamSlug", label: "Team Slug" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryTeamSlug"],
  },
  {
    value: "listIssues",
    label: "List Issues",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryProjectSlug", label: "Project ID or Slug" },
      { key: "sentryQuery", label: "Query" },
      { key: "sentryStatsPeriod", label: "Stats Period" },
      { key: "sentryLimit", label: "Limit" },
    ],
    requiredFields: ["sentryOrganizationSlug"],
  },
  {
    value: "getIssue",
    label: "Get Issue",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryIssueId", label: "Issue ID" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryIssueId"],
  },
  {
    value: "updateIssue",
    label: "Update Issue",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryIssueId", label: "Issue ID" },
      { key: "sentryStatus", label: "Status" },
      { key: "sentryAssignedTo", label: "Assigned To" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryIssueId"],
  },
  {
    value: "deleteIssue",
    label: "Delete Issue",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryIssueId", label: "Issue ID" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryIssueId"],
  },
  {
    value: "listEvents",
    label: "List Events",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryProjectSlug", label: "Project Slug" },
      { key: "sentryQuery", label: "Query" },
      { key: "sentryLimit", label: "Limit" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryProjectSlug"],
  },
  {
    value: "getEvent",
    label: "Get Event",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryProjectSlug", label: "Project Slug" },
      { key: "sentryEventId", label: "Event ID" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryProjectSlug", "sentryEventId"],
  },
  {
    value: "listReleases",
    label: "List Releases",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryLimit", label: "Limit" },
    ],
    requiredFields: ["sentryOrganizationSlug"],
  },
  {
    value: "getRelease",
    label: "Get Release",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryReleaseVersion", label: "Release Version" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryReleaseVersion"],
  },
  {
    value: "createRelease",
    label: "Create Release",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryReleaseVersion", label: "Release Version" },
      { key: "sentryReleaseProjects", label: "Projects (JSON Array)" },
      { key: "sentryReleaseRefs", label: "Refs (JSON Array)" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryReleaseVersion"],
  },
  {
    value: "updateRelease",
    label: "Update Release",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryReleaseVersion", label: "Release Version" },
      { key: "sentryPayload", label: "Payload JSON" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryReleaseVersion", "sentryPayload"],
  },
  {
    value: "deleteRelease",
    label: "Delete Release",
    fields: [
      { key: "sentryOrganizationSlug", label: "Organization Slug" },
      { key: "sentryReleaseVersion", label: "Release Version" },
    ],
    requiredFields: ["sentryOrganizationSlug", "sentryReleaseVersion"],
  },
];

const metadataByOperation = new Map(
  sentryOperationMetadata.map((metadata) => [metadata.value, metadata]),
);

const sentryOperationGroupDefinitions: Array<{
  label: string;
  operations: SentryOperation[];
}> = [
  { label: "Event", operations: ["getEvent", "listEvents"] },
  { label: "Issue", operations: ["deleteIssue", "getIssue", "listIssues", "updateIssue"] },
  { label: "Organization", operations: ["listOrganizations", "updateOrganization"] },
  {
    label: "Project",
    operations: ["createProject", "deleteProject", "getProject", "listProjects", "updateProject"],
  },
  {
    label: "Release",
    operations: [
      "createRelease",
      "deleteRelease",
      "getRelease",
      "listReleases",
      "updateRelease",
    ],
  },
  { label: "Team", operations: ["createTeam", "deleteTeam", "listTeams", "updateTeam"] },
];

export function getSentryOperationMetadata(
  operation: SentryOperation | string | undefined,
): SentryOperationMetadata {
  return metadataByOperation.get(operation as SentryOperation) ?? metadataByOperation.get("listIssues")!;
}

export function getSentryOperationOptions(): SentryOperationOption[] {
  return sentryOperationMetadata
    .map(({ value, label }) => ({ value, label }))
    .toSorted((left, right) => left.value.localeCompare(right.value));
}

export function getSentryOperationGroups(): SentryOperationOptionGroup[] {
  return sentryOperationGroupDefinitions.map((group) => ({
    label: group.label,
    options: group.operations.map((operation) => {
      const metadata = getSentryOperationMetadata(operation);
      return { value: metadata.value, label: metadata.label };
    }),
  }));
}

export function isSentryFieldVisible(
  operation: SentryOperation | string | undefined,
  field: SentryFieldKey,
): boolean {
  return getSentryOperationMetadata(operation).fields.some((fieldMetadata) => fieldMetadata.key === field);
}

export function isSentryFieldRequired(
  operation: SentryOperation | string | undefined,
  field: SentryFieldKey,
): boolean {
  return getSentryOperationMetadata(operation).requiredFields.includes(field);
}

/** Returns ordered expression-evaluate dialog slots for the given Sentry operation. */
export function getSentryExpressionFields(operation: string): SentryExpressionField[] {
  return [...getSentryOperationMetadata(operation).fields];
}
