# Condition

The **Condition** node branches the workflow based on an if/else expression. Routes to the true or false path depending on the result.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 2 (true, false) |
| Output | Passes through input to the chosen branch |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `condition` | expression | JavaScript-like expression (e.g. `$input.text.length > 0`) |

## Edge Handles

- **Source handle `true`** – when condition evaluates to truthy
- **Source handle `false`** – when condition evaluates to falsy

## Expression Operators

Supports: `==`, `!=`, `>`, `<`, `>=`, `<=`, `&&`, `||`, `.length`, `.contains()`, etc. See [Expression DSL](../reference/expression-dsl.md).

## Example

```json
{
  "type": "condition",
  "data": {
    "label": "checkInput",
    "condition": "$userInput.body.text.length > 0"
  }
}
```

Connect edges with `sourceHandle: "true"` or `sourceHandle: "false"` to route to different branches.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Switch Node](./switch-node.md) – Multi-way routing by value
- [Expression DSL](../reference/expression-dsl.md) – Condition syntax
- [Expression Evaluation Dialog](../reference/expression-evaluation-dialog.md) – Expandable editor with live backend preview for condition
