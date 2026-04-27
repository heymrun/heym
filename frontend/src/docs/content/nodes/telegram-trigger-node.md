# Telegram Trigger

The **Telegram Trigger** node is a zero-input entry point that starts a workflow when your Telegram bot receives a webhook update. Use it for chatbots, support triage, slash-like commands, or inline button callbacks that should fan into downstream AI and integration nodes.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.update`, `$nodeLabel.message`, `$nodeLabel.callback_query`, `$nodeLabel.headers`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `telegram` credential containing the bot token and optional webhook secret token |

## Setup Guide

### 1. Create a `telegram` Credential

1. Go to **Settings → Credentials → New Credential**
2. Select type **Telegram Bot**
3. Paste the **Bot Token** from BotFather
4. Optionally set a **Webhook Secret Token** if you want Telegram to send a matching verification header
5. Save the credential

### 2. Add the Node to Your Workflow

1. Drag **Telegram Trigger** onto the canvas
2. Select the node to open the Properties panel
3. Choose your `telegram` credential
4. Copy the **Webhook URL** shown in the node panel

### 3. Register the Webhook in Telegram

Use the Bot API `setWebhook` method with the URL from the node:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://your-heym-domain/api/telegram/webhook/<node_id>"
```

If you configured a secret token in Heym, send the same value when setting the webhook:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://your-heym-domain/api/telegram/webhook/<node_id>" \
  -d "secret_token=<YOUR_SECRET_TOKEN>"
```

## Output Fields

After the node triggers, downstream nodes can access:

| Expression | Description |
|------------|-------------|
| `$nodeLabel.update` | Full Telegram update payload |
| `$nodeLabel.message` | Primary message-like object from the update |
| `$nodeLabel.message.text` | Incoming message text |
| `$nodeLabel.message.chat.id` | Chat ID for replying downstream |
| `$nodeLabel.message.from.id` | Telegram user ID |
| `$nodeLabel.callback_query` | Callback payload when the update came from an inline keyboard |
| `$nodeLabel.headers` | Sanitized webhook headers |
| `$nodeLabel.triggered_at` | ISO timestamp for this workflow execution |

## Example Workflow

**Telegram message → LLM → Telegram reply**

```
telegramTrigger → llm → telegram
```

- **Telegram Trigger** label: `telegramEvent`
- **LLM** user message: `"Reply briefly to this user message: $telegramEvent.message.text"`
- **Telegram** chatId: `$telegramEvent.message.chat.id`

## Security

- If your credential has a `secret_token`, Heym verifies `x-telegram-bot-api-secret-token` before running the workflow.
- Sensitive request headers are removed before the payload reaches downstream nodes.
- The webhook URL is static for the node ID, so you only need to re-register it when the node itself changes.

## Related

- [Telegram Node](./telegram-node.md) – Send a reply or outbound notification
- [Triggers](../reference/triggers.md) – Overview of all workflow entry points
- [Third-Party Integrations](../reference/integrations.md) – Telegram credential setup
- [Credentials Tab](../tabs/credentials-tab.md) – Add and manage `telegram` credentials
