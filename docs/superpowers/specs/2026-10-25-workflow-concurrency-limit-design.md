# Per-Workflow Concurrency Limit — Design

Date: 2026-10-25
Status: Approved in brainstorming; awaiting written-spec review

Implementation plan: `docs/superpowers/plans/2026-10-25-workflow-concurrency-limit.md`.

## Goal

Let a workflow editor cap how many production runs of one workflow execute at
the same time. Runs beyond the cap wait in a first-in, first-out queue instead
of running in parallel. Callers that cannot hold a connection open get an
execution id and a status URL straight away and collect the result later.

The setting is off by default. When it is on, the number the editor enters is
the cap: 1, 2, or any positive integer.

## Non-goals

- **No DSL change.** The setting lives on the workflow row next to the timeout
  and the rate limit, not in the node graph. `workflow_dsl_prompt.py` is not
  touched.
- **No per-trigger limits.** One cap per workflow, shared by every trigger.
- **No priority lanes.** Strict FIFO. No trigger jumps the queue.
- **No gating of work that runs inside another run.** Sub-workflow calls run in
  their parent's process; gating them would deadlock a workflow that calls
  itself.

## Terminology

**Production run**: any run that is not an editor test run. Cron, HTTP, the
SSE endpoint, Portal, Quick Drawer, MCP, Slack, Telegram, Discord, IMAP,
RabbitMQ, WebSocket, Google Drive/Sheets triggers, Heym events, error-workflow
runs, and the Dashboard Run widget all start production runs.

**Editor test run**: a run with `test_run=true` started by a signed-in Heym
user who has access to the workflow. A request that only sets
`?test_run=true`, without such a session, is a production run. Otherwise an
anonymous caller could skip the queue by adding one query parameter.

**Slot**: the right to execute. A workflow with limit `n` has `n` slots.

**Held run**: a production run waiting for a slot.

## Settings

Three nullable columns on `workflows`:

| Column | Meaning | `NULL` means |
|---|---|---|
| `concurrency_limit` | Max production runs executing at once (≥ 1) | Feature off (default) |
| `concurrency_max_queue` | Max held runs waiting at once (≥ 1) | Unbounded queue |
| `concurrency_max_wait_seconds` | A held run older than this expires (≥ 1) | Never expires |

- `PUT /api/workflows/{id}` accepts all three. `0` clears a field and a
  positive value sets it, matching `workflow_timeout_seconds` and the
  rate-limit fields. Negative values are rejected with 422.
- `concurrency_max_queue` and `concurrency_max_wait_seconds` are independent
  and both optional. Neither has any effect while `concurrency_limit` is
  `NULL`.
- The endpoint already calls `require_workflow_write`, so the owner and write
  collaborators can change the settings and read-only collaborators get 403.
  In the properties panel the fields are enabled when the workflow is not
  read-only. This differs on purpose from the neighbouring owner-only settings:
  the request was "editors can change it".
- The settings are not versioned in Edit History and do not travel in the
  workflow export, the same as the timeout.
- Saving a workflow immediately runs one promotion pass for it, so raising the
  limit or turning it off drains the queue without waiting for the sweep.

## Data model

### `workflow_concurrency_slots` (new)

| Column | Notes |
|---|---|
| `execution_id` | UUID, primary key |
| `workflow_id` | UUID, FK `workflows.id` `ON DELETE CASCADE`, indexed |
| `acquired_at` | timestamptz |

One row per production run that holds a slot. `count(*) WHERE workflow_id = ?`
is the single answer to "how many are running", identical in every process and
every cluster instance.

### `workflow_run_queue` (extended)

Held runs are rows in the existing cluster run queue, so a promoted run is
executed, persisted, cancelled and recovered by machinery that already exists.

New statuses:

| Status | Meaning |
|---|---|
| `held` | Waiting for a concurrency slot. No target instance yet. |
| `expired` | Waited longer than `concurrency_max_wait_seconds`. Terminal. |
| `cancelled` | Cancelled while held. Terminal. |

The cluster code only reads `queued` and `waiting_for_main` when claiming,
expiring and releasing, so `held` rows are invisible to it until promotion
turns them into `queued`.

New nullable columns:

| Column | Notes |
|---|---|
| `concurrency_seq` | `bigint`, from the Postgres sequence `workflow_concurrency_seq`. FIFO order that does not depend on instance clocks. Non-null marks a row as a concurrency-queued run. |
| `expires_at` | `enqueued_at + max_wait`, computed at enqueue. Changing the setting later does not move runs already waiting. |
| `status_token_hash` | `hash_secret()` of the status token. Anonymous workflows only. |
| `run_options` | JSON executor extras a held run must carry: `conversation_history` (Portal) and `run_error_workflow` (the error-workflow recursion guard). |

