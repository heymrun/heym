# Error Handler

The **Error Handler** node catches errors from any node in the workflow. When present, it runs automatically when any node fails. No incoming connections are needed—it is triggered by the workflow engine.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 (triggered on error) |
| Outputs | 1 |
| Output | `$nodeLabel.error.message`, `$nodeLabel.error.node_label`, `$nodeLabel.error.node_type`, `$nodeLabel.error.node_id`, and `$nodeLabel.message` when `message` is set |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `message` | expression | Optional. Default (pre-filled on the canvas): `$error.message`. Its text is added to the output as `message`. Inside it, `$error.message`, `$error.node_label`, `$error.node_type` and `$error.node_id` describe the failure |

## Error Context

When the error handler runs, these fields are available:

| Field | Description |
|-------|-------------|
| `$errorHandler.error.message` | Error message string |
| `$errorHandler.error.node_label` | Label of the node that failed |
| `$errorHandler.error.node_type` | Type of the failed node |
| `$errorHandler.error.node_id` | ID of the node that failed |

## Use Cases

- Send [Telegram](./telegram-node.md), [Slack](./slack-node.md), or [Send Email](./send-email-node.md) notifications on failure
- Log errors to external systems
- Return a custom error response via [Output](./output-node.md)

Only one Error Handler per workflow.

## Example

```json
{
  "type": "errorHandler",
  "data": {
    "label": "catchErrors"
  }
}
```

Connect to Output for custom error response:
```json
{"message": "Error: $errorHandler.error.message at $errorHandler.error.node_label"}
```

Or connect to Slack for notifications:
```json
{"message": "Workflow failed: $errorHandler.error.message in $errorHandler.error.node_label"}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Telegram Node](./telegram-node.md) – Notify on error
- [Slack Node](./slack-node.md) – Notify on error
- [Send Email Node](./send-email-node.md) – Email alerts
- [Throw Error Node](./throw-error-node.md) – Intentional errors
