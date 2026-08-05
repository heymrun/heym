# Cal.com Trigger

The **Cal.com Trigger** node is a zero-input entry point that receives signed Cal.com webhooks and
starts a workflow. It only handles incoming delivery and verification. Use the separate
[Cal.com node](./cal-node.md) for Cal.com API operations such as creating or deleting webhooks.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.event`, `$nodeLabel.triggerEvent`, `$nodeLabel.payload`, `$nodeLabel.headers`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `cal_trigger` credential containing the webhook signing secret |
| `active` | boolean | Enables incoming delivery; defaults to `true` |

## Setup

1. Create a **Cal.com Trigger (Webhook Secret)** credential with a strong random secret.
2. Add a **Cal.com Trigger**, select that credential, and copy the displayed webhook URL.
3. Create the remote webhook in Cal.com settings or with a [Cal.com node](./cal-node.md).
4. Use the copied URL as `subscriberUrl` and the same secret as the remote webhook `secret`.

Cal.com Cloud accepts only publicly reachable HTTPS subscriber URLs. Self-hosted Cal.com may use
HTTP or internal addresses according to its own configuration.

## Output Fields

| Expression | Description |
|------------|-------------|
| `$nodeLabel.event` | Complete Cal.com webhook body |
| `$nodeLabel.triggerEvent` | Top-level event name, or `null` when omitted |
| `$nodeLabel.payload` | Top-level `payload`, or the complete body when `payload` is absent |
| `$nodeLabel.headers` | Sanitized request headers |
| `$nodeLabel.triggered_at` | ISO timestamp assigned when Heym receives the event |

The payload shape varies by Cal.com event. Meeting events and custom templates can be flat, so Heym
falls back to the complete body when no top-level `payload` exists. The payload version remains
available through `headers['x-cal-webhook-version']`.

## Custom Payload Templates

When configuring a custom template on the remote webhook, keep `triggerEvent` and `createdAt` at the
top level. `triggerEvent` preserves the event-name output; `createdAt` enables duplicate-delivery
suppression.

## Security and Delivery

- Heym verifies HMAC-SHA256 over the raw body against `x-cal-signature-256`.
- Missing credentials, missing signatures, and invalid signatures are rejected before execution.
- Authorization and signature headers are not exposed downstream.
- Payloads with a top-level `createdAt` or `idempotencyKey` are deduplicated for 24 hours.
- Verified requests are acknowledged immediately and execute in the background.
- The workflow-specific URL is `POST /api/cal/webhook/{workflow_id}/{node_id}`.
- The deprecated node-only URL remains available when its signature identifies exactly one workflow.

## Related

- [Cal.com Node](./cal-node.md) – Webhook API operations
- [Triggers](../reference/triggers.md) – Workflow entry points
- [Credentials](../reference/credentials.md) – Credential storage