Index: `(workflow_id, status, concurrency_seq)`.

## Admission, release, promotion

All three live in one new module, `backend/app/services/workflow_concurrency.py`.
Every transaction that changes slots or held rows for a workflow first takes
`pg_advisory_xact_lock(hashtextextended('heym.concurrency:' || workflow_id, 0))`.
The counts are therefore exact under any number of processes and instances.

### Admission: `admit(...) -> Admission`

Called before a production run starts, from `dispatch_workflow` (every
trigger), the SSE execute endpoint and both Portal execute endpoints. Editor
test runs never call it.

Inside the locked transaction:

1. Read the three settings from `workflows`.
2. Limit `NULL` → `Admission(kind="unlimited")`. No slot is taken; the run
   behaves exactly as today.
3. A slot already exists for this `execution_id` → admitted. This makes
   admission idempotent for recovery re-runs.
4. `running < limit` and no held rows → insert a slot → `Admission(kind="admitted")`.
5. `max_queue` set and `held >= max_queue` → `Admission(kind="queue_full")`.
6. Otherwise insert a `held` row with the next `concurrency_seq`, the run's
   inputs, trigger source, actor, credentials owner, placement, `run_options`,
   `expires_at` and (anonymous only) `status_token_hash`, and return
   `Admission(kind="queued", position, size, running, limit)`.

### Release: `release(execution_id)`

The slot is released by whoever executed the run, when it ends:

| Executor | Where |
|---|---|
| In-process run (`dispatch_workflow`) | its `finally` |
| Queue worker (`RunQueueWorker._execute_claimed`) | its `finally`, or after the allow-downstream finalizer |
| SSE / Portal streaming run | the stream's `finally`, including client disconnect |
| Execution recovery re-run | `_finalize` |

A run that pauses for HITL or Codex review releases its slot when it pauses. Its
resume is a continuation and is not gated. A run that returns early through
`allowDownstream` keeps its slot until the background branch has joined.

`release` is a no-op when no slot exists, so every path can call it
unconditionally.

### Promotion: `promote(workflow_id)`

Runs inside the release transaction, and on its own from the sweep and after a
settings save. While there is free capacity (or for every held row when the
limit is `NULL`):

1. Take the held row with the smallest `concurrency_seq`.
2. If `expires_at` has passed, mark it `expired`, write its history row and
   wake its waiters, then continue with the next row.
3. Otherwise insert a slot (skipped when the limit is `NULL`) and turn the row
   into a normal queued run: target chosen by the usual cluster rules (own
   instance id without a cluster, `choose_target(placement)` with one, status
   from `run_queue.next_status`), `not_after = now + cron_misfire_grace_seconds`,
   then `pg_notify('heym_run_queue', target)` inside the transaction.

### Who executes a promoted run

Always `RunQueueWorker`, which today starts only with `HEYM_CLUSTER_ENABLED`.
It now starts on every install and claims rows targeted at its own instance id.
On a single instance that is one cheap indexed poll every 5 seconds per process,
plus `LISTEN` wake-ups.

For concurrency-queued rows the worker also:

- passes `run_options.conversation_history` to the executor;
- fires the configured error workflow when the run fails and
  `run_options.run_error_workflow` is not `false`. The original caller may no
  longer be waiting, so the worker is the only place that can do it exactly
  once. `dispatch_workflow` skips its own error-workflow call for these rows.

### Sweep

`CronScheduler._maintain_run_queue` runs on the leader every 30 seconds. It
gains a concurrency pass that runs with or without a cluster:

1. Expire held rows whose `expires_at` has passed.
2. Reclaim stale slots: older than 120 seconds, with no
   `active_workflow_executions` row and no `queued` / `waiting_for_main` /
   `claimed` queue row for that execution. This is the same rule as
   `expire_stranded_claims`, and it covers a process that died mid-run.
3. Promote every workflow that has held rows.

The existing stranded-claim and late-row sweeps also run without a cluster now,
because the worker does. `release_waiting_for_main` stays cluster-only.

`dispatch_workflow` registers an execution handle for gated in-process runs
when the caller did not (`dashboard_data.py`, `error_workflow_runner.py`).
Otherwise step 2 would treat a long, healthy run as stale.

### Cancellation

`POST /api/workflows/{wid}/executions/{eid}/cancel` first checks for a `held`
row. If one exists it is marked `cancelled`, a `cancelled` history row is
written, and waiters are woken. A held run holds no slot, so nothing else
changes. A promoted run is cancelled through the existing path.

## Behaviour by entry point

### HTTP `/api/workflows/{id}/execute`

| Admission | Response |
|---|---|
| unlimited / admitted | Unchanged |
| queued | `202 Accepted`, `Location: <status_url>`, body below, regardless of `x-simple-response` |
| queue_full | `429` `Concurrency queue is full`, plus a `queue_full` history row, the same way rate limiting writes `rate_limited` |

