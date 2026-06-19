# GitHub Node

The **GitHub** node adds native GitHub REST operations to a workflow, similar to the multi-operation GitHub nodes you may know from tools like n8n.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Credential | GitHub |
| Output | `$nodeLabel.*` |

## Supported Operations

The node currently provides 40 actions:

| Resource | Actions |
|----------|---------|
| Repository | `Get Repository`, `Get Repository License`, `Get Repository Profile`, `Get Repository Issues`, `Get Repository Pull Requests`, `List Popular Paths for Repository`, `List Top Referrers for Repository` |
| Organization / User | `List Organization Repositories`, `List User Repositories`, `Get User Repositories`, `Get User Issues`, `Invite User` |
| Issue | `Create Issue`, `Get Issue`, `List Issues`, `Edit Issue`, `Lock Issue`, `Create Comment` |
| Pull request | `Create Pull Request`, `List Pull Requests` |
| Review | `Create Review`, `Get Review`, `List Reviews`, `Update Review` |
| Release | `Create Release`, `Get Release`, `List Releases`, `Update Release`, `Delete Release` |
| Workflow | `List Workflows`, `Get Workflow`, `Enable Workflow`, `Disable Workflow`, `Get Workflow Usage`, `Dispatch Workflow`, `Dispatch Workflow and Wait` |
| File | `Get File`, `List Files`, `Create or Update File`, `Delete File` |

## Credential

Create a **GitHub** credential in the [Credentials Tab](../tabs/credentials-tab.md) with:

- A personal access token
- Optional full REST API base URL for GitHub Enterprise Server

Leave the base URL empty for GitHub.com. Fine-grained PATs are recommended.

For GitHub Enterprise Server, enter the complete REST API endpoint including `/api/v3`, such as
`https://github.example.com/api/v3`. Do not enter only the web UI root
(`https://github.example.com`).

If you use GitHub Enterprise Server and later edit the credential to rotate the token, leaving
`base_url` empty preserves the existing Enterprise endpoint. Enter a new URL only when you want
to change that endpoint.

## Common Fields

Most operations use:

- **Owner** – Repository owner, organization name, or username
- **Repository** – Repository name

`List Organization Repositories` only requires **Owner** (the organization name) and does not use the repository field.

`List User Repositories` only requires **Owner** (the username) and does not use the repository field.

`Get User Repositories` mirrors n8n's User → Get Repositories action. `Get User Issues` returns
issues assigned to the authenticated GitHub user by default. Set **Mentioned Filter** to any
non-empty value to return issues mentioning the authenticated user instead. It also supports
state, labels, updated-since, sort, direction, and per-page filters. `Invite User` requires an
organization and email address and does not use Owner or Repository.

## Repository

Repository operations include metadata, detected license content, community health profile, and
traffic insights. `List Popular Paths for Repository` and
`List Top Referrers for Repository` return GitHub's top traffic entries for the last 14 days and
require repository administration push access.

`List Issues` supports optional assignee, creator, mentioned user, comma-separated labels,
updated-since timestamp, sort, and direction filters. `List Pull Requests` supports state, sort,
direction, and per-page controls.

`Get Repository Issues` and `Get Repository Pull Requests` expose the same APIs as their List
counterparts under explicit n8n-compatible repository action names.

### Get Repository metadata

`Get Repository` stores GitHub's complete response in `$github.repository` and also exposes
`$github.full_name`, `$github.default_branch`, `$github.private`, and `$github.url`.

The repository payload commonly includes:

- Identity and ownership: ID, name, full name, description, owner, and visibility
- Repository state: private, fork, archived, disabled, and default branch
- URLs: GitHub page, API, clone, SSH, and Git URLs
- Activity and size: creation, update and push timestamps, size, stars, watchers, forks, subscribers, and open issues
- Features: issues, projects, wiki, Pages, discussions, topics, language, and homepage
- License, merge settings, caller permissions, security settings, and fork parent/source metadata when available

Some administrative, permission, merge, and security fields depend on the credential's repository
permissions.

Example:

- Owner: `heymrun`
- Repository: `heym`

## Issues

Issue operations support title/body fields and optional JSON-array fields for labels and assignees.

`List Issues` returns repository issues only. Pull requests are excluded; use `List Pull Requests` for PR results.

```json
["bug", "backend"]
```

```json
["octocat"]
```

### Edit Issue field semantics

For `Edit Issue`, only fields you explicitly set are sent to GitHub:

- **State** – Choose `Don't change`, `Open`, or `Closed`. Leave unset to keep the current state.
- **State Reason** – Optionally set `Completed`, `Not Planned`, `Duplicate`, or `Reopened`.
- **Title / Body** – Leave blank to keep the current value.
- **Labels / Assignees** – Leave the field empty to keep the current value. Use `[]` to clear all labels or assignees. Use a JSON array such as `["bug"]` to replace them.

`Edit Issue` requires at least one field to change at runtime. If you only provide an issue number, execution fails with a validation error from the GitHub API layer.

