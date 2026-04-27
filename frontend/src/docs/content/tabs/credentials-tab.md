# Credentials Tab

The **Credentials** tab manages API keys and secrets used by nodes. Add credentials here and reference them by name in workflow nodes. For an overview of what credentials are and how nodes use them, see [Credentials](../reference/credentials.md).

<video src="/features/showcase/credentials.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/credentials.webm">▶ Watch Credentials demo</a></p>

## Credential Types

| Type | Use Case |
|------|----------|
| **OpenAI** | OpenAI API key for LLM, Agent, and RAG nodes |
| **Google** | Google AI (Gemini) API key |
| **Custom** | Custom LLM endpoints |
| **Bearer** | Bearer token for HTTP auth |
| **Header** | Custom header key-value for HTTP requests |
| **Telegram** | Telegram bot token and optional webhook secret |
| **Slack** | Slack API token |
| **IMAP** | Inbound mailbox trigger credentials |
| **SMTP** | Email sending credentials |
| **Redis** | Redis connection |
| **Qdrant** | Vector store for RAG nodes |
| **Cohere** | Cohere API for embeddings |

## Adding Credentials

1. Click **Add Credential**
2. Choose the credential type
3. Enter the required values (API key, URL, etc.)
4. Give it a name for reference in nodes

## Editing and Deleting

- **Edit** – Update credential values (sensitive values are masked)
- **Delete** – Remove a credential; workflows using it will need a replacement

## Sharing

- [Share credentials](../reference/credentials-sharing.md) with other users by email or with [Teams](../reference/teams.md)
- Shared credentials appear with an indicator
- Revoke sharing from the credential card menu

## Using in Nodes

Reference credentials by name in node configuration. For example:
- [LLM node](../nodes/llm-node.md) – Select credential for the model API
- [HTTP node](../nodes/http-node.md) – Use Bearer or Header credentials for auth
- [RAG node](../nodes/rag-node.md) – Use Qdrant credential for the vector store
- [Telegram Trigger node](../nodes/telegram-trigger-node.md) – Receive Telegram bot webhooks
- [Telegram node](../nodes/telegram-node.md) – Send Telegram bot messages
- [IMAP Trigger node](../nodes/imap-trigger-node.md) – Poll a shared inbox for new email

See [Expression DSL](../reference/expression-dsl.md) for referencing credential-backed values in expressions.

## Related

- [Third-Party Integrations](../reference/integrations.md) – Detailed setup guide for each credential type (Telegram, Qdrant, Grist, IMAP, SMTP, RabbitMQ, Redis, Slack, and more)
- [Credentials Sharing](../reference/credentials-sharing.md) – Share credentials with other users
- [Security](../reference/security.md) – Encryption at rest, session management, rate limiting
- [Node Types](../reference/node-types.md) – Nodes that use credentials ([LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), [RAG](../nodes/rag-node.md), [HTTP](../nodes/http-node.md), [Telegram](../nodes/telegram-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md), [Slack](../nodes/slack-node.md), [IMAP Trigger](../nodes/imap-trigger-node.md), [Send Email](../nodes/send-email-node.md), [Redis](../nodes/redis-node.md))
- [Vectorstores Tab](./vectorstores-tab.md) – Uses Qdrant credentials
- [Chat Tab](./chat-tab.md) – Uses OpenAI/Google credentials
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
