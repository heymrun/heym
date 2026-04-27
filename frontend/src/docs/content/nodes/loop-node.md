# Loop

The **Loop** node iterates over an array, executing downstream nodes for each item. Requires a back-connection from the last node in the iteration body to advance.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 2 (default + loop back) |
| Outputs | 2 (loop, done) |
| Output | `$nodeLabel.item`, `$nodeLabel.index`, `$nodeLabel.total`, `$nodeLabel.isFirst`, `$nodeLabel.isLast` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `arrayExpression` | expression | Expression that resolves to an array (e.g. `$input.items`) |

## Edge Handles

- **Source `loop`** – Connects to nodes that process each item (runs per iteration)
- **Source `done`** – Connects to nodes that run after all iterations complete
- **Target default** – Receives initial data containing the array
- **Target `loop`** – Receives back-connection from the last iteration body node

## Loop Context (in iteration body)

- `$loopNode.item` – Current item
- `$loopNode.index` – 0-based index
- `$loopNode.total` – Total items
- `$loopNode.isFirst` – Boolean
- `$loopNode.isLast` – Boolean

## Critical Rules

1. **Back-connection required:** The last node in the iteration body MUST connect back to the loop's `loop` input handle.
2. **No output in loop body:** [Output](./output-node.md) nodes are forbidden inside the loop body. Use [Set](./set-node.md) or [Variable](./variable-node.md) for intermediate results.
3. **No automatic results:** The loop does not collect results. Use Variable nodes with `$array()` and `.add()` to accumulate.

## Example

```json
{
  "type": "loop",
  "data": {
    "label": "processItems",
    "arrayExpression": "$httpResponse.body.items"
  }
}
```

Flow: loop → process node → (back to loop) → loop → done branch → output.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Variable Node](./variable-node.md) – Collect items in a loop
- [Expression DSL](../reference/expression-dsl.md) – `item`, `index`, array methods
