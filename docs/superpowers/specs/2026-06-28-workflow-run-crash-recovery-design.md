# Crash-recovery for interrupted workflow runs

**Date:** 2026-06-28
**Status:** Approved (design)

## Problem

When the backend restarts (deploy, docker restart, crash) while a workflow is
executing, the worker thread dies mid-run. The execution is tracked only in the
`active_workflow_executions` table via `worker_id` + `heartbeat_at`. Today:

- The row lingers and the run appears stuck in **"running"** in the UI.
- After `ACTIVE_EXECUTION_STALE_AFTER_SECONDS` (300s) the row is **silently
  deleted** (`cleanup_stale_persisted_executions`) — no terminal
  `ExecutionHistory` entry is ever written. The run is simply lost.

We want interrupted runs to be **re-run from scratch with the same parameters**
after a restart, consumed asynchronously/in parallel, and to produce a proper
terminal entry in run history ("completed"). A per-workflow toggle (default on)
controls the behavior; when off, the orphaned run is recorded as `skipped`.

Must work uniformly across `run.sh`, `deploy.sh`, and the single docker image.

## Decisions (from brainstorming)

- **Scope:** recover **all top-level executions except sub-workflows**.
  Sub-workflows are re-driven by their recovered parent.
- **Detection speed:** **instant on graceful restart** (SIGTERM) + **60s
  heartbeat-staleness fallback** for hard crashes (SIGKILL/OOM).
- **Retry policy:** **retry once**, then write a terminal `failed` entry.
- **Toggle:** per-workflow `auto_recover_runs`, **default true**, surfaced in the
  canvas run panel. When off → orphaned runs recorded as `skipped`.
- **Re-run semantics:** from scratch with the original **inputs**, using the
  **current** workflow definition (nodes/edges fetched fresh) — not a resume.
- **Known accepted risk:** rabbitmq/cron/imap triggers self-redeliver (broker
  nack/requeue, cron re-fire, imap re-poll). Recovering them as well means some
  runs may execute twice. Accepted by product owner.

## Why it works across all deployment modes

Recovery piggybacks on the **existing leader election** (`distributed_lock`,
Postgres advisory lock). Only the leader runs the recovery sweep:

- **Single docker image / `run.sh`:** the sole process is always the leader, so
  it recovers its own orphans on the next startup.
- **`deploy.sh` / multi-worker:** the elected leader recovers orphans left by any
  worker.

**No changes to `run.sh` / `deploy.sh` / Dockerfile are required.** Migrations
already run via `alembic upgrade head` in the existing startup flow.

## Architecture

### 1. Persist what's needed to replay

Add columns to `ActiveWorkflowExecution` (Alembic migration; all nullable /
defaulted so the migration is safe online):

| Column | Type | Notes |
|---|---|---|
| `inputs` | JSON, default `{}` | parameters to replay |
| `trigger_source` | String(50), nullable | history attribution |
| `actor_user_id` | UUID, nullable | rebuild credentials / global-vars context |
| `attempt` | Integer, default `0` | recovery counter (enforces retry-once) |
| `recoverable` | Boolean, default `true` | sub-workflows set `false` |

Recovery uses the **current** workflow definition + stored `inputs`. If the
workflow was deleted, the run is marked `failed`.

### 2. Capture recovery info at every top-level entry point

Extend `register_execution(...)` (backwards-compatible — new params optional):

```python
def register_execution(
    *,
    workflow_id, execution_id,
    event=None, started_at=None,
    inputs=None, trigger_source=None, actor_user_id=None,
    recoverable=True,
) -> threading.Event: ...
```

The registry's `_drain_commands` upsert persists the new columns.

Call-site work:

- **Already register** → pass the new fields: `api/workflows.py` (manual ×2),
  `api/portal.py`, `api/mcp.py`, `api/mcp_servers.py`.
- **Do not register today** → add registration: `services/cron_scheduler.py`,
  `services/imap_trigger_service.py`, `services/websocket_trigger_service.py`,
  `services/rabbitmq_consumer.py`, `api/discord.py`, `api/slack.py`,
  `api/telegram.py`.
- **Sub-workflows** (`workflow_executor.py` `_register_sub_execution`) → pass
  `recoverable=False`.

### 3. Graceful-shutdown marking (instant recovery)

