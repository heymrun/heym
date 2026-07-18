# OpenCode Go Node

The **OpenCode Go** node runs the [OpenCode](https://opencode.ai) CLI (Go) in an isolated, hardened Heym container against a GitHub repository. Like the Codex node, it is designed for coding tasks such as fixing tests, editing files, producing a patch, or opening a pull request — but it uses the provider-agnostic **OpenCode Go** model gateway instead of OpenAI Codex.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Credential | OpenCode Go API key + GitHub |
| Output | `$nodeLabel.summary`, `$nodeLabel.diff`, `$nodeLabel.changedFiles`, `$nodeLabel.pullRequestUrl` |

## Authentication

The **OpenCode Go** credential stores an OpenCode Go gateway **API key** (from [opencode.ai/go](https://opencode.ai/go)) and an optional **Gateway Base URL** (defaults to `https://opencode.ai/zen/go/v1`; override only for a self-hosted or proxied gateway).

The node also requires a **GitHub** credential for cloning private repositories, pushing the working branch, and creating pull requests. The GitHub token is **never placed inside the sandbox container** — Heym performs all git and GitHub operations on the host, so generated code cannot exfiltrate push credentials.

## Isolation and security

Execution isolation is chosen by `HEYM_OPENCODE_CLI_COMMAND`, exactly like the Codex node:

- **Local development (`run.sh`)** leaves it at the default `opencode`, so OpenCode runs as a host subprocess against the cloned workspace — no Docker required, no extra flags.
- **Docker deployments (`deploy.sh` and the single GHCR image)** set it to `/usr/local/bin/heym-opencode-docker`, a wrapper that runs `opencode run` inside a **hardened, throwaway sibling container** sharing the OpenCode workspace named volume.

The hardened runner container drops all Linux capabilities, sets `no-new-privileges`, uses a read-only root with a tmpfs `/tmp`, and applies pid/memory/CPU limits. Network egress is allowed (OpenCode must reach the model gateway). The **GitHub token is never placed inside the container** — all git and GitHub operations run host-side, so only the OpenCode API key and repository files are ever inside.

OpenCode only edits files on disk; Heym owns every git/GitHub action.

## Models

OpenCode Go's model roster changes often, so the **Model** field is populated live from the gateway's model list (`GET https://opencode.ai/zen/go/v1/models`) and shown as a searchable dropdown. If the live list is unavailable, a built-in fallback list is used. Model ids use the `opencode/<model>` form (for example `opencode/kimi-k3`, `opencode/deepseek-v4-pro`, `opencode/qwen3.7-max`). Leave the field empty to use the runner default (`opencode/kimi-k3`).

## Fields

| Field | Description |
|-------|-------------|
| OpenCode Go Credential | OpenCode Go credential (gateway API key) |
| GitHub Credential | GitHub PAT credential used for repository access |
| Repository URL | HTTPS GitHub repository URL; supports expressions |
| Base Branch | Branch to clone before OpenCode runs, default `main` |
| Model | OpenCode Go model (live searchable dropdown, `opencode/<model>`); empty uses the runner default |
| Reasoning Variant | Optional; maps to `opencode run --variant` for models that support reasoning effort |
| Task Prompt | Coding task for OpenCode; supports expressions such as `$input.text` |
| Publish Mode | How changes are delivered (see table below) |
| Branch Name | Working branch for PR/commit modes, default `opencode/$executionId` |
| Timeout | Maximum OpenCode execution time in seconds |
| Setup Command | Optional command to run before OpenCode |

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
| `status` | Always `completed` (the OpenCode Go node does not pause for input) |
| `summary` | OpenCode's final message |
| `validation` | Validation notes when reported |
| `diff` | Git patch when files changed |
| `changedFiles` | Changed file paths |
| `branchName` | Working branch name |
| `pullRequestUrl` | PR URL in `draft_pr`, `open_pr`, and `update_existing_pr` modes |
| `pushedBranch` | Branch that was pushed in commit/PR modes |
| `patchUrl` | Download link for the diff in `patch_artifact` mode |

## UI screenshots on pull requests

For UI/frontend tasks, OpenCode should save PNG screenshots under a gitignored path such as `frontend/.e2e-artifacts/` (not in source). After Heym opens or updates the pull request, it uploads those images to a single shared GitHub **prerelease** (`opencode-pr-assets`) as assets named `pr-<number>-…`, then embeds them in the PR description.

## As an agent tool

The OpenCode Go node can be attached to an **AI Agent** node's tool handle so the agent can delegate coding tasks. Configure the credential, GitHub credential, and repository on the node, then mark **Task Prompt** (and optionally **Repository URL**) with the agent-provided toggle so the agent supplies them at call time.

## Example

```json
{
  "id": "opencode-1",
  "type": "opencodeGo",
  "position": { "x": 420, "y": 120 },
  "data": {
    "label": "fix_pr",
    "credentialId": "opencode-credential-uuid",
    "githubCredentialId": "github-credential-uuid",
    "repositoryUrl": "https://github.com/acme/app",
    "baseBranch": "main",
    "taskPrompt": "$input.text",
    "publishMode": "open_pr",
    "branchName": "opencode/$executionId",
    "opencodeModel": "opencode/kimi-k3",
    "timeoutSeconds": 3600,
    "setupCommand": "npm install && npm test"
  }
}
```

## Related

- [Codex Node](./codex-node.md)
- [GitHub Node](./github-node.md)
- [Agent Node](./agent-node.md)
- [Credentials](../reference/credentials.md)
- [Credentials Sharing](../reference/credentials-sharing.md)
- [Node Types](../reference/node-types.md)
