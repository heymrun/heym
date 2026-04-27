# Disable Node

The **Disable Node** node permanently disables another node in the workflow. When executed, it sets the target node's `active` to `false` and persists the change. Use it for one-time operations like stopping a cron trigger after a condition is met.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.targetNode`, `$nodeLabel.disabled` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `targetNodeLabel` | string | Label of the node to disable (e.g. `hourlyCheck`) |

## Use Case

Disable a [Cron](./cron-node.md) trigger after a condition is met so it no longer runs in future workflow executions.

## Example

```json
{
  "type": "disableNode",
  "data": {
    "label": "stopCron",
    "targetNodeLabel": "hourlyCheck"
  }
}
```

Flow: Cron → HTTP check → Condition (status complete?) → if true: Disable Node (target: cron) → Output.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Cron Node](./cron-node.md) – Trigger to disable
- [Condition Node](./condition-node.md) – Branch before disabling
