# Merge

The **Merge** node waits for multiple parallel inputs and combines them into a single output. Use it when you need to join results from parallel branches before continuing.

## Overview

| Property | Value |
|----------|-------|
| Inputs | n (configurable) |
| Outputs | 1 |
| Output | `$nodeLabel.merged` – object with inputs from each branch |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `inputCount` | number | Number of inputs to wait for (default: 2) |

## When to Use

- Use when you need to **combine** or **join** results from parallel branches
- Do **not** use for parallel workflows that end with separate [Output](./output-node.md) nodes
- Each input branch contributes to the merged output

## Example

```json
{
  "type": "merge",
  "data": {
    "label": "combineResults",
    "inputCount": 2
  }
}
```

Connect multiple branches to the merge node. The node waits for all inputs before producing output.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Parallel Execution](../reference/parallel-execution.md) – How parallel branches run
- [Workflow Structure](../reference/workflow-structure.md) – Edges and handles
