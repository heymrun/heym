# Heym Incident Playbook (L0)

Use this playbook to confirm a Heym incident, assess user impact, choose a severity, and reach the right recovery procedure and owner.

Detailed procedures: [Heym Runbook (L1)](./operations-runbook.md)

Last reviewed: 2026-11-10. Scope: self-hosted Heym, single instance or cluster, on Docker Compose or Kubernetes.

## Deployment handover

Fill in this table for each environment before using these documents on call. Names, URLs, capacity targets, and recovery objectives are deployment-specific. Repository examples are not a production inventory.

| Item | Deployment value |
| --- | --- |
| Environment and public Heym URL | `<environment>`, `<public-url>` |
| Platform on-call and backup | `<rotation-or-contact>`, `<backup-contact>` |
| Incident channel and incident tracker | `<channel>`, `<tracker-url>` |
| Database on-call and database identifier | `<contact>`, `<database-id>` |
| Infrastructure, networking, and storage owners | `<contacts>` |
| Release owner and deployment system | `<contact>`, `<deployment-url>` |
| Application errors, latency, and availability dashboard | `<dashboard-url>` |
| Host or pod CPU, memory, disk, and restart dashboard | `<dashboard-url>` |
| PostgreSQL connections, locks, disk, and replication dashboard | `<dashboard-url>` |
| Logs and optional OTel trace backend | `<logs-url>`, `<trace-url-or-disabled>` |
| Compose project/files or Kubernetes context/namespace | `<exact-target>` |
| Main, workers, database, and storage locations | `<services-or-deployments>`, `<storage-ids>` |
| Approved smoke workflow and expected result | `<workflow-id>`, `<safe-input>`, `<expected-result>` |
| Database and file backup procedure, latest restore test | `<procedure-url>`, `<test-date>` |
| Recovery time and recovery point objectives | `<RTO>`, `<RPO>` |

Keep contacts and dashboard links in the deployment's restricted operational copy. Evidence should contain IDs, timestamps, counts, and sanitized errors rather than credentials or workflow payloads.

## Platform inventory

| Component | Responsibility | Incident implication |
| --- | --- | --- |
| Frontend and main backend | UI, API, MCP, Portal, interactive execution | Check the public route and the main process separately |
| PostgreSQL | Application state, execution registry, run queue, concurrency slots, coordination, and notifications | A database outage can stop both request handling and background execution |
| Worker instances, when cluster mode is enabled | Eligible queued background runs | Healthy workers do not replace main's public endpoints |
| Elected leader process | Cron, alert evaluation, background coordination | A compatible worker can become leader; this does not change its role to main |
| Main's persistent storage | Drive files, installed plugins, and coding-agent workspaces | Recover the storage with main; routing ingress to a worker does not recover it |
| Sandbox backend on each executing instance | Docker containers or Kubernetes pods for isolated execution | A failed sandbox backend can affect selected nodes while the UI works |
| Workflow dependencies | Model providers, MCP servers, external APIs, data stores, and messaging services | Determine whether one dependency or the whole platform is failing |
| Optional OTel collector | Exported workflow, node, and Agent tool spans | Missing exported traces alone do not prove execution failed |

Heym's built-in run queue uses PostgreSQL. Redis, RabbitMQ, and vector stores can be workflow dependencies; they are not mandatory services for the built-in queue.

`GET /api/health` reports process health and version only. It does not test PostgreSQL, the queue, leader election, sandbox capacity, or credential synchronization. A green response is one check, not an end-to-end readiness guarantee.

## First five minutes

| Step | Action | Decision or evidence |
| --- | --- | --- |
| 1 | Acknowledge the alert and verify environment, service, and start time | Record UTC timestamps and the most recent release/configuration change |
| 2 | Check the public UI and `/api/health`, then the direct main backend | Public failure with a healthy direct backend suggests routing or frontend trouble |
| 3 | Check PostgreSQL connectivity and connection pressure | Route database failures to L1 before restarting application services |
| 4 | Check container/pod state, CPU, memory, storage, and recent errors | Separate infrastructure failure, load, and workflow-specific failure |
| 5 | In cluster mode, check **Settings > Instances**, queue states, and leader evidence | Identify main loss, offline/mismatched workers, or main-only work |
| 6 | Assign severity and start one mitigation from the routing table | For P1/P2, open an incident and involve the relevant owner immediately |
| 7 | Verify a safe production-mode workflow run and watch recovery | Confirm queue age, errors, and resources improve; set the next update time |

