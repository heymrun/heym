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
| [HTTP](../nodes/http-node.md) | Bearer, Header | Auth for requests |
| [Telegram](../nodes/telegram-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md) | Telegram | Bot token and optional webhook secret |
| [RAG](../nodes/rag-node.md) | Qdrant | Vector store connection |
| [Slack](../nodes/slack-node.md) | Slack | Webhook or API token |
| [IMAP Trigger](../nodes/imap-trigger-node.md) | IMAP | Inbound mailbox connection |
| [Send Email](../nodes/send-email-node.md) | SMTP | Mail server |
| [Redis](../nodes/redis-node.md) | Redis | Connection |
| [Grist](../nodes/grist-node.md) | Grist | API key + server URL |
| [Google Sheets](../nodes/google-sheets-node.md) | Google Sheets (OAuth2) | Client ID + Client Secret + OAuth2 consent |
| [RabbitMQ](../nodes/rabbitmq-node.md) | RabbitMQ | AMQP URL |

For detailed setup (hosts, ports, provider-specific fields), see [Third-Party Integrations](./integrations.md). That includes Telegram bot setup, inbound email via IMAP, and outbound email via SMTP.

## In Expressions

Some nodes allow expressions for auth. Use [Expression DSL](./expression-dsl.md) with `$credentials.CredentialName` to reference a credential's value (e.g. Bearer token) inside an expression.

## Related

- [Credentials Tab](../tabs/credentials-tab.md) – Add, edit, delete credentials
- [Credentials Sharing](./credentials-sharing.md) – Share with users and teams
- [Third-Party Integrations](./integrations.md) – Setup guide per credential type
- [Expression DSL](./expression-dsl.md) – `$credentials` in expressions