```json
{
  "status": "queued",
  "execution_id": "6f1c0c2e-…",
  "status_url": "https://heym.example.com/api/workflows/{wid}/executions/{eid}/status",
  "queue": { "position": 2, "size": 5, "running": 1, "limit": 1 },
  "status_token": "…"
}
```

`status_token` is present only for anonymous workflows and is returned only in
this response.

The response cache is written only by runs that execute synchronously. A cache
hit returns before admission, so it never queues.

### Status URL: `GET /api/workflows/{wid}/executions/{eid}/status`

- Authenticated exactly like the execute endpoint, through
  `validate_workflow_auth`: session or JWT, execution token, or the workflow's
  header auth. The caller polls with the credential that started the run.
- Anonymous workflows have no credential to check, so the endpoint requires the
  `X-Heym-Run-Token` header. The header is compared by digest against
  `status_token_hash`. A missing or wrong token is a 404, so the response does
  not reveal whether the execution exists. The token is never accepted from the
  query string, and the stored digest does not work as a token.
- The token is `secrets.token_urlsafe(32)`, which is distinguishable from a hex
  digest. No backfill is involved because the column is new.

```json
{
  "execution_id": "…",
  "workflow_id": "…",
  "status": "queued",
  "queue": { "position": 2, "size": 5, "running": 1, "limit": 1 },
  "outputs": null,
  "error": null,
  "execution_time_ms": null
}
```

How `status` is derived from the queue row:

| Queue row | `status` |
|---|---|
| `held` | `queued` (`queue` present) |
| `queued`, `waiting_for_main`, `claimed` | `running` |
| `done` | the summary's status: `success`, `error`, `pending` (HITL), `cancelled` |
| `failed` | `error` |
| `expired` | `expired` |
| `cancelled` | `cancelled` |

`outputs`, `error` and `execution_time_ms` are filled once the run is terminal.
With no queue row, the endpoint falls back to the `execution_history` row with
that id, so a run that started immediately can be queried too. With neither, it
returns 404.

The waiting state is named `queued` rather than `pending` because `pending`
already means "waiting for HITL review" in Heym.

### SSE: `/execute/stream`, Quick Drawer

- unlimited / admitted: unchanged.
- queued: the stream opens and sends
  `{"type": "queued", "execution_id", "position", "size", "running", "limit"}`
  immediately and again whenever the position changes. It polls every 2
  seconds. When the run is claimed it sends `execution_started`. When the run
  is terminal it sends `execution_complete` with the status, outputs and
  execution time from the status body. `node_results` is empty; the node
  results stay in the run's history row.
- Node-by-node events and LLM token deltas are **not** streamed for a queued
  run, because it executes in the worker, possibly in another process. A
  disconnect does not cancel a queued run, the same as a 202.
- queue_full: `429` before the stream opens.

### Portal

- `/{slug}/execute/stream` behaves like the SSE endpoint above. The chat shows
  `Waiting in queue (2/5)` in its progress line.
- `/{slug}/execute` (stream disabled) waits for the result in place, through
  the same wait as background triggers. A Portal user's browser has no use for a
  status URL.
- The conversation history travels in `run_options`.

### MCP (`/api/mcp`: REST `tools/call`, JSON-RPC, legacy SSE; named MCP servers)

- unlimited / admitted: unchanged.
- queued: a non-error tool result whose text is

  ```json
  {
    "status": "queued",
    "execution_id": "…",
    "queue": { "position": 2, "size": 5, "running": 1, "limit": 1 },
    "next_step": "Call heym_execution_status with this execution_id every 5-10 seconds until status is success, error, cancelled or expired."
  }
  ```

- queue_full: `isError` result `Concurrency queue is full`.
- New tool `heym_execution_status` takes `execution_id` and returns the status
  body above. It only finds executions of workflows that this MCP surface
  exposes (the user's MCP-enabled workflows, or the named server's workflows).
  It appears in `tools/list` only when at least one exposed workflow has a
  concurrency limit.

### Background triggers

Cron, Slack, Telegram, Discord, IMAP, RabbitMQ, WebSocket, Google Drive/Sheets,
Heym events, error-workflow runs and the Dashboard Run widget all go through
`dispatch_workflow`. A queued run behaves as a cluster-offloaded run does
today: the dispatcher waits on `heym_run_done` for the result when the call
site waits (up to the existing 900 seconds, `DEFAULT_WAIT_SECONDS`) and then
carries on. The run executes either way and its history is written by the
worker. A queue_full rejection writes a `queue_full` history row and logs a
warning.

### Not gated

Editor test runs, sub-workflow calls (Execute node, agent workflow tools),
Evals, chat build-mode test runs, and HITL / Codex resumes.

