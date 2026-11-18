# Outlook Trigger

The **Outlook Trigger** node watches an Outlook.com or Microsoft 365 (work or school) mailbox through Microsoft Graph and starts a workflow once for each new email. It does everything the [IMAP Trigger](./imap-trigger-node.md) does, with the same `email` output, and adds what Outlook has: the Focused and Other inbox, mail folders, flagged email, aliases, and an action Heym takes on the email after its run starts, such as marking it read.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.email`, `$nodeLabel.attachments`, `$nodeLabel.file_ids`, `$nodeLabel.triggered_at` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `outlook` credential (Microsoft OAuth) |
| `pollIntervalMinutes` | Integer | How often Heym checks the mailbox. Minimum and default `1` |
| `outlookMailbox` | String | Which mail starts a run. See [Mailboxes](#mailboxes). Default `inbox` |
| `outlookFolderId` | String | Mail folder id when `outlookMailbox` is `folder`. `outlookFolderName` keeps its path, such as `Inbox / Invoices` |
| `outlookFlaggedOnly` | Boolean | **Flagged email only**. Only flagged email in the mailbox starts a run. See [Flagged email](#flagged-email). Off by default |
| `outlookAliases` | String[] | Only email sent or delivered to one of these addresses starts a run. Empty means any address |
| `outlookAfterAction` | String | What Heym does to the email once its run has started. See [After the run starts](#after-the-run-starts). Default `none` |
| `outlookDownloadAttachments` | Boolean | **Download attachments to Drive**. Saves each attachment to the workflow owner's Heym Drive during the run. Off by default |

These fields hold plain values, not expressions: the poller reads them before any run exists.

## Setup Guide

### 1. Create an `outlook` Credential

1. In the [Microsoft Entra admin center](https://entra.microsoft.com), open **App registrations → New registration**. Under **Supported account types**, pick the accounts that should connect: any organization plus personal Microsoft accounts, or only your organization.
2. Add a **Web** redirect URI: `https://your-heym-domain/api/credentials/outlook/oauth/callback`. For local development, use your browser's Heym origin with the same path.
3. Under **API permissions**, add the Microsoft Graph delegated permissions `Mail.ReadWrite`, `Mail.Send`, `User.Read` and `offline_access`. If your organization does not let users consent to apps, an administrator clicks **Grant admin consent**.
4. Under **Certificates & secrets**, create a client secret and copy its **Value**.
5. Open **Dashboard → Credentials → New → Outlook Mail (OAuth2)**, enter a name, the **Application (client) ID**, the client secret and the **Tenant**, then click **Connect** and sign in with the mailbox to watch.

| Tenant | Who can connect |
|--------|-----------------|
| `common` (default) | Work, school and personal Microsoft accounts |
| `organizations` | Any work or school account |
| `consumers` | Outlook.com, Hotmail and Live accounts only |
| A tenant id or domain, such as `contoso.com` | Accounts of that one organization |

Tokens are encrypted in storage and refreshed automatically. `Mail.ReadWrite` lets Heym read mail, mark it read and move it between folders, and `Mail.Send` lets [Outlook Send](./outlook-send-node.md) send from the mailbox. Heym never deletes mail permanently. The credential shows the connected address once connected.

### 2. Add the Node to Your Workflow

1. Drag **Outlook Trigger** onto the canvas and select your `outlook` credential.
2. Pick a **Mailbox**. For **A folder…**, choose one of the account's folders from the list; nested folders show their path.
3. Turn on **Flagged email only** to start runs only for email you flag.
4. Optionally list addresses under **Only email sent to**. The account's own addresses (the primary one and its aliases) appear as chips you can click.
5. Choose what happens **After the run starts**, and turn on **Download attachments to Drive** when a later node needs the files.

### Exchange Server (on-premises)

