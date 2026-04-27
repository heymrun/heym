# Running Executions in History Dialogs

**Date:** 2026-04-08  
**Status:** Approved

## Problem

Running executions are not visible in either history dialog. `ExecutionHistory` DB records are only written after execution completes, so `status=running` entries never appear. Users have no way to cancel a run from the history view.

## Scope

Two dialogs:
1. `ExecutionHistoryDialog.vue` — per-workflow, opened from the editor canvas
2. `ExecutionHistoryAllDialog.vue` — all workflows, opened from the dashboard

## Approach

Backend exposes active in-memory executions via a new lightweight endpoint. Frontend fetches it on dialog open and renders running entries above completed history, each with a Cancel button.

---

## Backend

### 1. `execution_cancellation.py` — add `started_at` + list function

Add `started_at: datetime` field to `ExecutionCancellationHandle` (set to `datetime.utcnow()` in `register_execution`).

Add new public function:

```python
def list_active_executions() -> list[ExecutionCancellationHandle]:
    with _LOCK:
        return list(_ACTIVE_EXECUTIONS.values())
```

### 2. New endpoint: `GET /workflows/executions/active`

Location: `workflows.py` router (before the `/{workflow_id}` routes to avoid route conflict).

Behavior:
- Call `list_active_executions()`
- For each handle, query DB to resolve `workflow_name` and verify `workflow.owner_id == current_user.id` (or shared)
- Return only executions the user owns or has access to

Response schema (`ActiveExecutionItem`):
```python
class ActiveExecutionItem(BaseModel):
    execution_id: str       # UUID str, used for cancel call
    workflow_id: str        # UUID str
    workflow_name: str
    started_at: datetime
```

Response: `list[ActiveExecutionItem]`

### 3. `workflowApi.ts` — new API method

```ts
getActiveExecutions: async (): Promise<ActiveExecutionItem[]>
```

Calls `GET /workflows/executions/active`.

---

## Frontend

### Types

```ts
interface ActiveExecutionItem {
  execution_id: string
  workflow_id: string
  workflow_name: string
  started_at: string  // ISO datetime
}
```

### ExecutionHistoryDialog.vue (per-workflow)

On dialog open, fetch active executions in parallel with existing `fetchExecutionHistory()`. Filter results to the current `workflowId`.

**List rendering:**

```
┌────────────────────────────────────────────────────┐
│  ⟳ Running  [14:23:01]                 [X Cancel]  │  ← pulsing blue/amber
├────────────────────────────────────────────────────┤
│  ✓ 14:22:45                           2340.12ms    │
│  ✗ 14:20:10                           1205.50ms    │
└────────────────────────────────────────────────────┘
```

- Running entries rendered before completed entries, separated by a visual divider if both exist
- Icon: `Loader2` with `animate-spin`, color `text-blue-400`
- Cancel button: `X` icon, `variant="ghost"`, `size="sm"`, calls cancel API then refreshes
- After cancel: re-fetch active executions + history list

### ExecutionHistoryAllDialog.vue (all workflows)

Same pattern. No workflow_id filter — show all active executions the user owns.

```
┌───────────────────────────────────────────────────────────────┐
│  ⟳ Running  Email Workflow  [14:23:01]          [X Cancel]    │
│  ⟳ Running  Data Pipeline   [14:22:55]          [X Cancel]    │
├───────────────────────────────────────────────────────────────┤
│  ✓ 14:22:45  Email Workflow             2340.12ms             │
└───────────────────────────────────────────────────────────────┘
```

### Cancel flow

Cancel button calls:
```
POST /workflows/{workflow_id}/executions/{execution_id}/cancel
```

Uses `execution_id` and `workflow_id` from `ActiveExecutionItem`. On success or 404 (already done), refresh both active list and history list.

---

## Error handling

- Active executions endpoint: on error, silently show empty running section (don't break the dialog)
- Cancel 404 → treat as already finished, just refresh
- Cancel success → re-fetch active list after ~500ms to let backend settle

---

## What is NOT in scope

- DB-level `status=running` persistence (no migration)
- Multi-worker support (in-memory, single server is current setup)
- Running entries in DebugPanel (already has Stop button)
