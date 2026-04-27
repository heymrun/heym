# IMAP Trigger

The **IMAP Trigger** node polls an email inbox on a fixed interval and starts a workflow once for each newly detected message. It is a zero-input trigger node designed for inbound email automation such as support triage, shared mailbox monitoring, and approval mailboxes.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.email`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `imap` credential containing server, login, mailbox, and SSL settings |
| `pollIntervalMinutes` | Integer | How often Heym checks the mailbox for new email |

## Setup Guide

### 1. Create an `imap` Credential

1. Go to **Settings → Credentials → New Credential**
2. Select type **IMAP Email Inbox**
3. Enter:
   - **IMAP Host** (for example `imap.gmail.com`)
   - **IMAP Port** (`993` for SSL/TLS on most providers)
   - **Username / Email**
   - **Password / App Password**
   - Optional **Mailbox** (default: `INBOX`)
4. Leave **Use SSL / TLS** enabled unless your mail server explicitly requires non-SSL IMAP
5. Save the credential

### 2. Add the Node to Your Workflow

1. Drag **IMAP Trigger** onto the canvas
2. Select the node to open the Properties panel
3. Choose your `imap` credential
4. Set **Poll Interval (Minutes)** with an integer value such as `1`, `5`, or `15`

## Trigger Semantics

- The first poll establishes a baseline of the current mailbox contents and does **not** replay older email.
- Later polls trigger once per message whose IMAP UID is newer than the saved cursor.
- If the mailbox `UIDVALIDITY` changes, Heym resets the cursor and baselines again to avoid duplicate processing.
- Each new email starts a separate workflow execution with `trigger_source = "imap"`.

## Output Fields

After the node triggers, downstream nodes can access:

| Expression | Description |
|------------|-------------|
| `$nodeLabel.email` | Full parsed email payload |
| `$nodeLabel.email.subject` | Decoded subject |
| `$nodeLabel.email.from` | Raw `From` header |
| `$nodeLabel.email.fromAddresses` | Parsed sender list |
| `$nodeLabel.email.toAddresses` | Parsed recipient list |
| `$nodeLabel.email.ccAddresses` | Parsed CC list |
| `$nodeLabel.email.replyToAddresses` | Parsed reply-to list |
| `$nodeLabel.email.text` | Plain-text body |
| `$nodeLabel.email.html` | HTML body |
| `$nodeLabel.email.attachments` | Array of attachment metadata (`filename`, `content_type`, `size_bytes`) |
| `$nodeLabel.email.headers` | Decoded header object |
| `$nodeLabel.email.uid` | IMAP UID for deduping or logging |
| `$nodeLabel.triggered_at` | ISO timestamp for the workflow execution |

## Example Workflow

**Inbound support email → summarize → route**

```
imapTrigger → llm → condition → slack / sendEmail
```

- **IMAP Trigger** label: `supportInbox`
- **LLM** user message: `"Summarize this email from $supportInbox.email.from: $supportInbox.email.text"`
- **Condition**: `$supportInbox.email.subject.lower().contains("urgent")`

## Notes

- Many providers require an **app password** for IMAP access instead of your main account password.
- Attachment contents are not injected into the workflow input; only attachment metadata is included.
- Use [Send Email](./send-email-node.md), [Telegram](./telegram-node.md), [Slack](./slack-node.md), or [DataTable](./datatable-node.md) downstream to route or log new email.

## Related

- [Triggers](../reference/triggers.md) – Overview of all workflow entry points
- [Third-Party Integrations](../reference/integrations.md) – IMAP credential setup
- [Credentials Tab](../tabs/credentials-tab.md) – Add and manage `imap` credentials
- [Send Email](./send-email-node.md) – Reply or forward inbound messages
