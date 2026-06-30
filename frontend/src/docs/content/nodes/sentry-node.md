# Sentry Node

Use the Sentry node to automate Sentry organization, project, team, issue, event, and release operations from a workflow.

## Credential

Create a **Sentry** credential with an auth token. Leave Base URL empty for Sentry SaaS, or set the root URL for a self-hosted Sentry instance.

## Operations

- `listOrganizations`
- `listProjects`, `createProject`
- `listTeams`, `createTeam`
- `listIssues`, `getIssue`, `updateIssue`
- `listEvents`, `getEvent`
- `listReleases`, `getRelease`, `createRelease`

## Common Fields

| Field | Description |
| --- | --- |
| Credential | Sentry credential to use |
| Operation | Sentry action to run |
| Organization Slug | Sentry organization slug for project, team, issue, event, and release operations |
| Project Slug | Project slug for event operations and project-scoped filters |
| Limit | Page size for list operations, capped at 100 |

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
  "sentryIssueId": "$input.issue_id",
  "sentryStatus": "resolved"
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

## Outputs

List operations return `success`, `operation`, `count`, and the relevant collection such as `issues`, `events`, or `releases`. Single-resource operations return `issue`, `event`, `release`, `project`, or `team`.
