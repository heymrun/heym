# JSON output mapper

The **JSON output mapper** node builds a JSON object from key/value [mappings](./set-node.md) (same model as [Set](./set-node.md)). Use it when callers should receive a **plain JSON body** at the root of the response.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 0 (sink) |
| Runtime output | Object built from `mappings` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `mappings` | array | `{ "key": "fieldName", "value": "expression" }` entries (same as Set) |

## Webhook and run behavior

When this node is the **only** terminal output of the workflow, execution **outputs** are the mapped object itself: keys from `mappings` appear at the **top level** of the JSON. There is **no** outer wrapper keyed by the node label and **no** `{ "result": ... }` object (unlike the [Output](./output-node.md) node).

If multiple terminal nodes produce outputs (for example [Output](./output-node.md) plus JSON output mapper, or several branches), Heym uses the normal shape: each terminal is keyed by its `label`.

## Loop restriction

Same rule as [Output](./output-node.md): do not place this node inside a loop iteration branch—only after the loop `done` branch. See [Loop](./loop-node.md).

## Example

```json
{
  "type": "jsonOutputMapper",
  "data": {
    "label": "apiPayload",
    "mappings": [
      { "key": "message", "value": "$llm.text" },
      { "key": "ok", "value": "true" }
    ]
  }
}
```

## Related

- [Set](./set-node.md) – Same mapping mechanics for intermediate transforms
- [Output](./output-node.md) – Message or schema-based response with `result` wrapping
- [Node Types](../reference/node-types.md) – All node types
- [Workflow Structure](../reference/workflow-structure.md) – JSON workflow format
- [Webhooks](../reference/webhooks.md) – Execute endpoint and responses
