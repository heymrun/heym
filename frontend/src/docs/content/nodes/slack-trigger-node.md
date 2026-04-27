# Slack Trigger

The **Slack Trigger** node is a zero-input entry point that receives Slack Events API webhooks and starts a workflow automatically. It handles Slack's URL verification challenge and verifies request signatures with a signing secret.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.event`, `$nodeLabel.headers` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `slack_trigger` credential containing the signing secret |

## Setup Guide

### 1. Create a `slack_trigger` Credential

1. Go to **Settings → Credentials → New Credential**
2. Select type **Slack Trigger (Signing Secret)**
3. Paste the **Signing Secret** from your Slack App:
   - In Slack: **App settings → Basic Information → App Credentials → Signing Secret**
4. Save the credential

### 2. Add the Node to Your Workflow

1. Open the workflow canvas
2. Drag **Slack Trigger** from the node panel onto the canvas
3. Click the node to open the Properties panel
4. Select your `slack_trigger` credential
5. Copy the **Webhook URL** shown in the panel

### 3. Configure Your Slack App

1. In your Slack App settings go to **Event Subscriptions**
2. Toggle **Enable Events** on
3. Paste the Webhook URL into the **Request URL** field
4. Slack sends a URL verification challenge — Heym responds automatically within milliseconds
5. The field turns green: ✓ Verified
6. Subscribe to the **Bot Events** you need (e.g. `message.channels`, `reaction_added`)
7. Save your changes and reinstall the app to your workspace if prompted

## Output Fields

After the node triggers, downstream nodes can access:

| Expression | Description |
|------------|-------------|
| `$nodeLabel.event` | Full Slack event object |
| `$nodeLabel.event.type` | Event type (e.g. `"message"`, `"reaction_added"`) |
| `$nodeLabel.event.text` | Message text (when applicable) |
| `$nodeLabel.event.user` | Slack user ID who triggered the event |
| `$nodeLabel.event.channel` | Channel ID |
| `$nodeLabel.event.ts` | Event timestamp |
| `$nodeLabel.headers` | Sanitized HTTP headers from Slack |

## Example Workflow

**Slack message → LLM reply → Slack send:**

```
slackTrigger → llm → slack
```

- **slackTrigger** label: `slackEvent`
- **LLM** user message: `"Reply to this Slack message: $slackEvent.event.text"`
- **Slack** message: `$llm.text`

## Security

- Requests are verified using **HMAC-SHA256** with your signing secret
- Timestamps older than **5 minutes** are rejected (replay attack prevention)
- Sensitive headers (`x-slack-signature`, `authorization`, etc.) are stripped before they reach downstream nodes
- If no credential is set the node runs without verification — only recommended for local testing

## Notes

- Heym responds with `200 OK` immediately and runs the workflow in the background — this satisfies Slack's 3-second response requirement
- The webhook URL is derived from the node ID and never changes, even after workflow renames
- Only one `slackTrigger` node per workflow is needed; use **Switch** or **Condition** nodes downstream to route different event types
