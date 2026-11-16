# RabbitMQ

The **RabbitMQ** node sends or receives messages from RabbitMQ queues and exchanges. Use it for message-driven workflows and event processing.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.status`, `$nodeLabel.message_id` (send); `$nodeLabel.body`, `$nodeLabel.headers`, `$nodeLabel.message_id`, `$nodeLabel.routing_key`, `$nodeLabel.exchange`, `$nodeLabel.timestamp` (receive) |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | RabbitMQ credential from [Credentials](../tabs/credentials-tab.md) |
| `rabbitmqOperation` | `"send"` \| `"receive"` | Operation type |
| `rabbitmqExchange` | string | Exchange name (optional for send) |
| `rabbitmqRoutingKey` | string | Routing key (for send) |
| `rabbitmqQueueName` | string | Queue name (required for receive, optional for send) |
| `rabbitmqMessageBody` | expression | Message body for send (supports expressions) |
| `rabbitmqDelayMs` | number | x-delay header in ms (delayed message plugin) |

## Operations

### Send

Publishes a message to a queue or exchange.

| Field | Required | Description |
|-------|----------|-------------|
| `rabbitmqMessageBody` | yes | JSON or string body |
| `rabbitmqQueueName` | optional | Direct queue target |
| `rabbitmqExchange` | optional | Exchange name |
| `rabbitmqRoutingKey` | optional | Routing key |
| `rabbitmqDelayMs` | optional | Delay in milliseconds |

**Output:** `$nodeLabel.status` ("published"), `$nodeLabel.message_id`, `$nodeLabel.exchange`, `$nodeLabel.routing_key`

### Receive

Trigger mode: workflow starts when a message arrives from the configured queue. No incoming edge needed when used as trigger.

**Output fields:**
- `$nodeLabel.body`: Message payload (parsed JSON value, or original text if invalid JSON)
- `$nodeLabel.headers`: Message headers dictionary (values normalized for JSON compatibility)
- `$nodeLabel.message_id`: Message ID string or `null`
- `$nodeLabel.routing_key`: Routing key string
- `$nodeLabel.exchange`: Exchange name string
- `$nodeLabel.timestamp`: Message timestamp formatted as an ISO 8601 string or `null`

#### Header Normalization

RabbitMQ headers are normalized across message delivery to ensure full JSON compatibility:
- **datetime / date**: Converted to ISO 8601 strings
- **bytes / bytearray**: Decoded as UTF-8 text with invalid byte sequences replaced
- **Decimal**: Converted to strings to preserve exact numeric precision without float rounding
- **Nested containers**: Dictionaries, arrays, and lists are converted recursively

#### Retry and Dead-Letter Handling

When messages are routed from a RabbitMQ dead-letter exchange (DLX), RabbitMQ attaches an `x-death` array to the headers. Downstream nodes (such as a Condition node) can inspect retry counts or routing metadata using expressions (where `trigger` is the receive node's label):

```javascript
$trigger.headers["x-death"][0].count > 3
```

## Example – Send

```json
{
  "type": "rabbitmq",
  "data": {
    "label": "publishMessage",
    "credentialId": "rabbitmq-credential-uuid",
    "rabbitmqOperation": "send",
    "rabbitmqQueueName": "tasks",
    "rabbitmqMessageBody": "$userInput.body"
  }
}
```

## Example – Receive

```json
{
  "type": "rabbitmq",
  "data": {
    "label": "incomingTask",
    "credentialId": "rabbitmq-credential-uuid",
    "rabbitmqOperation": "receive",
    "rabbitmqQueueName": "tasks"
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Triggers](../reference/triggers.md) – RabbitMQ as workflow trigger
- [Credentials Tab](../tabs/credentials-tab.md) – Add RabbitMQ credentials
- [Third-Party Integrations](../reference/integrations.md#rabbitmq) – RabbitMQ credential setup and delay plugin details
