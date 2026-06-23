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
3. Paste the key into a new Linear credential in Heym.

Personal API keys act as the user who created them. Keep the key scoped to the workspaces and
teams the workflow needs.

## Operations

| Operation | Required fields | Output |
|-----------|-----------------|--------|
| Get Viewer | — | `viewer` |
| List Teams | Limit | `teams`, `count` |
| List Projects | Limit | `projects`, `count` |
| List Issues | Limit; optional Team ID and Project ID | `issues`, `count` |
| Get Issue | Issue ID or identifier such as `ENG-123` | `issue`, `identifier`, `url` |
| Create Issue | Team ID, Title | `issue`, `identifier`, `url` |
| Update Issue | Issue ID or identifier and at least one changed field | `issue`, `identifier`, `url` |
| Create Comment | Issue ID or identifier, Comment Body | `comment` |

All text fields support [expressions](../reference/expression-dsl.md).

## Issue fields

- **Team ID** and **Project ID** are Linear UUIDs. Use List Teams or List Projects to discover them.
- **State ID** is the workflow-state UUID used when updating an issue.
- **Assignee ID** is a Linear user UUID.
- **Priority** accepts `0` through `4`: no priority, urgent, high, normal, and low.
- Leave optional update fields empty to preserve their current values.

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

## Output

Every successful operation sets:

- `$linear.success`
- `$linear.operation`

List operations also expose `count`. Issue operations expose the complete Linear issue payload and
convenience fields such as `identifier` and `url`.

## Related

- [Credentials Tab](../tabs/credentials-tab.md)
- [Node Types](../reference/node-types.md)
- [Expression DSL](../reference/expression-dsl.md)
