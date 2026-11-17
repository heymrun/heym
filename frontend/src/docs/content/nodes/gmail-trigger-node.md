# Gmail Trigger

The **Gmail Trigger** node watches a Gmail or Google Workspace mailbox through the Gmail API and starts a workflow once for each new email. It does everything the [IMAP Trigger](./imap-trigger-node.md) does, with the same `email` output, and adds what only Gmail has: the inbox tabs (Primary, Promotions and the rest), labels, aliases, and an action Heym takes on the email after its run starts, such as marking it read.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.email`, `$nodeLabel.attachments`, `$nodeLabel.file_ids`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `gmail` credential (Google OAuth) |
| `pollIntervalMinutes` | Integer | How often Heym checks the mailbox. Minimum and default `1` |
| `gmailMailbox` | String | Which mail starts a run. See [Mailboxes](#mailboxes). Default `inbox` |
| `gmailLabelId` | String | Gmail label id when `gmailMailbox` is `label`. `gmailLabelName` keeps its display name |
| `gmailAliases` | String[] | Only email sent or delivered to one of these addresses starts a run. Empty means any address |
| `gmailAfterAction` | String | What Heym does to the email once its run has started. See [After the run starts](#after-the-run-starts). Default `none` |
| `gmailDownloadAttachments` | Boolean | **Download attachments to Drive**. Saves each attachment to the workflow owner's Heym Drive during the run. Off by default |

These fields hold plain values, not expressions: the poller reads them before any run exists.

## Setup Guide

### 1. Create a `gmail` Credential

1. In [Google Cloud Console](https://console.cloud.google.com), enable the **Gmail API**.
2. Configure the OAuth consent screen and create a **Web application** OAuth client. Add your Google account as a test user if the app is in testing mode.
3. Register `https://your-heym-domain/api/credentials/gmail/oauth/callback` as an authorized redirect URI. For local development, use your browser's Heym origin with the same path.
4. Open **Dashboard → Credentials → New → Gmail (OAuth2)**, enter a name, Client ID and Client Secret, then click **Connect** and sign in with the Gmail account to watch.
5. Allow Heym to read, send and organize your mail (`gmail.modify`). The credential then shows the connected address.

Tokens are encrypted in storage and refreshed automatically. `gmail.modify` lets Heym read mail, change labels and move mail to Trash, and lets [Gmail Send](./gmail-send-node.md) send from the account. It cannot delete mail permanently.

### 2. Add the Node to Your Workflow

1. Drag **Gmail Trigger** onto the canvas and select your `gmail` credential.
2. Pick a **Mailbox**. For **A label…**, choose one of the account's labels from the list.
3. Optionally list addresses under **Only email sent to**. The account's own addresses (the primary one and its **Send mail as** aliases) appear as chips you can click.
4. Choose what happens **After the run starts**, and turn on **Download attachments to Drive** when a later node needs the files.

## Mailboxes

| `gmailMailbox` | Starts a run for |
|----------------|------------------|
| `inbox` | Every email in the inbox, whatever its tab |
| `primary` | Inbox email in the **Primary** tab, that is, not in Social, Promotions, Updates or Forums |
| `social`, `promotions`, `updates`, `forums` | Inbox email in that tab |
| `important` | Email Gmail marks as important |
| `starred` | Email you star |
| `sent` | Email the account sends |
| `all` | All received email, archived included (for example mail a Gmail filter skips the inbox for). The account's own sent mail is left out |
| `label` | Email with the chosen label |

A run starts when an email arrives in the mailbox, and also when it is moved or labelled into it later: starring an email starts a `starred` run, and a Gmail filter that applies a label starts a `label` run. An email that leaves the mailbox and comes back starts a new run, as a message moved back into an IMAP folder does. Drafts, Spam and Trash never start runs.

## Aliases

With addresses in **Only email sent to** (`gmailAliases`), an email starts a run only when one of them is among its `To`, `Cc`, `Delivered-To`, `X-Original-To` or `X-Forwarded-To` addresses. Matching ignores case, and for `gmail.com` addresses it ignores the dots Gmail ignores, so `jane.doe@gmail.com` matches `janedoe@gmail.com`.

Use it for:

- a **Send mail as** alias or a Google Workspace alias, such as `sales@example.com`,
- a plus address such as `me+invoices@gmail.com`. A plus address matches only itself: `me@gmail.com` does not match mail sent to `me+invoices@gmail.com`, and the other way round.

