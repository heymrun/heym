# Switch

The **Switch** node routes execution to different paths based on matching a value against cases. Supports N cases plus a default.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | n (one per case + default) |
| Output | Passes through input to the matched branch |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `expression` | expression | Value to evaluate (e.g. `$input.category`) |
| `cases` | string[] | Case values to match (e.g. `["case1", "case2", "case3"]`) |

## Edge Handles

- Each case gets a source handle (index 0, 1, 2, …)
- Default handle for non-matching values

## Example

```json
{
  "type": "switch",
  "data": {
    "label": "routeByCategory",
    "expression": "$classifier.category",
    "cases": ["sales", "support", "billing"]
  }
}
```

Connect edges with `sourceHandle` set to the case index (0, 1, 2) or the default handle for unmatched values.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Condition Node](./condition-node.md) – If/else branching
- [Expression DSL](../reference/expression-dsl.md) – Expression syntax
