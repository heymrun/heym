# Gmail Send

The **Gmail Send** node sends an email from a Gmail or Google Workspace account through the Gmail API, with the same `gmail` credential as the [Gmail Trigger](./gmail-trigger-node.md). It has every field of the [Send Email](./send-email-node.md) node (To, Cc, Bcc, Subject, Body and Drive attachments), and there is no App Password or SMTP server to set up. The sent email appears in the account's **Sent** mail.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.status`, `$nodeLabel.to`, `$nodeLabel.cc`, `$nodeLabel.bcc`, `$nodeLabel.subject`, `$nodeLabel.attachment_count`, `$nodeLabel.from`, `$nodeLabel.message_id`, `$nodeLabel.thread_id` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `gmail` credential (Google OAuth) |
| `fromAddress` | expression | Optional. One of the account's **Send mail as** addresses. Blank sends as the account, with the name Gmail shows for it |
| `to` | expression | Recipient(s). Comma-separated for multiple; a quoted name such as `"Doe, John" <john@example.com>` counts as one |
| `cc` | expression | Carbon-copy recipient(s) |
| `bcc` | expression | Blind carbon-copy recipient(s). Hidden from other recipients |
| `subject` | expression | Email subject |
| `emailBody` | expression | Email body. A body with HTML tags such as `<p>`, `<div>`, `<table>` or `<br>` is sent as HTML with a plain-text alternative |
| `attachments` | expression | Comma-separated [Drive](./drive-node.md) file IDs to attach. Only files owned by the workflow owner or shared with one of their teams can be attached |

A blank Subject or Body stays blank. Every text field accepts `$` expressions, and each one can be left to an [Agent](./agent-node.md) when the node is attached as a tool.

## Setup Guide

1. Create a `gmail` credential as described in the [Gmail Trigger setup](./gmail-trigger-node.md#setup-guide). The same credential reads and sends mail: `gmail.modify` covers both, so a credential that already runs a Gmail Trigger can send without reconnecting.
2. Drag **Gmail Send** onto the canvas and select the credential.
3. Leave **From** blank to send as the account, or click one of the account's addresses shown under it. The list holds the primary address and the **Send mail as** aliases set up in Gmail settings.
4. Fill in **To**, **Subject** and **Body**, and optionally **Cc**, **Bcc** and **Attachments**.

## From Address

Gmail only sends as an address the account owns: its primary address or a verified **Send mail as** alias. When **From** names any other address, the node fails with a clear error before anything is sent, instead of Gmail quietly sending from the primary address.

## Example

Answer an email that a Gmail Trigger labelled `supportGmail` started the run with:

```json
{
  "type": "gmailSend",
  "data": {
    "label": "replyByGmail",
    "credentialId": "gmail-credential-uuid",
    "fromAddress": "support@example.com",
    "to": "$supportGmail.email.fromAddresses[0].email",
    "subject": "Re: $supportGmail.email.subject",
    "emailBody": "<p>Hi,</p><p>$draftReply.text</p>",
    "attachments": "$drive.id"
  }
}
```

## Notes

- Gmail accepts messages up to 35 MB, attachments included.
- `message_id` and `thread_id` are Gmail's ids for the sent email, for a later node that labels or looks it up.
- A run with attachments runs on the main instance of a cluster, where Drive files are stored. Without attachments it can run on any instance.
- Use [Send Email](./send-email-node.md) for other mail providers.

## Related

- [Gmail Trigger](./gmail-trigger-node.md): start a workflow on new Gmail email
- [Outlook Send](./outlook-send-node.md): the same node for Outlook and Microsoft 365
- [Send Email](./send-email-node.md): send through any SMTP server
- [Third-Party Integrations](../reference/integrations.md#gmail-oauth2): Gmail credential setup
- [Credentials Sharing](../reference/credentials-sharing.md#gmail-mailbox-access): what sharing a Gmail credential allows
