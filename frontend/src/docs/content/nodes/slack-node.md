# Slack

The **Slack** node sends a message to a Slack channel via an Incoming Webhook. Use it for notifications, alerts, and error reporting.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | Passes through input |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | Slack credential (webhook URL) from [Credentials](../tabs/credentials-tab.md) |
| `message` | expression | Message text. Supports [expressions](../reference/expression-dsl.md). |

## Setup

1. Create an Incoming Webhook in your Slack workspace
2. Add a Slack credential in Credentials tab with the webhook URL
3. Reference the credential in the node

## Example

```json
{
  "type": "slack",
  "data": {
    "label": "notifyTeam",
    "credentialId": "slack-credential-uuid",
    "message": "Workflow completed: $userInput.body.text"
  }
}
```

Use with [Error Handler](./error-handler-node.md) for failure notifications:
```json
"message": "Error in $errorHandler.errorNode: $errorHandler.error"
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Error Handler](./error-handler-node.md) – Send Slack on workflow failure
- [Credentials Tab](../tabs/credentials-tab.md) – Add Slack webhook
