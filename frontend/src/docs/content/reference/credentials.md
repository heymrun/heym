# Credentials

Credentials store API keys and secrets used by workflow nodes. You add them in the [Credentials Tab](../tabs/credentials-tab.md) and reference them by name in node configuration.

## What Credentials Are

- **Stored per user** – Each credential belongs to a user and can be [shared](./credentials-sharing.md) with other users or [Teams](./teams.md).
- **Encrypted at rest** – Sensitive values are encrypted; the UI masks them after creation.
- **Referenced by name** – Nodes select a credential by name (or ID). The execution engine resolves the credential for the workflow owner at run time.

## How Nodes Use Them

| Node type | Typical credential | Purpose |
|-----------|--------------------|---------|
| [LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md) | OpenAI, Google, Custom | API key for the model |
| [Agent](../nodes/agent-node.md), [HTTP](../nodes/http-node.md), [GitHub](../nodes/github-node.md) | GitHub | GitHub personal access token (PAT) for GitHub API calls, GitHub node operations, and MCP integrations |
| [HTTP](../nodes/http-node.md) | Bearer, Header | Auth for requests |
| [Telegram](../nodes/telegram-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md) | Telegram | Bot token and optional webhook secret |
| [Discord](../nodes/discord-node.md) | Discord | Incoming webhook URL |
| [Discord Trigger](../nodes/discord-trigger-node.md) | Discord Trigger (Public Key) | Application public key for signature verification |
| [RAG](../nodes/rag-node.md) | RAG: Qdrant + OpenAI, RAG: Psql + OpenAI | Vector store connection (external Qdrant, or Heym's own Postgres via pgvector) |
| [Slack](../nodes/slack-node.md) | Slack | Webhook or API token |
| [IMAP Trigger](../nodes/imap-trigger-node.md) | IMAP | Inbound mailbox connection |
| [Send Email](../nodes/send-email-node.md) | SMTP | Mail server |
| [Redis](../nodes/redis-node.md) | Redis | Connection |
| [Grist](../nodes/grist-node.md) | Grist | API key + server URL |
| [Google Sheets](../nodes/google-sheets-node.md) | Google Sheets (OAuth2) | Client ID + Client Secret + OAuth2 consent |
| [BigQuery](../nodes/bigquery-node.md) | BigQuery (OAuth2) | Client ID + Client Secret + OAuth2 consent |
| [Supabase](../nodes/supabase-node.md) | Supabase | Project URL + API key (+ optional default schema) |
| [ClickHouse](../nodes/clickhouse-node.md) | ClickHouse | Host + port + username/password + database (+ secure) |
| [Notion](../nodes/notion-node.md) | Notion | Internal integration token, or public integration Client ID + Client Secret + OAuth consent |
| [Amazon S3](../nodes/amazon-s3-node.md) | Amazon S3 | Access key, secret key, region |
| [RabbitMQ](../nodes/rabbitmq-node.md) | RabbitMQ | AMQP URL |

For detailed setup (hosts, ports, provider-specific fields), see [Third-Party Integrations](./integrations.md). That includes Telegram bot setup, inbound email via IMAP, and outbound email via SMTP.

GitHub credentials can also include an optional `base_url` when you are targeting GitHub
Enterprise Server instead of GitHub.com. When you edit a GitHub credential to rotate the token,
leaving `base_url` empty preserves the existing Enterprise endpoint. Enter a new URL only when
you want to change that endpoint.

## In Expressions

Some nodes allow expressions for auth. Use [Expression DSL](./expression-dsl.md) with `$credentials.CredentialName` to reference a credential's resolved secret inside an expression.

| Credential type | Value exposed to `$credentials.Name` |
|-----------------|--------------------------------------|
| Bearer | Bearer token string |
| GitHub | Personal access token |
| Notion | Internal `api_token` or OAuth `access_token` (Bearer token for Notion API calls) |
| Discord / Slack | Webhook URL |

Example:

```
$credentials.MyBearerToken
$credentials.MyNotionWorkspace
```

Use the Notion **node** for native database, page, and block operations. Use `$credentials` when a custom [HTTP](../nodes/http-node.md) request needs the same Notion bearer token.

## Related

- [Credentials Tab](../tabs/credentials-tab.md) – Add, edit, delete credentials
- [GitHub Node](../nodes/github-node.md) – Native GitHub REST operations
- [Notion Node](../nodes/notion-node.md) – Search and manage Notion content
- [Credentials Sharing](./credentials-sharing.md) – Share with users and teams
- [Third-Party Integrations](./integrations.md) – Setup guide per credential type
- [Expression DSL](./expression-dsl.md) – `$credentials` in expressions
