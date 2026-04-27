# RabbitMQ

The **RabbitMQ** node sends or receives messages from RabbitMQ queues and exchanges. Use it for message-driven workflows and event processing.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.status`, `$nodeLabel.message_id`, `$nodeLabel.body` (receive) |

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

Trigger mode: workflow starts when a message arrives. No incoming edge needed when used as trigger.

**Output:** `$nodeLabel.body` (message payload), `$nodeLabel.message_id`, `$nodeLabel.queue`

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

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Triggers](../reference/triggers.md) – RabbitMQ as workflow trigger
- [Credentials Tab](../tabs/credentials-tab.md) – Add RabbitMQ credentials
- [Third-Party Integrations](../reference/integrations.md#rabbitmq) – RabbitMQ credential setup and delay plugin details
