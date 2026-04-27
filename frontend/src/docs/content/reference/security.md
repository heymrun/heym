# Security

Security practices and configuration for the Heym platform.

## Password Policy

All passwords — at registration and when changing your password — must meet these requirements:

| Rule | Requirement |
|------|-------------|
| Minimum length | 8 characters |
| Uppercase | At least one uppercase letter (A–Z) |
| Lowercase | At least one lowercase letter (a–z) |
| Digit | At least one number (0–9) |

These rules are enforced on both the frontend and the backend (Pydantic validator). A request with a non-compliant password is rejected with a `422 Unprocessable Entity` response before any database write occurs.

**Example of a valid password:** `MyWorkflow7!`

## Session Management

- Access tokens are stored in **HttpOnly** cookies, not `localStorage`. This prevents JavaScript (including XSS payloads) from reading the token.
- The refresh token is scoped to the `/api/auth/refresh` path and cannot be sent to other endpoints.
- Each `/api/auth/refresh` call **rotates** the refresh token: the old token is immediately revoked and a new one is issued. Replaying a used refresh token returns `401`.

## Rate Limiting

The following endpoints are rate-limited per IP:

| Endpoint | Limit | Ban duration |
|----------|-------|--------------|
| `POST /api/auth/login` | 10 req / 60 s | 15 min |
| `POST /api/auth/register` | 5 req / 60 s | 10 min |
| `POST /register` (OAuth clients) | 5 req / 60 s | 10 min |
| Portal login | 3 attempts | 24 h |

When `REDIS_URL` is configured, rate limits are shared across all backend workers. Without it, limits apply per worker process.

## Credential Encryption

All API keys, webhook URLs, and bearer tokens stored in the [Credentials](../tabs/credentials-tab.md) panel are encrypted at rest using AES-256 (Fernet) before being written to the database. The key is derived from the `ENCRYPTION_KEY` environment variable, which must be explicitly set — the application will refuse to start if this variable is absent.

## MCP API Key

The MCP API key is used to authenticate external MCP clients connecting to the `/api/mcp/sse` endpoint. When the SSE connection is established, a short-lived (1-hour) session token is issued and embedded in the message endpoint URL instead of the real API key, preventing the key from appearing in server access logs. See [MCP Tab](../tabs/mcp-tab.md) for setup.

## OAuth / PKCE

The OAuth 2.0 authorization server (used for MCP clients) supports only the `authorization_code` grant with PKCE (`S256`). The consent form uses HMAC-SHA256 CSRF tokens valid for 10 minutes. All values displayed in the consent page are HTML-escaped.

## Content Safety

Use [Guardrails](./guardrails.md) on LLM and Agent nodes to block unsafe or policy-violating user messages before they reach the model. Guardrails support nine content categories (violence, hate speech, sexual content, etc.) with configurable sensitivity levels.

## Related

- [Running & Deployment](../getting-started/running-and-deployment.md) – Configure `SECRET_KEY`, `ENCRYPTION_KEY`, and `ALLOW_REGISTER` at startup
- [Guardrails](./guardrails.md) – Block unsafe content in LLM and Agent nodes
- [User Defaults](./user-defaults.md) – Change your password
- [Credentials Tab](../tabs/credentials-tab.md) – Manage API keys
- [MCP Tab](../tabs/mcp-tab.md) – MCP API key and OAuth clients
- [Portal](./portal.md) – Public chat portal access control
