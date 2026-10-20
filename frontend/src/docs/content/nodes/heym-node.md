# Heym

The **Heym** node reads Heym's own data: the workflows you can reach, one workflow's structure, and its execution history. It is how you build meta-workflows — instance inventories, execution digests, and health reports about Heym itself.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Operations | `listWorkflows`, `getWorkflow`, `getExecutionHistory` |
| Credential | None required |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `heymOperation` | Select | Which read to perform |
| `heymWorkflowId` | UUID | Target workflow. Required for `getWorkflow` and `getExecutionHistory`. Set it to `all` on `getExecutionHistory` to read every workflow you can reach. Expression-capable. |
| `heymLimit` | String | Maximum rows to return. **Leave it empty or enter `0` to return everything** — that is the default. Expression-capable. |
| `heymStatus` | String | Optional status filter for `getExecutionHistory`. Expression-capable. |
| `heymSinceDays` | String | Optional lookback in days for `getExecutionHistory`. Expression-capable. |

The workflow picker is a searchable dropdown listing every workflow you can reach. For Get Execution History, its first item is **All workflows**.

## Access Scope

Results are scoped to the **owner of the workflow the node lives in** — not to whoever started the run. The visible set is:

- workflows the owner owns,
- workflows shared directly with the owner,
- workflows shared with a team the owner belongs to.

Owner scoping is what makes the node behave identically whether a run was started manually, by cron, from a portal, or by a platform event. Actor scoping would return nothing on every unattended run. It is the same rule Heym already uses for credentials and global variables.

A workflow you cannot reach and a workflow that does not exist produce the same error message, so the node cannot be used to probe for workflow ids.

## Operations

### List Workflows

Returns every workflow the owner can reach, most recently updated first.

| Expression | Description |
|------------|-------------|
| `$nodeLabel.workflows` | Array of workflow summaries |
| `$nodeLabel.workflows[0].id` | Workflow UUID |
| `$nodeLabel.workflows[0].name` | Workflow name |
| `$nodeLabel.workflows[0].description` | Description, or `null` |
| `$nodeLabel.workflows[0].active` | Whether the workflow is active |
| `$nodeLabel.workflows[0].folder_id` | Folder UUID, or `null` |
| `$nodeLabel.workflows[0].updated_at` | ISO timestamp of the last save |
| `$nodeLabel.workflows[0].node_count` | How many nodes the workflow contains |
| `$nodeLabel.total` | Full accessible count **before** the limit is applied |

`total` is deliberately the unlimited count, so `$inventory.total` still reports the real size when you cap the returned rows. Clearing **Limit**, or setting it to `0`, returns every workflow — which is the default.

### Get Workflow

Returns one workflow's identity and shape.

| Expression | Description |
|------------|-------------|
| `$nodeLabel.id`, `$nodeLabel.name`, `$nodeLabel.description` | Workflow identity |
| `$nodeLabel.active`, `$nodeLabel.folder_id`, `$nodeLabel.updated_at` | Workflow metadata |
| `$nodeLabel.node_count` | Number of nodes |
| `$nodeLabel.nodes` | Array of `{ id, type, label, position, data }` |
| `$nodeLabel.edges` | Array of `{ id, source, target, sourceHandle, targetHandle }` |

`data` is the **full node configuration** — every field as it was saved. That is what makes auditing possible: you cannot scan a workflow for an API key someone pasted into a field if the node refuses to show the field.

This grants no reach the caller did not already have. The node is scoped to workflows the owner can open in the editor anyway, and stored credential secrets are still not here: node data holds only credential **ids**, while the secrets themselves live encrypted in the credentials table.

### Scanning for hardcoded secrets

```
cron → heym (listWorkflows) → loop → heym (getWorkflow) → agent → slack
```

Give the agent `$detail.nodes` and ask it to flag any `data` value that looks like a live key or token. Fields worth watching are the free-text ones — `curl` on HTTP nodes, `userMessage` and `systemInstruction` on LLM and Agent nodes, and Python tool bodies — because a credential id is a harmless UUID, but a pasted `sk-…` is not.

### Get Execution History

Returns execution-history entries for one workflow, or for every workflow you can reach when you pick **All workflows**, newest first.

| Expression | Description |
|------------|-------------|
| `$nodeLabel.executions` | Array of history entries |
| `$nodeLabel.executions[0].id` | Execution UUID |
| `$nodeLabel.executions[0].status` | `success`, `error`, and so on |
| `$nodeLabel.executions[0].started_at` | ISO timestamp |
| `$nodeLabel.executions[0].execution_time_ms` | Wall-clock duration |
| `$nodeLabel.executions[0].trigger_source` | What started the run, for example `cron` or `heym_event` |
| `$nodeLabel.executions[0].recovered` | Whether the run was recovered after a crash |
| `$nodeLabel.executions[0].inputs` | What the run received - the trigger payload or the caller's input |
| `$nodeLabel.executions[0].outputs` | The workflow's output for that run |
| `$nodeLabel.workflow_id`, `$nodeLabel.workflow_name` | The workflow the history belongs to, or `null` with **All workflows** |
| `$nodeLabel.executions[0].workflow_id`, `$nodeLabel.executions[0].workflow_name` | With **All workflows**, the workflow each run belongs to |
| `$nodeLabel.total` | Total matching executions **before** the limit |
| `$nodeLabel.by_status` | Counts keyed by status, for example `{ "success": 41, "error": 3 }` |
| `$nodeLabel.since` | Start of the window, or `null` for the full history |

Entries carry both `inputs` and `outputs` - what the run received and what it answered - but never `node_results`: the per-node trace is the largest column in the table and would dwarf everything downstream. Fetch a single execution through the API when you need the full trace.

`total` and `by_status` always describe the **whole** matching history, even when **Limit** caps the returned entries — so you can pull the five most recent runs and still report an accurate failure count.

Leave **Since (days)** empty to cover everything, **Status filter** empty to include every status, and **Limit** empty or `0` to return every entry.

**All workflows** covers the same set as [List Workflows](#list-workflows), and `total` and `by_status` then count runs across all of it. It answers instance-wide questions in a single node, such as how many runs failed in the last day, without looping over the workflow list first.

## Example Workflow

**Daily instance digest**

```
cron → heym (listWorkflows) → loop → heym (getExecutionHistory) → llm → sendEmail
```

- **Heym** `listWorkflows` labelled `inventory`
- **Loop** over `$inventory.workflows`
- **Heym** `getExecutionHistory` with `heymWorkflowId` set to the loop item's `id`, `heymSinceDays` of `1`, and `heymLimit` of `5`
- **LLM** turns the collected runs and status counts into a readable summary

## Notes

- No credential is needed; the node reads the same database Heym runs on.
- **Limit** is the same field for both list operations, and it means the same thing in both: empty or `0` returns everything.
- The node takes a normal input and can be attached to an Agent node as a tool, so an agent can answer questions about your Heym instance — or audit it.
- `getWorkflow` payloads grow with the workflow: long prompts and Python tool bodies all travel inside `data`.
- Pair it with [Heym Trigger](./heym-trigger-node.md) to react to workflow changes as they happen instead of polling on a schedule.

## Related

- [Heym Trigger](./heym-trigger-node.md) – Start a workflow from platform events
- [Execute](./execute-node.md) – Run another workflow rather than describe it
- [Loop](./loop-node.md) – Iterate over the returned workflow list
