# Credentials Sharing

Credentials can be shared with other users so their workflows can use your API keys. See [Credentials](./credentials.md) for an overview and [Credentials Tab](../tabs/credentials-tab.md) for adding and managing credentials.

## Sharing Credentials with an LLM

To let an LLM or an AI agent use an API key, store the key as a credential and let the node that makes the request attach it. The model decides what to call; the node authenticates the call when it runs.

- **Store the secret as a credential.** Sensitive values are encrypted at rest and masked in the UI after creation.
- **Reference it where the request is made.** The [LLM](../nodes/llm-node.md) and [Agent](../nodes/agent-node.md) nodes select their model credential by ID, and HTTP requests put `$credentials.CredentialName` in the auth header. Keep secrets out of prompt fields, because everything in a prompt is sent to the model provider as text.
- **Give the agent tools, not keys.** When an Agent calls an HTTP node, an MCP server, or a sub-workflow as a tool, the credential is applied inside that tool and the model receives the tool's result.
- **Outputs are masked.** When a credential value longer than seven characters appears in a node's output, only its first seven characters are kept, so a response that echoes a key shows only that prefix in results and traces. See [Output Masking](#output-masking).
- **Let the assistant create credentials.** When the [AI Assistant](./ai-assistant.md#credentials) or the Chat tab creates a credential, it sees only the name and type, and you enter the secret in the regular credential form.
- **Share with people the same way.** Share the credential with a user or a team, as described below, and their workflows can use your key through their own LLM and Agent nodes.

## Sharing Model

- **CredentialShare** – Links `credential_id` to `user_id` (unique per pair)
- **Share by email** – `POST /api/credentials/{credential_id}/shares` with email; user is looked up and added
- **Revoke** – `DELETE /api/credentials/{credential_id}/shares/{user_id}`

You can also share credentials with [Teams](./teams.md):

- **CredentialTeamShare** – Links `credential_id` to `team_id`; all team members gain access
- **Share with team** – `POST /api/credentials/{credential_id}/team-shares` with `team_id`
- **Revoke team share** – `DELETE /api/credentials/{credential_id}/team-shares/{team_id}`

Shared credentials show an indicator in the [Credentials Tab](../tabs/credentials-tab.md) UI.

## Broad-Scope Credentials

Sharing a credential grants the recipient everything that credential can do. For most integrations that is scoped to one workspace or one API key's permissions, but some credentials are far broader.

> **Google Drive credentials grant full Drive access.** The [Google Drive](../nodes/google-drive-node.md) credential is authorized with the `https://www.googleapis.com/auth/drive` scope so the node can operate on files you already own. Sharing it with a user or a team gives every one of them the ability to **read, modify, and permanently delete anything in your Google Drive** through a workflow — not just the files you had in mind. Share it only with people you would give full Drive access to directly.

If you need to limit exposure, create a dedicated Google account with access to only the folders the workflow needs, and connect the credential with that account instead of your primary one.

A **Decision Model** credential carries the endpoint and, when set, an API key. Sharing it lets the recipient spend against that key from any workflow they can run, exactly like an LLM credential.

A **Model Router** credential shares everything it routes to. The people you share it with can run requests against every credential in its option list, and those requests spend your keys. They cannot read the keys, and the credentials do not appear in their own credential list.

This is the same grant as sharing an OpenAI credential directly, and it is what makes a router useful to a team. If you do not want that, share the individual credentials instead and let each person pick a model.

## Sharing with Workflow Collaborators

When you share a workflow, collaborators can open and run it but cannot use your credentials unless you share those credentials with them too. This applies to credentials in the main workflow and in any sub-workflows it calls. Share each credential with the same users or teams you invited to the workflow. Sub-workflows must also be shared separately from the child workflow's editor. See [Workflow Organization](./workflow-organization.md#sharing-workflows).

## Execution Context

When a workflow runs, credentials are resolved for the **workflow owner** (or current user when running). `get_credentials_context()` merges:

1. **Owned credentials** – `Credential.owner_id == user_id`
2. **User-shared credentials** – `CredentialShare` where `CredentialShare.user_id == user_id`
3. **Team-shared credentials** – `CredentialTeamShare` where the user is a member of the team

All are merged into a single context dict keyed by credential name.

## Usage in Workflows

### By Name (Expression DSL)

Credentials are exposed as `$credentials.CredentialName` in the [Expression DSL](./expression-dsl.md). Use this for:

- HTTP nodes (Bearer/Header auth)
- Telegram nodes
- Slack nodes
- Notion bearer tokens in custom HTTP requests (internal token or OAuth access token)
- Any node that accepts expressions for auth

```dsl
$credentials.MyBearerToken
$credentials.MyNotionWorkspace
```

### By ID (credentialId)

Some nodes store `credentialId` (UUID) in `node.data`:

| Node Type | Field | Description |
|-----------|-------|-------------|
| [LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), [RAG](../nodes/rag-node.md), Image Gen | `credentialId` | LLM API credential |
| [Codex](../nodes/codex-node.md) | `credentialId`, `githubCredentialId` | Codex access token credential and GitHub credential |
| [OpenCode Go](../nodes/opencode-go-node.md) | `credentialId`, `githubCredentialId` | OpenCode Go gateway credential and GitHub credential |
| [Jira](../nodes/jira-node.md) | `credentialId` | Jira Cloud email/API token or Data Center username/password credential |
| [Notion](../nodes/notion-node.md) | `credentialId` | Notion internal token or OAuth workspace credential |
| [Sentry](../nodes/sentry-node.md) | `credentialId` | Sentry auth token and optional base URL |
| [Supabase](../nodes/supabase-node.md) | `credentialId` | Supabase project URL and API key |
| [ClickHouse](../nodes/clickhouse-node.md) | `credentialId` | ClickHouse connection details (host, port, auth, database) |
| [Telegram Trigger](../nodes/telegram-trigger-node.md), [Telegram](../nodes/telegram-node.md) | `credentialId` | Telegram bot credential |
| [Discord Trigger](../nodes/discord-trigger-node.md), [Discord](../nodes/discord-node.md) | `credentialId` | Discord public key or webhook credential |
| Vector Store | `credential_id` | Qdrant or Postgres (pgvector) vector DB, via a Qdrant, Psql, or Custom Embeddings RAG credential |
| Evals | `credential_id`, `judge_credential_id` | Model credential; a model or Decision Model credential for the LLM-as-Judge judge |
| [Playwright](../nodes/playwright-node.md) AI step | `credentialId` | LLM/Vision model (for AI step and [Auto Heal](../nodes/playwright-node.md#ai-auto-heal)) |

The executor loads the credential directly from the database by ID and decrypts the config.

## Output Masking

After execution, `mask_sensitive_output()` masks credential values in outputs, keeping the first seven characters of each secret longer than seven characters and replacing the rest with `**`, so secrets are not exposed in results or traces.

## Related

- [Credentials Tab](../tabs/credentials-tab.md) – Add and share credentials
- [Third-Party Integrations](./integrations.md) – Detailed setup for each credential type
- [Teams](./teams.md) – Share with teams
- [Expression DSL](./expression-dsl.md) – `$credentials` syntax
- [Node Types](./node-types.md) – Nodes that use credentials ([LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), [Codex](../nodes/codex-node.md), [Jira](../nodes/jira-node.md), [Linear](../nodes/linear-node.md), [RAG](../nodes/rag-node.md), [Playwright](../nodes/playwright-node.md), [HTTP](../nodes/http-node.md), [Notion](../nodes/notion-node.md), [Sentry](../nodes/sentry-node.md), [Supabase](../nodes/supabase-node.md), [ClickHouse](../nodes/clickhouse-node.md), [Telegram](../nodes/telegram-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md), [Discord](../nodes/discord-node.md), [Discord Trigger](../nodes/discord-trigger-node.md), [Slack](../nodes/slack-node.md))
- [Agent Node](../nodes/agent-node.md) – Uses `credentialId` for LLM
