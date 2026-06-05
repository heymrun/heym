# Webhook Trigger

The **Webhook Trigger** node starts a workflow from a node-specific HTTP webhook URL. Use it when an external system should call a dedicated trigger URL, similar to n8n or Make webhook modules.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Endpoint | `/api/webhooks/{node_id}` |
| Output | `$nodeLabel.body`, `$nodeLabel.headers`, `$nodeLabel.query`, `$nodeLabel.method`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier used in expressions |

The node panel shows a read-only **Webhook URL** with a copy button. Send HTTP requests to that URL to execute the workflow.

## Authentication

Webhook Trigger uses the workflow's existing authentication settings:

| Workflow auth | Behavior |
|---------------|----------|
| `anonymous` | Anyone with the webhook URL can trigger the workflow |
| `jwt` | Requires a user session bearer token or scoped execution token |
| `header_auth` | Requires the configured custom header and value |

## Accessing Request Data

```text
$webhook.body
$webhook.body.event
$webhook.headers
$webhook.query
$webhook.method
$webhook.triggered_at
```

Header keys are lowercased and sensitive headers are removed before they are exposed to the workflow.

## Example

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  "https://app.heym.ai/api/webhooks/{node_id}?source=crm" \
  -d '{"event":"created","user":{"id":"123"}}'
```

Downstream expressions:

- `$webhook.body.event`
- `$webhook.body.user.id`
- `$webhook.query.source`

## Related

- [Webhooks](../reference/webhooks.md) – Generic workflow execution webhooks
- [Triggers](../reference/triggers.md) – All workflow entry points
- [Expression DSL](../reference/expression-dsl.md) – Referencing `$nodeLabel.field`
- [Execution Tokens](../reference/execution-tokens.md) – Scoped JWTs for external callers
