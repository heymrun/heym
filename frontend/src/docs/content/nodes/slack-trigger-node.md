# Slack Trigger

The **Slack Trigger** node is a zero-input entry point that receives Slack Events API webhooks and starts a workflow automatically. It handles Slack's URL verification challenge and verifies request signatures with a signing secret.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.event`, `$nodeLabel.headers`, `$nodeLabel.triggered_by`, `$nodeLabel.trigger_node_id` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `slack_trigger` credential, or a `slack_bot` credential with a signing secret |
| `slackEventScope` | string | What starts a run: `all` (default, every event), `messages` (a person's message in a channel or DM), `directMessages` (DMs to the bot), `mentions` (the bot is mentioned), `channel` (messages in one channel) |
| `slackEventChannel` | string | Channel ID for the `channel` scope, e.g. `C0123ABCD` |

## One Slack app, many workflows

A Slack app has a single Event Subscriptions Request URL. Use the credential's events URL, `<Heym URL>/api/slack/events/<credential id>`, shown in the node panel and in the Slack Bot credential dialog. Every Slack Trigger that uses the credential hears the app's events, and each starts only for its own scope: one workflow can answer DMs while another watches `#support`. The node's own webhook URL still works when only that workflow should hear the app.

## Direct messages

To start on DMs, the app needs the `im:history` scope, the `message.im` bot event, and its **Messages Tab** turned on with "Allow users to send Slash commands and messages from the messages tab". The manifest from a Slack Bot credential sets all three. A DM arrives with `$nodeLabel.event.channel_type` set to `im`, and a reply to `$nodeLabel.event.channel` answers in the same DM.

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
| `$nodeLabel.triggered_by` | Trigger source label (`"Slack"`) |
| `$nodeLabel.trigger_node_id` | Canvas node ID that received the Slack event |

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
