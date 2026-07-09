# Jira Node

The **Jira** node connects workflows to the Jira REST API for project, issue, comment, attachment, user, notification, and transition automation. The default operation is **Search Issues**.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Credential | Jira (Cloud email/API token or Data Center username/password, base URL, deployment mode, optional REST API version) |
| Output | `$nodeLabel.*` |

## Credential

Create a **Jira** credential in the [Credentials Tab](../tabs/credentials-tab.md). Stored config keys are `email`, `api_token`, `base_url`, `deployment`, and optional `api_version`. For Jira Cloud, `email` stores the Atlassian account email and `api_token` stores the Atlassian API token. For Jira Data Center / Server, those same keys store the Basic auth username and password. See [Third-Party Integrations](../reference/integrations.md#jira) for setup steps.

| Field | Config key | Description |
| --- | --- | --- |
| Jira Email / Username | `email` | Jira Cloud Atlassian account email, or Jira Data Center / Server username |
| API Token / Password | `api_token` | Jira Cloud Atlassian API token, or Jira Data Center / Server password for Basic auth |
| Base URL | `base_url` | Jira site URL, for example `https://your-domain.atlassian.net` |
| Deployment | `deployment` | `cloud` for Jira Cloud or `data_center` for Jira Data Center / Server |
| REST API Version | `api_version` | Defaults to `3` for Jira Cloud. Data Center / Server uses REST API v2 |

Data Center / Server personal access tokens and Bearer auth are not supported by the Jira credential yet.

Use **Test Connection** to verify the credential against the current Jira user.

## Operations

| Operation | Required fields | Output |
| --- | --- | --- |
| Get Myself | — | `user` |
| List Projects | Optional Limit, Start At | `projects`, `count`, `pagination` |
| Search Issues | Optional JQL, Issue Fields, Limit, Next Page Token, Start At | `issues`, `count`, `pagination` |
| Get Issue | Issue Key or ID | `issue`, `key` |
| Create Issue | Project Key, Summary | `issue`, `key` |
| Update Issue | Issue Key or ID and at least one changed field | `issue`, `key` |
| Delete Issue | Issue Key or ID | `deleted` |
| Get Issue Changelog | Issue Key or ID; optional Limit, Start At | `changelog`, `count`, `pagination` |
| Notify Issue | Issue Key or ID, Subject, Text Body | `notified` |
| List Comments | Issue Key or ID; optional Limit, Start At | `comments`, `count`, `pagination` |
| Create Comment | Issue Key or ID, Comment Body | `comment` |
| Get Comment | Issue Key or ID, Comment ID | `comment` |
| Update Comment | Issue Key or ID, Comment ID, Comment Body | `comment` |
| Delete Comment | Issue Key or ID, Comment ID | `deleted` |
| Add Attachment | Issue Key or ID, Filename, Base64 content | `attachments`, `count` |
| Get Attachment | Attachment ID; optional Include Binary | `attachment` |
| List Attachments | Issue Key or ID; optional Limit, Start At, Include Binary | `attachments`, `count`, `pagination` |
| Delete Attachment | Attachment ID | `deleted` |
| List Transitions | Issue Key or ID | `transitions`, `count` |
| Transition Issue | Issue Key or ID, Transition ID | `transition`, `issue`, `key` |
| Get User | Account ID / Username | `user` |
| Create User | User Email | `user` |
| Delete User | Account ID / Username | `deleted` |

Expression-capable text fields support [expressions](../reference/expression-dsl.md) such as `$input.text`. `jiraIncludeBinary` is a boolean toggle and does not support expressions, but it can be marked as agent-provided when the Jira node is attached to an Agent tool handle.

## Issue and update fields

- **Project Key** is the short project key such as `ENG`. Use List Projects to discover keys.
- **Issue Key or ID** accepts keys such as `ENG-123` or numeric issue IDs. Use Search Issues or List Projects to discover values.
- **Transition ID** comes from List Transitions. Each transition object includes an `id` field.
- **Comment ID** and **Attachment ID** come from List Comments, List Attachments, or prior create/get responses.
- **Account ID / Username** is the Jira Cloud `accountId` value or the Jira Data Center / Server username. Get Myself or Get User can help you discover it.
- Issue **description** and comment **body** text are sent as Atlassian Document Format on REST
  API v3; when the credential deployment is Data Center / Server, they are sent as plain text.
  In v3, newline characters become separate paragraphs.
- **Get Issue Changelog** uses Jira Cloud's paginated changelog endpoint. For Data Center / Server, it reads expanded issue changelog data and applies the configured offset/limit to the returned histories.
- On **Update Issue**, leave optional fields empty to preserve their current values.
- Set **Description** or **Assignee Account ID / Username** to `null` on update to clear those fields. Labels cannot be cleared with `null`.
- **Recipients JSON** on Notify Issue defaults to `{"assignee":true}` when omitted. Common keys include `assignee`, `reporter`, `watchers`, and `voters` (for example `{"assignee":true,"watchers":true}`).
- **Add Attachment** accepts raw base64 or data URL content and is limited by the platform file size setting (default 99 MB).

## Pagination

- **Search Issues** uses cursor pagination via `jiraNextPageToken` for Jira Cloud. Read `pagination.nextPageToken` from the previous run and pass it into the next Search Issues node.
- **Search Issues** uses offset pagination via `jiraStartAt` for Jira Data Center / Server. Read `pagination.startAt`, `pagination.maxResults`, and `pagination.total` to calculate the next page.
- **List Projects**, **Get Issue Changelog**, **List Comments**, and **List Attachments** use offset pagination with `jiraLimit` and `jiraStartAt`. Paged results return `pagination.startAt`, `pagination.maxResults`, `pagination.total`, and `pagination.isLast`.
- **List Attachments** fetches all attachments from the issue first, then slices the result client-side. Pagination fields still describe the returned page, but large issues may incur an extra fetch cost.
- **List Transitions** does not paginate.

## Key Fields

| Field | Used by | Notes |
| --- | --- | --- |
| `credentialId` | All operations | Owned Jira credential UUID |
| `jiraOperation` | All operations | Defaults to `searchIssues` |
| `jiraProjectKey` | Create Issue | Project key such as `ENG` |
| `jiraIssueKey` | Issue, comment, attachment, notification, and transition operations | Issue key such as `ENG-123` or numeric issue ID |
| `jiraIssueType` | Create Issue | Defaults to `Task` |
| `jiraIssueTypeId` | Create Issue | Optional issue type ID; overrides `jiraIssueType` when set |
| `jiraSummary` | Create/Update Issue | Required for Create Issue |
| `jiraDescription` | Create/Update Issue | Sent as ADF on REST API v3 or plain text on REST API v2; use `null` on update to clear description |
| `jiraJql` | Search Issues | Defaults to `updated >= -30d ORDER BY updated DESC` |
| `jiraFields` | Search Issues | Optional JSON array or comma-separated issue fields; defaults to `key`, `summary`, `status`, `assignee`, and `issuetype` when empty |
| `jiraAssigneeAccountId` | Create/Update Issue | Jira Cloud accountId or Data Center / Server username; use `null` on update to clear assignee |
| `jiraLabels` | Create/Update Issue | JSON array or comma-separated text |
| `jiraCommentBody` | Create/Update Comment | Sent as ADF on REST API v3 or plain text on REST API v2 |
| `jiraCommentId` | Get/Update/Delete Comment | Jira comment ID |
| `jiraTransitionId` | Transition Issue | Discover with List Transitions |
| `jiraAttachmentId` | Get/Delete Attachment | Jira attachment ID |
| `jiraAttachmentFilename` | Add Attachment | Uploaded filename |
| `jiraAttachmentBase64` | Add Attachment | Raw base64 or data URL content; subject to file size limit |
| `jiraAttachmentMimeType` | Add Attachment | Optional MIME type; inferred from filename when empty |
| `jiraIncludeBinary` | Get/List Attachment | Boolean toggle; adds `content_base64` when enabled |
| `jiraNotifySubject` | Notify Issue | Required notification subject |
| `jiraNotifyTextBody` | Notify Issue | Required plain-text notification body |
| `jiraNotifyHtmlBody` | Notify Issue | Optional HTML body |
| `jiraNotifyTo` | Notify Issue | Recipients JSON; defaults to `{"assignee":true}` |
| `jiraAccountId` | Get/Delete User | Jira Cloud accountId or Data Center / Server username |
| `jiraUserEmail` | Create User | New user email address |
| `jiraUsername` | Create User | Optional Data Center / Server username; falls back to `jiraUserEmail` |
| `jiraUserDisplayName` | Create User | Optional display name |
| `jiraUserProducts` | Create User | JSON array or comma-separated product keys; Jira Cloud only |
| `jiraLimit` | Search Issues, List Projects, Get Issue Changelog, List Comments, List Attachments | Defaults to `50`; range 1–100 |
| `jiraStartAt` | Search Issues on Data Center / Server, List Projects, Get Issue Changelog, List Comments, List Attachments | Offset pagination start index |
| `jiraNextPageToken` | Search Issues on Jira Cloud | Cursor token from a previous search response |

## Examples

Create an issue from upstream input:

- Operation: `createIssue`
- Project Key: `ENG`
- Issue Type: `Task`
- Summary: `$input.title`
- Description: `$input.description`
- Labels: `["automation"]`

Update an issue and clear the assignee:

- Operation: `updateIssue`
- Issue Key or ID: `ENG-123`
- Summary: `$input.title`
- Assignee Account ID / Username: `null`

Search issues with custom fields and cursor pagination:

- Operation: `searchIssues`
- JQL: `project = ENG AND updated >= -30d ORDER BY updated DESC`
- Issue Fields: `["key","summary","status"]`
- Limit: `25`
- Next Page Token: `$searchJira.pagination.nextPageToken`

Search issues on Data Center with offset pagination:

- Operation: `searchIssues`
- JQL: `project = ENG ORDER BY updated DESC`
- Limit: `25`
- Start At: `25`

Transition an issue after listing available transitions:

- Operation: `listTransitions`
- Issue Key or ID: `ENG-123`
- Then run **Transition Issue** with Transition ID: `$listTransitions.transitions[0].id`

Notify watchers about an issue update:

- Operation: `notifyIssue`
- Issue Key or ID: `ENG-123`
- Subject: `Issue updated`
- Text Body: `$input.text`
- Recipients JSON: `{"assignee":true,"watchers":true}`

## Output

Every successful operation sets:

- `$jira.success`
- `$jira.operation`

**Get Myself** exposes `user`.

**Paginated list operations** expose `count`, a collection field, and `pagination`:

| Operation | Collection key | Pagination shape |
| --- | --- | --- |
| List Projects | `projects` | `{ startAt, maxResults, total, isLast }` |
| Search Issues | `issues` | Cloud: `{ maxResults, nextPageToken, isLast }`; Data Center: `{ startAt, maxResults, total, isLast }` |
| Get Issue Changelog | `changelog` | `{ startAt, maxResults, total, isLast }` |
| List Comments | `comments` | `{ startAt, maxResults, total, isLast }` |
| List Attachments | `attachments` | `{ startAt, maxResults, total, isLast }` |

**List Transitions** exposes `transitions` and `count` without pagination.

**Issue mutations and reads** expose the Jira issue payload plus `key` where applicable.

**Comment** get/create/update expose `comment`; delete exposes `deleted`.

**Transition Issue** exposes `transition` as `{ transitionId }`, plus the refreshed `issue` and `key`.

**Attachment add** exposes `attachments` and `count`. **Get Attachment** exposes `attachment`; **List Attachments** exposes `attachments`, `count`, and `pagination`. When **Include Binary** is enabled, each attachment object may include `content_base64`. Delete exposes `deleted`.

**User** get/create expose `user`; delete exposes `deleted`.

**Notify Issue** exposes `notified`.

Common access patterns:

- `$searchJira.issues[0].key`
- `$searchJira.pagination.nextPageToken`
- `$createJiraIssue.key`
- `$listTransitions.transitions[0].id`
- `$getAttachment.attachment.content_base64`

## Related

- [Credentials Tab](../tabs/credentials-tab.md)
- [Third-Party Integrations](../reference/integrations.md#jira)
- [Node Types](../reference/node-types.md)
- [Expression DSL](../reference/expression-dsl.md)
