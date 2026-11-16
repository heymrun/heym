# Heym Trigger

The **Heym Trigger** node starts a workflow when Heym itself publishes a platform event. It is a zero-input trigger node for automating Heym with Heym: change audit trails, deploy announcements, and instance health digests.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.events`, `$nodeLabel.count`, `$nodeLabel.triggered_at` |
| Credential | None required |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `eventNames` | String array | Which events to subscribe to. Leave empty to receive every event. |

## Events

| Event | Published when | Scope |
|-------|----------------|-------|
| `heym.started` | The Heym platform starts | Instance-wide: every subscriber receives it |
| `workflow.created` | A workflow is created | Only the workflow owner's subscribers |
| `workflow.updated` | A workflow is saved | Only the workflow owner's subscribers |
| `workflow.deleted` | A workflow is deleted, right away or when its scheduled deletion runs | Only the workflow owner's subscribers |

Dashboard widgets are stored as workflows internally, but they never produce `workflow.*` events.

## Delivery Is Batched

Heym dispatches events every five seconds. **Every event claimed in one dispatch pass arrives in a single workflow run**, as an array.

- Create two workflows within five seconds of each other → **one** run with two events.
- Create one workflow → **one** run with a one-element array.

The shape never changes, so downstream expressions never have to branch on whether one event or many arrived. When you need to act once per event, put a [Loop](./loop-node.md) node over `$nodeLabel.events`.

## Exactly-Once Delivery

Each event is claimed per subscribing node through a unique database constraint before it is delivered. This holds across every uvicorn worker, every container, and every machine: running Heym on two servers does not deliver an event twice. If a claim cannot be recorded, the event is not delivered at all — the design fails closed rather than firing twice.

Two different `heymTrigger` nodes subscribing to the same event each receive it once; they do not compete for it.

## The Dispatch Window

The dispatcher only considers events published in the **last five minutes**. Older events stay in the log for inspection but are never delivered. This bounds what happens after downtime: bringing Heym back up after an hour offline replays nothing, instead of firing an hour of backlog at once.

Events are kept for **7 days** and then deleted.

## Output Fields

| Expression | Description |
|------------|-------------|
| `$nodeLabel.events` | Array of event objects, oldest first. Always an array. |
| `$nodeLabel.events[0].id` | Event UUID |
| `$nodeLabel.events[0].name` | Event name, for example `workflow.created` |
| `$nodeLabel.events[0].payload` | Event body |
| `$nodeLabel.events[0].workflow_id` | Subject workflow id, or `null` for `heym.started` |
| `$nodeLabel.events[0].created_at` | ISO timestamp for when the event was published |
| `$nodeLabel.count` | Number of events in this batch |
| `$nodeLabel.triggered_at` | ISO timestamp for the workflow execution |

### Payload shapes

`workflow.created`, `workflow.updated`, `workflow.deleted`:

```json
{
  "workflow_id": "…",
  "name": "Nightly report",
  "owner_id": "…",
  "actor_user_id": "…",
  "updated_at": "2026-08-11T09:30:00+00:00"
}
```

`heym.started`:

```json
{ "version": "1.4.2", "started_at": "2026-08-11T09:30:00+00:00" }
```

`workflow.deleted` carries the name captured just before deletion, since the workflow row is gone by the time you read the event.

## Example Workflow

**Workflow change audit trail**

```
heymTrigger → heym (getWorkflow) → slack
```

- **Heym Trigger** label `platformEvents`, subscribed to `workflow.created`, `workflow.updated`, `workflow.deleted`
- **Heym** node with `getWorkflow` and `heymWorkflowId` set to `$platformEvents.events[0].workflow_id`
- **Slack** message: `"$platformEvents.count workflow change(s), latest: $platformEvents.events[0].name"`

## Notes

- `heym.started` fires **once per platform start**, not once per worker, even though Heym runs eight workers per container. Containers that start more than five minutes apart each publish one event.
- Executions triggered this way appear in history with `trigger_source = "heym_event"`.
- Set **Events** to none rather than listing all four if you want to pick up event types added in future versions automatically.

## Related

- [Heym](./heym-node.md) – Read workflows and execution history
- [Triggers](../reference/triggers.md) – Overview of all workflow entry points
- [Loop](./loop-node.md) – Act once per event in a batch
