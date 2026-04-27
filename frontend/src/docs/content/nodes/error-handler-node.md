# Error Handler

The **Error Handler** node catches errors from any node in the workflow. When present, it runs automatically when any node fails. No incoming connections are needed—it is triggered by the workflow engine.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 (triggered on error) |
| Outputs | 1 |
| Output | `$nodeLabel.error`, `$nodeLabel.errorNode`, `$nodeLabel.errorNodeType`, `$nodeLabel.timestamp` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `message` | expression | Optional. Default: `$error.message` |

## Error Context

When the error handler runs, these fields are available:

| Field | Description |
|-------|-------------|
| `$errorHandler.error` | Error message string |
| `$errorHandler.errorNode` | Label of the node that failed |
| `$errorHandler.errorNodeType` | Type of the failed node |
| `$errorHandler.timestamp` | When the error occurred |

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
{"message": "Error: $errorHandler.error at $errorHandler.errorNode"}
```

Or connect to Slack for notifications:
```json
{"message": "Workflow failed: $errorHandler.error in $errorHandler.errorNode"}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Telegram Node](./telegram-node.md) – Notify on error
- [Slack Node](./slack-node.md) – Notify on error
- [Send Email Node](./send-email-node.md) – Email alerts
- [Throw Error Node](./throw-error-node.md) – Intentional errors
