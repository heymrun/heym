# Send Email

The **Send Email** node sends emails via SMTP. Use it for notifications, alerts, and transactional emails. To send from a Gmail account or an Outlook or Microsoft 365 mailbox without an SMTP password, use [Gmail Send](./gmail-send-node.md) or [Outlook Send](./outlook-send-node.md): they have the same fields.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.status`, `$nodeLabel.to`, `$nodeLabel.cc`, `$nodeLabel.bcc`, `$nodeLabel.subject`, `$nodeLabel.attachment_count` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | SMTP credential from [Credentials](../tabs/credentials-tab.md) |
| `to` | expression | Recipient(s). Comma-separated for multiple. |
| `cc` | expression | Carbon-copy recipient(s). Comma-separated for multiple. |
| `bcc` | expression | Blind carbon-copy recipient(s). Comma-separated for multiple. Hidden from other recipients. |
| `subject` | expression | Email subject |
| `emailBody` | expression | Email body content |
| `attachments` | expression | Comma-separated [Drive](./drive-node.md) file IDs to attach. Only files owned by the workflow owner or shared with one of their teams can be attached. |

## Attachments

Attach files from your [Drive](./drive-node.md) by passing one or more Drive file IDs to the `attachments`
field. Use a `$` expression to reference an upstream Drive node's `id` output (for example `$drive.id`),
or list static IDs separated by commas. Each ID is resolved in the workflow owner's scope; an invalid or
inaccessible ID fails the node rather than sending a partial email.

## Setup

Add an SMTP credential with server, port, email, and password. The visible sender is the credential's optional **From**; a blank From sends as the username. Common SMTP servers:

- Gmail: `smtp.gmail.com`, port 587 (App Password required). [Gmail Send](./gmail-send-node.md) needs none.
- Outlook: `smtp.office365.com`, port 587. [Outlook Send](./outlook-send-node.md) signs in with OAuth instead.

## Example

```json
{
  "type": "sendEmail",
  "data": {
    "label": "notifyUser",
    "credentialId": "smtp-credential-uuid",
    "to": "$userInput.body.email",
    "cc": "manager@example.com",
    "bcc": "audit@example.com",
    "subject": "Your request has been processed",
    "emailBody": "Hello,\n\nYour request for $userInput.body.text has been completed.",
    "attachments": "$drive.id"
  }
}
```

The `attachments` value above references an upstream [Drive](./drive-node.md) node labeled `drive`,
attaching the file it produced.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Gmail Send](./gmail-send-node.md) – Send from a Gmail account
- [Outlook Send](./outlook-send-node.md) – Send from an Outlook or Microsoft 365 mailbox
- [Error Handler](./error-handler-node.md) – Send email on failure
- [Credentials Tab](../tabs/credentials-tab.md) – Add SMTP credentials
- [Third-Party Integrations](../reference/integrations.md#smtp-email) – SMTP provider setup (Gmail, Outlook, Mailgun, SendGrid)
