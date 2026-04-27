# Variable

The **Variable** node sets or updates a variable accessible from any node via `$vars.variableName` (workflow-local) or `$global.variableName` (persistent). Use it for counters, accumulated lists, and shared state across the workflow.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.value`, or access via `$vars.variableName` / `$global.variableName` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `variableName` | string | Variable name (used as `$vars.variableName` or `$global.variableName`). Avoid [reserved names](../reference/expression-dsl.md). |
| `variableValue` | expression | Value to set. Supports expressions. |
| `variableType` | `"auto"` \| `"string"` \| `"number"` \| `"boolean"` \| `"array"` \| `"object"` | Type coercion (default: auto) |
| `isGlobal` | boolean | When `true`, store in [Global Variable Store](../reference/global-variables.md) (persistent, user-scoped). When `false` or omitted, workflow-local (in-memory). |

## Array Variables

Initialize arrays with `$array()` or `$array("a", "b")` in a Variable node before using `.add()`:

```json
{"variableName": "items", "variableValue": "$array()", "variableType": "array"}
```

Then add items (no `$` inside parentheses):

```json
{"variableName": "items", "variableValue": "$vars.items.add(loopNode.item)", "variableType": "array"}
```

## Critical Rule

**Never use `$` inside method parentheses:**

- ✅ `$vars.myArray.add(previousNode.text)`
- ❌ `$vars.myArray.add($previousNode.text)` – breaks the expression

## Example – Counter

```json
{
  "type": "variable",
  "data": {
    "label": "incrementCounter",
    "variableName": "counter",
    "variableValue": "$vars.counter + 1",
    "variableType": "number"
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Loop Node](./loop-node.md) – Collect items with Variable in loop body
- [Expression DSL](../reference/expression-dsl.md) – `$vars`, `$global`, reserved names
- [Global Variables](../reference/global-variables.md) – Persistent variables with `isGlobal`