## Lock Issue

`Lock Issue` accepts an optional **Lock reason**. When provided, it must be one of GitHub's supported values:

- `off-topic`
- `too heated`
- `resolved`
- `spam`

Leave the reason empty to lock without a specific reason.

## Pull Requests

Create PR requires:

- Title
- Head branch
- Base branch
- Optional body
- Optional draft mode

## Pull Request Reviews

Review operations match GitHub's pull request review API:

| Operation | Required fields | Optional fields |
|-----------|-----------------|-----------------|
| `Create Review` | Pull request number, event | Body, commit ID |
| `Get Review` | Pull request number, review ID | — |
| `List Reviews` | Pull request number | Per page |
| `Update Review` | Pull request number, review ID, body | — |

`Create Review` supports `Approve`, `Request Changes`, `Comment`, and `Pending`.
The body is required for `Request Changes` and `Comment`. When Commit ID is empty, GitHub
reviews the pull request's latest commit.

## Releases

| Operation | Required fields at runtime | Commonly optional |
|-----------|---------------------------|-------------------|
| `Create Release` | Tag name | Release name (title), body, target branch, draft, prerelease |
| `Update Release` | Release ID | Tag name, release name, body, target branch, draft, prerelease |
| `Get Release` / `Delete Release` | Release ID | — |

`Update Release` can explicitly set `draft` / `prerelease` to either `true` or `false`.

## Workflows

Workflow operations support:

- Listing repository workflows
- Getting a workflow by numeric ID or workflow file name
- Enabling or disabling a workflow
- Reading billable workflow usage by runner operating system
- Dispatching a workflow with a ref or branch plus optional JSON inputs object

GitHub is in the process of closing down the `Get Workflow Usage` endpoint. Workflows using
this operation may need to migrate when GitHub removes the endpoint.

`Dispatch Workflow` accepts both GitHub response forms: legacy `204 No Content` and the newer
`200` response containing `workflow_run_id`, `run_url`, and `html_url`.

`Dispatch Workflow and Wait` dispatches the workflow and polls the run until its status is
`completed`. Configure the timeout and polling interval in seconds. Heym uses
`workflow_run_id` when GitHub returns the newer `200` response. For the traditional `204 No
Content` response, Heym discovers the newly created `workflow_dispatch` run for the selected
workflow and ref, then waits for that run.

## File Contents

`Get File` reads a repository file through GitHub's contents API and decodes text content when available. Binary files and non-UTF-8 content may return metadata without a decoded `content` field.

`List Files` returns directory entries from the repository contents API for a given folder path and optional ref. Leave **Directory Path** empty to list the repository root.

`Create or Update File` writes text content to a repository path using:

- File path
- Commit message
- File content
- Optional branch

`Delete File` removes a repository path using a commit message and optional branch. If the file exists, Heym fetches the current SHA automatically before deleting it.

If the file already exists, Heym fetches the current SHA automatically before updating it.

## Pagination

`List Issues`, `Get Repository Issues`, `Get User Issues`, `List Pull Requests`,
`Get Repository Pull Requests`, `List Reviews`, `List Releases`, `List Workflows`,
`List Organization Repositories`, `List User Repositories`, and `Get User Repositories` support
**Per Page** (1–100). Heym requests one page of results; there is no `page` field for fetching
additional pages in the same operation.

## Output

The exact shape depends on the selected operation. Common fields include:

- `$github.success`
- `$github.operation`
- `$github.repository`
- `$github.license`
- `$github.profile`
- `$github.paths`
- `$github.referrers`
- `$github.issue`
- `$github.issues`
- `$github.pull_request`
- `$github.pull_requests`
- `$github.review`
- `$github.reviews`
- `$github.release`
- `$github.releases`
- `$github.workflow`
- `$github.workflows`
- `$github.workflow_run`
- `$github.workflow_run_id`
- `$github.completed`
- `$github.conclusion`
- `$github.usage`
- `$github.billable`
- `$github.invitation`
- `$github.file`
- `$github.items`
- `$github.path`
- `$github.sha`
- `$github.commit_sha`
- `$github.deleted`
- `$github.created`
- `$github.ref`
- `$github.inputs`

Replace `github` with your node label.

## Notes

- Labels and assignees must be valid JSON arrays when provided.
- Workflow dispatch inputs must be a valid JSON object when provided.
- `Edit Issue` uses `state` only when you explicitly set it; leave it unset to keep the current issue state.
- GitHub API permissions depend on the token scopes or fine-grained repository permissions you grant.

## Related

- [Credentials Tab](../tabs/credentials-tab.md) – Add and manage GitHub credentials
- [Third-Party Integrations](../reference/integrations.md) – GitHub credential setup and Enterprise `base_url`
- [Agent Node](./agent-node.md) – Use GitHub credentials with `@modelcontextprotocol/server-github`
- [Node Types](../reference/node-types.md) – Full node catalog
