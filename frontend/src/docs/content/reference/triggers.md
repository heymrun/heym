# Triggers

Workflows are started by **trigger nodes** or **entry points**. Each trigger type has its own endpoint or background process.

## Trigger Nodes

Start nodes (no incoming edges) that initiate execution:

| Node Type | Description |
|-----------|-------------|
| [Input](../nodes/input-node.md) (textInput) | HTTP entry point. Receives `body`, `headers`, `query` from requests. |
| [Cron](../nodes/cron-node.md) | Runs on a schedule (cron expression, e.g. `0 * * * *` for hourly). |
| [Telegram Trigger](../nodes/telegram-trigger-node.md) | Starts when Telegram sends a bot webhook update to the node-specific webhook URL. |
| [IMAP Trigger](../nodes/imap-trigger-node.md) | Polls an IMAP mailbox and starts once for each newly detected email. |
| [WebSocket Trigger](../nodes/websocket-trigger-node.md) | Opens an outbound client connection to an external socket and starts on selected socket events. |
| [RabbitMQ](../nodes/rabbitmq-node.md) (receive) | Starts when a message is consumed from a RabbitMQ queue. |
| [Slack Trigger](../nodes/slack-trigger-node.md) | Starts when Slack sends an event via the Events API webhook. |

## Entry Points

| Trigger | Endpoint / Source | Auth |
|---------|-------------------|------|
| **Webhook/API** | `POST /api/workflows/{id}/execute` | `anonymous` / `jwt` / `header_auth` |
| **MCP** | `POST /api/mcp/tools/call`, `/message`, `/sse` | `X-MCP-Key` header or Bearer token |
| **Portal** | `POST /api/portal/{slug}/execute` | Portal session token |
| **Cron** | Cron scheduler (runs every 60s, evaluates cron expressions) | N/A |
| **IMAP** | IMAP trigger manager (leader worker, per-node polling interval) | IMAP username/password |
| **WebSocket** | Outbound WebSocket trigger manager (leader worker, persistent client connections) | Optional per-node headers |
| **RabbitMQ** | RabbitMQ consumer (leader worker) | N/A |
| **Slack** | `POST /api/slack/webhook/{node_id}` | HMAC-SHA256 signing secret |
| **Telegram** | `POST /api/telegram/webhook/{node_id}` | Optional `x-telegram-bot-api-secret-token` |
| **Editor** | Same as Webhook, via `workflowStore.executeWorkflow` | JWT |

### Webhook / API

- **Endpoint**: `POST /api/workflows/{workflow_id}/execute`
- **Input**: Request body is passed as `body` to textInput nodes
- **Body mode**: Workflows can use `defined` field-shaped examples or `generic` raw JSON examples in the editor and cURL dialog
- **Auth**: Configured per workflow (`auth_type`, `allow_anonymous`)

See [Webhooks](./webhooks.md) for details on TTL, cache, rate limiting, and auth.

### MCP

Workflows with `mcp_enabled=true` appear as tools to MCP clients. Tool name is derived from the workflow name. See [MCP Tab](../tabs/mcp-tab.md).

### Portal

Public chat UI at `/chat/{slug}`. See [Portal](./portal.md) for details.

### Cron

The cron scheduler runs every 60 seconds, finds workflows with active `cron` nodes, evaluates cron expressions, and runs matching workflows. Input includes `{"triggered_by": "cron"}`.

### IMAP

The IMAP trigger manager runs in the leader worker and checks active `imapTrigger` nodes on their configured `pollIntervalMinutes`. Each node stores an IMAP cursor (`UIDVALIDITY` + last seen UID). Input includes `email`, `triggered_by: "imap"`, `trigger_node_id`, and `triggered_at`.

### WebSocket

The WebSocket trigger manager runs in the leader worker and keeps one outbound client connection per active [WebSocket Trigger](../nodes/websocket-trigger-node.md) node. It can emit runs for `onMessage`, `onConnected`, and `onClosed`. Input includes `eventName`, `url`, `triggered_by: "websocket"`, `trigger_node_id`, and one of `message`, `connection`, or `close`.

### Telegram

Telegram sends bot webhook updates to `POST /api/telegram/webhook/{node_id}`. The payload is passed into the workflow as `update`, `message`, optional `callback_query`, sanitized `headers`, `trigger_node_id`, and `triggered_at`. If the selected credential has a secret token, Heym verifies `x-telegram-bot-api-secret-token` before execution.

### RabbitMQ

The RabbitMQ consumer starts when the leader worker initializes. Workflows with `rabbitmq` nodes where `rabbitmqOperation === "receive"` get a consumer. Input includes `message_data` (body, headers, routing_key, etc.) and `triggered_by: "rabbitmq"`.

## trigger_source

Execution history records `trigger_source` for every entry point:

| Value | When |
|-------|------|
| `"API"` | Webhook / API call with no explicit header (default) |
| `"Canvas"` | Run from the workflow editor canvas |
| `"Quick Drawer"` | Run from the editor quick-drawer panel |
| `"cron"` | Cron scheduler |
| `"imap"` | IMAP trigger manager |
| `"websocket"` | Outbound WebSocket trigger manager |
| `"telegram"` | Telegram bot webhook |
| `"MCP"` | MCP tool call |
| `"portal"` | Portal execute |
| `"dashboard_chat"` | AI assistant chat |
| `"AI Agents"` | Sub-workflow invoked by an AI agent node |
| `"SUB_WORKFLOW"` | Sub-workflow invoked by an Execute Workflow node |
| custom | Any value sent in `X-Trigger-Source` header or `trigger_source` query/body param |
| (not set) | RabbitMQ consumer |

## Inputs by Trigger

- **HTTP/Webhook**: `body`, `headers`, `query` from the request
- **Cron**: `{"triggered_by": "cron"}`
- **Telegram**: `update` + `message` + optional `callback_query` + sanitized `headers` + `triggered_by: "telegram"`
- **IMAP**: `email` + `triggered_by: "imap"` + `triggered_at`
- **WebSocket**: `eventName` + `url` + `triggered_by: "websocket"` + `message` / `connection` / `close`
- **RabbitMQ**: `message_data` + `triggered_by: "rabbitmq"`
- **Slack**: `event` (full Slack event object) + `headers` (sanitized) + `triggered_by: "Slack"`
- **Portal**: `body.inputs` + optional `conversation_history`

## Related

- [Webhooks](./webhooks.md) – Webhook TTL, cache, rate limit, auth
- [Workflow Structure](./workflow-structure.md) – Nodes and edges
- [Node Types](./node-types.md) – [Input](../nodes/input-node.md), [Cron](../nodes/cron-node.md), [Telegram Trigger](../nodes/telegram-trigger-node.md), [IMAP Trigger](../nodes/imap-trigger-node.md), [WebSocket Trigger](../nodes/websocket-trigger-node.md), [RabbitMQ](../nodes/rabbitmq-node.md)
- [Quick Start](../getting-started/quick-start.md) – Build a workflow with Input
- [Portal](./portal.md) – Portal trigger and chat UI
- [Execution History](./execution-history.md) – View past runs and trigger_source
