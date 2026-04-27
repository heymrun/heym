# Console Log

The **Console Log** node logs a value to the backend (server) console. Use it for debugging and inspection during development.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | Passes through input |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `logMessage` | expression | Value to log. Supports [expressions](../reference/expression-dsl.md). |

## Example

```json
{
  "type": "consoleLog",
  "data": {
    "label": "debugOutput",
    "logMessage": "$userInput.body"
  }
}
```

Output appears in the server logs (e.g. terminal output when running `uvicorn`).

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Logs Tab](../tabs/logs-tab.md) – View application logs
