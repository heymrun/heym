# Multi-Instance Load Distribution — Design

Date: 2026-08-27
Status: Awaiting approval

Implementation plan: `docs/superpowers/plans/2026-08-27-multi-instance-load-distribution.md`.

## Goal

Let two or more Heym instances share one Postgres database and split background
workflow execution between them by an operator-configured percentage, so the
machine serving the UI and the API is not also the only machine running every
workflow.

## Non-goals

- **High availability.** The main instance remains a single point of failure for
  HTTP ingress, file storage, plugins, and the editor. This feature distributes
  load; it does not survive the loss of main. Neither the docs nor the UI will
  claim otherwise.
- **Shared file storage.** No blob table, no NFS requirement, no object store.
  Work that touches local disk runs on main instead.
- **Distributing streamed runs.** The editor canvas and the chat portal keep
  their SSE runs on main.
- **A new infrastructure dependency.** No Redis, no message broker. Postgres is
  the only channel between instances, and they never open HTTP to each other.
- **Per-run cost weighting or concurrency caps.** Percentages distribute run
  counts, not run cost. Explicitly deferred.
- **License gating.** The feature ships in the free self-hostable product, the
  same way SSO did. `README.md`'s "No Enterprise Gatekeeping" section stands
  unchanged.

## Terminology

**Instance** — one Heym deployment: one machine, one container, one
`FILE_STORAGE_DIR`. Under the release image an instance is 8 uvicorn processes
(`docker/release-entrypoint.sh:7`), all sharing one identity.

**Main** — the instance pinned by `HEYM_INSTANCE_ROLE=main`. Serves ingress, owns
file storage and plugins, runs the editor and portal.

**Worker** — any instance with `HEYM_INSTANCE_ROLE=worker`. Reaches only Postgres,
serves no user traffic, executes background runs.

**Leader** — the holder of the existing `pg_advisory_lock`
(`services/distributed_lock.py`). Owns cron, alert evaluation, and execution
recovery. Unrelated to main: if main dies, leadership moves to a worker within
about five seconds and cron keeps running.

## What already works

The cluster primitives are largely in place and are not being rewritten:

- `services/distributed_lock.py` elects a leader with `pg_advisory_lock`, which
  is cluster-wide in Postgres. Two instances against one database already elect
  one leader between them.
- `services/cron_slot_state.py` claims each cron slot behind
  `uq_cron_slot_claim`, fail-closed, so no slot fires twice.
- `db/models.py:575` `ActiveWorkflowExecution` already carries `worker_id` and
  `heartbeat_at`, and `services/execution_recovery.py` already reclaims orphans
  behind the leader gate.
- `services/execution_cancel_bus.py` already runs a Postgres `LISTEN/NOTIFY`
  loop. The run queue reuses that pattern rather than inventing one.

## Placement: where a run may execute

`backend/app/services/cluster/node_placement.py` declares, for every node type,
whether it may leave the main instance. A node is `MAIN_ONLY` when it reads or
writes `FILE_STORAGE_DIR`, leaves state on local disk that a later run reads
back, or depends on something installed per instance.

| Node | Placement | Reason |
|---|---|---|
| `codex`, `opencodeGo` | MAIN_ONLY | `CodexRunnerService.resume_task` reopens `workspace_path` on local disk (`codex_runner_service.py:336`), plus Drive writes |
| `agent` with a skill tool | MAIN_ONLY | `_load_skill_drive_files` / `_persist_skill_files` (`llm_service.py:2458`, `:2323`) |
| `drive`, `converter`, `googleDrive` | MAIN_ONLY | read/write `FILE_STORAGE_DIR` |
| `fileUploadTrigger` | MAIN_ONLY | the upload lands on main's disk |
| `sendEmail` | MAIN_ONLY | corporate SMTP relays commonly allowlist source IPs; a single fixed egress point removes the failure mode entirely |
| `plugin`, `pluginTrigger` | MAIN_ONLY | `plugin_store.py:47` extracts the zip to the local plugins directory |
| everything else | ANYWHERE | including `code`, `playwright`, `agent` with Python tools, and `mcpCall` over stdio |