## After the run starts

| `gmailAfterAction` | Effect in Gmail |
|--------------------|-----------------|
| `none` | Nothing. The email stays as it is (default) |
| `markRead` | Marks the email as read |
| `archive` | Removes it from the inbox |
| `markReadAndArchive` | Both |
| `trash` | Moves it to Trash, where Gmail keeps it for 30 days |

Heym applies the action once the email's run has started, whatever the run's outcome, also when the run waits for human review or runs on another [instance](../reference/cluster.md). If the run could not be started at all, the email is left alone. An action Gmail refuses is logged and the next email still runs. Heym never deletes mail permanently.

A trigger whose action moves the email out of the mailbox (archive, Trash) can make another Gmail Trigger on the same mailbox miss it if that one polls later. Give such workflows the same trigger, or use `markRead` instead.

## Trigger Semantics

- The first poll records where the mailbox is and does **not** replay older email.
- Each new email starts a separate run with `trigger_source = "gmail"`, at most once, also on multi-worker and multi-instance installs.
- A poll runs at most 50 emails; the rest run on the next poll.
- When the credential is reconnected to another Google account, or Gmail no longer keeps the mailbox history from the last poll (after about a week turned off), the trigger records where the mailbox is again without starting runs.
- Turning the trigger off and on again starts from the mailbox as it is then.

## Output Fields

The `email` payload has the same fields as the [IMAP Trigger](./imap-trigger-node.md#output-fields) (`subject`, `from`, `fromAddresses`, `toAddresses`, `ccAddresses`, `replyToAddresses`, `text`, `html`, `attachments`, `headers`, `messageId`, `date`), without the IMAP `uid`, plus:

| Expression | Description |
|------------|-------------|
| `$nodeLabel.email.id` | Gmail message id |
| `$nodeLabel.email.threadId` | Gmail thread id |
| `$nodeLabel.email.labelIds` | The message's Gmail labels, for example `["INBOX", "UNREAD", "CATEGORY_PERSONAL"]` |
| `$nodeLabel.email.snippet` | Gmail's short preview of the body |
| `$nodeLabel.attachments` | One item per attachment, in email order |
| `$nodeLabel.file_ids` | Drive file ids of the saved attachments; `[]` when the toggle is off |
| `$nodeLabel.triggered_at` | ISO timestamp for the workflow execution |

## Attachments in Heym Drive

**Download attachments to Drive** works as on the [IMAP Trigger](./imap-trigger-node.md#attachments-in-heym-drive): the same `attachments` item fields and `skipped_reason` values, at most 10 attachments per email, each within the Drive file size limit. Heym fetches the email again by its Gmail id during the run, so an email moved to Trash by the after-run action can still be read. These runs stay on the [main instance](../reference/cluster.md), where Drive files live.

## Example Workflows

**Primary inbox → summarize → mark read**

```
gmailTrigger → llm → slack
```

- **Gmail Trigger** label `supportGmail`, Mailbox **Primary tab**, After the run starts **Mark as read**
- **LLM** user message: `"Summarize this email from $supportGmail.email.from: $supportGmail.email.text"`

**Invoice label → read the PDFs → archive**

```
gmailTrigger (Download attachments to Drive) → agent → dataTable
```

- **Gmail Trigger** label `invoiceGmail`, Mailbox **A label…** `Invoices`, **Mark as read and archive**
- **Agent** user message: `"Extract vendor, total and due date from these invoices: $invoiceGmail.file_ids"`

## Notes

- Use the [IMAP Trigger](./imap-trigger-node.md) for mail providers other than Gmail.
- Attachment contents never go into the workflow input or execution history; only metadata does.
- A workflow that watches `sent` and also sends email through the same account starts itself again. Filter on the recipient or the subject first.

## Related

- [Triggers](../reference/triggers.md): every workflow entry point
- [Third-Party Integrations](../reference/integrations.md#gmail-oauth2): Gmail credential setup
- [Credentials Sharing](../reference/credentials-sharing.md#gmail-mailbox-access): what sharing a Gmail credential allows
- [Gmail Send](./gmail-send-node.md): answer from the same Gmail account
- [Send Email](./send-email-node.md): reply to or forward inbound email over SMTP
