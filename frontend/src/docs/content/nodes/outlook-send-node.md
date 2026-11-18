# Outlook Send

The **Outlook Send** node sends an email from an Outlook.com or Microsoft 365 (work or school) mailbox through Microsoft Graph. It has every field of the [Send Email](./send-email-node.md) node (To, Cc, Bcc, Subject, Body and Drive attachments) and uses the same `outlook` credential as the [Outlook Trigger](./outlook-trigger-node.md). Microsoft is retiring password sign-in for SMTP, so this is the way to send from a Microsoft mailbox. The sent email appears in the mailbox's **Sent Items**.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.status`, `$nodeLabel.to`, `$nodeLabel.cc`, `$nodeLabel.bcc`, `$nodeLabel.subject`, `$nodeLabel.attachment_count`, `$nodeLabel.from` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | `outlook` credential (Microsoft OAuth) |
| `fromAddress` | expression | Optional. Another address to send from: an alias of the account or a shared mailbox it may send as. Blank sends as the signed-in account |
| `to` | expression | Recipient(s). Comma-separated for multiple; a quoted name such as `"Doe, John" <john@example.com>` counts as one |
| `cc` | expression | Carbon-copy recipient(s) |
| `bcc` | expression | Blind carbon-copy recipient(s). Hidden from other recipients |
| `subject` | expression | Email subject |
| `emailBody` | expression | Email body. A body with HTML tags such as `<p>`, `<div>`, `<table>` or `<br>` is sent as HTML, anything else as text |
| `attachments` | expression | Comma-separated [Drive](./drive-node.md) file IDs to attach. Only files owned by the workflow owner or shared with one of their teams can be attached |

A blank Subject or Body stays blank. Every text field accepts `$` expressions, and each one can be left to an [Agent](./agent-node.md) when the node is attached as a tool.

## Setup Guide

1. Create an `outlook` credential as described in the [Outlook Trigger setup](./outlook-trigger-node.md#setup-guide). Sending needs the Microsoft Graph delegated permission `Mail.Send` next to `Mail.ReadWrite`, `User.Read` and `offline_access`.
2. Drag **Outlook Send** onto the canvas and select the credential.
3. Leave **From** blank to send as the account, or enter another address. The account's own addresses are shown under the field.
4. Fill in **To**, **Subject** and **Body**, and optionally **Cc**, **Bcc** and **Attachments**.

### Credentials connected before Outlook Send

An Outlook credential connected before this node existed was granted `Mail.ReadWrite` only, which cannot send. Its triggers keep working. To send with it, add `Mail.Send` to the app's API permissions, then open the credential in **Credentials** and click **Connect** again. Until then the node shows a reminder under the credential and a run fails before sending.

### Exchange Server (on-premises)

An `outlook` credential that signs in to an organization's own Exchange Server sends through Exchange Web Services and keeps a copy in Sent Items. No `Mail.Send` permission or reconnect is involved; see [Exchange Server sign-in](../reference/integrations.md#exchange-server-on-premises).

## From Address

Exchange decides who may send as which address. Sending from an alias works when the organization allows it, and sending from a shared mailbox needs **Send As** permission on that mailbox. When Microsoft refuses the From address, the node fails with Microsoft's reason.

## Example

```json
{
  "type": "outlookSend",
  "data": {
    "label": "sendQuote",
    "credentialId": "outlook-credential-uuid",
    "to": "$crmLookup.body.contact_email",
    "cc": "sales@contoso.com",
    "subject": "Your quote $crmLookup.body.quote_number",
    "emailBody": "Hello $crmLookup.body.contact_name,\n\nYour quote is attached.\n\nBest regards",
    "attachments": "$quotePdf.id"
  }
}
```

## Notes

- Large attachments (3 MB and more) are uploaded in parts, so a message can be as large as the mailbox allows (35 MB by default in Microsoft 365).
- A run with attachments runs on the main instance of a cluster, where Drive files are stored. Without attachments it can run on any instance.
- Use [Send Email](./send-email-node.md) for other mail providers.

## Related

- [Outlook Trigger](./outlook-trigger-node.md): start a workflow on new Outlook email
- [Gmail Send](./gmail-send-node.md): the same node for Gmail
- [Send Email](./send-email-node.md): send through any SMTP server
- [Third-Party Integrations](../reference/integrations.md#outlook-mail-oauth2): Outlook credential setup
- [Credentials Sharing](../reference/credentials-sharing.md#outlook-mailbox-access): what sharing an Outlook credential allows
