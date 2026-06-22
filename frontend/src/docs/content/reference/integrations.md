# Third-Party Integrations

Heym connects to external services through **credentials**. Each credential type stores the connection details for one service and can be reused across multiple nodes and workflows. See [Credentials](./credentials.md) for an overview.

Add credentials in [Settings → Credentials](../tabs/credentials-tab.md). All values are encrypted at rest. Credentials can be [shared](./credentials-sharing.md) with other users or [Teams](./teams.md).

Some integration nodes do **not** require credentials. [WebSocket Trigger](../nodes/websocket-trigger-node.md) and [WebSocket Send](../nodes/websocket-send-node.md) connect to external sockets using the URL, headers, and subprotocols configured directly on the node.

## Credential Types at a Glance

| Type | Used By | Key Fields |
|------|---------|------------|
| **OpenAI** | [LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), [RAG](../nodes/rag-node.md) | `api_key` |
| **Google** | [LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md) | `api_key` |
| **GitHub** | [GitHub](../nodes/github-node.md), [Agent](../nodes/agent-node.md), [HTTP](../nodes/http-node.md) | `api_key`, optional `base_url` |
| **Custom** | [LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md) | `api_key`, `base_url` |
| **Cohere** | Embeddings | `api_key` |
| **RAG: Qdrant + OpenAI** | [RAG](../nodes/rag-node.md), Vectorstores | `qdrant_host`, `openai_api_key` |
| **RAG: Psql + OpenAI** | [RAG](../nodes/rag-node.md), Vectorstores | `openai_api_key` (vectors stored in Heym's own Postgres via pgvector) |
| **Grist** | [Grist node](../nodes/grist-node.md) | `api_key`, `server_url` |
| **Google Sheets** | [Google Sheets node](../nodes/google-sheets-node.md) | `client_id`, `client_secret` + OAuth2 consent |
| **BigQuery** | [BigQuery node](../nodes/bigquery-node.md) | `client_id`, `client_secret` + OAuth2 consent |
| **Supabase** | [Supabase node](../nodes/supabase-node.md) | `supabase_url`, `supabase_key`, optional `supabase_schema` |
| **Notion** | [Notion node](../nodes/notion-node.md) | `api_token`, or `client_id` + `client_secret` OAuth |
| **Amazon S3** | [Amazon S3 node](../nodes/amazon-s3-node.md) | `aws_access_key_id`, `aws_secret_access_key`, `aws_region` |
| **SMTP** | [Send Email](../nodes/send-email-node.md) | `host`, `port`, `email`, `password` |
| **IMAP** | [IMAP Trigger node](../nodes/imap-trigger-node.md) | `imap_host`, `imap_port`, `imap_username`, `imap_password` |
| **Telegram** | [Telegram Trigger node](../nodes/telegram-trigger-node.md), [Telegram node](../nodes/telegram-node.md) | `bot_token`, optional `secret_token` |
| **Discord** | [Discord node](../nodes/discord-node.md) | `webhook_url` |
| **Discord Trigger** | [Discord Trigger node](../nodes/discord-trigger-node.md) | `public_key` |
| **RabbitMQ** | [RabbitMQ node](../nodes/rabbitmq-node.md) | `rabbitmq_host`, `rabbitmq_username`, `rabbitmq_password` |
| **Redis** | [Redis node](../nodes/redis-node.md) | `host`, `port`, `password` |
| **Slack** | [Slack node](../nodes/slack-node.md) | `webhook_url` |
| **Slack Trigger** | [Slack Trigger node](../nodes/slack-trigger-node.md) | `signing_secret` |
| **Bearer** | [HTTP node](../nodes/http-node.md) | `token` |
| **Header** | [HTTP node](../nodes/http-node.md) | `header_key`, `header_value` |
| **FlareSolverr** | [Crawler node](../nodes/crawler-node.md) | `flaresolverr_url` |

---

## GitHub

The GitHub credential stores a GitHub personal access token (PAT) so workflows can call the GitHub REST API through the [GitHub node](../nodes/github-node.md), pass the token into MCP servers such as `@modelcontextprotocol/server-github`, or use it from the [HTTP node](../nodes/http-node.md) for custom REST calls.

### Required Fields

| Field | Description |
|-------|-------------|
| `api_key` | GitHub personal access token (`github_pat_...` fine-grained PAT or classic `ghp_...` PAT) |

### Optional Fields

| Field | Description |
|-------|-------------|
| `base_url` | GitHub API base URL for GitHub Enterprise Server (for example `https://github.example.com/api/v3`) |

### Notes

- Fine-grained personal access tokens are recommended when possible because you can scope them to specific repositories and permissions.
- Leave `base_url` empty for GitHub.com. For GitHub Enterprise Server, use the full REST API
  endpoint including `/api/v3` (for example `https://github.example.com/api/v3`), not the
  server's web UI root such as `https://github.example.com`.
- This credential currently models PAT-based auth only. To access organization repositories, use a PAT that has been granted the required organization/repository permissions.
- GitHub App installation tokens and GitHub App setup flows are not first-class in the Heym UI today.
- Prefer the [GitHub node](../nodes/github-node.md) for native repository, user, issue, pull request, review, release, Actions workflow, traffic, and file operations. Use the [HTTP node](../nodes/http-node.md) only when you need endpoints or payloads the GitHub node does not cover.
- Use the [Agent node](../nodes/agent-node.md) with MCP by passing `$credentials.YourGitHubCredential` into an MCP connection environment variable such as `GITHUB_PERSONAL_ACCESS_TOKEN`.
- GitHub's REST API commonly expects `Authorization: Bearer <token>` plus `Accept: application/vnd.github+json`.
- When editing a GitHub credential, leaving the GitHub Enterprise `base_url` empty preserves the
  existing endpoint. Enter a new URL only when you want to change that endpoint.

### Used By

- [GitHub node](../nodes/github-node.md)
- [Agent node](../nodes/agent-node.md)
- [HTTP node](../nodes/http-node.md)

---

## Qdrant

[Qdrant](https://qdrant.tech) is an open-source vector database used for semantic search and RAG (Retrieval Augmented Generation).

### Required Fields

| Field | Description |
|-------|-------------|
| `qdrant_host` | Full URL to your Qdrant instance (e.g. `http://localhost:6333` or a cloud endpoint) |
| `openai_api_key` | OpenAI API key used to generate embeddings when indexing and searching documents |

### Notes

- Qdrant collections are managed from the [Vectorstores](../tabs/vectorstores-tab.md) tab. Each vector store maps to a Qdrant collection.
- The [RAG node](../nodes/rag-node.md) uses a vector store (which references a Qdrant credential) — it does not reference the credential directly.
- If your Qdrant instance requires an API key, include it in the `qdrant_host` value or configure Qdrant accordingly; the current integration does not have a separate Qdrant API key field.
- Self-hosted Qdrant: use the [official Docker image](https://hub.docker.com/r/qdrant/qdrant) and expose port `6333`.

### Used By

- [RAG node](../nodes/rag-node.md) (via vector store)
- [Vectorstores Tab](../tabs/vectorstores-tab.md)

## Postgres (pgvector)

Heym can also store vectors **inside its own Postgres database** using the
[pgvector](https://github.com/pgvector/pgvector) extension — no external vector service
required. Create a **RAG: Psql + OpenAI** credential and use it when creating a vector
store, then pick **Postgres (pgvector)** in the RAG node's Database dropdown.

### Required Fields

| Field | Description |
|-------|-------------|
| `openai_api_key` | OpenAI API key used to generate embeddings when indexing and searching documents |

### Notes

- No host/port is needed — vectors are written to Heym's own database; Heym never connects to a different database.
- Every RAG feature available with Qdrant (insert, search, metadata filters, Cohere reranking, cloning, sharing) works identically with the Postgres backend.
- Requires the `vector` extension. Heym keeps the official `postgres:16` image unchanged (so existing data is never touched) and **auto-installs the `postgresql-16-pgvector` package at startup** — `run.sh`, `deploy.sh`, and `run_e2e.sh` all handle this. The install is non-fatal: if it cannot run (e.g. no network), Qdrant RAG keeps working and the Postgres backend stays inactive (the migration skips the table gracefully).
- If you run the published single-container image (`ghcr.io/heymrun/heym`) against **your own external Postgres**, that database must support the `vector` extension (Heym cannot install it into a database it does not manage). Without it, creating or uploading to a Postgres vector store returns a clear message and Qdrant RAG continues to work.

### Used By

- [RAG node](../nodes/rag-node.md) (via vector store)
- [Vectorstores Tab](../tabs/vectorstores-tab.md)

---

## Grist

[Grist](https://www.getgrist.com) is a spreadsheet/database hybrid that supports structured data and formulas. The Grist credential allows Heym to read and write Grist documents.

### Required Fields

| Field | Description |
|-------|-------------|
| `api_key` | Grist API key (found in **Profile → API Key** on your Grist instance) |
| `server_url` | Base URL of your Grist server (e.g. `https://docs.getgrist.com` for Grist Cloud, or your self-hosted URL) |

### Notes

- The [Grist node](../nodes/grist-node.md) requires the **Document ID** (from the Grist document URL) and **Table ID** in its configuration — these are not part of the credential.
- For self-hosted Grist, set `server_url` to your instance's domain.
- Column IDs in Grist use underscores (e.g. `User_Name`), not display labels. Use the `listColumns` operation to discover them.

### Used By

- [Grist node](../nodes/grist-node.md)

---

## Google Sheets (OAuth2)

The Google Sheets credential connects Heym to the Google Sheets API using an OAuth2 "Bring Your Own App" model. You supply a Google Cloud OAuth2 Client ID and Client Secret, then authorize access via a browser popup. Tokens are refreshed automatically in the background.

### Setup

1. Open [Google Cloud Console](https://console.cloud.google.com) → **APIs & Services** → **Library** → search for and enable **Google Sheets API**.
2. Go to **Credentials** → **Create Credentials** → **OAuth client ID** → application type **Web application**.
3. Under **Authorized redirect URIs** add: `https://your-heym-domain/api/credentials/google-sheets/oauth/callback`
4. Copy the generated **Client ID** and **Client Secret**.
5. In Heym Dashboard → **Credentials** → **New** → type **Google Sheets (OAuth2)**.
6. Enter the Client ID, Client Secret, and a name, then click **Connect** to open the Google consent popup and authorize access.

### Required Fields

| Field | Description |
|-------|-------------|
| `client_id` | OAuth2 Client ID from Google Cloud Console |
| `client_secret` | OAuth2 Client Secret from Google Cloud Console |

Tokens (`access_token`, `refresh_token`, `token_expiry`) are stored and refreshed automatically — you do not manage them directly.

### Notes

- The OAuth2 consent screen requires the spreadsheets scope (`https://www.googleapis.com/auth/spreadsheets`).
- Heym uses the refresh token to obtain new access tokens before they expire (60-second safety buffer).
- If you rotate the Client Secret in Google Cloud Console, reconnect the credential via the **Connect** button.
- **Production:** Set backend **`FRONTEND_URL`** to the exact public URL users open in the browser (scheme + host, e.g. `https://heym.example.com`). Heym builds the Google OAuth redirect URI from this value only — it does **not** trust `Origin` or `X-Forwarded-*` headers (client-controlled). Register `{FRONTEND_URL}/api/credentials/google-sheets/oauth/callback` in Google Cloud Console.

### Used By

- [Google Sheets node](../nodes/google-sheets-node.md)

---

## BigQuery (OAuth2)

The BigQuery credential connects Heym to the Google BigQuery API using an OAuth2 "Bring Your Own App" model. You supply a Google Cloud OAuth2 Client ID and Client Secret, then authorize access via a browser popup. Tokens are refreshed automatically in the background.

### Setup

1. Open [Google Cloud Console](https://console.cloud.google.com) → **APIs & Services** → **Library** → search for and enable **BigQuery API**.
2. Go to **Credentials** → **Create Credentials** → **OAuth client ID** → application type **Web application**.
3. Under **Authorized redirect URIs** add: `https://your-heym-domain/api/credentials/bigquery/oauth/callback`
4. Copy the generated **Client ID** and **Client Secret**.
5. In Heym Dashboard → **Credentials** → **New** → type **BigQuery (OAuth2)**.
6. Enter the Client ID, Client Secret, and a name, then click **Connect** to open the Google consent popup and authorize access.

### Required Fields

| Field | Description |
|-------|-------------|
| `client_id` | OAuth2 Client ID from Google Cloud Console |
| `client_secret` | OAuth2 Client Secret from Google Cloud Console |

Tokens (`access_token`, `refresh_token`, `token_expiry`) are stored and refreshed automatically.

### Notes

- The OAuth2 consent screen requires the BigQuery scope (`https://www.googleapis.com/auth/bigquery`).
- **Production:** Set backend **`FRONTEND_URL`** to the public URL. Register `{FRONTEND_URL}/api/credentials/bigquery/oauth/callback` in Google Cloud Console.

### Used By

- [BigQuery node](../nodes/bigquery-node.md)

---

## Supabase

The Supabase credential connects Heym to a Supabase project's PostgREST API so workflows can query and mutate Postgres-backed tables.

### Required Fields

| Field | Description |
|-------|-------------|
| `supabase_url` | Project base URL, for example `https://your-project.supabase.co` |
| `supabase_key` | API key with access to the target tables |
| `supabase_schema` | Optional default schema (defaults to `public`) |

### Notes

- The [Supabase node](../nodes/supabase-node.md) talks to `/rest/v1/<table>` and supports operator filters (`eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `like`, `ilike`, `is`, `in`, and related PostgREST operators) plus nested `or` / `and` logical groups.
- For write operations, prefer a key intended for trusted server-side use with the minimum required table permissions.
- Nodes can override the schema per step even if the credential defines a default schema.

### Used By

- [Supabase node](../nodes/supabase-node.md)

## Notion

The Notion credential supports either an internal integration token or a public-integration OAuth
connection. OAuth lets each user authorize a Notion workspace from Heym instead of manually copying
a token.

### Required Fields

| Mode | Field | Description |
|------|-------|-------------|
| Internal token | `api_token` | Internal integration token (`ntn_...`) |
| OAuth | `client_id` | Client ID from a Notion public integration |
| OAuth | `client_secret` | Client Secret from the Notion public integration |

The OAuth callback stores `access_token`, `auth_mode`, `workspace_id`, `workspace_name`, and `bot_id`
automatically. Any previous internal `api_token` is removed when OAuth completes. Register this
redirect URI in Notion:
`{FRONTEND_URL}/api/credentials/notion/oauth/callback`.

### OAuth setup flow

1. Choose **OAuth** in the credential dialog, enter a name, Client ID, and Client Secret.
2. Click **Connect** and authorize the workspace in the Notion popup.
   - For a **new** credential, Heym creates the credential record when you click **Connect**.
   - Complete authorization in the popup, then click **Save** to return to the credentials list.
3. A connected credential shows `connected (Workspace Name)` in the list. Pending OAuth
   credentials show `Not connected` until authorization finishes.

Use **Test Connection** in the credential dialog to verify either an internal token or a completed
OAuth authorization. When editing, leaving the token field blank preserves the stored internal token.

Both internal tokens and OAuth access tokens are available through
`$credentials.CredentialName` for custom [HTTP](../nodes/http-node.md) calls that need a Notion
bearer token.

### Notes

- Internal integrations require the relevant pages, databases, and data sources to be shared.
- OAuth users choose the workspace/pages during Notion authorization.
- OAuth application credentials are encrypted inside the Notion credential. The callback reloads
  them server-side; the secret is not embedded in OAuth state.
- Connected OAuth credentials display the workspace name; pending OAuth credentials show
  `Not connected` until authorization completes.
- **Production:** Set backend **`FRONTEND_URL`** to the public browser URL (scheme + host, no
  trailing slash). The Notion redirect URI must match exactly:
  `{FRONTEND_URL}/api/credentials/notion/oauth/callback`.
- The node uses API version `2026-03-11` and current `data_source` terminology. See the
  [Notion node](../nodes/notion-node.md#api-version-notes) article for migration guidance from
  older `archived`, `after`, or database-query examples.
- Old search filters with object value `database` are normalized to `data_source`.

### Used By

- [Notion node](../nodes/notion-node.md)

---

## SMTP (Email)

The SMTP credential stores email server connection details for sending outgoing mail.

### Required Fields

| Field | Description |
|-------|-------------|
| `host` | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `port` | SMTP port (typically `587` for STARTTLS, `465` for SSL) |
| `email` | Sender email address |
| `password` | SMTP password or App Password |

### Common SMTP Providers

| Provider | Host | Port | Notes |
|----------|------|------|-------|
| Gmail | `smtp.gmail.com` | `587` | Requires an [App Password](https://support.google.com/accounts/answer/185833) (2FA must be enabled) |
| Outlook / Office 365 | `smtp.office365.com` | `587` | Use your Microsoft account credentials |
| Mailgun | `smtp.mailgun.org` | `587` | Use Mailgun SMTP credentials from your domain settings |
| SendGrid | `smtp.sendgrid.net` | `587` | Use `apikey` as username and an API key as password |
| Custom / Self-hosted | your domain | `587` / `465` | Postfix, Exim, etc. |

### Notes

- Gmail requires an **App Password** instead of your regular password when 2-Step Verification is enabled.
- Port `587` uses STARTTLS (starts plaintext, upgrades to TLS). Port `465` uses implicit TLS (SSL from the start).

### Used By

- [Send Email node](../nodes/send-email-node.md)

---

## IMAP (Inbound Email)

The IMAP credential stores connection details for monitoring an inbox with the [IMAP Trigger node](../nodes/imap-trigger-node.md).

### Required Fields

| Field | Description |
|-------|-------------|
| `imap_host` | IMAP server hostname (for example `imap.gmail.com`) |
| `imap_port` | IMAP port (`993` for SSL/TLS on most providers) |
| `imap_username` | Mailbox username or full email address |
| `imap_password` | Password or provider-specific app password |

### Optional Fields

| Field | Description |
|-------|-------------|
| `imap_mailbox` | Mailbox folder to monitor (default: `INBOX`) |
| `imap_use_ssl` | Enable SSL/TLS (recommended; default: `true`) |

### Notes

- The IMAP trigger baselines the current mailbox on first poll and then only processes newer email.
- Gmail, Microsoft 365, and other hosted providers often require an **app password** or similar IMAP-specific secret.
- Attachment content is not downloaded into the workflow payload; Heym exposes attachment metadata only.

### Used By

- [IMAP Trigger node](../nodes/imap-trigger-node.md)
- [Triggers](./triggers.md) (IMAP as workflow trigger)

---

## RabbitMQ

[RabbitMQ](https://www.rabbitmq.com) is an open-source message broker. The RabbitMQ credential stores connection details for publishing to and consuming from queues and exchanges.

### Required Fields

| Field | Description |
|-------|-------------|
| `rabbitmq_host` | AMQP connection URL (e.g. `amqp://localhost:5672`) |
| `rabbitmq_username` | RabbitMQ username (default: `guest`) |
| `rabbitmq_password` | RabbitMQ password (default: `guest`) |

### Virtual Hosts

To connect to a specific virtual host, include it in the `rabbitmq_host` URL:

```
amqp://username:password@hostname:5672/vhost
```

If using the default vhost, the path `/` can be omitted.

### Delayed Message Plugin

The [RabbitMQ node](../nodes/rabbitmq-node.md) supports the **rabbitmq_delayed_message_exchange** plugin. When this plugin is enabled on your RabbitMQ server, you can set a delay (in milliseconds) on outgoing messages using the `rabbitmqDelayMs` field on the node.

The node sets the `x-delay` header on the published message. The exchange type must be `x-delayed-message` for delays to take effect.

To enable the plugin on a self-hosted RabbitMQ instance:

```bash
rabbitmq-plugins enable rabbitmq_delayed_message_exchange
```

When the plugin is not installed, the `x-delay` header is ignored and messages are delivered immediately.

### Used By

- [RabbitMQ node](../nodes/rabbitmq-node.md)
- [Triggers](./triggers.md) (RabbitMQ as workflow trigger)

---

## Amazon S3

The Amazon S3 credential connects Heym to [Amazon S3](https://aws.amazon.com/s3/). Use it with the [Amazon S3 node](../nodes/amazon-s3-node.md) to manage buckets and folders, upload and download objects, copy keys, and list or delete objects from workflows.

### Required Fields

| Field | Description |
|-------|-------------|
| `aws_access_key_id` | AWS IAM access key ID |
| `aws_secret_access_key` | Secret access key paired with the access key ID |
| `aws_region` | AWS region where buckets live (e.g. `us-east-1`) |

### Optional Fields

| Field | Description |
|-------|-------------|
| `aws_session_token` | Temporary session token when using AWS STS credentials |

### Notes

- The credential uses standard AWS SigV4 authentication via boto3.
- Upload operations currently send UTF-8 text content; downloads can return text or base64 for binary objects.

### Used By

- [Amazon S3 node](../nodes/amazon-s3-node.md)

---

## Redis

[Redis](https://redis.io) is an in-memory key-value store used for caching and fast data access.

### Required Fields

| Field | Description |
|-------|-------------|
| `host` | Redis server hostname or IP (e.g. `localhost`) |
| `port` | Redis port (default: `6379`) |
| `password` | Redis password (leave empty if not set) |

### Used By

- [Redis node](../nodes/redis-node.md)

---

## Slack

The Slack credential stores an **Incoming Webhook URL** for posting messages to Slack channels.

### Required Fields

| Field | Description |
|-------|-------------|
| `webhook_url` | Slack Incoming Webhook URL (from your Slack app configuration) |

### Notes

- Create an Incoming Webhook at [api.slack.com/apps](https://api.slack.com/apps) → your app → **Incoming Webhooks**.
- Each webhook is scoped to a specific channel. Create multiple credentials for different channels.

### Used By

- [Slack node](../nodes/slack-node.md)

---

## Telegram

The Telegram credential stores a **Bot Token** and an optional **Webhook Secret Token** for bot-based workflows.

### Required Fields

| Field | Description |
|-------|-------------|
| `bot_token` | Telegram Bot API token from BotFather |

### Optional Fields

| Field | Description |
|-------|-------------|
| `secret_token` | Shared secret verified against `x-telegram-bot-api-secret-token` on incoming webhooks |

### Notes

- Use the same credential for both [Telegram Trigger](../nodes/telegram-trigger-node.md) and [Telegram](../nodes/telegram-node.md).
- Register the webhook manually with Telegram's `setWebhook` API using the URL shown in the Telegram Trigger node panel.
- `chatId` in the Telegram node can be a literal ID or an expression like `$telegramEvent.message.chat.id`.

### Used By

- [Telegram Trigger node](../nodes/telegram-trigger-node.md)
- [Telegram node](../nodes/telegram-node.md)

---

## HTTP Auth (Bearer & Header)

These credentials are used by the [HTTP node](../nodes/http-node.md) to authenticate outgoing requests.

### Bearer

Attaches an `Authorization: Bearer <token>` header to HTTP requests.

| Field | Description |
|-------|-------------|
| `token` | The bearer token value |

### Header

Attaches a custom header to HTTP requests.

| Field | Description |
|-------|-------------|
| `header_key` | Header name (e.g. `X-Api-Key`) |
| `header_value` | Header value |

Both types can also be referenced via `$credentials.CredentialName` in the [Expression DSL](./expression-dsl.md) for dynamic use in any node that accepts expressions.

### Used By

- [HTTP node](../nodes/http-node.md)

---

## LLM Providers (OpenAI, Google, Custom, Cohere)

These credentials power AI nodes.

| Type | Description |
|------|-------------|
| **OpenAI** | API key for GPT models and OpenAI embeddings |
| **Google** | API key for Gemini models |
| **Custom** | API key + base URL for OpenAI-compatible endpoints (Ollama, vLLM, LM Studio, etc.) |
| **Cohere** | API key for Cohere embeddings |

### OpenAI Prompt Caching

OpenAI automatically caches the static (unchanging) prefix of your system prompt — no extra configuration required. Repeated workflow runs that share the same system prompt prefix benefit from cached token pricing, which reduces both cost and latency. This is especially useful when you have long, fixed instructions and only the user message changes between runs. Monitor cache hit rates and token savings in the [Traces tab](../tabs/traces-tab.md) or the OpenAI usage dashboard to optimize your prompt structure for maximum cache reuse.

### Used By

- [LLM node](../nodes/llm-node.md)
- [Agent node](../nodes/agent-node.md)
- [RAG node](../nodes/rag-node.md) (OpenAI embeddings via Qdrant credential)

---

## FlareSolverr

[FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) is a proxy server for bypassing Cloudflare and similar bot-protection challenges.

### Required Fields

| Field | Description |
|-------|-------------|
| `flaresolverr_url` | URL of your FlareSolverr instance (e.g. `http://localhost:8191`) |

### Used By

- [Crawler node](../nodes/crawler-node.md)

---

## Related

- [Credentials](./credentials.md) – Overview of credentials and how nodes use them
- [Credentials Tab](../tabs/credentials-tab.md) – Add and manage credentials
- [Credentials Sharing](./credentials-sharing.md) – Share credentials with users and teams
- [Security](./security.md) – Encryption at rest, access control
- [Expression DSL](./expression-dsl.md) – `$credentials` syntax for dynamic access
