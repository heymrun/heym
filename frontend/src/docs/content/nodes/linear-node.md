# Linear Node

The **Linear** node connects workflows to the Linear GraphQL API for issue and workspace automation.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Credential | Linear personal API key |
| Output | `$nodeLabel.*` |

## Credential

Create a **Linear** credential in the [Credentials Tab](../tabs/credentials-tab.md):

1. In Linear, open **Settings → Security & Access → Personal API keys**.
2. Create a key with access to the workspace you want to automate.
3. Paste the key into a new Linear credential in Heym and use **Test Connection** to verify it.

Personal API keys act as the user who created them. Keep the key scoped to the workspaces and
teams the workflow needs.

## Operations

| Operation | Required fields | Output |
|-----------|-----------------|--------|
| Get Viewer | — | `viewer` |
| List Teams | Limit; optional After Cursor | `teams`, `count`, `pageInfo` |
| List Projects | Limit; optional After Cursor | `projects`, `count`, `pageInfo` |
| List Issues | Limit; optional Team ID, Project ID, After Cursor | `issues`, `count`, `pageInfo` |
| List Workflow States | Team ID | `states`, `count` |
| List Team Members | Team ID, Limit; optional After Cursor | `members`, `count`, `pageInfo` |
| Get Issue | Issue ID or identifier such as `ENG-123` | `issue`, `identifier`, `url` |
| Create Issue | Team ID, Title | `issue`, `identifier`, `url` |
| Update Issue | Issue ID or identifier and at least one changed field | `issue`, `identifier`, `url` |
| Create Comment | Issue ID or identifier, Comment Body | `comment` |

All text fields support [expressions](../reference/expression-dsl.md).

## Issue fields

- **Team ID** and **Project ID** are Linear UUIDs. Use List Teams or List Projects to discover them.
- **State ID** is the workflow-state UUID used when updating an issue. Use List Workflow States to discover it.
- **Assignee ID** is a Linear user UUID. Use List Team Members to discover it.
- **Priority** accepts `0` through `4`: no priority, urgent, high, normal, and low.
- Leave optional update fields empty to preserve their current values.
- Set an update field to `null` to clear description, project, assignee, or state.

## Pagination

List operations return `pageInfo.hasNextPage` and `pageInfo.endCursor`. Pass the cursor into
**After Cursor** on the next node run to fetch the next page.

## Examples

Create an issue from upstream input:

- Operation: `Create Issue`
- Team ID: `team UUID`
- Title: `$input.title`
- Description: `$input.description`
- Priority: `2`

Add a comment to a created issue:

- Operation: `Create Comment`
- Issue ID: `$createLinearIssue.issue.id`
- Comment Body: `$input.comment`

Paginate through team members:

- Operation: `List Team Members`
- Team ID: `$listTeams.teams[0].id`
- Limit: `50`
- After Cursor: `$listTeamMembers.pageInfo.endCursor` on the next run when `hasNextPage` is true

Discover workflow state IDs before updating an issue:

- Operation: `List Workflow States`
- Team ID: `$listTeams.teams[0].id`
- Then use `$listStates.states[0].id` as **State ID** in **Update Issue**

## Output

Every successful operation sets:

- `$linear.success`
- `$linear.operation`

List operations also expose `count` and, where applicable, `pageInfo`. Issue operations expose the
complete Linear issue payload and convenience fields such as `identifier` and `url`.

## Related

- [Credentials Tab](../tabs/credentials-tab.md)
- [Node Types](../reference/node-types.md)
- [Expression DSL](../reference/expression-dsl.md)