If a release coincides with the failure, inspect [Bad deploy or configuration regression](./operations-runbook.md#bad-deployment-or-configuration-regression). Check schema compatibility before rollback.

## Severity and response

These are starting response targets. Apply the deployment's incident policy and business impact when it is stricter.

| Severity | Examples | Response |
| --- | --- | --- |
| P1 | Main unavailable to all users; database unavailable or writes failing; widespread execution failure; critical intake unavailable across workflows | Immediate mitigation, incident record, platform and dependency on-call |
| P2 | Growing backlog; lost worker capacity; connection exhaustion approaching; one workflow degrading shared capacity; repeated OOM | Start mitigation immediately, target containment within 15 minutes, incident record |
| P3 | Isolated workflow/provider failure; limited impact with healthy platform capacity | Workflow or dependency owner, tracked follow-up and on-call note |
| P4 | Informational signal, expected capacity trend, verified false positive | Acknowledge, document, and tune monitoring if needed |

## Signal to L1 routing

Use these relative anchors when configuring alert links. Where a monitoring service needs an absolute URL, prefix the location of your hosted operational copy.

| Signal | Start here |
| --- | --- |
| UI/API unavailable, public 5xx, process health failure | [UI or API down](./operations-runbook.md#ui-or-api-down) |
| PostgreSQL unreachable, connection refused, write failure | [Database down](./operations-runbook.md#postgresql-down-or-not-writable) |
| Too many clients, pool timeout, lock waits, active connection spike | [Database connections and locks](./operations-runbook.md#active-db-connections-pool-saturation-and-locks) |
| Controlled backend/worker restart required | [Service restart](./operations-runbook.md#controlled-service-restart) |
| Execution count, total duration, tokens, CPU, or memory spike | [Most resource-consuming workflows](./operations-runbook.md#most-resource-consuming-workflows) |
| Growing queue, runs waiting or apparently stuck | [Queue backlog](./operations-runbook.md#queue-backlog-or-apparently-stuck-runs) |
| Offline/Mismatch instance, worker idle, scheduler or distribution issue | [Cluster checks](./operations-runbook.md#cluster-mode-checks) |
| Main lost while workers remain healthy | [Main instance unavailable](./operations-runbook.md#main-instance-unavailable-while-workers-are-live) |
| Webhook errors, MCP/Portal failures, SSE disconnects | [Ingress and execution endpoints](./operations-runbook.md#webhook-mcp-portal-or-streaming-failures) |
| OOM, CrashLoop, Pending, disk full, persistent-volume failure | [Container, pod, or storage issue](./operations-runbook.md#container-pod-oom-or-storage-issue) |
| Error increase after image, environment, or schema change | [Bad deploy](./operations-runbook.md#bad-deployment-or-configuration-regression) |
| Agent/LLM/MCP provider errors, 429, credential failure | [Model or integration failure](./operations-runbook.md#model-credential-or-integration-failure) |
| Code/Playwright/skill/coding-agent sandbox failures | [Sandbox failure](./operations-runbook.md#sandbox-failure) |
| Recovery cannot meet objectives; database or files lost | [Recovery and disaster response](./operations-runbook.md#recovery-and-disaster-response) |

## Escalation

| Finding | Bring in | Supply |
| --- | --- | --- |
| Multiple surfaces or workflows affected | Platform on-call and incident lead | Environment, scope, start time, mitigation, next update |
| Database unavailable, saturated, locked, or out of disk | Database on-call | Database ID, connection counts, blocker PIDs, sanitized errors, storage state |
| Pod/node failure, storage attachment, sandbox capacity | Infrastructure/storage owner | Context, namespace, workload, pod events, resource pressure |
| Public route fails while direct backend works | Networking/ingress owner | Affected routes, status codes, latency, backend comparison |
| Single workflow dominates load or fails alone | Workflow owner | Workflow/run IDs, trigger source, rate, time window, temporary limits |
| Correlated deployment/configuration change | Release owner | Running image digest, rollout time, schema revision, last known-good release |
| Provider quota/authentication/availability | Credential or integration owner | Provider, model/service, status code, request ID if safe; no secret values |

If P1/P2 impact persists after the first mitigation, escalate immediately with the evidence already collected. Do not wait for a complete root cause.

## Failure expectations

| Failure | What may continue | First action |
| --- | --- | --- |
| PostgreSQL unavailable | Static frontend may still load | Restore the database path; do not restart every application instance |
| Main unavailable, workers healthy | Eligible background work and scheduling may continue if a compatible worker leads | Restore main with its persistent storage; public UI/API/MCP/Portal remain unavailable |
| Worker unavailable | Other eligible instances take queued work as it is reassigned | Check placement, spare capacity, and recovery before adding traffic |
| Interrupted run | Eligible recoverable runs may restart from the beginning, once | Check automatic recovery and external side effects before manual replay |
| Main-only workload overload | Workers may stay idle | Reduce offending intake or increase main capacity; weight changes cannot move pinned work |
| Internal alerting unavailable | External uptime/DB/infra monitoring may still work | Use monitoring outside Heym; Heym alerts depend on the same DB and scheduler |
| Sandbox or provider unavailable | Workflows without that dependency may work | Contain affected workflows and repair the dependency |

## Recovery and incident closure

1. Verify public access, database access, intended instance eligibility, and a safe production-mode smoke workflow. An editor test does not prove worker dispatch.
2. Observe at least 10 minutes of stable errors, latency, resource use, and decreasing queue age. Also observe the next expected critical schedule or an agreed equivalent smoke check.
3. Reconcile failed, recovered, skipped, expired, and pending runs with workflow owners. Check external side effects before replaying anything.
4. Restore temporary trigger pauses, limits, and worker weights gradually. Give every remaining restriction an owner and expiry time.
5. Update the incident with impact, UTC timeline, actions, evidence, and outstanding risks. Assign a root cause review for P1/P2 and update both documents if a procedure was missing.

## Related operating references

- [L1 command setup and checks](./operations-runbook.md#command-setup)
- [Running and deployment](../getting-started/running-and-deployment.md)
- [Load distribution](./cluster.md)
- [Kubernetes deployment](../getting-started/kubernetes.md)
- [Security and key rotation](./security.md)
