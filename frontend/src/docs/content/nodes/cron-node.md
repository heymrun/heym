# Cron

The **Cron** node triggers a workflow on a schedule using a cron expression. No user input is required—the workflow runs automatically at the specified times.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | Trigger event (no payload) |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `cronExpression` | string | Cron expression (e.g. `0 * * * *` for hourly) |

## Cron Expression Format

Standard 5-field cron: `minute hour day-of-month month day-of-week`

| Field | Values | Example |
|-------|--------|---------|
| Minute | 0–59 | `0` = at minute 0 |
| Hour | 0–23 | `*` = every hour |
| Day of month | 1–31 | `*` = every day |
| Month | 1–12 | `*` = every month |
| Day of week | 0–7 (0 and 7 = Sunday) | `*` = every day |

**Common examples:**

- `0 * * * *` – every hour
- `0 0 * * *` – daily at midnight
- `*/15 * * * *` – every 15 minutes
- `0 9 * * 1-5` – weekdays at 9:00

## Example

```json
{
  "type": "cron",
  "data": {
    "label": "hourlyCheck",
    "cronExpression": "0 * * * *"
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Triggers](../reference/triggers.md) – Cron, Input, RabbitMQ
- [Disable Node](./disable-node.md) – Stop a cron trigger after a condition
