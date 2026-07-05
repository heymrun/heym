# Codex Node

The **Codex** node runs the OpenAI Codex CLI in an isolated Heym workspace against a GitHub repository. It is designed for coding tasks such as fixing tests, editing files, producing a patch, or opening a draft pull request.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1, plus `question` |
| Credential | Codex access token + GitHub |
| Output | `$nodeLabel.summary`, `$nodeLabel.diff`, `$nodeLabel.changedFiles`, `$nodeLabel.pullRequestUrl` |

## Authentication

The **OpenAI Codex** credential supports two authentication modes:

| Mode | Description |
|------|-------------|
| **Sign in with ChatGPT** (recommended) | OAuth (PKCE) sign-in that uses your ChatGPT Plus/Pro subscription, so runs do **not** incur per-token API costs. Click **Sign in with ChatGPT** in the credential dialog, authorize in your browser, then paste the `localhost:1455` redirect URL back into Heym. Heym stores the resulting token bundle and refreshes it automatically as it expires. |
| **Access token** | Paste a ChatGPT/Codex `access_token` used only by the local Codex runner. |

API keys are not accepted for the Codex credential. The node does not submit cloud Codex tasks; it clones the repository inside the Heym runtime, writes the ChatGPT token bundle to an isolated `auth.json` (or passes `CODEX_ACCESS_TOKEN`) only to the Codex process, and keeps the token out of `$credentials`.

The node also requires a **GitHub** credential for cloning private repositories, pushing the working branch, and creating draft pull requests.

In Docker deployments, Heym runs Codex inside a sibling container from the same Heym image (not a separate GHCR image). That container mounts only the Codex workspace volume and lets Codex's own bubblewrap sandbox create namespaces, which avoids the common Docker error `bwrap: No permissions to create a new namespace`.

OpenAI references:

- [Codex authentication](https://developers.openai.com/codex/auth)
- [Codex access tokens](https://developers.openai.com/codex/enterprise/access-tokens)
- [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive)
- [Codex pricing](https://developers.openai.com/codex/pricing)

## Fields

| Field | Description |
|-------|-------------|
| Codex Credential | OpenAI Codex credential (ChatGPT sign-in or `access_token`) |
| GitHub Credential | GitHub PAT credential used for repository access |
| Repository URL | HTTPS GitHub repository URL |
| Base Branch | Branch to clone before Codex runs, default `main` |
| Model | Optional Codex model (editable dropdown, e.g. `gpt-5.4`); empty uses Codex's default |
| Task Prompt | Coding task for Codex; supports expressions such as `$input.text` |
| Publish Mode | How changes are delivered (see table below) |
| Branch Name | Working branch for PR/commit modes, default `codex/$executionId` |
| Timeout | Maximum Codex execution time in seconds |
| Setup Command | Optional command to run before Codex, without Codex/OpenAI secrets in env |

## Publish Modes

| Mode | What it does |
|------|--------------|
| `diff_only` | Edits files locally and returns the patch and changed files. Nothing is pushed. |
| `draft_pr` | Commits to the branch, pushes it, and opens a draft pull request. |
| `open_pr` | Commits to the branch, pushes it, and opens a review-ready (non-draft) pull request. |
| `commit_push` | Commits to the branch and pushes it, without opening a pull request. |
| `direct_commit` | Commits and pushes straight to the base branch (no separate branch or PR). |
| `update_existing_pr` | Adds a commit to the existing branch/PR; opens one if none exists yet. |
| `patch_artifact` | Saves the diff as a downloadable file and returns `patchUrl`. Nothing is pushed. |

## Outputs

| Key | Description |
|-----|-------------|
| `status` | `completed` or `needs_input` |
| `summary` | Codex's summary |
| `validation` | Validation notes, tests, or checks reported by Codex |
| `diff` | Git patch when files changed |
| `changedFiles` | Changed file paths |
| `threadId` | Codex thread/session id when available |
| `branchName` | Working branch name |
| `pullRequestUrl` | PR URL in `draft_pr`, `open_pr`, and `update_existing_pr` modes |
| `pushedBranch` | Branch that was pushed in commit/PR modes |
| `patchUrl` | Download link for the diff in `patch_artifact` mode |
| `usage` | Usage metadata reported by Codex CLI when available |

## Follow-up Questions

If Codex needs missing requirements or a product decision, it returns `needs_input`. Heym pauses the execution and exposes a `question` output handle. Connect that handle to a notification branch, for example Slack or Send Email, to send the reviewer the public follow-up link.

When the reviewer answers, Heym resumes the same execution snapshot and Codex thread from the saved workspace metadata.

## As an agent tool

The Codex node can be attached to an **AI Agent** node's tool handle so the agent can delegate coding tasks. Configure the credential, GitHub credential, and repository on the node, then mark **Task Prompt** (and optionally **Repository URL**) with the agent-provided toggle so the agent supplies them at call time. When Codex runs as a tool, a `needs_input` result is returned inline to the agent instead of pausing the workflow, so the agent can refine the request and call Codex again.

## Example

```json
{
  "id": "codex-1",
  "type": "codex",
  "position": { "x": 420, "y": 120 },
  "data": {
    "label": "fix_pr",
    "credentialId": "codex-credential-uuid",
    "githubCredentialId": "github-credential-uuid",
    "repositoryUrl": "https://github.com/acme/app",
    "baseBranch": "main",
    "taskPrompt": "$input.text",
    "publishMode": "draft_pr",
    "branchName": "codex/$executionId",
    "timeoutSeconds": 3600,
    "setupCommand": "npm install && npm test"
  }
}
```

## Related

- [GitHub Node](./github-node.md)
- [Agent Node](./agent-node.md)
- [Credentials](../reference/credentials.md)
- [Credentials Sharing](../reference/credentials-sharing.md)
- [Node Types](../reference/node-types.md)
