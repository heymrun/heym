# Cal.com Node

The **Cal.com** node calls Cal.com API v2 to list, create, update, and delete webhooks. It is an
action node with one input and one output. Incoming webhook delivery belongs to the separate
[Cal.com Trigger](./cal-trigger-node.md).

## Credentials

Select a `cal_api` credential containing an API key. Cal.com Cloud uses `https://api.cal.com`.
Self-hosted installations may set another base URL; private/internal targets require the operator
setting `HEYM_HTTP_ALLOW_PRIVATE_URLS=true`.

## Operations

| Operation | Required fields | Output |
|-----------|-----------------|--------|
| `listWebhooks` | none | `webhooks`, `count` |
| `createWebhook` | `calWebhook` | `webhook` |
| `updateWebhook` | `calWebhookId`, `calWebhook` | `webhook` |
| `deleteWebhook` | `calWebhookId` | `deleted`, `webhookId` |

`calWebhookId` and `calWebhook` support [expressions](../reference/expression-dsl.md), expression
preview navigation, and Agent tool autofill. `calWebhook` must be a JSON object or an expression
that resolves to an object.

## Create a Trigger Webhook

Copy the URL from a Cal.com Trigger and send it in the create body:

```json
{
  "subscriberUrl": "https://heym.example/api/cal/webhook/WORKFLOW_ID/NODE_ID",
  "triggers": ["BOOKING_CREATED", "BOOKING_CANCELLED"],
  "secret": "the-same-secret-used-by-the-cal-trigger-credential",
  "active": true,
  "version": "2021-10-20"
}
```

Cal.com also supports fields such as `payloadTemplate`, `time`, and `timeUnit`. The node passes the
object to the documented Cal.com webhook endpoint without hiding operation-specific fields.

## Outputs

Every operation includes `success: true` and `operation`. Lists also include `count`; create and
update include the returned `webhook`; delete includes `deleted: true` and the deleted `webhookId`.

## Related

- [Cal.com Trigger](./cal-trigger-node.md) – Signed incoming webhook delivery
- [Third-Party Integrations](../reference/integrations.md) – Integration overview
- [Credentials](../reference/credentials.md) – Credential setup and sharing
