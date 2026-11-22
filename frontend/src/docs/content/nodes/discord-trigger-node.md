# Discord Trigger

The **Discord Trigger** node is a zero-input entry point that receives Discord Interactions API webhooks and starts a workflow automatically. Use it for slash commands, buttons, modals, and other Discord application interactions that should flow into downstream AI or integration nodes.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.interaction`, `$nodeLabel.type`, `$nodeLabel.data`, `$nodeLabel.headers`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `discord_trigger` credential containing the Discord application public key |

## Setup Guide

### 1. Create a `discord_trigger` Credential

1. Go to **Settings → Credentials → New Credential**
2. Select type **Discord Trigger (Public Key)**
3. Paste the **Application Public Key** from Discord Developer Portal:
   - **Your application → General Information → Public Key**
4. Save the credential

### 2. Add the Node to Your Workflow

1. Drag **Discord Trigger** onto the canvas
2. Select the node to open the Properties panel
3. Choose your `discord_trigger` credential
4. Copy the **Interactions URL** shown in the node panel

### 3. Register the Interactions Endpoint in Discord

1. Open the [Discord Developer Portal](https://discord.com/developers/applications)
2. Select your application
3. Go to **General Information** or **Interactions**
4. Paste the node's **Interactions Endpoint URL** into the endpoint field
5. Discord sends a `PING` request to validate the endpoint and Heym responds automatically after verifying the signature
6. Save your changes

## Output Fields

After the node triggers, downstream nodes can access:

| Expression | Description |
|------------|-------------|
| `$nodeLabel.interaction` | Full Discord interaction payload |
| `$nodeLabel.type` | Interaction type |
| `$nodeLabel.data` | Command, button, or modal payload |
| `$nodeLabel.data.name` | Slash command name, when applicable |
| `$nodeLabel.data.options` | Slash command options array |
| `$nodeLabel.headers` | Sanitized webhook headers |
| `$nodeLabel.triggered_at` | ISO timestamp for this workflow execution |

## Example Workflow

**Discord slash command → LLM → Output**

```
discordTrigger → llm → output
```

- **Discord Trigger** label: `discordEvent`
- **LLM** user message: `"Reply to this Discord command: $discordEvent.data.name"`
- **Output** message: `$llm.text`

## Security

- Requests are verified using **Ed25519** with your application's public key
- Timestamps older than **5 minutes** are rejected to reduce replay attacks
- Sensitive headers (`x-signature-ed25519`, `authorization`, etc.) are removed before data reaches downstream nodes
- The trigger requires a valid `discord_trigger` credential; requests are rejected if the credential is missing or invalid

## Notes

- Heym returns a deferred Discord response immediately, runs the workflow in the background, and posts the final workflow output as a Discord follow-up when an `Output` node produces content
- The interactions URL is derived from the node ID and stays stable even if the workflow is renamed
- Use a regular [Discord Node](./discord-node.md) only when you also want a separate webhook post in addition to the interaction follow-up
- One `discordTrigger` node is usually enough; use **Switch** or **Condition** downstream to route different interaction types

## Related

- [Discord Node](./discord-node.md) – Send outbound Discord messages
- [Triggers](../reference/triggers.md) – Overview of all workflow entry points
- [Third-Party Integrations](../reference/integrations.md) – Discord credential setup
- [Credentials Tab](../tabs/credentials-tab.md) – Add and manage `discord_trigger` credentials
