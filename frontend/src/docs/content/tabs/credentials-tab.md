# Credentials Tab

The **Credentials** tab manages API keys and secrets used by nodes. Add credentials here and reference them by name in workflow nodes. For an overview of what credentials are and how nodes use them, see [Credentials](../reference/credentials.md).

<video src="/features/showcase/credentials.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/credentials.webm">▶ Watch Credentials demo</a></p>

## Credential Types

| Type | Use Case |
|------|----------|
| **OpenAI** | OpenAI API key for LLM, Agent, and RAG nodes |
| **Google** | Google AI (Gemini) API key |
| **GitHub** | GitHub personal access token (PAT) for GitHub API, GitHub node workflows, MCP servers, and agent workflows; optional GitHub Enterprise `base_url` |
| **Notion** | Internal integration token or public-integration OAuth workspace authorization |
| **Custom** | Custom LLM endpoints |
| **Bearer** | Bearer token for HTTP auth |
| **Header** | Custom header key-value for HTTP requests |
| **Telegram** | Telegram bot token and optional webhook secret |
| **Slack** | Slack incoming webhook URL |
| **Discord** | Discord incoming webhook URL |
| **Discord Trigger** | Discord application public key |
| **IMAP** | Inbound mailbox trigger credentials |
| **SMTP** | Email sending credentials |
| **Redis** | Redis connection |
| **RAG: Qdrant + OpenAI** | Vector store for RAG nodes, backed by an external Qdrant server |
| **RAG: Psql + OpenAI** | Vector store for RAG nodes, backed by Heym's own Postgres database (pgvector) — no external service |
| **Cohere** | Cohere API for embeddings |

## Adding Credentials

1. Click **Add Credential**
2. Choose the credential type
3. Enter the required values (API key, URL, etc.)
4. Give it a name for reference in nodes

For GitHub, the current credential flow is PAT-based. Fine-grained PATs are recommended. GitHub App installation flows are not first-class in the UI today. If you use GitHub Enterprise Server, you can also set an optional GitHub API base URL such as `https://github.example.com/api/v3`.

For **Notion**, choose **Internal token** or **OAuth** in the dialog. OAuth uses the Client ID and
Client Secret from your Notion public integration; Heym stores them encrypted in the credential.
Use **Test Connection** to verify Supabase or Notion credentials before saving a workflow. See
[Third-Party Integrations](../reference/integrations.md#notion) for setup details.

## Editing and Deleting

- **Edit** – Update credential values (sensitive values are masked)
- **Delete** – Remove a credential; workflows using it will need a replacement

When editing a **GitHub** credential on GitHub Enterprise Server, leaving the optional **GitHub
API Base URL** empty preserves the existing Enterprise endpoint. Enter a new URL only when you
want to change that endpoint.

## Sharing

- [Share credentials](../reference/credentials-sharing.md) with other users by email or with [Teams](../reference/teams.md)
- Shared credentials appear with an indicator
- Revoke sharing from the credential card menu

## Using in Nodes

Reference credentials by name in node configuration. For example:
- [LLM node](../nodes/llm-node.md) – Select credential for the model API
- [HTTP node](../nodes/http-node.md) – Use Bearer or Header credentials for auth
- [Agent node](../nodes/agent-node.md) – Pass GitHub tokens into MCP server env vars such as `GITHUB_PERSONAL_ACCESS_TOKEN`
- [GitHub node](../nodes/github-node.md) – Run native GitHub repository, user, issue, review, release, workflow, traffic, and file operations
- [Notion node](../nodes/notion-node.md) – Manage Notion databases, data sources, pages, and blocks
- [RAG node](../nodes/rag-node.md) – Use a Qdrant or Postgres (pgvector) credential for the vector store
- [Telegram Trigger node](../nodes/telegram-trigger-node.md) – Receive Telegram bot webhooks
- [Telegram node](../nodes/telegram-node.md) – Send Telegram bot messages
- [Discord Trigger node](../nodes/discord-trigger-node.md) – Receive Discord interaction webhooks
- [Discord node](../nodes/discord-node.md) – Send Discord webhook messages
- [IMAP Trigger node](../nodes/imap-trigger-node.md) – Poll a shared inbox for new email

See [Expression DSL](../reference/expression-dsl.md) for referencing credential-backed values in expressions.

## Related

- [Third-Party Integrations](../reference/integrations.md) – Detailed setup guide for each credential type (Telegram, Discord, Qdrant, Grist, IMAP, SMTP, RabbitMQ, Redis, Slack, and more)
- [Credentials Sharing](../reference/credentials-sharing.md) – Share credentials with other users
- [Security](../reference/security.md) – Encryption at rest, session management, rate limiting
- [Node Types](../reference/node-types.md) – Nodes that use credentials ([LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), [GitHub](../nodes/github-node.md), [RAG](../nodes/rag-node.md), [HTTP](../nodes/http-node.md), [Telegram](../nodes/telegram-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md), [Discord](../nodes/discord-node.md), [Discord Trigger](../nodes/discord-trigger-node.md), [Slack](../nodes/slack-node.md), [IMAP Trigger](../nodes/imap-trigger-node.md), [Send Email](../nodes/send-email-node.md), [Redis](../nodes/redis-node.md))
- [Vectorstores Tab](./vectorstores-tab.md) – Uses Qdrant or Postgres (pgvector) credentials
- [Chat Tab](./chat-tab.md) – Uses OpenAI/Google credentials
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
