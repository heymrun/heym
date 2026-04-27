# WebSocket Send

The **WebSocket Send** node opens an outbound client connection to an external WebSocket server, sends one message, and closes the connection. Use it when a workflow needs to push events to a realtime system without exposing a Heym-owned socket endpoint.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.status`, `$nodeLabel.url`, `$nodeLabel.message_type`, `$nodeLabel.size_bytes` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `websocketUrl` | string / expression | External `ws://` or `wss://` URL |
| `websocketHeaders` | JSON object string / expression | Optional handshake headers |
| `websocketSubprotocols` | string | Optional comma-separated subprotocol list |
| `websocketMessage` | expression | Payload to send |

## Message Serialization Rules

- If `websocketMessage` resolves to a **string**, Heym sends a text frame.
- If it resolves to an **object**, **array**, **number**, **boolean**, or `null`, Heym serializes it as JSON text.
- If it resolves to **bytes**, Heym sends a binary frame.
- Full expressions such as `$input` preserve native types before serialization.

## Output Fields

| Expression | Description |
|------------|-------------|
| `$nodeLabel.status` | `"sent"` on success |
| `$nodeLabel.url` | Resolved destination URL |
| `$nodeLabel.message_type` | `text`, `json`, or `binary` |
| `$nodeLabel.size_bytes` | Payload size in bytes |
| `$nodeLabel.subprotocol` | Negotiated subprotocol when present |
| `$nodeLabel.sent_at` | ISO timestamp |

## Example Workflow

**HTTP request → transform → publish over WebSocket**

```
input → set → websocketSend → output
```

- **Set** creates a payload object such as `{ "type": "user.updated", "user": $input.body }`
- **WebSocket Send** uses `$payloadNode` as `websocketMessage`
- **Output** can return `$socketSend.status`

## Example Node JSON

```json
{
  "type": "websocketSend",
  "data": {
    "label": "socketSend",
    "websocketUrl": "wss://stream.example.com/publish",
    "websocketHeaders": "{\"Authorization\": \"Bearer $vars.socketToken\"}",
    "websocketSubprotocols": "json",
    "websocketMessage": "$payloadBuilder"
  }
}
```

## Notes

- No [credential](../reference/credentials.md) is required for this node.
- If the remote server expects auth or tenant headers, pass them via `websocketHeaders`.
- Use [HTTP](./http-node.md) when the remote system is request/response based instead of socket based.

## Related

- [WebSocket Trigger](./websocket-trigger-node.md) – Listen to an external socket and trigger workflows on events
- [Node Types](../reference/node-types.md) – Integration node overview
- [Expression DSL](../reference/expression-dsl.md) – Build dynamic JSON payloads
- [Third-Party Integrations](../reference/integrations.md) – Credential-backed vs direct-config integrations
