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
| `setupMode` | `manual` / `managed` | Keep existing webhooks manual, or let Heym manage them through the Cal.com API |
| `credentialId` | UUID | Manual mode: `cal_trigger` credential containing the shared webhook secret |
| `calApiCredentialId` | UUID | Managed mode: `cal_api` credential used for webhook CRUD |
| `events` | string[] | Managed mode: one or more Cal.com event names |
| `payloadVersion` | string | `2021-10-20` (default) or its backward-compatible `2026-07-27` extension, which adds optional attendee and organizer ICS content to selected booking events |
| `payloadTemplate` | string | Optional Cal.com payload template |
| `noShowTime` | integer | Delay before evaluating host/guest Cal Video no-show events; minimum `1`, default `5` |
| `noShowTimeUnit` | string | `MINUTE` (default), `HOUR`, or `DAY` |
| `active` | boolean | Enables delivery and managed synchronization |

## Setup Guide

### Managed setup (recommended)

1. Create a **Cal.com API** credential with a Cal.com API key. Keep
   `https://api.cal.com` for Cal.com Cloud, or enter the origin of your self-hosted instance.
   Heym uses API v2 exclusively: an origin gets `/v2` appended automatically, while an explicit
   versioned URL must end in `/v2`. URLs containing `/v1` or another API version are rejected.
2. Add a **Cal.com Trigger**, select **Managed with Cal.com API**, and choose the API credential.
3. Select one or more events and a payload version. Optionally add a payload template. Host/guest
   Cal Video no-show events also require an evaluation delay and unit.
4. Select **Save & Sync**. Heym generates a unique webhook secret, stores it encrypted, and creates
   or updates the Cal.com webhook.
5. Use **Disable webhook** to remove the remote webhook. Deleting, disabling, or switching the node
   out of managed mode removes the remote webhook before the local configuration is discarded.

The status box shows whether the local registration is active, inactive, or in an error state. A
Cal.com API credential cannot be deleted while an active managed webhook still references it.
Its API key and base URL also cannot be changed until those managed webhooks are disabled, preventing
the old Cal.com instance or account from retaining an unreachable webhook.

Heym blocks Cal.com API base URLs that resolve to loopback, private, link-local, or cloud metadata
addresses by default. Trusted self-hosted deployments that intentionally use an internal Cal.com API
must set `HEYM_HTTP_ALLOW_PRIVATE_URLS=true`.

### Manual setup

#### 1. Create a `cal_trigger` Credential

1. Go to **Settings → Credentials → New Credential**
2. Select **Cal.com Trigger (Webhook Secret)**
3. Enter a strong random secret
4. Save the credential

#### 2. Add the Node

1. Drag **Cal.com Trigger** onto the canvas
2. Select the credential you created
3. Copy the **Webhook URL** shown in the Properties panel

#### 3. Create the Webhook in Cal.com

1. Open your Cal.com webhook settings or use the Cal.com API
2. Set the subscriber URL to the URL copied from Heym
3. Select events such as `BOOKING_CREATED`, `INSTANT_MEETING`, or `BOOKING_CANCELLED`
4. Set the webhook secret to exactly the same value stored in the Heym credential
5. Enable and save the webhook

Cal.com Cloud accepts only publicly reachable HTTPS subscriber URLs. It rejects `localhost`, private
IP addresses, and hostnames that resolve to private addresses. A self-hosted Cal.com instance can use
HTTP and internal addresses, but still rejects cloud metadata endpoints.

## Output Fields

| Expression | Description |
|------------|-------------|
| `$nodeLabel.event` | Complete Cal.com webhook body |
| `$nodeLabel.triggerEvent` | Top-level event name, such as `BOOKING_CREATED`; `null` when a custom template omits it |
| `$nodeLabel.payload` | Top-level `payload` value, or the complete body when that field is absent |
| `$nodeLabel.headers` | Sanitized request headers |
| `$nodeLabel.triggered_at` | ISO timestamp assigned when Heym receives the event |

The fields inside `payload` vary by event. `MEETING_STARTED` and `MEETING_ENDED` use a flat Cal.com
event shape, so their `payload` output contains the complete event body. The same fallback applies to
custom templates without a top-level `payload` field. Inspect a completed run before writing
expressions for a new event type.

Cal.com includes the payload version in `x-cal-webhook-version`. Heym preserves that header in
`$nodeLabel.headers`, for example `$nodeLabel.headers['x-cal-webhook-version']`.

## Custom Payload Templates

Custom templates replace Cal.com's standard wrapper. Include `triggerEvent` when downstream nodes
need the event name, and include a top-level `createdAt` to enable Heym's duplicate-delivery
protection. Keeping application fields under `payload` preserves the standard output shape:

```json
{
  "triggerEvent": "{{triggerEvent}}",
  "createdAt": "{{createdAt}}",
  "payload": {
    "uid": "{{uid}}",
    "title": "{{title}}"
  }
}
```

The field names must be exactly `triggerEvent` and `createdAt` at the top level. Nesting or renaming
them prevents Heym from exposing `triggerEvent` or recognizing duplicate deliveries.

## Example Workflow

```text
calTrigger → set → slack
```

- **Cal.com Trigger** label: `calEvent`
- **Set** attendee email: `$calEvent.payload.attendees[0].email`
- **Set** event type: `$calEvent.triggerEvent`

## Security

- Heym calculates HMAC-SHA256 over the raw request body and compares it to `x-cal-signature-256`
- Manual mode uses the selected `cal_trigger` webhook secret; managed mode uses the generated secret
  stored with the local subscription (not the Cal.com API key)
- Missing credentials, missing signatures, and invalid signatures are rejected before execution
- The signature and other sensitive authorization headers are removed from downstream output
- Use a unique secret for each independently managed webhook

## Notes

- Heym acknowledges a verified webhook immediately and runs the workflow in the background
- Payloads containing a top-level `createdAt` or `idempotencyKey` are deduplicated for 24 hours;
  this is a Heym retention policy, not a Cal.com retry-window guarantee
- If you use a custom payload template, include top-level `createdAt`; without a delivery identity, Heym
  executes every signed delivery rather than risk dropping two distinct events with identical bodies
- The webhook URL contains both the workflow ID and node ID and remains stable when the workflow is renamed
- Older node-only manual URLs remain available as a deprecated compatibility path when the signature
  identifies exactly one workflow. Update them to the workflow-specific URL; ambiguous cloned node IDs
  are rejected instead of choosing an arbitrary workflow.
- In manual mode, event selection remains managed in Cal.com. In managed mode, select events in the node.
- Managed mode preserves its generated signing secret across re-syncs and removes the remote webhook on disable.
- Clearing the payload template and syncing explicitly clears the template on Cal.com.
- Workflow and scheduled hard deletion stop and retry later if Cal.com cleanup fails, preserving the
  local webhook ID until the remote webhook is removed.

## Related

- [Triggers](../reference/triggers.md) – Workflow entry points
- [Third-Party Integrations](../reference/integrations.md) – Cal.com setup summary
- [Credentials](../reference/credentials.md) – Credential storage
- [Credentials Sharing](../reference/credentials-sharing.md) – Sharing rules