In `main.py` lifespan shutdown, **after** stopping the active-execution registry
(so its heartbeat loop can't overwrite), call a new helper that backdates this
worker's in-flight recoverable rows so the next process's sweep treats them as
immediately orphaned:

```python
# mark_own_executions_orphaned()
UPDATE active_workflow_executions
SET heartbeat_at = '1970-01-01T00:00:00+00:00'
WHERE worker_id = <this worker_id> AND recoverable = true;
```

Reusing `heartbeat_at` (rather than a new flag column) means the recovery sweep
query stays a single staleness check. Hard crashes skip this step and are caught
by the 60s fallback.

### 4. Recovery loop — `services/execution_recovery.py`

A background service started in `main.py` lifespan, gated on
`lock_service.is_leader` (mirrors `rabbitmq_consumer_manager`). After a short
startup grace, then every ~15s:

1. **Find orphans:** `recoverable = true` rows with
   `heartbeat_at < now - RECOVERY_STALE_AFTER_SECONDS` (60s).
2. **Atomically claim** each: a single guarded UPDATE
   (`SET worker_id = self, heartbeat_at = now, attempt = attempt + 1
   WHERE execution_id = :id AND heartbeat_at < :cutoff`). Only one leader wins;
   a still-alive worker (heartbeating every 0.5s) is never matched.
3. **Decide** per claimed row:
   - `attempt > 1` (retry-once exhausted) → write `ExecutionHistory` **`failed`**, delete row.
   - workflow missing/deleted → **`failed`**, delete row.
   - workflow `auto_recover_runs` is **off** → write **`skipped`**, delete row.
   - else → **re-run async/parallel**:
     `asyncio.create_task(asyncio.to_thread(execute_workflow, ...))` with context
     rebuilt from `actor_user_id` (credentials, global vars, workflow_cache).
     On completion write the normal terminal `ExecutionHistory` and clear the row
     (also persists analytics snapshot + global variables, matching existing
     trigger paths).

The blind `cleanup_stale_persisted_executions` 300s delete is **replaced** by
this path so runs are never silently dropped. The `/executions/active` display
cutoff is unaffected.

### 5. History semantics

- Re-run finishes → normal terminal `ExecutionHistory` → UI shows success
  ("completed").
- Toggle off → new **`skipped`** status entry.
- Retry exhausted / workflow gone → **`failed`** entry.

Frontend: add a badge/colour for the **`skipped`** status wherever execution
status is rendered (history list/dialog + `DebugPanel`).

### 6. UI toggle

- New `auto_recover_runs: bool` (default **true**) on `Workflow`, following the
  existing `sse_enabled` / `mcp_enabled` / `portal_enabled` pattern:
  - Alembic migration (default true, server_default).
  - `WorkflowUpdate` (optional) + `WorkflowResponse` fields.
  - Update endpoint handling + create default.
- Surfaced in the canvas run panel (`DebugPanel.vue`) as a labeled switch
  ("Auto-recover interrupted runs", default on) that PATCHes the workflow.

## Testing (backend, required)

`backend/tests/test_execution_recovery.py`:

- Orphan claim & re-run produces a terminal `ExecutionHistory`.
- Retry-once exhausted → `failed`.
- Toggle off → `skipped`.
- Sub-workflow (`recoverable = false`) ignored by the sweep.
- Atomic claim prevents double-recovery (concurrent claim attempts).
- Non-leader does not sweep.
- Deleted workflow → `failed`.
- Graceful-shutdown marking backdates only this worker's recoverable rows.

Run `./check.sh` (includes `ruff format`, lint, backend tests) before push.

## Out of scope

- Resuming a run from the node it stopped at (we re-run from scratch).
- A live-worker registry / fencing tokens beyond the existing advisory-lock
  leader election.
- Deduplicating against broker-native redelivery (accepted double-exec risk).

## Files touched (anticipated)

- `backend/app/db/models.py` — new `ActiveWorkflowExecution` columns + `Workflow.auto_recover_runs`.
- `backend/alembic/versions/*` — two migrations (or one) for the above.
- `backend/app/services/execution_cancellation.py` — extend `register_execution` + registry upsert; add `mark_own_executions_orphaned`; remove/replace blind stale-delete.
- `backend/app/services/execution_recovery.py` — **new** leader-gated recovery loop.
- `backend/app/services/workflow_executor.py` — sub-workflow `recoverable=False`.
- `backend/app/api/{workflows,portal,mcp,mcp_servers,discord,slack,telegram}.py` — pass recovery fields.
- `backend/app/services/{cron_scheduler,imap_trigger_service,websocket_trigger_service,rabbitmq_consumer}.py` — register executions.
- `backend/app/main.py` — start recovery service; shutdown marking.
- `backend/app/models/schemas.py` — `auto_recover_runs` on workflow schemas.
- `frontend/src/components/Panels/DebugPanel.vue` — toggle + `skipped` badge.
- Frontend history components — `skipped` status styling.
- `backend/tests/test_execution_recovery.py` — **new**.
