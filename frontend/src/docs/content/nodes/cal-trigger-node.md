# Cal.com Trigger

The **Cal.com Trigger** node is a zero-input entry point that receives signed Cal.com webhooks and starts a workflow. Use it for booking, meeting, recording, routing-form, and other Cal.com automation events.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.event`, `$nodeLabel.triggerEvent`, `$nodeLabel.payload`, `$nodeLabel.headers`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `cal_trigger` credential containing the shared webhook secret |

## Setup Guide

### 1. Create a `cal_trigger` Credential

1. Go to **Settings → Credentials → New Credential**
2. Select **Cal.com Trigger (Webhook Secret)**
3. Enter a strong random secret
4. Save the credential

### 2. Add the Node

1. Drag **Cal.com Trigger** onto the canvas
2. Select the credential you created
3. Copy the **Webhook URL** shown in the Properties panel

### 3. Create the Webhook in Cal.com

1. Open your Cal.com webhook settings or use the Cal.com API
2. Set the subscriber URL to the URL copied from Heym
3. Select events such as `BOOKING_CREATED`, `BOOKING_RESCHEDULED`, or `BOOKING_CANCELLED`
4. Set the webhook secret to exactly the same value stored in the Heym credential
5. Enable and save the webhook

## Output Fields

| Expression | Description |
|------------|-------------|
| `$nodeLabel.event` | Complete Cal.com webhook body |
| `$nodeLabel.triggerEvent` | Event name, such as `BOOKING_CREATED` |
| `$nodeLabel.payload` | Event-specific Cal.com payload |
| `$nodeLabel.headers` | Sanitized request headers |
| `$nodeLabel.triggered_at` | ISO timestamp assigned when Heym receives the event |

The fields inside `payload` vary by event. Inspect a completed run before writing expressions for a new event type.

## Example Workflow

```text
calTrigger → set → slack
```

- **Cal.com Trigger** label: `calEvent`
- **Set** attendee email: `$calEvent.payload.attendees[0].email`
- **Set** event type: `$calEvent.triggerEvent`

## Security

- Heym calculates HMAC-SHA256 over the raw request body using the selected credential
- The result must match the `x-cal-signature-256` header
- Missing credentials, missing signatures, and invalid signatures are rejected before execution
- The signature and other sensitive authorization headers are removed from downstream output
- Use a unique secret for each independently managed webhook

## Notes

- Heym acknowledges a verified webhook immediately and runs the workflow in the background
- The webhook URL is based on the node ID and remains stable when the workflow is renamed
- Event selection is managed in Cal.com; use **Switch** or **Condition** when one webhook sends several event types
- Removing or replacing the node changes the subscriber URL, so update the Cal.com webhook afterward

## Related

- [Triggers](../reference/triggers.md) – Workflow entry points
- [Third-Party Integrations](../reference/integrations.md) – Cal.com setup summary
- [Credentials](../reference/credentials.md) – Credential storage
- [Credentials Sharing](../reference/credentials-sharing.md) – Sharing rules
