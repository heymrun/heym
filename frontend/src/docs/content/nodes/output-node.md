# Output

The **Output** node is the workflow endpoint that returns the response to the caller. Always reference the previous node by label—never use `$input`.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 (optional, for async post-processing) |
| Output | Returns `message` to caller |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `message` | expression | Output value. **Must** reference previous node: `$previousNodeLabel.field` |
| `allowDownstream` | boolean | If true, nodes after output run asynchronously after response is sent |

## Critical Rule

**Never use `$input` in the output node.** Always use the previous node's label:

- ❌ `"message": "$input.text"`
- ✅ `"message": "$processData.text"` (where `processData` is the previous node's label)

## Async Post-Processing

When `allowDownstream: true`, the response is returned immediately. Nodes connected after the output run in the background (e.g. Slack notifications, logging).

## Example

```json
{
  "type": "output",
  "data": {
    "label": "apiResponse",
    "message": "$generateResponse.text"
  }
}
```

## Example – With Async

```json
{
  "type": "output",
  "data": {
    "label": "apiResponse",
    "message": "$generateResponse.text",
    "allowDownstream": true
  }
}
```

Then connect a [Telegram](./telegram-node.md), [Slack](./slack-node.md), or other node after the output for fire-and-forget notifications.

## Related

- [JSON output mapper](./json-output-mapper-node.md) – Root JSON body without `result` wrapping when sole terminal
- [Node Types](../reference/node-types.md) – Overview of all node types
- [Expression DSL](../reference/expression-dsl.md) – Referencing node output
- [Expression Evaluation Dialog](../reference/expression-evaluation-dialog.md) – Expandable editor with live backend preview for message
- [Workflow Structure](../reference/workflow-structure.md) – JSON format
