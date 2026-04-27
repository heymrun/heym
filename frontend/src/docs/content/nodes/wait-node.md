# Wait

The **Wait** node pauses workflow execution for a specified duration. Use it for rate limiting, delayed actions, or polling intervals.

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
| `duration` | number | Delay in milliseconds (e.g. 1000 = 1 second) |

## Example

```json
{
  "type": "wait",
  "data": {
    "label": "delayOneSecond",
    "duration": 1000
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Loop Node](./loop-node.md) – Use Wait inside loops for rate limiting
