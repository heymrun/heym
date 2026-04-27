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

Use cURL syntax with `-H` for headers, `-d` for POST body, etc. Expressions can be used in the curl string for dynamic URLs.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Triggers](../reference/triggers.md) – HTTP as workflow entry point
- [Credentials Tab](../tabs/credentials-tab.md) – Add API keys for authenticated requests
