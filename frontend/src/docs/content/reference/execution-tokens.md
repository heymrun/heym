# Execution Tokens

Execution tokens are scoped JWTs that grant access to a single workflow's execute and stream endpoints. They let you call a workflow from external systems without exposing your long-lived user session token.

## Why Use Execution Tokens

When a workflow's authentication is set to **JWT**, the endpoint normally requires a valid user session. Execution tokens let you:

- Share a callable token with external scripts, CI pipelines, or integrations without sharing your account credentials.
- Limit exposure — a token is valid only for one specific workflow.
- Revoke access instantly without changing your password or rotating session tokens.
- Choose between short-lived tokens (minutes or hours) and long-lived tokens (up to 10 years).

## Creating a Token

Open the **Run with cURL** dialog in the editor (top-right toolbar). When the workflow authentication is set to **JWT Token**, the dialog shows a token manager:

1. Choose **Short-lived** or **Long-lived (10yr)**.
2. For short-lived tokens, enter the duration in seconds (minimum 60).
3. Click **+ New Token**.

The token is created immediately, added to the list, and auto-selected so the cURL command updates to include it.

## Token List

Each token row shows:

| Column | Description |
|--------|-------------|
| Created | Creation timestamp |
| Status | **Expires:** date, **Expired**, or **Revoked** |
| Eye icon | Toggle token value visibility |
| Revoke button | Mark token as revoked (irreversible) |

Click any active (non-expired, non-revoked) row to select it. The selected token is embedded in the cURL command preview.

Expired and revoked tokens remain visible in the list but cannot be selected.

## Using a Token

Copy the token value from the list (click the eye icon to reveal it) and include it as a `Bearer` token:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-Trigger-Source: my-service" \
  -H "Authorization: Bearer <execution-token>" \
  "https://app.heym.ai/api/workflows/{workflow_id}/execute" \
  -d '{"message": "Hello"}'
```

When you use **Copy cURL** in the dialog with a token selected, the token is already embedded in the command — no manual substitution needed.

## Token Scoping

Each token carries these JWT claims:

| Claim | Value |
|-------|-------|
| `sub` | User ID of the token creator |
| `wid` | Workflow UUID — the token is rejected for any other workflow |
| `scope` | `workflow:execute` — distinguishes it from a user session token |
| `jti` | Unique token ID used for revocation lookups |
| `exp` | Expiry timestamp |

The backend checks all of these on every request: signature validity, expiry, matching `wid`, and that the `jti` has not been revoked.

## Revocation

Click the revoke (circle-slash) button next to a token to revoke it. Revocation takes effect immediately — subsequent requests using that token return `401`. The token row stays visible in the list with a **Revoked** label.

There is no un-revoke. Create a new token if you need to restore access.

## API

The token management endpoints are authenticated with your regular session.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/workflows/{id}/execution-tokens` | Create a token |
| `GET` | `/api/workflows/{id}/execution-tokens` | List your tokens for this workflow |
| `DELETE` | `/api/workflows/{id}/execution-tokens/{token_id}` | Revoke a token |

**Create request body:**

```json
{ "ttl_seconds": 900 }
```

**Create response:**

```json
{
  "id": "uuid",
  "token": "<full jwt>",
  "expires_at": "2026-04-30T15:22:00Z",
  "created_at": "2026-04-30T15:07:00Z",
  "revoked": false
}
```

The `token` field is only returned once at creation. Store it immediately; subsequent `GET` requests return the same row but you can also reveal it in the cURL dialog at any time.

## Visibility Scope

Each user sees only the tokens they created. Team members with access to a shared workflow cannot see each other's tokens.

## Related

- [Webhooks](./webhooks.md) — HTTP trigger endpoints and the cURL dialog
- [Security](./security.md) — Session management and authentication overview
- [SSE Streaming](./sse-streaming.md) — Use execution tokens with the streaming endpoint