For an organization that runs its own Exchange Server instead of Microsoft 365, choose **Sign in with → Exchange Server (on-premises)** in the `outlook` credential and enter the email address and the Windows password; the user name (blank signs in with the email address) and the server are optional. Heym reads the mailbox through Exchange Web Services; see [Exchange Server sign-in](../reference/integrations.md#exchange-server-on-premises). Every mailbox works except **Focused** and **Other**, which Exchange Server does not have. If Exchange refuses the password, the trigger stops polling until the credential is updated.

## Mailboxes

| `outlookMailbox` | Starts a run for |
|------------------|------------------|
| `inbox` | Every email received in the inbox |
| `focused` | Inbox email in **Focused** |
| `other` | Inbox email in **Other** |
| `important` | Email marked high importance, in any folder that receives mail |
| `sent` | Email the account sends (Sent Items) |
| `all` | All received email, archived and filed included. Sent Items, Drafts, Deleted Items, Junk Email and Outbox are left out |
| `folder` | Email in the chosen folder, for example one an Outlook rule files mail into |

A run starts when an email is received into the mailbox. Mail an Outlook rule files into a folder counts for that folder. Moving older email into a folder by hand does not start a run; use **Flagged email only** when you want to pick older email yourself.

## Flagged email

With **Flagged email only** (`outlookFlaggedOnly`) on, only flagged email in the chosen mailbox starts a run:

- Flagging an email starts its run at the next poll, however old the email is.
- An email that arrives already flagged (for example by a rule) starts a run too.
- Email that was flagged before the trigger was turned on does not start runs.
- Unflagging an email and flagging it again starts another run. Marking a flag complete counts as unflagging.

It combines with every mailbox: **Inbox** plus **Flagged email only** reacts to flags in the inbox, **All mail** to flags anywhere. The trigger follows up to 1,000 flagged emails per mailbox.

## Aliases

With addresses in **Only email sent to** (`outlookAliases`), an email starts a run only when one of them is among its `To`, `Cc`, `Delivered-To`, `X-Original-To` or `X-Forwarded-To` addresses. Matching ignores case.

Use it for:

- a Microsoft 365 alias (an extra address of the mailbox), such as `sales@contoso.com`,
- a plus address such as `me+invoices@contoso.com`. A plus address matches only itself.

## After the run starts

| `outlookAfterAction` | Effect in Outlook |
|----------------------|-------------------|
| `none` | Nothing. The email stays as it is (default) |
| `markRead` | Marks the email as read |
| `archive` | Moves it to the Archive folder |
| `markReadAndArchive` | Both |
| `delete` | Moves it to Deleted Items, where it stays recoverable |

Heym applies the action once the email's run has started, whatever the run's outcome, also when the run waits for human review or runs on another [instance](../reference/cluster.md). If the run could not be started at all, the email is left alone. An action Outlook refuses (for example **Archive** on a mailbox without an Archive folder) is logged and the next email still runs. Heym never deletes mail permanently.

## Trigger Semantics

- The first poll records where the mailbox is and does **not** replay older email.
- Each new email starts a separate run with `trigger_source = "outlook"`, at most once, also on multi-worker and multi-instance installs.
- Email that shows up in the mailbox up to 10 minutes after it was received still starts its run.
- A poll runs at most 50 emails; the rest run on the next poll.
- Changing the account, the mailbox, the folder or **Flagged email only** records where the mailbox is again without starting runs.
- Turning the trigger off and on again starts from the mailbox as it is then.

## Output Fields

The `email` payload has the same fields as the [IMAP Trigger](./imap-trigger-node.md#output-fields) (`subject`, `from`, `fromAddresses`, `toAddresses`, `ccAddresses`, `replyToAddresses`, `text`, `html`, `attachments`, `headers`, `messageId`, `date`), without the IMAP `uid`, plus:

| Expression | Description |
|------------|-------------|
| `$nodeLabel.email.id` | Outlook message id (stays the same when the email moves between folders) |
| `$nodeLabel.email.conversationId` | Outlook conversation id |
| `$nodeLabel.email.folderId` | Id of the folder the email is in |
| `$nodeLabel.email.categories` | The email's Outlook categories, for example `["Red category"]` |
| `$nodeLabel.email.importance` | `low`, `normal` or `high` |
| `$nodeLabel.email.inferenceClassification` | `focused` or `other` |
| `$nodeLabel.email.flagged` | Whether the email is flagged |
| `$nodeLabel.email.isRead` | Whether the email was read when the poll saw it |
| `$nodeLabel.email.webLink` | Link that opens the email in Outlook on the web |
| `$nodeLabel.email.snippet` | Outlook's short preview of the body |
| `$nodeLabel.attachments` | One item per attachment, in email order |
| `$nodeLabel.file_ids` | Drive file ids of the saved attachments; `[]` when the toggle is off |
| `$nodeLabel.triggered_at` | ISO timestamp for the workflow execution |

## Attachments in Heym Drive

**Download attachments to Drive** works as on the [IMAP Trigger](./imap-trigger-node.md#attachments-in-heym-drive): the same `attachments` item fields and `skipped_reason` values, at most 10 attachments per email, each within the Drive file size limit. Heym fetches the email again by its Outlook id during the run, so an email moved to Archive or Deleted Items by the after-run action can still be read. These runs stay on the [main instance](../reference/cluster.md), where Drive files live.

## Example Workflows

**Focused inbox → summarize → mark read**

```
outlookTrigger → llm → slack
```

- **Outlook Trigger** label `supportOutlook`, Mailbox **Focused Inbox**, After the run starts **Mark as read**
- **LLM** user message: `"Summarize this email from $supportOutlook.email.from: $supportOutlook.email.text"`

**Flag an email → create a follow-up task**

```
outlookTrigger (Flagged email only) → agent → linear
```

- **Outlook Trigger** label `flaggedOutlook`, Mailbox **Inbox**, **Flagged email only** on
- **Agent** user message: `"Write a follow-up task for this email: $flaggedOutlook.email.subject $flaggedOutlook.email.text. Link: $flaggedOutlook.email.webLink"`

**Invoice folder → read the PDFs → archive**

```
outlookTrigger (Download attachments to Drive) → agent → dataTable
```

- **Outlook Trigger** label `invoiceOutlook`, Mailbox **A folder…** `Inbox / Invoices`, **Mark as read and move to Archive**
- **Agent** user message: `"Extract vendor, total and due date from these invoices: $invoiceOutlook.file_ids"`

## Notes

- Use the [Gmail Trigger](./gmail-trigger-node.md) for Gmail and the [IMAP Trigger](./imap-trigger-node.md) for other mail providers. Microsoft 365 no longer accepts passwords over IMAP, so prefer this node for Outlook mailboxes.
- The trigger reads the signed-in user's own mailbox.
- Attachment contents never go into the workflow input or execution history; only metadata does.
- A workflow that watches `sent` and also sends email through the same account starts itself again. Filter on the recipient or the subject first.

## Related

- [Triggers](../reference/triggers.md): every workflow entry point
- [Third-Party Integrations](../reference/integrations.md#outlook-mail-oauth2): Outlook credential setup
- [Credentials Sharing](../reference/credentials-sharing.md#outlook-mailbox-access): what sharing an Outlook credential allows
- [Outlook Send](./outlook-send-node.md): answer from the same Outlook mailbox
- [Send Email](./send-email-node.md): reply to or forward inbound email over SMTP