## History and UI

- New history statuses: `expired` and `queue_full`, each with its own text
  badge in `frontend/src/lib/executionHistoryStatus.ts`.
  `upsert_workflow_analytics_snapshot` already counts any status other than
  success and error toward the total only, as it does for `rate_limited`.
- `GET /api/workflows/executions/active` adds held rows as
  `status: "queued"` with `queue_position` and `queue_size`, scoped by
  `workflow_access_clause` like the other sections.
- Both Execution History dialogs (canvas and All History) render a queued row
  in the active section with a `Queued 2/5` badge and Cancel, and no
  Open live. A small shared `ActiveExecutionStatusLabel.vue` keeps the two
  already-oversized dialogs from growing.
- Properties panel: a new `WorkflowConcurrencySettings.vue`, with a
  `useWorkflowConcurrencySettings.ts` composable beside it, rendered inside
  `WorkflowSettingsPanel.vue`. It has a toggle (off by default); on → "Max
  concurrent runs" (min 1, defaults to 1 when switched on), "Max queue size
  (optional)", "Max wait (seconds, optional)" and a short explanation. The
  fields are disabled when read-only. Saves are optimistic with rollback, like
  the neighbouring fields.
- Quick Drawer and Portal show `Waiting in queue (2/5)` while they receive
  `queued` events.

## Release tour

Release `2026.21` shipped in v0.0.137, so this starts release `2026.22` with
`tourEnabled: false`. The section id is `concurrency-limit` and its visual is
`ConcurrencyLimitTourVisual.vue`. The visual is a mock that loops through
three incoming requests: one running, two badged `#1` and `#2`, and the head
promoted when the running one finishes. It is registered in `tourVisuals.ts`.
The registry keeps five sections, so the oldest (`heym-work`) is dropped along
with its visual and its registration, and release `2026.19` is trimmed if it
is left without sections.

## Documentation

Through the `heym-documentation` skill:

- `reference/features.md`: a "Concurrency Limit" section beside "Workflow
  Timeout", and a note in the webhook paragraph.
- `reference/webhooks.md`: the 202 response, the status URL, the run token and
  429.
- `reference/sse-streaming.md`: the `queued` event, and that queued runs do not
  stream node events.
- `reference/portal.md`, `reference/quick-drawer.md`: the waiting state.
- `tabs/mcp-tab.md`: the queued result and `heym_execution_status`.
- `reference/execution-history.md`: queued rows and the `expired` and
  `queue_full` statuses.
- `reference/triggers.md`: background trigger behaviour and what is not gated.
- `reference/cluster.md`: the limit is counted cluster-wide, and the run queue
  worker now runs on every install.

## Testing

Backend (pytest, `unittest` style, as `AGENTS.md` requires):

- `test_workflow_concurrency.py`: the admission decision (unlimited, admitted,
  queued positions, queue_full), idempotent re-admission, FIFO promotion,
  promotion of several runs after the limit is raised, draining when the limit
  is turned off, expiry, stale-slot reclaim and held-run cancellation.
- `test_workflow_concurrency_postgres.py`: N concurrent admissions with limit k
  produce exactly k slots and N−k held rows with contiguous positions. Modelled
  on `test_active_execution_registry_resilience.py`, and skipped without a
  reachable database the same way.
- `test_workflow_concurrency_dispatch.py`: an editor test run is not gated and
  an anonymous `?test_run=true` is. The slot is released on success, error,
  exception, HITL pause and the allow-downstream join. The worker releases in
  `finally`. The error workflow fires exactly once for a queued run.
- `test_workflow_concurrency_api.py`: the 202 body and `Location`, 429 with a
  `queue_full` history row, the status endpoint for JWT, header auth and
  execution tokens, settings validation (0 clears, negative → 422), a write
  share can set the settings and a read share gets 403, and held-run cancel.
- `test_advisory_concurrency_status_token.py`: an anonymous status poll needs
  the token. The stored digest does not authenticate, the query string is
  ignored, and a wrong token gets the same 404 as an unknown id.
- `test_workflow_concurrency_mcp.py`: the queued tool result,
  `heym_execution_status` scoping (an unexposed workflow's execution is not
  found), and the tool being listed only when a limit exists.
- Streaming: the SSE endpoint emits `queued`, then `execution_started` and
  `execution_complete`, for a held run.

Frontend:

- Vitest: `WorkflowConcurrencySettings` (the toggle reveals the fields,
  read-only disables them, an empty value clears), the active-row status label
  mapping, and the release-tour registry test.
- Playwright `frontend/e2e/workflow-concurrency.spec.ts`: set the limit in the
  properties panel and confirm it survives a reload; start two API runs of a
  workflow with a 5-second Wait node, then confirm the second shows as Queued
  in History.
