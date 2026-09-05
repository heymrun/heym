# WebSocket Trigger

The **WebSocket Trigger** node opens an outbound client connection to an external WebSocket server and starts the workflow when selected socket events happen. Use it for event streams such as market feeds, telemetry, or chat backplanes. Connecting to internal realtime systems requires the private-URL opt-out described below.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.eventName`, `$nodeLabel.message`, `$nodeLabel.connection`, `$nodeLabel.close` |

## Important Behavior

- This node connects **from Heym to another WebSocket server**.
- It does **not** expose a WebSocket endpoint on Heym.
- No [credential](../reference/credentials.md) is required. Configure URL, headers, and subprotocols directly on the node.
- The leader worker keeps the connection open in the background and reconnects when enabled.

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `websocketUrl` | string | External `ws://` or `wss://` URL |
| `websocketHeaders` | JSON object string | Optional handshake headers |
| `websocketSubprotocols` | string | Optional comma-separated subprotocol list |
| `websocketTriggerEvents` | array | Any of `onMessage`, `onConnected`, `onClosed` |
| `retryEnabled` | boolean | Reconnect after a disconnect |
| `retryWaitSeconds` | integer | Delay before reconnecting |

## Emitted Events

### `onMessage`

Fires when a frame arrives from the remote socket.

Useful fields:

| Expression | Description |
|------------|-------------|
| `$nodeLabel.message.data` | Parsed JSON payload or raw message value |
| `$nodeLabel.message.text` | UTF-8 decoded text when available |
| `$nodeLabel.message.base64` | Binary payload as base64 |
| `$nodeLabel.message.sizeBytes` | Payload size |
| `$nodeLabel.message.isJson` | Whether the message parsed as JSON |

### `onConnected`

Fires after the socket opens successfully.

Useful fields:

| Expression | Description |
|------------|-------------|
| `$nodeLabel.connection.reconnected` | `false` on first connect, `true` on later reconnects |
| `$nodeLabel.connection.subprotocol` | Negotiated subprotocol |

### `onClosed`

Fires when an established connection closes.

Useful fields:

| Expression | Description |
|------------|-------------|
| `$nodeLabel.close.initiatedBy` | `server`, `client`, or `unknown` |
| `$nodeLabel.close.code` | WebSocket close code |
| `$nodeLabel.close.reason` | Close reason |
| `$nodeLabel.close.wasClean` | `true` for normal `1000` close |
| `$nodeLabel.close.reconnecting` | Whether the node will try to reconnect |

## Trigger Semantics

- One active node keeps one long-lived outbound socket connection.
- The connection runs only on the leader worker, similar to [IMAP Trigger](./imap-trigger-node.md) and [RabbitMQ](./rabbitmq-node.md) receive mode.
- If reconnect is enabled, Heym waits `retryWaitSeconds` and opens the socket again after a drop.
- Each emitted event creates a separate workflow run with `trigger_source = "websocket"`.

## Egress Safety

- By default, the URL must use `ws://` or `wss://` and resolve only to public addresses. Loopback, private, link-local, multicast, and cloud-metadata destinations are blocked.
- Heym revalidates DNS on every reconnect, validates every resolved address, and connects directly to one of those addresses. Environment proxies and WebSocket redirects are disabled while the guard is active.
- Permanent policy violations stop the trigger instead of retrying indefinitely. Temporary DNS or network failures still follow the node's retry settings.
- `Authorization`, `Origin`, `User-Agent`, and custom data headers are supported. `Origin` is sent through the WebSocket client's dedicated option. `Host`, `Connection`, `Upgrade`, and `Sec-WebSocket-*` headers cannot be overridden.
- Trusted self-hosted deployments that intentionally connect to internal services can set `HEYM_HTTP_ALLOW_PRIVATE_URLS=true`. Keep the default on hosted or multi-tenant deployments.

**Upgrade note for v0.0.105:** this instance-wide policy now also protects credential-derived destinations used by Jira, Sentry, GitHub, Grist, Supabase, ClickHouse, custom LLM execution and model discovery, the AI assistant, guardrails, and RAG embeddings. Existing credentials that point to loopback, private, or link-local addresses are refused unless `HEYM_HTTP_ALLOW_PRIVATE_URLS=true` is enabled on a trusted self-hosted instance. Guarded HTTP clients ignore `HTTP_PROXY` and `HTTPS_PROXY`, while operator CA bundles configured through `SSL_CERT_FILE` or `SSL_CERT_DIR` remain supported. ClickHouse is checked before the connection opens but is not pinned at dial time, because clickhouse-connect brings its own urllib3 transport.

## Example Workflow

**External event stream → filter → notify**

```
websocketTrigger → condition → slack
```

- **WebSocket Trigger** label: `streamEvent`
- **Condition**: `$streamEvent.eventName == "onMessage" && $streamEvent.message.data.type == "alert"`
- **Slack** message: `"Realtime alert: $streamEvent.message.data.title"`

## Example Node JSON

```json
{
  "type": "websocketTrigger",
  "data": {
    "label": "streamEvent",
    "websocketUrl": "wss://stream.example.com/events",
    "websocketHeaders": "{\"Authorization\": \"Bearer token\"}",
    "websocketSubprotocols": "json",
    "websocketTriggerEvents": ["onMessage", "onClosed"],
    "retryEnabled": true,
    "retryWaitSeconds": 5
  }
}
```

## Related

- [Triggers](../reference/triggers.md) – Background trigger architecture and `trigger_source`
- [WebSocket Send](./websocket-send-node.md) – Push data to an external socket from a workflow step
- [Node Types](../reference/node-types.md) – Overview of all nodes
- [Third-Party Integrations](../reference/integrations.md) – Which nodes use credentials and which do not
