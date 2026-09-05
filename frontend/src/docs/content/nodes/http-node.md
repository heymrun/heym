# HTTP

The **HTTP** node makes HTTP requests using cURL syntax. It can be a workflow starting point (no incoming edge) or receive input from upstream nodes.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 or 1 |
| Outputs | 1 |
| Output | `$nodeLabel.status`, `$nodeLabel.body`, `$nodeLabel.headers` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `curl` | string | cURL command (e.g. `curl -X GET https://api.example.com`) |

## Response Format

```json
{
  "status": 200,
  "headers": { "content-type": "application/json", ... },
  "body": "response body or parsed JSON",
  "request": { "method": "POST", "url": "...", "headers": {...} }
}
```

## Accessing Response

- `$httpNode.status` – HTTP status code
- `$httpNode.body` – Response body (string or parsed JSON)
- `$httpNode.body.fieldName` – Access JSON fields
- `$httpNode.headers` – Response headers

## Example

```json
{
  "type": "http",
  "data": {
    "label": "fetchApi",
    "curl": "curl -X GET https://api.example.com/data"
  }
}
```

Use cURL syntax with `-H` for headers, `-d` for POST body, etc. Expressions can be used anywhere in the curl string, including the URL, a header, or a whole header line. A [Header credential](../reference/credentials.md) resolves to `key: value`, so `-H "$credentials.MyApiKey"` sends the complete header:

```
curl -X GET "https://api.example.com/search?q=$query.body.text.urlEncode()" -H "$credentials.MyApiKey"
```

Quotes and spaces inside an expression belong to the expression, not to the cURL command, so methods that take string arguments work inline:

```
curl "https://r.jina.ai/$url.text.replaceAll("\n", "").strip()" -H "Authorization: $credentials.Jina"
```

## Egress Safety

- By default, the URL must use `http://` or `https://` and resolve only to public addresses. Loopback, private, link-local, multicast, and cloud-metadata destinations are blocked.
- Heym validates the resolved addresses and pins the connection target to prevent DNS rebinding. Environment proxies are disabled while the guard is active. Redirects are not followed by default; add cURL's `-L` option to follow them. When enabled, every redirect hop is checked against the same public-address policy and pinned before connecting.
- Trusted self-hosted deployments that intentionally connect to internal services can set `HEYM_HTTP_ALLOW_PRIVATE_URLS=true`. Keep the default on hosted or multi-tenant deployments.

**Upgrade note for v0.0.105:** this instance-wide policy now also protects credential-derived destinations used by Jira, Sentry, GitHub, Grist, Supabase, ClickHouse, custom LLM execution and model discovery, the AI assistant, guardrails, and RAG embeddings. Existing credentials that point to loopback, private, or link-local addresses are refused unless `HEYM_HTTP_ALLOW_PRIVATE_URLS=true` is enabled on a trusted self-hosted instance. Guarded HTTP clients ignore `HTTP_PROXY` and `HTTPS_PROXY`, while operator CA bundles configured through `SSL_CERT_FILE` or `SSL_CERT_DIR` remain supported. ClickHouse is checked before the connection opens but is not pinned at dial time, because clickhouse-connect brings its own urllib3 transport.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Triggers](../reference/triggers.md) – HTTP as workflow entry point
- [Credentials Tab](../tabs/credentials-tab.md) – Add API keys for authenticated requests
