# Heym Runbook (L1)

Follow these procedures to diagnose and recover Heym services, PostgreSQL connections, workflow queues, cluster capacity, and sandbox execution.

Start with [Heym Incident Playbook (L0)](./incident-playbook.md) for severity, contacts, and deployment inventory.

Last reviewed: 2026-11-10. Commands match the repository at review time. Confirm the deployed release and topology before use. All service-changing commands below are instructions for an operator, not automatic remediation.

## Procedure index

| Incident |
| --- |
| [UI or API down](#ui-or-api-down) |
| [PostgreSQL down](#postgresql-down-or-not-writable) |
| [Active DB connections, pool saturation, locks](#active-db-connections-pool-saturation-and-locks) |
| [Service restart](#controlled-service-restart) |
| [Most resource-consuming workflows](#most-resource-consuming-workflows) |
| [Queue backlog or stuck execution](#queue-backlog-or-apparently-stuck-runs) |
| [Cluster mode checks](#cluster-mode-checks) |
| [Main unavailable](#main-instance-unavailable-while-workers-are-live) |
| [Webhook, MCP, Portal, or streaming failure](#webhook-mcp-portal-or-streaming-failures) |
| [Pod, container, or storage failure](#container-pod-oom-or-storage-issue) |
| [Bad deployment or configuration](#bad-deployment-or-configuration-regression) |
| [Model or integration failure](#model-credential-or-integration-failure) |
| [Sandbox failure](#sandbox-failure) |
| [Disaster recovery](#recovery-and-disaster-response) |

## Command setup

Work from the deployed checkout or deployment tooling. Select only the topology actually running in the affected environment. Do not use an example project to address a production incident.

### Docker Compose

Define this shell helper for the standard Compose installation:

```bash
heym_compose() { docker compose -f docker-compose.yml "$@"; }
HEYM_MAIN_SERVICE=backend
HEYM_FRONTEND_SERVICE=frontend
```

For the repository's cluster example, use this definition instead:

```bash
heym_compose() { docker compose -f docker-compose.cluster.yml "$@"; }
HEYM_MAIN_SERVICE=main
HEYM_WORKER_SERVICE=worker-a
```

For a standalone worker on its own host, use `docker compose -f docker-compose.worker.yml` and service `worker`. It has no local PostgreSQL or frontend service. Include the deployment's actual project name, override files, and environment file in the helper if it uses them.

```bash
heym_compose ps
heym_compose images
heym_compose logs --since 15m --tail 200 "$HEYM_MAIN_SERVICE"
docker stats --no-stream
```

The standard Compose stack publishes the frontend on host port `4017` and PostgreSQL on `6543` by default. Its backend port `10105` is internal. The cluster example publishes main's API on `10105`, worker-a's API on `10111`, and PostgreSQL on `6544`. A release image combines frontend and backend in one container. Verify port mappings with `ps`.

For a direct backend process check inside a Compose main container:

```bash
heym_compose exec -T "$HEYM_MAIN_SERVICE" uv run python -c \
  'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:10105/api/health", timeout=5).read().decode())'
```

### Kubernetes

Set the actual context, namespace, and workload names. These deployment names match the repository examples only.

```bash
HEYM_KUBE_CONTEXT='<actual-context>'
HEYM_NAMESPACE=heym
HEYM_MAIN_DEPLOYMENT=heym
HEYM_WORKER_DEPLOYMENT=heym-worker
kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_NAMESPACE" get deployments,pods,svc,pvc
kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_NAMESPACE" get events --sort-by=.lastTimestamp
kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_NAMESPACE" logs \
  "deployment/$HEYM_MAIN_DEPLOYMENT" --all-containers=true --since=15m --tail=200
```

The base deployment is one main replica with strategy `Recreate`, persistent storage, and a readiness probe on `/api/health`. Its public container port is `4017`; a backend-only worker uses `10105`. Do not assume a restart or rollout is free of downtime. See [Kubernetes Deployment behavior](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#recreate-deployment).

### Health and API access

```bash
HEYM_PUBLIC_URL='https://your-heym-host.example'
curl --fail --silent --show-error --connect-timeout 3 --max-time 10 \
  "$HEYM_PUBLIC_URL/api/health"
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  --connect-timeout 3 --max-time 10 "$HEYM_PUBLIC_URL/"
```

`/api/health` returns `status`, `service`, and `version`; it performs no dependency check. Confirm the database and an approved end-to-end workflow separately.

Authenticated examples below use a curl config file provisioned outside this repository at `$HEYM_CURL_CONFIG`, containing the operator's `Authorization` header. Restrict its permissions to the operator, keep it out of version control, and remove temporary copies after use. Do not paste tokens into commands, URLs, logs, or incident notes. Use an existing authenticated UI session when available. Inspect status codes and the deployed OpenAPI schema at backend `/docs` before retrying a failed mutation.

### SQL access and query limits

For the bundled Compose database, open a session with the database container's configured identity:

```bash
heym_compose exec postgres sh -c \
  'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

For an external database, use an approved `psql` service definition and password file or the database provider's console. A libpq connection uses `postgresql://`, not SQLAlchemy's `postgresql+asyncpg://`. Test from the affected application's network path as well as the DBA path.

Run diagnostic SQL with a read-only role where possible. At the start of each diagnostic session:

```sql
SET default_transaction_read_only = on;
SET statement_timeout = '5s';
SET lock_timeout = '1s';
SELECT now() AS observed_at, current_database(), pg_is_in_recovery();
```

Use the intended writable primary for application checks. A replica may answer `SELECT 1` while the write path is unavailable. `pg_stat_activity` detail may require database monitoring privileges; hidden rows or NULL fields are not proof of no activity. The diagnostic queries below omit payloads, secrets, and SQL text. They do not update Heym tables. See [PostgreSQL activity and visibility](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-PG-STAT-ACTIVITY-VIEW).

## Shared verification

After each mitigation, check public access, database responsiveness, one approved smoke workflow, and the relevant capacity/backlog metrics. Use a safe production-mode trigger when verifying cluster dispatch: editor test runs stay on the receiving instance. Watch at least 10 minutes, plus the next expected critical schedule or an agreed equivalent check. Record changes and arrange an owner/time to reverse temporary restrictions.

## UI or API down

**Severity:** P1 for widespread production unavailability; P2 for partial degradation.

**Diagnose**

1. Compare the public UI, public `/api/health`, and direct main backend check from [Command setup](#command-setup).
2. Inspect main/frontend container or pod state, recent errors, and CPU/memory/disk. A static UI loading does not prove the API works.
3. Run the [database check](#postgresql-down-or-not-writable). Inspect the last release and ingress/proxy changes.
4. If only authenticated requests fail, distinguish expired sessions/SSO from general API failure. Do not reset shared keys to test login.

**Mitigate**

1. Repair database or storage dependencies first when they explain the failure.
2. If the direct backend works, restore the frontend/proxy/ingress route. Ingress must target main in cluster mode.
3. If main is stuck and dependencies are healthy, follow [Service restart](#controlled-service-restart). Restore only the affected frontend service when that is the failed component.
4. For a release regression, follow [Bad deploy](#bad-deployment-or-configuration-regression).

**Verify:** Public UI loads, authenticated API access succeeds, and a smoke workflow completes. A green process endpoint alone is insufficient.

**Escalate:** Platform on-call for backend failure; networking/ingress owner when only the public path fails; database or storage owner when dependency checks fail.

## PostgreSQL down or not writable

**Severity:** P1 when production connections or writes fail; P2 for intermittent degradation.

**Diagnose**

For bundled PostgreSQL:

```bash
heym_compose ps postgres
heym_compose logs --since 15m --tail 150 postgres
heym_compose exec -T postgres sh -c \
  'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

1. `pg_isready` checks whether the server accepts connections. Confirm authenticated SQL access and primary status using [SQL access](#command-setup).
2. From the affected instance, check DNS, routing, database endpoint/port, TLS, and network policy. A local DBA connection does not establish application reachability.
3. Read the sanitized error: connection refused/timeout, authentication failure, connection exhaustion, read-only transaction, storage exhaustion, or migration failure.
4. Check database host disk/inodes, database logs, failover/replication state, and maintenance events. Use [Connections and locks](#active-db-connections-pool-saturation-and-locks) for saturation.

**Mitigate**

1. Reduce producer intake and retry storms. Pause offending automatic triggers through Heym if its API works; otherwise coordinate upstream traffic reduction. Avoid bulk reruns.
2. For a stopped bundled database with verified intact storage and no active failover/recovery operation, start only the existing service:

   ```bash
   heym_compose start postgres
   ```

3. For managed PostgreSQL, network failures, full disk, corruption, or failover, use the database owner's recovery procedure. Preserve the existing database volume and key material.
4. After the writable primary is reachable, allow pools/listeners to reconnect. Restart only an application instance that still fails after the DB path is healthy.
5. Never initialize a replacement empty database over an incident, delete WAL files, or run `docker compose down -v`. Restore follows [Disaster recovery](#recovery-and-disaster-response).

**Verify:** Application-path SQL works against the intended primary, normal application writes succeed via the smoke workflow, connection errors stop, heartbeats resume, and queue age decreases.

**Escalate:** Database on-call immediately for P1, primary/failover problems, data corruption, or exhausted storage. Send endpoint identity, timestamps, status/error class, and storage/connection evidence without credentials.

## Active DB connections, pool saturation, and locks

**Severity:** P1 if no useful work can connect; P2 if pressure or blocking is degrading execution.

**Diagnose**

Run this on the affected PostgreSQL server. The total is server-wide because other databases consume the same connection ceiling. `active` is executing a query; `idle` is connected without a current query. Both consume a slot. PostgreSQL reserves some slots, so ordinary clients may be refused before the total reaches `max_connections`.

```sql
SELECT current_setting('max_connections')::int AS max_connections,
       current_setting('superuser_reserved_connections')::int AS superuser_reserved,
       current_setting('reserved_connections', true) AS reserved_connections,
       count(*) FILTER (WHERE backend_type = 'client backend') AS client_connections,
       count(*) FILTER (WHERE backend_type = 'client backend'
                         AND state = 'active') AS active_connections,
       count(*) FILTER (WHERE backend_type = 'client backend'
                         AND state LIKE 'idle in transaction%') AS idle_in_transaction
FROM pg_stat_activity;

SELECT datname, application_name, usename, client_addr, state,
       wait_event_type, wait_event, count(*) AS connections
FROM pg_stat_activity
WHERE backend_type = 'client backend'
GROUP BY datname, application_name, usename, client_addr, state,
         wait_event_type, wait_event
ORDER BY connections DESC
LIMIT 50;
```

Heym tags pooled and listener connections `heym-<instance-id>`. Compare the connection group to instance heartbeats and the process count. An idle pool is expected. A growing `idle in transaction` population requires investigation.

```sql
SELECT pid, application_name, state,
       now() - xact_start AS transaction_age,
       CASE WHEN state = 'active' THEN now() - query_start END AS active_query_age,
       wait_event_type, wait_event, pg_blocking_pids(pid) AS blocking_pids
FROM pg_stat_activity
WHERE datname = current_database()
  AND backend_type = 'client backend'
  AND pid <> pg_backend_pid()
  AND (state = 'active' OR state LIKE 'idle in transaction%')
ORDER BY xact_start ASC NULLS LAST
LIMIT 30;
```

Distinguish server exhaustion (`too many clients`) from a local SQLAlchemy pool timeout. A local pool can saturate because requests hold connections or wait on locks even when the server has spare slots.

Budget the configured peak, including overflow and every uvicorn process:

```text
sum over instances:
  process_count * (async_pool_size + async_max_overflow
                   + sync_pool_size + sync_max_overflow + 4 listeners)
then add other clients, monitoring, and operational headroom
```

Defaults per process are `HEYM_DB_POOL_SIZE=10`, `HEYM_DB_MAX_OVERFLOW=20`, `HEYM_DB_SYNC_POOL_SIZE=5`, and `HEYM_DB_SYNC_MAX_OVERFLOW=10`. The standard backend entrypoint starts 8 processes: its theoretical peak is `8 * (10 + 20 + 5 + 10 + 4) = 392`, before other clients. Pools grow on demand; this is a ceiling, not the expected open count. The leader's dedicated session is held from the async pool. Four listener connections exist per process even on a single-instance install; chat streams share a listener.

Read actual settings from the deployed manifest. Example files override some defaults and process counts. Adding workers also adds pools and listeners; it can worsen DB pressure.

**Mitigate**

1. Throttle the identified workload/producers. Preserve a DBA access path and operational headroom.
2. Ask the database owner to inspect individual blockers/long transactions. Do not bulk-kill Heym sessions: listeners and the leader's advisory-lock session are essential coordination paths. Query cancellation and session termination have different effects; the DBA should target a confirmed culprit. See [PostgreSQL server signaling](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADMIN-SIGNAL).
3. If capacity requires it, reduce pool/overflow sizes or process count through the deployment configuration, then drain/recreate instances one at a time. Verify API load and executor capacity after the reduction. A pool change requires process replacement; `restart` does not apply changed Compose environment values.
4. `docker-compose.yml` does not forward the four pool variables explicitly. Add approved environment overrides in the actual deployment configuration rather than assuming a host `.env` entry reaches the container. Cluster and worker examples have their own mappings.
5. Coordinate any `max_connections` increase with the database owner and memory budget. Avoid simultaneous reconnects across the fleet.

**Verify:** Total client connections stabilize with headroom, pool errors stop, blocking clears, listener/heartbeat errors stop, and the smoke workflow succeeds.

**Escalate:** Database owner for blocker intervention or connection ceiling changes; platform owner for connection leaks, pool starvation, or repeated reconnect storms.

## Controlled service restart

**Severity:** Inherit the incident severity. Restarting main interrupts public service in the documented topology.

**Before restarting**

1. Confirm the target instance/service and capture logs, image digest, restart reason, and active/queued run IDs. Confirm PostgreSQL and storage are healthy.
2. Reduce new intake. For a worker, turn **On** off under **Settings > Instances** and wait for assigned queued work to move and claimed/active runs to finish. Disabling assignment does not immediately cancel existing work or remove leadership eligibility.
3. For main, plan an interruption and coordinate ingress/producer intake. Main cannot be disabled through the Instances toggle; main-only work can still target it at weight zero. Inspect all its active runs and claimed queue rows before proceeding.
4. Inspect `auto_recover_runs` and external side effects. Eligible interrupted recoverable runs can rerun from the beginning once, with the same execution ID. This is not checkpoint resume or exactly-once delivery. A successful HTTP cancellation request also is not proof a run has finished.

**Restart one service with unchanged configuration**

```bash
# Compose main. Use the existing topology helper.
heym_compose restart -t 60 "$HEYM_MAIN_SERVICE"
heym_compose ps "$HEYM_MAIN_SERVICE"
heym_compose logs --since 5m --tail 150 "$HEYM_MAIN_SERVICE"
```

For a drained cluster-example worker, substitute `$HEYM_WORKER_SERVICE`. The 60-second stop timeout is a limit, not a promise that long runs finish. Drain first and use an incident-approved timeout for remaining work. Do not use `./deploy.sh --restart` for a targeted incident restart; it restarts the whole Compose stack, including PostgreSQL.

```bash
# Kubernetes main. Recreate strategy can cause downtime.
kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_NAMESPACE" rollout restart \
  "deployment/$HEYM_MAIN_DEPLOYMENT"
kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_NAMESPACE" rollout status \
  "deployment/$HEYM_MAIN_DEPLOYMENT" --timeout=180s
```

Substitute `$HEYM_WORKER_DEPLOYMENT` for a drained worker. A Deployment with multiple worker replicas must have a unique stable Heym instance ID for each instance; do not scale the example's fixed-ID worker as if it already provides that.

When environment or image configuration changes, use the approved deployment/recreate path with a pinned image. A Compose restart alone does not pick up those changes. Main's entrypoint runs Alembic migrations before startup; workers should use their worker entrypoint, which skips migrations.

**Verify:** Process health, DB access, instance eligibility, and smoke workflow pass. Check interrupted executions in history, expected recovery, pending reviews, and queue age before re-enabling the worker or restoring intake.

**Escalate:** A single restart that does not restore service is evidence to investigate dependencies, load, or release state. Repeated restarts require platform/infrastructure review.

## Most resource-consuming workflows

**Severity:** P2 when shared capacity suffers; P1 if platform-wide critical work stops; otherwise P3 for owner follow-up.

**Diagnose**

1. Use **Analytics** for execution counts, failures, duration, and node-type trends. Use **Traces** for model calls/tokens/cost. Align the time window with the resource spike and compare with the previous baseline.
2. Use infrastructure CPU/memory charts and `docker stats --no-stream` or `kubectl top pods --containers` in the actual context/namespace. Include sibling sandbox containers/pods, not just the main backend. Kubernetes `top` requires metrics-server.
3. Use the SQL below for a precise recent history window. It covers recorded history, not every still-running execution; retention and recovery affect what is present. The UI and its snapshots may have different time buckets and visibility. Admin status does not make every UI metric instance-wide; database diagnostics require a separately authorized monitoring role.

Recent workflows ranked by total recorded elapsed duration:

```sql
SELECT h.workflow_id, w.name, w.owner_id,
       count(*) AS recorded_runs,
       count(*) FILTER (WHERE h.status IN ('error', 'failed', 'timeout')) AS failed_runs,
       round((sum(h.execution_time_ms) / 1000.0)::numeric, 1) AS total_elapsed_seconds,
       round((max(h.execution_time_ms) / 1000.0)::numeric, 1) AS max_elapsed_seconds
FROM execution_history h
JOIN workflows w ON w.id = h.workflow_id
WHERE h.started_at >= now() - interval '1 hour'
GROUP BY h.workflow_id, w.name, w.owner_id
ORDER BY total_elapsed_seconds DESC
LIMIT 20;
```

To identify high-volume workflows, rerun the same query with `ORDER BY recorded_runs DESC`. Repeat with a 24-hour window if needed after checking the query cost. Do not keep retrying a timed-out scan on an overloaded database.

Inspect live work separately:

```sql
SELECT a.execution_id, a.workflow_id, w.name,
       a.executed_by_instance_id, a.trigger_source,
       now() - a.started_at AS run_age,
       now() - a.heartbeat_at AS heartbeat_age,
       a.running_node_ids, a.attempt, a.recoverable, a.cancel_requested_at
FROM active_workflow_executions a
JOIN workflows w ON w.id = a.workflow_id
ORDER BY a.started_at
LIMIT 50;

SELECT t.workflow_id, w.name, count(*) AS trace_records,
       sum(coalesce(t.total_tokens, 0)) AS tokens
FROM llm_traces t
LEFT JOIN workflows w ON w.id = t.workflow_id
WHERE t.created_at >= now() - interval '1 hour'
GROUP BY t.workflow_id, w.name
ORDER BY tokens DESC
LIMIT 20;
```

NULL workflow IDs can represent chat or assistant activity. Trace records are not a universal model-call count. Coding-agent provider usage is not included in Heym's token/cost alert totals. Use **Traces** and its configured pricing for USD amounts; unpriced models are not free.

Total elapsed duration, token volume, and active count are load indicators. Heym does not persist per-workflow CPU seconds or peak RSS in these tables. Long elapsed time can mean waiting on a provider. Attribute CPU/memory by correlating run IDs, executing instance, node timing, sandbox identity, and infrastructure measurements. Do not label the first duration row the proven largest CPU or memory consumer.

**Mitigate**

1. Record the workflow/run IDs and owner. Contain the highest-impact producer: pause automatic triggers, reduce webhook traffic, or reduce schedule frequency/fan-out/retries with the owner.
2. An instance administrator who can access the workflow can pause its automatic triggers through the supported endpoint:

   ```bash
   HEYM_WORKFLOW_ID='<workflow-uuid>'
   curl --config "$HEYM_CURL_CONFIG" --fail --silent --show-error \
     --output /dev/null --connect-timeout 3 --max-time 30 --request POST \
     "$HEYM_PUBLIC_URL/api/workflows/$HEYM_WORKFLOW_ID/pause-triggers"
   ```

   Pausing automatic triggers does not stop already-running or already-queued work, and does not block explicit API/webhook, manual, Portal, MCP, or sub-workflow execution. Reduce those callers separately. It is not a global workflow kill switch.

3. Set workflow **Properties > Concurrency limit**, queue length, and wait bounds where appropriate. API rate limits control HTTP intake; they are not a replacement for concurrency controls across trigger types. A zero concurrency limit disables the limit. Editor test runs bypass production admission controls.
4. If an identified active run must stop, request cancellation using its exact execution ID:

   ```bash
   HEYM_EXECUTION_ID='<execution-uuid>'
   curl --config "$HEYM_CURL_CONFIG" --fail --silent --show-error \
     --connect-timeout 3 --max-time 30 --request POST \
     "$HEYM_PUBLIC_URL/api/workflows/$HEYM_WORKFLOW_ID/executions/$HEYM_EXECUTION_ID/cancel"
   ```

   Confirm final history state and registry removal. `cancel_requested` is asynchronous, and cancellation cannot undo external effects. A 404 can mean finished or inaccessible; inspect history. Cancellation is not a bulk purge of every `queued` or `claimed` row.

5. Add worker capacity only for distributable work and only after checking DB connection headroom. For pinned work, reduce load or size main appropriately.

**Verify:** Arrival rate drops, CPU/memory and connections recover, queued age decreases, and critical workflows succeed. Agree on the owner's correction before gradual re-enable. The matching administrator endpoint is `POST /api/workflows/{workflow_id}/resume-triggers`; record prior trigger state and check for any other pause reason before using it.

**Escalate:** Platform on-call if owner isolation does not restore capacity; workflow owner for loops/retries/fan-out; integration owner when provider latency is retaining many runs.

## Queue backlog or apparently stuck runs

**Severity:** P2 for growing backlog; P1 for platform-wide critical execution delay.

**Diagnose**

Run a snapshot of unfinished queue rows. The status filter includes older unfinished work, not only recent arrivals.

```sql
SELECT status, placement, target_instance_id, count(*) AS runs,
       min(enqueued_at) AS oldest_enqueued_at,
       max(now() - enqueued_at) AS oldest_age
FROM workflow_run_queue
WHERE status IN ('held', 'queued', 'waiting_for_main', 'claimed')
GROUP BY status, placement, target_instance_id
ORDER BY oldest_enqueued_at;

SELECT q.execution_id, q.workflow_id, w.name, q.status, q.placement,
       q.target_instance_id, q.enqueued_at, q.not_after, q.expires_at,
       q.claimed_at, a.heartbeat_at, a.cancel_requested_at
FROM workflow_run_queue q
JOIN workflows w ON w.id = q.workflow_id
LEFT JOIN active_workflow_executions a ON a.execution_id = q.execution_id
WHERE q.status IN ('held', 'queued', 'waiting_for_main', 'claimed')
ORDER BY q.enqueued_at
LIMIT 50;
```

| State | Interpretation | Action |
| --- | --- | --- |
| `held` | Waiting for the workflow's production concurrency slot | Inspect that workflow's running/pending work and its limit/wait bounds |
| `queued` | Assigned to an instance but not claimed | Inspect target liveness, eligibility, credential synchronization, DB capacity, and queue worker logs |
| `waiting_for_main` | Dispatch found no eligible target | Inspect placement and the candidate pool; this can also happen when distributable work has no eligible instance |
| `claimed` | A process took the run | Correlate active execution heartbeat, run nodes, and final history; age alone is not a stuck-run test |
| `skipped_late` | Not claimed before `not_after` | Reconcile missed work with owner before replay |
| `expired` | Concurrency wait exceeded its configured bound | Inspect admission pressure and `concurrency_max_wait_seconds` |
| `done` / `failed` / `cancelled` | Queue lifecycle ended | Inspect execution history and final outcome as applicable |

1. Correlate [Cluster checks](#cluster-mode-checks), [DB connections](#active-db-connections-pool-saturation-and-locks), and [Resource-heavy workflows](#most-resource-consuming-workflows).
2. Look for `Run queue worker loop failed`, queue listener failures, and `Run queue maintenance failed`. The queue worker also runs on single-instance installs for concurrency-queued work.
3. Inspect held runs alongside `workflow_concurrency_slots` and pending reviews through the UI. Do not delete slots because a run appears absent from one screen.

**Mitigate**

1. Reduce runaway arrivals first. Restore healthy eligible executors and repair DB/listener failures.
2. The leader moves unclaimed distributable rows away from unavailable/disabled/zero-weight/incompatible targets on its maintenance pass, normally about every 30 seconds. Main-only work needs main. Watch reassignment before manual intervention.
3. Queued/waiting rows past `not_after` become `skipped_late`. The `cron_misfire_grace_seconds` setting defaults to 600 seconds and reads `CRON_MISFIRE_GRACE_SECONDS` when provided to the process. Confirm environment forwarding in the deployment before changing it. Held concurrency rows use their own wait policy; increasing the cron grace is not a fix for a full concurrency queue.
4. A `claimed` row is retired as failed only when it has no active execution row and its claim is older than the 120-second grace. Recoverable orphan execution handling is separate: after a stale execution heartbeat, recovery can rerun from the beginning once when enabled. Do not reset queue state manually or bulk-replay while recovery is active.
5. For genuine capacity shortage, adjust eligible-instance shares or add capacity after checking DB and sandbox limits. Weights distribute queued runs, not reserved CPU or guaranteed simultaneous slots.

**Verify:** Both depth and oldest age fall, a newly submitted approved run is claimed and finishes, and critical schedules meet their expected timing. Inventory skipped/expired/failed work even if the current queue is empty.

**Escalate:** Platform owner when healthy eligible targets do not claim/reassign work; workflow owner for held/pending bottlenecks; DB owner for notification/connectivity failure.

## Cluster mode checks

**Severity:** P2 for partial loss of capacity; P1 when critical scheduling or execution stops.

**Diagnose**

1. Confirm `HEYM_CLUSTER_ENABLED=true` on participating instances, one intended main, worker roles, unique stable instance IDs, and the same database. Identical images alone do not establish compatibility.
2. Open **Settings > Instances** as an instance administrator, or request:

   ```bash
   curl --config "$HEYM_CURL_CONFIG" --fail --silent --show-error \
     --connect-timeout 3 --max-time 10 "$HEYM_PUBLIC_URL/api/admin/cluster"
   ```

3. Check `cluster_enabled`, `live`, `compatible`, `enabled`, `weight`, `credentials_synced`, heartbeat age, DB latency, and sandbox availability (`docker_ok` in the API). A live instance needs eligibility as well as liveness to receive distributed work. The historical `docker_ok` name also covers Kubernetes sandbox reachability.

```sql
SELECT id, name, role, enabled, weight, weight_configured,
       version, schema_revision, docker_ok, db_latency_ms,
       now() - heartbeat_at AS heartbeat_age,
       now() - credentials_synced_at AS credential_sync_age
FROM cluster_instances
ORDER BY role, id;

SELECT executed_by_instance_id, status, count(*) AS recorded_runs
FROM execution_history
WHERE started_at >= now() - interval '1 hour'
GROUP BY executed_by_instance_id, status
ORDER BY executed_by_instance_id, status;
```

The SQL heartbeat view is evidence, not a full compatibility calculation. Use the admin API for compatibility/key-rotation logic. Heartbeats run every 10 seconds and the liveness window is 30 seconds. The admin view also checks `heym-<instance-id>` DB connections when visible; if it cannot read that activity, it falls back to heartbeats.

4. Correlate leader logs across instances: `became the leader`, `still leader`, `lost leader status`, and eligibility errors. Leadership uses a PostgreSQL session advisory lock, checked roughly every 5 seconds. Main role and process leadership are independent. Do not infer the leader from the Instances role or generic advisory locks alone.
5. If workers are idle, inspect placement and queue state. File/Drive operations, plugins, Send Email, coding-agent workspaces, Agent skills, and dependent sub-workflows can pin a whole workflow to main. Code and Playwright can run on workers when their configuration has no main-only dependency. Streaming/editor work is not evidence of queued distribution.
6. For Kubernetes credential imports, check `credentials_synced` and the credential watcher/RBAC on each process. Process health can pass before synchronization completes.

**Mitigate**

1. Offline worker: restore process/DB reachability or leave it disabled until repaired. Observe queued reassignment.
2. Mismatch worker: align deployed version, schema expectations, shared `SECRET_KEY`, and compatible encryption key rings through the managed secret/deployment system. Never generate replacement keys during diagnosis. During intentional rotation, follow the [key rotation procedure](./security.md#rotating-the-key).
3. Zero-weight/disabled worker: restore its intended share only after confirming capacity and compatibility. Automatic weighting seeds a new instance once; an intentionally configured zero is not automatically overwritten. Weights are relative shares among eligible instances and need not total 100.
4. Scheduler stalled: repair DB/leader eligibility and inspect scheduler errors. A compatible worker can lead even when disabled or at weight zero. Drain state alone does not transfer scheduling responsibility.
5. Do not scale multiple public mains or round-robin ingress to workers to mask main loss. Restore main with its data or follow the approved disaster procedure.

**Verify:** Intended instances are live, compatible, synchronized, and enabled with meaningful shares; leader activity is visible; a safe production background run lands on an eligible worker; a main-only smoke run stays on main. Evaluate shares over enough queued runs, not a single sample.

**Escalate:** Platform owner for compatibility, placement, election, or dispatch problems; infrastructure/DB owners for host, network, or database faults.

## Main instance unavailable while workers are live

**Severity:** P1 when the production UI/API/MCP/Portal are unavailable.

**Diagnose:** Confirm main host/pod, persistent storage, and ingress state. Determine whether a compatible worker is leading and whether queued work is distributable or main-only.

**Mitigate**

1. Restore the original main and its storage, networking, keys, and stable instance identity. Use [Service restart](#controlled-service-restart) or [Infrastructure](#container-pod-oom-or-storage-issue) as appropriate.
2. Keep ingress pointing to main's intended service. A worker can serve HTTP but does not automatically have main's files, plugins, workspaces, or audit-log location.
3. Watch the main-only backlog and deadlines. Eligible work may continue on workers, but old queued rows can expire as `skipped_late` before main returns.
4. If the host or its data is lost, follow [Disaster recovery](#recovery-and-disaster-response). A role change alone is not main recovery.

**Verify:** Public surfaces, files/plugins, a main-only smoke workflow, worker dispatch, and scheduling recover. Reconcile skipped runs and any interrupted-run recovery.

**Escalate:** Incident lead, infrastructure/storage owner, and platform owner immediately. Give the estimated recovery time and any threatened business deadline.

## Webhook, MCP, Portal, or streaming failures

**Severity:** P1 for widespread critical intake failure; P2/P3 for a single workflow or client.

**Diagnose**

1. Separate public-route failure, authentication, admission controls, workflow execution, and downstream errors. Compare direct main and public checks.
2. For API workflows, inspect `/api/workflows/{workflow_id}/execute` and the workflow's configured HTTP method/body/authentication. Streaming uses `/execute/stream`. Test only the deployment's approved smoke endpoint with safe input.
3. Interpret `401/403` as authentication/access evidence, `429` as a possible rate/admission limit, and `202` as accepted queued work. Inspect response details before retrying. A queued response is not completion.
4. Status polling is `GET /api/workflows/{workflow_id}/executions/{execution_id}/status`. Use the same credential as the originating request. Anonymous status tokens belong in `X-Heym-Run-Token`, never a query parameter.
5. For SSE, compare proxy buffering/timeouts and client disconnects with final run history. A disconnected stream or an offloaded-result timeout does not prove the underlying run stopped.
6. For scheduled/event intake, check trigger activation and leader/consumer logs. For MCP/Portal, inspect that surface's auth/session and the target workflow independently.

**Mitigate:** Repair routing to main, correct the approved client configuration, or reduce a retry storm at the caller. For expected limits, honor backoff and poll accepted runs. For an execution failure, involve the workflow/dependency owner. Do not repeatedly replay a request with external side effects until run history and recovery state are known.

**Verify:** An approved request authenticates, receives the expected immediate or queued response, and reaches its expected final result. Confirm streaming clients also receive events where required.

**Escalate:** Networking owner for public-only/streaming failures; platform owner for intake/dispatch; workflow owner for node failures; identity owner for widespread authentication issues.

## Container, pod, OOM, or storage issue

**Severity:** P1 for main loss or shared storage failure; P2 for partial execution capacity loss.

**Diagnose**

```bash
# Compose container state and host filesystem pressure.
heym_compose ps
docker stats --no-stream
df -h
df -i
```

Check the actual data-volume filesystem and database host as well as the shell host. Read-only container state without environment values:

```bash
HEYM_CONTAINER_ID='<affected-container-id>'
docker inspect --format \
  '{{.Name}} status={{.State.Status}} oom={{.State.OOMKilled}} exit={{.State.ExitCode}} restarts={{.RestartCount}}' \
  "$HEYM_CONTAINER_ID"
```

```bash
HEYM_POD='<affected-pod>'
kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_NAMESPACE" describe pod "$HEYM_POD"
kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_NAMESPACE" logs "$HEYM_POD" \
  --all-containers=true --previous --tail=150
kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_NAMESPACE" top pods --containers
```

Inspect OOMKilled versus failed probes, image pull, Pending scheduling, node pressure, and volume attach/mount errors. Previous logs exist only when a prior container instance is available. Pod descriptions/logs can include sensitive application details; sanitize them before sharing.

**Mitigate**

1. For OOM, contain [resource-heavy work](#most-resource-consuming-workflows). Change resource limits through the deployment configuration when justified; increasing backend memory does not change a sandbox container's separate limit.
2. Repair node/quota/image/PVC problems with the infrastructure owner. Use a targeted restart only after capturing evidence and validating dependencies.
3. For disk pressure, identify database data/WAL, generated files, coding-agent workspaces, images, or logs. Use approved retention/storage expansion. Do not delete queue rows, PostgreSQL files, Drive data, workspace volumes, or run broad prune commands as incident cleanup.
4. For repeated restarts, move to dependency, workload, or release investigation. Avoid restart loops that destroy useful evidence and repeatedly trigger recovery.

**Verify:** Intended replica count is healthy, restarts stop, storage has operational headroom, and affected workflows complete with the expected persisted files.

**Escalate:** Infrastructure owner for scheduling/resources/runtime; storage and DB owner for data volume/disk issues; platform owner for recurring OOM or resource leaks.

## Bad deployment or configuration regression

**Severity:** Match impact, usually P1/P2.

**Diagnose:** Compare error start time to the rollout, actual image digests, configuration/secret references, and schema revision. Use deployment history and sanitized diffs. Do not dump full environment variables, Compose-rendered secrets, or Kubernetes Secret data into an incident.

```sql
SELECT version_num FROM alembic_version;
```

```bash
kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_NAMESPACE" rollout history \
  "deployment/$HEYM_MAIN_DEPLOYMENT"
```

**Mitigate**

1. Stop the rollout and reduce user impact. Identify the last known-good image/configuration in the deployment system; pin a version/digest rather than pulling `latest`.
2. Confirm with the release/database owners that the older application can read/write the current schema. Main's startup runs `alembic upgrade head`; an older image can fail against a newer revision. An application rollback does not undo schema changes.
3. If schema-compatible, restore the approved image/configuration using the deployment system. A Kubernetes rollback requires a reviewed revision, not an assumed previous one:

   ```bash
   HEYM_ROLLBACK_REVISION='<approved-revision-number>'
   kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_NAMESPACE" rollout undo \
     "deployment/$HEYM_MAIN_DEPLOYMENT" --to-revision="$HEYM_ROLLBACK_REVISION"
   kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_NAMESPACE" rollout status \
     "deployment/$HEYM_MAIN_DEPLOYMENT" --timeout=180s
   ```

4. Deployment rollback restores the pod template; it does not restore external Secret/ConfigMap content or persistent data. Restore those references/versions separately when they caused the regression.
5. For cluster upgrades, main goes first with the planned schema change; compatible workers rejoin as upgraded. Expect main load to rise while old workers are mismatched. During rollback, coordinate a compatible fleet and schema before restoring shares.
6. If rollback is schema-incompatible, use the release/database recovery plan. Do not run an ad hoc downgrade or replace the database under active workers.

**Verify:** Running version/configuration is the intended one, instance compatibility returns, errors/latency approach baseline, and critical workflows pass. Record any schema change that remains in place.

**Escalate:** Release owner and platform on-call; database owner before schema rollback/restore; incident lead if the safe rollback path is unavailable.

## Model, credential, or integration failure

**Severity:** P3 when isolated; P2/P1 when a critical shared dependency affects many workflows.

**Diagnose:** Compare an affected LLM/Agent/MCP/HTTP workflow with a safe workflow without that dependency. Inspect sanitized node errors and **Traces** for provider/model/credential identity, latency, 429/quota, 401/403, 5xx, and tool failures. Check key compatibility when only one instance fails. Check workers' outbound IP allowlists and shared `FRONTEND_URL` for generated-link failures.

**Mitigate**

1. Reduce producer/retry load for provider rate limits, timeouts, or quota exhaustion. Keep retries bounded.
2. Ask the credential owner to repair/rotate a credential through Heym or the managed secret source. Do not request secrets in chat or store them in URLs. Preserve shared encryption keys.
3. Use only an owner-approved alternative model/credential/integration that the workflow supports. Confirm output requirements, tool support, data handling, cost, and a safe result before restoring volume.
4. For imported Kubernetes credentials, repair watcher access/source ownership rather than trying to edit the read-only credential in Heym.

**Verify:** Affected node/tool calls succeed, downstream behavior matches expectations, latency/errors recover, and spend is consistent with the chosen provider/pricing.

**Escalate:** Credential/integration owner; platform owner for cross-instance decryption/session issues; provider support through the deployment's normal channel.

## Sandbox failure

**Severity:** P3 for one run; P2 when many Code, Playwright, skill, MCP stdio, or coding-agent runs fail.

**Diagnose**

1. Identify the executing instance and sandbox type from history/node errors. `docker_ok` indicates sandbox backend reachability, not successful execution of every sandbox.
2. Docker: inspect runtime access, image availability, sibling container resource limits, workspace mounts, and disk. Playwright step execution also needs adequate shared memory in the backend container; the repository Compose stack sets `2gb`.
3. Kubernetes: inspect sandbox pods in the configured sandbox namespace, their events/logs, image pulls, namespace quota, RBAC, PVC scheduling, and enforced NetworkPolicy. Sandboxes may use a separate namespace:

   ```bash
   HEYM_SANDBOX_NAMESPACE='<actual-sandbox-namespace>'
   kubectl --context "$HEYM_KUBE_CONTEXT" -n "$HEYM_SANDBOX_NAMESPACE" get pods \
     -l app.kubernetes.io/managed-by=heym -L heym.run/sandbox,heym.run/instance
   ```

4. Check the configured `HEYM_SANDBOX_BACKEND` and type-specific sandbox settings against the [Kubernetes deployment guide](../getting-started/kubernetes.md). Code/Playwright sandboxes can execute on workers; each worker needs its own working backend and applicable workspace/PVC access.

**Mitigate:** Restore the expected runtime, approved images, RBAC, storage, quota, or network path on the affected instance. Reduce resource-heavy intake. Keep isolation controls enabled; do not switch untrusted code to `subprocess`, expose the Docker API, or disable NetworkPolicy as a generic recovery step. Avoid deleting managed sandbox pods indiscriminately while runs or the janitor still own them.

**Verify:** A safe affected node completes with expected output/file behavior on the repaired instance, and sandbox resources are cleaned up normally. Verify a worker separately when the failure affected worker execution.

**Escalate:** Infrastructure/runtime owner for Docker/Kubernetes/PVC/RBAC; platform owner for sandbox implementation or cleanup failures.

## Recovery and disaster response

**Severity:** P1 when data loss or recovery beyond the deployment objective is possible.

**Diagnose:** Establish whether the loss concerns compute, PostgreSQL, main's files/workspaces, or multiple components. Record the last usable database backup/PITR point, file snapshot, key versions, application image, and schema revision. Confirm the deployment's RTO/RPO from L0; this repository does not supply a universal backup schedule or cross-site failover procedure.

**Recover**

1. Incident lead and database/storage owners choose the restore point and document possible lost writes and external effects.
2. Fence the old environment and stop application writers, workers, triggers, and inbound producers before a database restore or main replacement. Prevent old and new installations from both processing the same workload.
3. Restore PostgreSQL through its tested backup/PITR procedure into the intended recovery environment. Restore main's matching file/plugin/coding-workspace data and the required encryption key ring and signing secret from secure backup. A database-only backup does not contain file bytes.
4. Start a single intended main using a release compatible with the restored schema. Inspect migrations before startup because the main entrypoint runs them. Workers must not race migrations.
5. Keep production ingress and producers fenced during checks. A started main can elect a leader and run restored schedules/recovery; use the recovery environment's documented network restrictions and workflow trigger/recovery controls before startup. Restoring data is not a passive preview.
6. Reconcile active/queued/pending records and any automatic rerun with owners. Recovery restarts eligible runs from the beginning and cannot undo downstream effects. Do not replay every failed or skipped row.
7. Validate DB reads/writes, login, credential decryption, Drive files, plugins, coding-agent workspace access, and approved main-only/distributable smoke workflows. Add compatible workers gradually, then reopen intake and ingress.
8. Record actual data-loss interval, recovery duration, skipped work, and outstanding reconciliation. Arrange another restore test if this procedure exposed a gap.

**Verify:** The shared verification gate passes, critical schedules resume, owners accept reconciliation, and backup/restore monitoring is restored. A healthy empty installation is not recovery.

**Escalate:** Incident lead plus database, storage, and platform owners throughout. Do not improvise destructive data-directory repair or dual-site activation.

## Evidence and handoff template

```text
Incident / severity / environment:
Impact and first observed time (UTC):
Main / worker / database / deployment identifiers:
Last release or configuration change:
Affected workflow IDs and execution IDs:
Public health / direct health / DB check:
Connection totals, blocker PIDs, queue depth and oldest age:
Instance eligibility, leader evidence, CPU / memory / disk:
Action taken, timestamp, operator, expected effect:
Verification result and observation window:
Temporary restrictions, reversal owner, expiry:
Skipped / failed / recovered work requiring reconciliation:
Next action, owner, next update time:
```

Capture bounded logs and IDs; remove credential values, auth headers, capability links, user payloads, and SQL parameter data before attaching evidence. Router audit events are on main's stdout. Execution history records the executing instance; execution faults can therefore require logs from workers as well as main.

## Implementation references

These paths identify the implementation checked while writing this runbook. Revalidate them when execution, deployment, or schema behavior changes.

| Subject | Source |
| --- | --- |
| Health and startup services | [main.py](https://github.com/heymrun/heym/blob/main/backend/app/main.py) |
| Pool settings and connection tags | [config.py](https://github.com/heymrun/heym/blob/main/backend/app/config.py), [session.py](https://github.com/heymrun/heym/blob/main/backend/app/db/session.py) |
| Process count and migrations | [backend entrypoint](https://github.com/heymrun/heym/blob/main/backend/entrypoint.sh), [release entrypoint](https://github.com/heymrun/heym/blob/main/docker/release-entrypoint.sh) |
| Deployment topology and actual environment mappings | [Compose](https://github.com/heymrun/heym/blob/main/docker-compose.yml), [cluster example](https://github.com/heymrun/heym/blob/main/docker-compose.cluster.yml), [worker example](https://github.com/heymrun/heym/blob/main/docker-compose.worker.yml), [Kubernetes](../getting-started/kubernetes.md) |
| Registry eligibility and liveness | [registry.py](https://github.com/heymrun/heym/blob/main/backend/app/services/cluster/registry.py), [cluster API](https://github.com/heymrun/heym/blob/main/backend/app/api/admin_cluster.py) |
| Placement, queue states, and dispatch | [node_placement.py](https://github.com/heymrun/heym/blob/main/backend/app/services/cluster/node_placement.py), [run_queue.py](https://github.com/heymrun/heym/blob/main/backend/app/services/cluster/run_queue.py), [dispatch.py](https://github.com/heymrun/heym/blob/main/backend/app/services/cluster/dispatch.py) |
| Leadership and maintenance | [distributed_lock.py](https://github.com/heymrun/heym/blob/main/backend/app/services/distributed_lock.py), [cron_scheduler.py](https://github.com/heymrun/heym/blob/main/backend/app/services/cron_scheduler.py) |
| Recovery and cancellation | [execution_recovery.py](https://github.com/heymrun/heym/blob/main/backend/app/services/execution_recovery.py), [execution_cancellation.py](https://github.com/heymrun/heym/blob/main/backend/app/services/execution_cancellation.py) |
| Workflow pause/resume/cancel endpoints | [workflows.py](https://github.com/heymrun/heym/blob/main/backend/app/api/workflows.py), [workflow_lifecycle.py](https://github.com/heymrun/heym/blob/main/backend/app/services/workflow_lifecycle.py) |
| Diagnostic table and column definitions | [models.py](https://github.com/heymrun/heym/blob/main/backend/app/db/models.py) |
| Capacity and cost interpretation | [Analytics](../tabs/analytics-tab.md), [Traces](../tabs/traces-tab.md), [Alerts](../tabs/alerts-tab.md) |
