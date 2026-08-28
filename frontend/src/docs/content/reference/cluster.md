# Load Distribution

Point a second Heym instance at the same PostgreSQL database and it joins as a worker. Background workflow runs are then shared between the instances by a percentage you set, so the machine serving the UI and the API is not also the only machine running every workflow.

The instances never talk to each other. Postgres carries the work, so a worker needs no open port, no certificate, and no route back to the main instance — only database access.

## Roles

One instance is **main**, pinned by an environment variable. It serves the UI, the API, MCP and the chat portal, and it owns file storage and installed plugins. Every other instance is a **worker**: it reaches only the database and executes background runs.

```
HEYM_CLUSTER_ENABLED=true
HEYM_INSTANCE_ROLE=main       # or: worker
HEYM_INSTANCE_NAME=EU Main    # display label, editable later from Settings
HEYM_INSTANCE_ID=eu-main      # optional; derived from the name when empty
```

The main role is separate from leader election. Heym already elects one leader across the cluster to own cron, alert evaluation and crash recovery; if main goes down, leadership moves to a worker within a few seconds and scheduled runs keep firing. The main role does not move, because file storage cannot move with it.

## What can leave the main instance

Placement is decided from the workflow's nodes before the run starts. A run stays on main when any node in it — including nodes inside sub-workflows it calls — touches something that only exists on one machine:

| Node | Why it stays on main |
|---|---|
| Codex, OpenCode Go | The coding-agent workspace stays on local disk so a follow-up can resume in it |
| Agent with a skill attached | Skill code reads and writes Heym Drive |
| Drive, Converter, Google Drive | They read and write generated files |
| File Upload trigger | The upload lands on main's disk |
| Send Email | Corporate SMTP relays commonly allowlist one source address |
| Plugin nodes | A plugin is installed on one instance's disk |

**Everything else is distributed** — including the Code node, Playwright and Agent Python tools. Every instance runs the same image with its own Docker socket, so a sandbox is not a reason to keep a run on main, and those are the most CPU-hungry nodes in the product.

A workflow whose sub-workflow is chosen by an expression cannot be inspected ahead of time, so it stays on main.

## Choosing percentages

Weights are integers set under **Settings → Instances**. They are **shares of whichever instances can currently take work**, not percentages of 100: the scheduler divides by that pool's own total.

That distinction shows up as soon as one instance drops out. With `Main 41, Worker A 26, Worker B 33`, turning Worker B off leaves a pool of 67, so Main really receives 41/67 = **61%** and Worker A 26/67 = **39%**. The panel prints the effective split under the table for exactly this reason, and saving is never blocked because the numbers do not add to 100 — only a split where no enabled instance has a weight is refused.

Two more things are easy to get wrong.

**A percentage is not a share of machine power.** It only covers runs that go through the queue. Serving the UI and the API, streaming editor and portal runs, and handling file uploads are all main's work and none of it is counted. Main is doing more than its number says.

**Main's percentage is a ceiling, not a floor.** Runs that can only execute on main are charged against its quota, so once that quota is spent the remaining distributable runs fall to the workers. Setting main's number low is safe — work that must run there still does. Setting it high starves the workers.

So with a strong main and a smaller worker, start nearer 60/40 than the machines' raw ratio, then compare real run durations in the Traces tab and adjust.

Weights are renormalized across the instances that are currently live and enabled. With `main=70, A=15, B=15`, if A goes offline the split becomes 70/85 and 15/85 between main and B, and returns to 70/15/15 when A comes back.

### A new instance joins at zero

An instance that has never been given a weight starts at 0, which would leave it Live, Enabled and receiving nothing. **Give new instances a share automatically** — on by default, under the instances table — fixes that: on the leader's next pass the newcomer is given an equal share of the pool, and the existing weights are scaled down keeping their ratios to each other, so a deliberate 70/30 still reads as roughly 70/30 afterwards. The total stays exactly 100.

This runs **once per instance**. Both the automatic pass and your own edit mark the instance as configured, so an instance you set yourself is never changed behind your back — including one you deliberately set to 0. Turn the setting off if you would rather every new machine wait for you.

Only enabled, live and compatible instances take part. Handing a share to a machine that cannot execute anything would strand that share.

### When percentages cannot help

The settings panel reports how many of the last 24 hours' runs could only execute on main. If that number is high — a Codex-heavy or Drive-heavy workload — the workers will sit idle whatever the weights say, and the answer is a bigger main instance rather than more of them.

## Sizing PostgreSQL for a cluster

