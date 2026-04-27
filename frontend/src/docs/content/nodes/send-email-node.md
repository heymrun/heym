# Send Email

The **Send Email** node sends emails via SMTP. Use it for notifications, alerts, and transactional emails.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.status`, `$nodeLabel.to`, `$nodeLabel.subject` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | SMTP credential from [Credentials](../tabs/credentials-tab.md) |
| `to` | expression | Recipient(s). Comma-separated for multiple. |
| `subject` | expression | Email subject |
| `emailBody` | expression | Email body content |

## Setup

Add an SMTP credential with server, port, email, and password. Common SMTP servers:

- Gmail: `smtp.gmail.com`, port 587 (App Password required)
- Outlook: `smtp.office365.com`, port 587

## Example

```json
{
  "type": "sendEmail",
  "data": {
    "label": "notifyUser",
    "credentialId": "smtp-credential-uuid",
    "to": "$userInput.body.email",
    "subject": "Your request has been processed",
    "emailBody": "Hello,\n\nYour request for $userInput.body.text has been completed."
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Error Handler](./error-handler-node.md) – Send email on failure
- [Credentials Tab](../tabs/credentials-tab.md) – Add SMTP credentials
- [Third-Party Integrations](../reference/integrations.md#smtp-email) – SMTP provider setup (Gmail, Outlook, Mailgun, SendGrid)
