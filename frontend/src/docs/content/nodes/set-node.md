# Set

The **Set** node transforms and maps input data to custom output. Use it for uppercase, substring, concatenation, random numbers, and any data transformation—not for calling workflows (use [Execute](./execute-node.md) for that).

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.keyName` for each mapping key |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `mappings` | array | Key-value pairs. Each: `{ key, value }` where `value` is an [expression](../reference/expression-dsl.md) |

## Expression Rules

- Reference previous nodes: `$nodeName.text`, `$nodeName.body.field`
- Use functions: `$randomInt(1, 10)`, `$range(1, 5)`, `$now.format('HH:mm')`
- `$range(a,b)` b'yi hariç tutar; `a > b` durumunda hata verir.
- Only one `$` at the start of the expression—never inside parentheses
- Access output by key: `$setNode.randomNumber`, `$setNode.text`

## Example

```json
{
  "type": "set",
  "data": {
    "label": "transformData",
    "mappings": [
      { "key": "text", "value": "$userInput.body.text.upper()" },
      { "key": "firstChar", "value": "$userInput.body.text.substring(0, 1)" },
      { "key": "randomNum", "value": "$randomInt(1, 10)" },
      { "key": "rangeArr", "value": "$range(1, 5)" }
    ]
  }
}
```

Downstream nodes access via `$transformData.text`, `$transformData.firstChar`, `$transformData.randomNum`, `$transformData.rangeArr`.

## Related

- [JSON output mapper](./json-output-mapper-node.md) – Same mappings; sole terminal returns root JSON for webhooks/runs
- [Node Types](../reference/node-types.md) – Overview of all node types
- [Execute Node](./execute-node.md) – Call workflows (not data transformation)
- [Expression DSL](../reference/expression-dsl.md) – Functions and syntax
- [Expression Evaluation Dialog](../reference/expression-evaluation-dialog.md) – Expandable editor with live backend preview and Prev/Next for mappings
