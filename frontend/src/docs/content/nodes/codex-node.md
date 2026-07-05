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

Codex uses a dedicated **OpenAI Codex** credential with one field:

| Field | Description |
|-------|-------------|
| `access_token` | ChatGPT/Codex access token used only by the local Codex runner |

API keys are not accepted for the Codex credential. The node does not submit cloud Codex tasks; it clones the repository inside the Heym runtime, passes `CODEX_ACCESS_TOKEN` only to the Codex process, and keeps the token out of `$credentials`.

The node also requires a **GitHub** credential for cloning private repositories, pushing the working branch, and creating draft pull requests.

OpenAI references:

- [Codex authentication](https://developers.openai.com/codex/auth)
- [Codex access tokens](https://developers.openai.com/codex/enterprise/access-tokens)
- [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive)
- [Codex pricing](https://developers.openai.com/codex/pricing)

## Fields

| Field | Description |
|-------|-------------|
| Codex Credential | OpenAI Codex credential containing `access_token` |
| GitHub Credential | GitHub PAT credential used for repository access |
| Repository URL | HTTPS GitHub repository URL |
| Base Branch | Branch to clone before Codex runs, default `main` |
| Task Prompt | Coding task for Codex; supports expressions such as `$input.text` |
| Publish Mode | `diff_only` returns a patch; `draft_pr` pushes a branch and opens a draft PR |
| Branch Name | Branch name for draft PR mode, default `codex/$executionId` |
| Timeout | Maximum Codex execution time in seconds |
| Setup Command | Optional command to run before Codex, without Codex/OpenAI secrets in env |

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
| `pullRequestUrl` | Draft PR URL in `draft_pr` mode |
| `usage` | Usage metadata reported by Codex CLI when available |

## Follow-up Questions

If Codex needs missing requirements or a product decision, it returns `needs_input`. Heym pauses the execution and exposes a `question` output handle. Connect that handle to a notification branch, for example Slack or Send Email, to send the reviewer the public follow-up link.

When the reviewer answers, Heym resumes the same execution snapshot and Codex thread from the saved workspace metadata.

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