Connections scale with instances, not just users. Each instance runs several uvicorn processes, and each process holds a connection pool plus three `LISTEN` connections (cancellation, queue wake-ups, run results). A three-instance cluster on the default `max_connections = 100` runs out, and Heym then fails to reach its own database.

Budget roughly `instances x processes x (async pool + sync pool + 3)` and set `max_connections` above it.

Shrink the pools rather than only raising the ceiling. A single deployment defaults to 10+20 async and 5+10 sync connections per process, which is generous for one machine and far too much for a cluster:

| Variable | Single instance | Cluster |
|---|---|---|
| `HEYM_DB_POOL_SIZE` | 10 | 3 |
| `HEYM_DB_MAX_OVERFLOW` | 20 | 5 |
| `HEYM_DB_SYNC_POOL_SIZE` | 5 | 2 |
| `HEYM_DB_SYNC_MAX_OVERFLOW` | 10 | 3 |

The example compose file sets those and `max_connections = 300`. That takes a two-instance cluster from a 768-connection ceiling down to 192, with three instances still under 300.

## Requirements the cluster cannot enforce for you

**Every instance must use the same `SECRET_KEY` and `ENCRYPTION_KEY`.** A worker with a different `ENCRYPTION_KEY` cannot decrypt credentials, and every credential-using run would fail with an error naming nothing useful. Heym compares a digest of both keys on each heartbeat, along with the app version and the database revision, and marks a mismatched instance **Mismatch** so it receives no work at all. Load falls back to main until you fix it.

That also defines the upgrade order. Upgrading main first marks every worker incompatible; work returns to main, and each worker rejoins as it is upgraded. Slower, visible, and reversible.

**Point ingress at the main instance only.** Round-robining user traffic across instances would send a file upload to one machine and its download to another. Nothing in the code prevents this, because a worker runs the same image and will answer any request it receives.

**Worker instances have a different outbound IP.** Any API that allowlists source addresses sees the new one. Send Email runs on main for exactly this reason; for the HTTP node, either give the cluster a single NAT egress address or allowlist every instance.

## Adding a worker on another machine

`docker-compose.worker.yml` in the repository root runs a worker on its own host. It has no database and no UI: it reaches the main instance's PostgreSQL and takes its share of the background runs.

Fill in a `.env` beside it - image tag, database host and credentials, both keys, and an instance id - and start it. Compose refuses to start until every required value is set, rather than coming up with a placeholder that fails later in a way that is hard to read.

The image tag must be the version main runs, and both keys must be copied exactly. A difference in either shows the worker as Mismatch and it receives no work.

## Reading the Instances table

| Column | Meaning |
|---|---|
| Name | Editable label; it is stamped onto every run this instance executes |
| Role | `main` or `worker`, from the environment |
| Status | **Live** with a fresh heartbeat, **Offline** after 30 seconds of silence, **Mismatch** when the version, database revision or keys differ from main's |
| ms | Round trip from that instance to the database, measured by the instance itself |
| On | Take a worker out of rotation without stopping it — running executions finish, no new ones are assigned. Locked on for the main instance: file, plugin and coding-agent work runs there whatever the toggle says |
| Weight | Its share of distributable runs |

## Run history

Every run in the execution history names the instance that executed it, and both history dialogs can filter down to one instance. The filter matches on the instance's id while showing its name, so renaming an instance does not rewrite what old runs say.

Nothing about this appears on a single-instance install: the fields are empty, no label is shown, and no filter is offered.

## Failure behavior

**If a worker dies mid-run**, its heartbeat goes stale and the leader's existing recovery sweep re-runs the execution on a live instance. The queue row it had claimed is retired separately: once no active execution exists for it and a two-minute grace has passed, the leader fails the row and wakes whoever was waiting on the result. Age alone is never the trigger, so a legitimately long run is left alone; and the row is failed rather than requeued, because recovery already owns the rerun and requeueing would run the same workflow twice.

**If main goes down**, cron keeps firing from a worker and distributable runs keep executing. Runs that need main queue up and wait, and drain when it returns — but only within the misfire grace window (`HEYM_CRON_MISFIRE_GRACE_SECONDS`, 600 seconds by default). Anything older is closed as skipped, with the reason recorded, rather than replaying hours of backlog at once.

The UI, the API, MCP and the editor are unavailable while main is down, because ingress points there.

## Related

- [Running & Deployment](../getting-started/running-and-deployment.md) – Deploy a single instance first; the environment variables and key setup live there
- [Settings](./user-settings.md) – The Instances tab, and who can see it
- [Traces](../tabs/traces-tab.md) – Compare real run durations between instances before changing the split
- [Security](./security.md) – Why every instance must share `SECRET_KEY` and `ENCRYPTION_KEY`
