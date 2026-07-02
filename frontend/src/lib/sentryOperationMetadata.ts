import type { WorkflowNodeData } from "@/types/workflow";

export type SentryOperation = NonNullable<WorkflowNodeData["sentryOperation"]>;

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
  | "sentryReleaseRefs";

export interface SentryFieldMetadata {
  key: SentryFieldKey;
  label: string;
}

export interface SentryOperationMetadata {
  value: SentryOperation;
  label: string;
  fields: SentryFieldMetadata[];
  requiredFields: SentryFieldKey[];
}

export const sentryOperationMetadata: SentryOperationMetadata[] = [
  {
    value: "listOrganizations",
    label: "List Organizations",
    fields: [{ key: "sentryLimit", label: "Limit" }],
    requiredFields: [],
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
    fields: [{ key: "sentryIssueId", label: "Issue ID" }],
    requiredFields: ["sentryIssueId"],
  },
  {
    value: "updateIssue",
    label: "Update Issue",
    fields: [
      { key: "sentryIssueId", label: "Issue ID" },
      { key: "sentryStatus", label: "Status" },
      { key: "sentryAssignedTo", label: "Assigned To" },
    ],
    requiredFields: ["sentryIssueId"],
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
];

const metadataByOperation = new Map(
  sentryOperationMetadata.map((metadata) => [metadata.value, metadata]),
);

export function getSentryOperationMetadata(
  operation: SentryOperation | string | undefined,
): SentryOperationMetadata {
  return metadataByOperation.get(operation as SentryOperation) ?? metadataByOperation.get("listIssues")!;
}

export function getSentryOperationOptions(): Array<{ value: SentryOperation; label: string }> {
  return sentryOperationMetadata.map(({ value, label }) => ({ value, label }));
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
