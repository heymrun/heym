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
- Any node that accepts expressions for auth

```dsl
$credentials.MyBearerToken
```

### By ID (credentialId)

Some nodes store `credentialId` (UUID) in `node.data`:

| Node Type | Field | Description |
|-----------|-------|-------------|
| [LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), [RAG](../nodes/rag-node.md), Image Gen | `credentialId` | LLM API credential |
| [Telegram Trigger](../nodes/telegram-trigger-node.md), [Telegram](../nodes/telegram-node.md) | `credentialId` | Telegram bot credential |
| Vector Store | `credential_id` | Qdrant/vector DB |
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
- [Node Types](./node-types.md) – Nodes that use credentials ([LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), [RAG](../nodes/rag-node.md), [Playwright](../nodes/playwright-node.md), [HTTP](../nodes/http-node.md), [Telegram](../nodes/telegram-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md), [Slack](../nodes/slack-node.md))
- [Agent Node](../nodes/agent-node.md) – Uses `credentialId` for LLM
