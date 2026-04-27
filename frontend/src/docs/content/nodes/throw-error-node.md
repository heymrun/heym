# Throw Error

The **Throw Error** node stops workflow execution immediately and returns an error response with a custom HTTP status code. Use it for validation failures, unauthorized access, or other error conditions.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 0 |
| Output | Workflow stops; error response returned to caller |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `errorMessage` | expression | Error message (supports expressions) |
| `httpStatusCode` | number | HTTP status code (e.g. 400, 401, 403, 404, 429, 500) |

## Common Status Codes

| Code | Use case |
|------|----------|
| 400 | Bad Request (invalid input) |
| 401 | Unauthorized (authentication required) |
| 403 | Forbidden (access denied) |
| 404 | Not Found (resource missing) |
| 422 | Unprocessable Entity (validation error) |
| 429 | Too Many Requests (rate limit) |
| 500 | Internal Server Error |

## Example

```json
{
  "type": "throwError",
  "data": {
    "label": "validationError",
    "errorMessage": "Text input is required",
    "httpStatusCode": 400
  }
}
```

Use with [Condition](./condition-node.md) to validate input and throw only when invalid:
- Condition true → continue to Output
- Condition false → Throw Error

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Condition Node](./condition-node.md) – Validate before throwing
- [Error Handler](./error-handler-node.md) – Catch errors from other nodes
