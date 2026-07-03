# Credentials Sharing

Credentials can be shared with other users so their workflows can use your API keys. See [Credentials](./credentials.md) for an overview and [Credentials Tab](../tabs/credentials-tab.md) for adding and managing credentials.

## Sharing Model

- **CredentialShare** – Links `credential_id` to `user_id` (unique per pair)
- **Share by email** – `POST /api/credentials/{credential_id}/shares` with email; user is looked up and added
- **Revoke** – `DELETE /api/credentials/{credential_id}/shares/{user_id}`

You can also share credentials with [Teams](./teams.md):

- **CredentialTeamShare** – Links `credential_id` to `team_id`; all team members gain access
- **Share with team** – `POST /api/credentials/{credential_id}/team-shares` with `team_id`
- **Revoke team share** – `DELETE /api/credentials/{credential_id}/team-shares/{team_id}`

Shared credentials show an indicator in the [Credentials Tab](../tabs/credentials-tab.md) UI.

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
| [Notion](../nodes/notion-node.md) | `credentialId` | Notion internal token or OAuth workspace credential |
| [Sentry](../nodes/sentry-node.md) | `credentialId` | Sentry auth token and optional base URL |
| [Supabase](../nodes/supabase-node.md) | `credentialId` | Supabase project URL and API key |
| [ClickHouse](../nodes/clickhouse-node.md) | `credentialId` | ClickHouse connection details (host, port, auth, database) |
| [Telegram Trigger](../nodes/telegram-trigger-node.md), [Telegram](../nodes/telegram-node.md) | `credentialId` | Telegram bot credential |
| [Discord Trigger](../nodes/discord-trigger-node.md), [Discord](../nodes/discord-node.md) | `credentialId` | Discord public key or webhook credential |
| Vector Store | `credential_id` | Qdrant or Postgres (pgvector) vector DB |
| Evals | `credential_id`, `judge_credential_id` | Model credentials |
| [Playwright](../nodes/playwright-node.md) AI step | `credentialId` | LLM/Vision model (for AI step and [Auto Heal](../nodes/playwright-node.md#ai-auto-heal)) |

The executor loads the credential directly from the database by ID and decrypts the config.

## Output Masking

After execution, `mask_sensitive_output()` replaces credential values in outputs with placeholders so secrets are not exposed in results or traces.

## Related

- [Credentials Tab](../tabs/credentials-tab.md) – Add and share credentials
- [Third-Party Integrations](./integrations.md) – Detailed setup for each credential type
- [Teams](./teams.md) – Share with teams
- [Expression DSL](./expression-dsl.md) – `$credentials` syntax
- [Node Types](./node-types.md) – Nodes that use credentials ([LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), [Linear](../nodes/linear-node.md), [RAG](../nodes/rag-node.md), [Playwright](../nodes/playwright-node.md), [HTTP](../nodes/http-node.md), [Notion](../nodes/notion-node.md), [Sentry](../nodes/sentry-node.md), [Supabase](../nodes/supabase-node.md), [ClickHouse](../nodes/clickhouse-node.md), [Telegram](../nodes/telegram-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md), [Discord](../nodes/discord-node.md), [Discord Trigger](../nodes/discord-trigger-node.md), [Slack](../nodes/slack-node.md))
- [Agent Node](../nodes/agent-node.md) – Uses `credentialId` for LLM
