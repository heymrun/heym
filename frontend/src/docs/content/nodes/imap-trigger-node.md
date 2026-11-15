# IMAP Trigger

The **IMAP Trigger** node polls an email inbox on a fixed interval and starts a workflow once for each newly detected message. It is a zero-input trigger node designed for inbound email automation such as support triage, shared mailbox monitoring, and approval mailboxes.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.email`, `$nodeLabel.attachments`, `$nodeLabel.file_ids`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `imap` credential containing server, login, mailbox, and SSL settings |
| `pollIntervalMinutes` | Integer | How often Heym checks the mailbox for new email |
| `imapDownloadAttachments` | Boolean | **Download attachments to Drive**. Saves each attachment to the workflow owner's Heym Drive during the run. Off by default |

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
5. Turn on **Download attachments to Drive** when a later node needs the attached files, not only their names

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
| `$nodeLabel.attachments` | One item per attachment, in email order (see below) |
| `$nodeLabel.file_ids` | Drive file ids of the saved attachments; `[]` when the toggle is off |
| `$nodeLabel.triggered_at` | ISO timestamp for the workflow execution |

## Attachments in Heym Drive

With **Download attachments to Drive** on, each attachment is saved to the workflow owner's [Drive](../tabs/drive-tab.md), with the IMAP Trigger as its source. Each item in `$nodeLabel.attachments` has:

| Field | Description |
|-------|-------------|
| `id` | Drive file id, or `null` when the file was not saved |
| `filename` | Attachment file name |
| `content_type` | MIME type, for example `application/pdf` |
| `size_bytes` | Size in bytes |
| `download_url` | Drive download link, or `null` when the file was not saved |
| `skipped_reason` | `null` for a saved file, otherwise `too_large`, `too_many` or `unavailable` |

`$nodeLabel.file_ids` has the same shape as the Slack node's `file_ids`. Put it in an [Agent](./agent-node.md) user message and the agent opens the files with file analysis, or pass it to a [Converter](./converter-node.md) or [Drive](./drive-node.md) node.

With the toggle off, `$nodeLabel.attachments` holds the same metadata as `$nodeLabel.email.attachments` (`filename`, `content_type`, `size_bytes`), so expressions that read `attachments` work in both modes. `email.attachments` never changes.

**Limits:**

- An attachment larger than the Drive file size limit is skipped with `too_large`; the others are still saved.
- At most 10 attachments per email are saved. The rest are listed with `too_many`.
- Heym fetches the email again when the run starts. If it was deleted or moved, or the mailbox was rebuilt (`UIDVALIDITY` changed), nothing is saved and every item is `unavailable`. The run keeps going with the email text.
- A storage error, such as a full disk, fails the step and leaves no partial files behind.
- The email stays unread: Heym opens the mailbox read-only.
- These runs stay on the [main instance](../reference/cluster.md), where Drive files live.

## Example Workflow

**Inbound support email → summarize → route**

```
imapTrigger → llm → condition → slack / sendEmail
```

- **IMAP Trigger** label: `supportInbox`
- **LLM** user message: `"Summarize this email from $supportInbox.email.from: $supportInbox.email.text"`
- **Condition**: `$supportInbox.email.subject.lower().contains("urgent")`

**Invoice inbox → read the PDF → log it**

```
imapTrigger (Download attachments to Drive) → agent → dataTable
```

- **IMAP Trigger** label: `invoiceInbox`, **Download attachments to Drive** on
- **Agent** user message: `"Extract vendor, total and due date from these invoices: $invoiceInbox.file_ids"`
- **DataTable** inserts one row per invoice

## Notes

- Many providers require an **app password** for IMAP access instead of your main account password.
- Attachment contents are never put into the workflow input or execution history; only metadata is. Turn on **Download attachments to Drive** to work with the files themselves.
- Inline images with a file name, such as a signature logo, count as attachments.
- Use [Send Email](./send-email-node.md), [Telegram](./telegram-node.md), [Slack](./slack-node.md), or [DataTable](./datatable-node.md) downstream to route or log new email.

## Related

- [Triggers](../reference/triggers.md) – Overview of all workflow entry points
- [Third-Party Integrations](../reference/integrations.md) – IMAP credential setup
- [Credentials Tab](../tabs/credentials-tab.md) – Add and manage `imap` credentials
- [Send Email](./send-email-node.md) – Reply or forward inbound messages