Sandbox nodes are deliberately ANYWHERE. Every instance in a cluster runs the
same image with its own Docker socket, so `code` and `playwright` — the two most
CPU-hungry nodes — are exactly the work worth moving off main.

Placement is computed once per run over the whole graph, recursing through
`execute` nodes (the Execute Workflow node's registry type) and through an
agent's `call_sub_workflow` tools. A workflow id that is only resolvable at
runtime — an expression — makes the run MAIN_ONLY, because its contents cannot
be inspected. One MAIN_ONLY node anywhere in the reachable graph makes the whole
run MAIN_ONLY.

### No silent default

There is no fallback for an unlisted node type.
`backend/tests/test_cluster_node_placement.py` walks
`node_execution/registry.py` and fails the build when a registered node type has
no placement entry, mirroring `TestExpressionOperatorCoverage`. Plugin-provided
node types are the single exception: they are not in the registry at build time
and are MAIN_ONLY at runtime, which is already true for the reason above.

`AGENTS.md` gains a matching rule under **Node and operation integration**, so a
new node type cannot be added without deciding where it runs.

## Data model

### `cluster_instances`

One row per instance, upserted by all 8 of its processes.

| Column | Type | Notes |
|---|---|---|
| `id` | text, pk | `HEYM_INSTANCE_ID` — stable across restarts and processes |
| `name` | text | display label, editable from the admin UI |
| `role` | text | `main` / `worker`, from `HEYM_INSTANCE_ROLE` |
| `enabled` | bool | admin UI toggle |
| `weight` | int | 0-100 |
| `version` | text | `settings.resolved_version` |
| `schema_revision` | text | alembic head |
| `keys_fingerprint` | text | `sha256(ENCRYPTION_KEY)[:16] + sha256(SECRET_KEY)[:16]` |
| `docker_ok` | bool | probe result |
| `db_latency_ms` | float | round trip measured by the instance itself |
| `heartbeat_at` | timestamptz | freshness |

Identity must come from the environment: `distributed_lock.py:21` derives its id
from `os.getpid()`, which differs across the 8 processes and across restarts.

### `workflow_run_queue`

| Column | Notes |
|---|---|
| `id`, `workflow_id`, `execution_id` | `execution_id` is minted at enqueue so the caller knows what to watch for |
| `placement` | `main_only` / `anywhere` |
| `target_instance_id` | chosen at enqueue |
| `status` | `queued`, `waiting_for_main`, `claimed`, `done`, `failed`, `skipped_late` |
| `inputs`, `trigger_source`, `actor_user_id`, `credentials_owner_id`, `test_run`, `timeout_seconds` | run parameters |
| `not_after` | enqueue time plus `cron_misfire_grace_seconds` |
| `result`, `error` | read back by the waiting caller |
| `enqueued_at`, `claimed_at`, `claimed_by_process`, `finished_at` | timing |

Index on `(target_instance_id, status, enqueued_at)`.

**Decrypted credentials never enter this table.** The row carries
`credentials_owner_id`; the executing instance calls
`get_credentials_context(db, credentials_owner_id)` itself, which it can do
because it holds the same `ENCRYPTION_KEY`. Writing a resolved credentials
context into a queue row would put plaintext secrets in the database and violate
the secret-handling policy in `AGENTS.md`.

### `cluster_dispatch_state`

A single row holding a JSONB map of per-instance assignment counters, locked with
`SELECT ... FOR UPDATE` during assignment. One lock point, so no deadlock
ordering to reason about.

### Attribution columns

`execution_history` and `active_workflow_executions` each gain
`executed_by_instance_id` and `executed_by_instance_name`. The name is a snapshot
taken at write time, so history keeps meaning after an instance is renamed or
removed. Both stay `NULL` on a single-instance install and the dialogs render
nothing extra.

## Dispatch

```
Trigger  ──>  MAIN (or the cron leader)
               │ 1. load workflow, resolve placement
               │ 2. bump the assignment counter for the instance that will run it
               │ 3. if cluster disabled, or placement is MAIN_ONLY and we are main:
               │       run in-process, exactly as today, no queue
               │ 4. otherwise INSERT the queue row for the chosen instance
               │    in the same transaction as the counter bump
               │ 5. pg_notify('heym_run_queue', target_instance_id)
               │ 6. if the caller needs the result, wait on
               │    'heym_run_done' for this execution_id
               ▼
            POSTGRES
               ▲
               │ 7. SELECT ... FOR UPDATE SKIP LOCKED
               │    WHERE target_instance_id = me AND status = 'queued'
             INSTANCE
               │ 8. execute_workflow(...) in its own process
               │ 9. write execution_history with executed_by_instance_*
               │ 10. UPDATE the queue row to 'done' with the result
               │ 11. pg_notify('heym_run_done', execution_id)
               ▼
Caller   <──  MAIN returns the response
```

Step 3 is what keeps a single-instance install bit-for-bit unchanged: with no
cluster, nothing is ever enqueued and no latency is added.

The counter in step 2 is bumped for every run, including the ones step 3 keeps
in-process. Skipping it there would let main's forced work escape the accounting
and break the quota rule below.

A MAIN_ONLY run is not "selected": its target is always main. When main is not in
the live pool the row is enqueued as `waiting_for_main` instead of `queued`, and
no instance can claim it until main returns.

All 8 processes of an instance poll the queue. `FOR UPDATE SKIP LOCKED` resolves
the race, and the percentage stays meaningful because it is applied per instance
at enqueue time, not per process at claim time. In-machine parallelism comes free.

Cancellation needs no new work: `execution_cancel_bus.publish_execution_cancel`
already reaches every process on every instance over `LISTEN/NOTIFY`.

### Dispatch seam

A single `services/cluster/dispatch.py::dispatch_workflow(...)` mirrors
`execute_workflow`'s signature and replaces the direct call at the offloadable
sites: `api/workflows.py:2888` (the non-streaming execute endpoint),
`api/mcp.py:1057`, `api/mcp_servers.py:560`, `cron_scheduler.py:112`,
`api/telegram.py:154`, `api/slack.py:153`, `api/discord.py:273`,
`imap_trigger_service.py:440`, `rabbitmq_consumer.py:350`,
`websocket_trigger_service.py:428`, and `heym_event_dispatcher.py:243`.

`execute_workflow_streaming` call sites are untouched, and so is the sub-workflow
call in `node_execution/nodes/execute_node.py:79` — a sub-workflow runs inside its
parent's process and must not be enqueued separately.

## Weighted selection

Weights are integers summing to 100 across enabled instances, validated as a
whole map on write so there is no intermediate invalid state.

The candidate pool at enqueue time is every instance that is `enabled`, fresh
(`heartbeat_at` within the liveness window), and compatible (see below). Weights
are renormalized across that pool, so with `main=70, A=15, B=15` and A dead, main
gets 70/85 and B gets 15/85. When A returns, the split returns to 70/15/15 on its
own.

Selection is smooth weighted round-robin over deficits:

```
total     = sum(counter) + 1
deficit_i = weight_i / sum(weights) * total - counter_i
winner    = argmax(deficit_i)
counter[winner] += 1
```

Counters are halved across the board when the largest passes a threshold, so they
never grow without bound.

**A MAIN_ONLY run increments main's counter too.** That single rule is what makes
percentages describe total load rather than "70% of whatever is left over": every
forced run spends main's quota, so the next ANYWHERE runs fall to the workers. No
special case, no separate accounting.

The consequence, which the admin UI and the docs must state: **main's percentage
is a ceiling, not a floor.** Setting it low is safe — MAIN_ONLY work still lands
on main regardless — while setting it high starves the workers. When MAIN_ONLY
volume exceeds main's quota, main takes the overflow anyway and its ANYWHERE
share drops to zero; the quota floors at zero rather than going negative.

## Heartbeat and compatibility

Every instance upserts its row every 10 seconds, writing its version, alembic
head, key fingerprint, Docker probe result, and the measured `SELECT 1` round
trip. An instance counts as live while its `heartbeat_at` is within 30 seconds,
so a single missed beat does not remove it from the pool. Both values are module
constants, not environment variables: they are properties of the mechanism, not
deployment configuration.

Main's row is the reference. An instance whose version, schema revision, or key
fingerprint differs is marked **incompatible**: it shows red in the admin UI and
is excluded from the candidate pool.

This is what makes the mismatch in `services/encryption.py:11` visible. A worker
with a different `ENCRYPTION_KEY` cannot decrypt credentials, and every
credential-using run would fail with an unrelated-looking error. Excluding it up
front converts a silent, confusing failure into a red row with a named cause.

It also defines the upgrade procedure. Upgrading main first makes every worker
incompatible; load falls back to main, and each worker rejoins as it is upgraded.
Slower, visible, and reversible — never silently wrong.

## Failure behavior

**Main is down.** Leadership moves to a worker in about five seconds and cron
continues. ANYWHERE runs execute on the workers. MAIN_ONLY runs are enqueued as
`waiting_for_main` and wait. HTTP, API, MCP, the UI, and the editor are
unreachable, because ingress points at main.

**Main returns.** The backlog must not replay all at once — the mirror image of
the cron duplicate-fire incident of 2026-08-04. A `waiting_for_main` row past its
`not_after` deadline is closed as `skipped_late` and appears in history with that
reason. The deadline reuses `settings.cron_misfire_grace_seconds` (600 by
default, `config.py:57`), the same rule `cron_scheduler.py:164` already applies.

**An instance dies mid-run.** `ActiveWorkflowExecution.heartbeat_at` goes stale,
the leader's existing sweep in `execution_recovery.py` claims the orphan, and
`decide_recovery_action` re-runs it against the current live pool. Existing code;
the only addition is refreshing the attribution columns for the new instance.

**An instance is disabled from the UI.** It stops receiving new work and the
weights renormalize immediately. Running executions are not interrupted; the
admin UI shows the draining count so the operator knows when it is safe to stop
the machine.

**An instance runs an older image.** Marked incompatible, excluded, load returns
to main.

## Admin surface

Backed by `HEYM_ADMIN_EMAILS` through the existing
`services/instance_admin.py::is_instance_admin`, following the SSO precedent
exactly: `api/admin/cluster.py` behind `/api/admin/cluster`, rendered by
`frontend/src/components/Layout/settings/ClusterSettingsTab.vue` inside
`UserSettingsDialog`.

- `GET /api/admin/cluster` — global enabled flag, the instance rows, and the
  MAIN_ONLY / ANYWHERE run ratio over the last 24 hours.
- `PUT /api/admin/cluster/instances` — the whole `{id: {name, enabled, weight}}`
  map at once, rejecting any set whose enabled weights do not total 100.
- `DELETE /api/admin/cluster/instances/{id}` — remove a retired instance's row.

The table shows, per instance: name (editable), role, **Enabled** toggle,
**Live** indicator from heartbeat freshness, **ms** from `db_latency_ms`,
version, and **weight** as an integer. A **Refresh** button re-reads the
endpoint. Weights are only editable when they can be saved as a valid set.

The 24-hour ratio answers a question the percentages cannot: a codex-heavy or
Drive-heavy workload is mostly MAIN_ONLY, the workers stay idle whatever the
weights say, and the operator should see that rather than tune numbers that
cannot help.

Row rendering lives in a child component so `ClusterSettingsTab.vue` stays under
the 300-line limit.

The global switch is `HEYM_CLUSTER_ENABLED` on main, not a UI control — an
operator-level kill switch that returns the deployment to single-instance
behavior. Per-instance enable/disable is the UI control.

## Execution history attribution

`ExecutionHistoryDialog.vue` (canvas) and `ExecutionHistoryAllDialog.vue` (home)
show the executing instance's name, with its id in the tooltip, and both gain a
filter beside the existing trigger-source filter. The filter's value is the
instance **id** and its label is the **name**: names are snapshots and two
instances can end up sharing one, while ids never collide.

Options are derived from the entries already loaded, exactly as the
trigger-source options are, so an instance that has left the cluster still
appears while its runs are on screen and no extra request is needed.

Each dialog keeps its own filtering mechanism rather than gaining a second,
differently-behaving one: the canvas dialog sends `instance_id` to
`GET /api/workflows/{id}/history` and refetches, so the filter survives
pagination; the home dialog filters the loaded page in memory, the same scope
its trigger-source filter already has. `execution_history.executed_by_instance_id`
is indexed for the server-side path.

Nothing renders and no filter appears when the values are `NULL`, so a
single-instance install sees no change.

## Security

The trust boundary does not move. Workers open no HTTP to main and expose no new
port. Queue rows are written only by backend code, never from user input. Every
sandbox boundary — `--network none`, no Docker socket, dropped capabilities,
non-root — is a property of the image and holds identically on every instance.

Two facts belong in the docs:

- **Every instance with database access can claim any run and decrypt every
  credential.** That is already true of anything holding the database plus
  `ENCRYPTION_KEY`; a cluster increases the number of machines in that position.
  The network between the instances and Postgres must be trusted.
- **Worker egress IPs differ from main's.** Any API that allowlists source IPs —
  corporate SMTP relays, payment and banking endpoints, internal services — sees
  a new source address. `sendEmail` is pinned to main for exactly this reason;
  for `http` the operator must either give the cluster one NAT egress address or
  allowlist every instance.

Also documented as a deployment constraint: **ingress points only at main.**
Round-robining user traffic across instances would send uploads to one machine
and downloads to another. No code guard enforces this.

## Testing

- `test_cluster_node_placement.py` — every registered node type has a placement
  entry (build-failing); recursion through `execute` nodes and agent
  sub-workflow tools; a dynamic workflow id degrades to MAIN_ONLY.
- `test_cluster_dispatch.py` — renormalization across live instances; a MAIN_ONLY
  run spending main's quota; overflow flooring at zero; dead, disabled, and
  incompatible instances excluded; counter rescaling.
- `test_cluster_registry.py` — heartbeat upsert is idempotent across processes;
  each of version, schema revision, and key fingerprint independently marks an
  instance incompatible.
- `test_cluster_run_queue.py` — `SKIP LOCKED` gives a row to exactly one claimer;
  `waiting_for_main` with no main; `skipped_late` past `not_after`; no decrypted
  credential is ever written to a queue row.
- Playwright coverage for the Instances settings tab: weights that do not total
  100 are rejected, and a disabled instance stops taking work.

## Documentation

Following the path SSO took, which is already complete in both places
(`README.md:193`, `features.md:640`):

- `README.md` — a Key Capabilities bullet, and a Production Readiness paragraph
  with a `<details>` block for cluster setup. The "No Enterprise Gatekeeping"
  section is not touched.
- `frontend/src/docs/content/reference/features.md` — a
  `### [Load Distribution](./cluster.md)` section with its See-also line.
- `frontend/src/docs/content/reference/cluster.md` — new page: roles, the
  environment variables, the placement rule, how to choose percentages, the
  egress and key-alignment warnings, the ingress constraint.
- `frontend/src/docs/manifest.ts` — register the page.
- `frontend/src/docs/content/reference/user-settings.md` — the Instances tab.
- `AGENTS.md` — the node placement rule.
- `.env.example` and `ENVIRONMENT-VARIABLES.md` — `HEYM_INSTANCE_ID`,
  `HEYM_INSTANCE_NAME`, `HEYM_INSTANCE_ROLE`, `HEYM_CLUSTER_ENABLED`.
- A release tour entry with an animated mock of the Instances tab, registered in
  `tourVisuals.ts` and listed in the release's `sectionOrder`.

No document describes how to build a highly available deployment.
