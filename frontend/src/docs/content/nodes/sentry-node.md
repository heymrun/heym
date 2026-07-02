# Sentry Node

Use the Sentry node to automate Sentry organization, project, team, issue, event, and release operations from a workflow.

## Credential

Create a **Sentry** credential with an auth token. Leave Base URL empty for Sentry SaaS, or set the root URL for a self-hosted Sentry instance.

## Operations

- `createProject`, `createRelease`, `createTeam`
- `deleteIssue`, `deleteProject`, `deleteRelease`, `deleteTeam`
- `getEvent`, `getIssue`, `getProject`, `getRelease`
- `listEvents`, `listIssues`, `listOrganizations`, `listProjects`, `listReleases`, `listTeams`
- `updateIssue`, `updateOrganization`, `updateProject`, `updateRelease`, `updateTeam`

`createIssue` and `createOrganization` are not exposed because Sentry does not document public REST endpoints for them.

## Common Fields

| Field | Description |
| --- | --- |
| Credential | Sentry credential to use |
| Operation | Sentry action to run |
| Organization Slug | Sentry organization slug for organization update and project, team, issue, event, and release operations |
| Project Slug | Project slug for project get/update/delete and event operations; project slug or ID for issue filters |
| Team Slug | Team slug for project creation and team update/delete operations |
| Issue ID | Issue ID for issue get/update/delete operations |
| Event ID | Event ID for event lookup operations |
| Release Version | Release version for release get/update/delete operations |
| Name | Project or team name for create operations |
| Slug | Optional project or team slug for create operations |
| Platform | Optional Sentry platform for project creation |
| Status / Assigned To | Issue update fields. At least one is required for `updateIssue` |
| Query | Sentry search query. Omit it for unresolved issues, or set it to an empty string to fetch all issues |
| Limit | Result limit for list operations, capped at 1,000 total results |
| Release Projects JSON | JSON array of project slugs for release creation |
| Release Refs JSON | JSON array of repository/commit objects for release creation |
| Payload JSON | JSON object for update organization, project, release, and team operations |

## Examples

List unresolved issues:

```json
{
  "sentryOperation": "listIssues",
  "sentryOrganizationSlug": "acme",
  "sentryProjectSlug": "web-app",
  "sentryQuery": "is:unresolved level:error",
  "sentryStatsPeriod": "14d",
  "sentryLimit": "25"
}
```

Resolve an issue:

```json
{
  "sentryOperation": "updateIssue",
  "sentryOrganizationSlug": "acme",
  "sentryIssueId": "$input.issue_id",
  "sentryStatus": "resolved"
}
```

Delete an issue:

```json
{
  "sentryOperation": "deleteIssue",
  "sentryOrganizationSlug": "acme",
  "sentryIssueId": "$input.issue_id"
}
```

Create a release:

```json
{
  "sentryOperation": "createRelease",
  "sentryOrganizationSlug": "acme",
  "sentryReleaseVersion": "web-app@1.2.3",
  "sentryReleaseProjects": "[\"web-app\"]"
}
```

Update a project:

```json
{
  "sentryOperation": "updateProject",
  "sentryOrganizationSlug": "acme",
  "sentryProjectSlug": "web-app",
  "sentryPayload": "{\"name\":\"Web App\"}"
}
```

## Outputs

List operations return `success`, `operation`, `count`, and the relevant collection such as `organizations`, `projects`, `teams`, `issues`, `events`, or `releases`. Single-resource operations return `organization`, `issue`, `event`, `release`, `project`, or `team`. Delete operations return the relevant resource key with `deleted: true` and identifying fields.
