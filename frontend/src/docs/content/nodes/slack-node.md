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

## Egress Safety

- The webhook URL stored in the credential must use `http://` or `https://` and resolve only to public addresses. Loopback, private, link-local, multicast, and cloud-metadata destinations are blocked.
- Heym validates the resolved addresses and pins the connection target before sending, so a DNS answer cannot move the request onto an internal address after the check. Environment proxies are disabled while the guard is active, and redirects are not followed.
- Deployments that post to an internal webhook receiver can set `HEYM_HTTP_ALLOW_PRIVATE_URLS=true` on a trusted self-hosted instance. Keep the default on hosted or multi-tenant deployments.

**Upgrade note for v0.0.109:** this check is new for Slack. A credential whose webhook URL points at loopback or a private address is refused unless the setting above is enabled.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Error Handler](./error-handler-node.md) – Send Slack on workflow failure
- [Credentials Tab](../tabs/credentials-tab.md) – Add Slack webhook
