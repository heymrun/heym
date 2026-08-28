# Multi-Instance Load Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Implemented on `impl/worker-mode`, 2026-08-27. All 13 tasks complete;
`./check.sh` passes lint, typecheck and 3734/3737 backend tests (the 3 failures in
`test_mcp_stdio_sandbox.py` predate this work and come from the local `.env`).

Deviations from the plan as written, all made after reading the call sites:

- Task 7 grew a result hand-back (`run_result_bus`, `wait_for_result`). Every
  trigger uses the run's result, so returning `None` for an offloaded run would
  have left bots and API callers with nothing.
- The claiming instance writes `ExecutionHistory` itself (`cluster/run_history.py`).
  `ExecutionResult` holds `NodeResult`, `SubWorkflowExecution` and `Future`
  fields that cannot cross a process boundary, so it cannot travel through the
  queue.
- The claim worker calls `register_execution`, or an offloaded run would be
  invisible to the cancel bus and to orphan recovery.
- A `test_run` never leaves its instance. Not in the plan; added with a test.
- Migration 118 is `118_add_run_instance_attr`: `alembic_version.version_num` is
  `varchar(32)` and the planned name was longer.
- Task 12 covers the single-instance guard rather than the admin panel, which is
  gated on `HEYM_ADMIN_EMAILS` that the E2E harness does not set.
- Task 13 Step 8 needed no change: `e2e/support.ts` derives the seeded release id
  from the registry.

Still open: the two manual verification steps below have not been run.

**Goal:** Let two or more Heym instances share one Postgres database and split background workflow execution between them by an operator-configured percentage.

**Architecture:** Postgres is the only channel between instances — they never open HTTP to each other and no broker is added. A run's placement is decided statically from its node types: work touching local disk, a resumable coding-agent workspace, or a per-instance install stays on the main instance; everything else is enqueued in `workflow_run_queue` for a weighted-selected instance and claimed with `FOR UPDATE SKIP LOCKED`. Leader election, cron slot claiming, and orphan recovery already exist and are reused unchanged.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 async + Alembic + Postgres `LISTEN/NOTIFY` and advisory locks; Vue 3 `<script setup>` + TypeScript strict + Tailwind.

**Design doc:** `docs/superpowers/specs/2026-08-27-multi-instance-load-distribution-design.md`

---

## Background an implementer needs

Read these before starting. They are load-bearing and not obvious.

**An instance is 8 processes.** `docker/release-entrypoint.sh:7` starts uvicorn with `BACKEND_WORKERS=8`. Everything in this plan that says "instance" means one machine with 8 Python processes sharing one identity, one `FILE_STORAGE_DIR`, and one row in `cluster_instances`. Never derive instance identity from `os.getpid()` — `services/distributed_lock.py:21` does exactly that for a *different* purpose (per-process worker id) and must not be reused here.

**Leader is not main.** `services/distributed_lock.py` elects one leader across the whole cluster with `pg_advisory_lock`. The leader owns cron, alerts, and execution recovery, and moves to a worker if main dies. "Main" is a separate, env-pinned role that owns file storage and ingress and never moves. Do not conflate them.

**Two execution entry points.** `execute_workflow()` (blocking, returns a dict) is distributable. `execute_workflow_streaming()` (generator, writes SSE to the caller's response) is not, and none of its call sites are touched by this plan.

**Never put decrypted credentials in the queue.** Queue rows carry `credentials_owner_id`; the executing instance calls `get_credentials_context(db, credentials_owner_id)` itself. Writing a resolved context into a row would put plaintext secrets in the database.

**Running the test suite.** From `backend/`:
```bash
SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_file.py -v
```
`HEYM_OTEL_ENABLED=false` is required — a `.env` with OTel on and no collector makes the suite hang forever.

---

## File structure

**Backend — new module `app/services/cluster/`:**

| File | Responsibility |
|---|---|
| `node_placement.py` | Pure: node type / node data -> `Placement`; whole-graph resolution with recursion |
| `identity.py` | Pure: this process's instance id, name, role, and compatibility fingerprint |
| `registry.py` | `cluster_instances` reads and the heartbeat upsert loop |
| `weights.py` | Pure: renormalize live weights, pick a winner by deficit |
| `run_queue.py` | Enqueue, claim, complete, expire |
| `run_queue_bus.py` | `LISTEN/NOTIFY` wake-ups, mirroring `execution_cancel_bus.py` |
| `dispatch.py` | The seam: run in-process or enqueue, then wait for the result |

**Backend — modified:** `app/config.py`, `app/db/models.py`, `app/api/deps.py` (nothing), `app/api/admin_cluster.py` (new router), `app/main.py`, and the eleven dispatch call sites listed in Task 7.

**Frontend — new:** `src/services/cluster.ts`, `src/types/cluster.ts`, `src/components/Layout/settings/ClusterSettingsTab.vue`, `src/components/Layout/settings/ClusterInstanceRow.vue`, `src/features/release-tour/components/visuals/ClusterInstancesTourVisual.vue`.

**Frontend — modified:** `src/components/Layout/UserSettingsDialog.vue`, `src/components/Panels/ExecutionHistoryDialog.vue`, `src/components/Panels/ExecutionHistoryAllDialog.vue`, `src/services/api.ts`, `src/stores/workflow.ts`, `src/features/release-tour/releaseRegistry.ts`, `src/features/release-tour/tourVisuals.ts`.

Placement lives apart from the queue on purpose: it is pure, it is the thing a new node type must update, and its coverage test must be runnable without a database.

---

## Task 1: Node placement

**Files:**
- Create: `backend/app/services/cluster/__init__.py`
- Create: `backend/app/services/cluster/node_placement.py`
- Test: `backend/tests/test_cluster_node_placement.py`

- [x] **Step 1: Write the failing test**

```python
"""Placement rules, graph recursion, and full coverage of the node registry."""

import unittest

from app.services.cluster.node_placement import (
    NODE_PLACEMENT,
    Placement,
    node_placement,
    workflow_placement,
)
from app.services.node_execution.registry import handler_module_names


class NodePlacementTests(unittest.TestCase):
    def test_http_node_runs_anywhere(self) -> None:
        self.assertEqual(node_placement({"type": "http", "data": {}}), Placement.ANYWHERE)

    def test_drive_node_is_pinned_to_main(self) -> None:
        self.assertEqual(node_placement({"type": "drive", "data": {}}), Placement.MAIN_ONLY)

    def test_send_email_is_pinned_even_without_attachments(self) -> None:
        self.assertEqual(node_placement({"type": "sendEmail", "data": {}}), Placement.MAIN_ONLY)

    def test_code_node_runs_anywhere(self) -> None:
        self.assertEqual(node_placement({"type": "code", "data": {}}), Placement.ANYWHERE)

    def test_playwright_node_runs_anywhere(self) -> None:
        self.assertEqual(node_placement({"type": "playwright", "data": {}}), Placement.ANYWHERE)

    def test_plain_agent_runs_anywhere(self) -> None:
        self.assertEqual(node_placement({"type": "agent", "data": {}}), Placement.ANYWHERE)

    def test_agent_with_a_skill_is_pinned_to_main(self) -> None:
        node = {"type": "agent", "data": {"skills": [{"name": "report"}]}}
        self.assertEqual(node_placement(node), Placement.MAIN_ONLY)

    def test_unknown_node_type_is_pinned_to_main(self) -> None:
        self.assertEqual(node_placement({"type": "acmePlugin", "data": {}}), Placement.MAIN_ONLY)


class WorkflowPlacementTests(unittest.TestCase):
    def test_all_anywhere_nodes_stay_anywhere(self) -> None:
        nodes = [{"type": "http", "data": {}}, {"type": "set", "data": {}}]
        self.assertEqual(workflow_placement(nodes, resolve_workflow=lambda _: None), Placement.ANYWHERE)

    def test_one_main_only_node_pins_the_whole_graph(self) -> None:
        nodes = [{"type": "http", "data": {}}, {"type": "drive", "data": {}}]
        self.assertEqual(workflow_placement(nodes, resolve_workflow=lambda _: None), Placement.MAIN_ONLY)

    def test_recursion_finds_a_pinned_node_in_a_sub_workflow(self) -> None:
        nodes = [{"type": "execute", "data": {"executeWorkflowId": "wf-2"}}]
        sub = {"wf-2": [{"type": "codex", "data": {}}]}
        placement = workflow_placement(nodes, resolve_workflow=lambda wid: sub.get(wid))
        self.assertEqual(placement, Placement.MAIN_ONLY)

    def test_recursion_through_an_agent_sub_workflow_tool(self) -> None:
        nodes = [{"type": "agent", "data": {"subWorkflowIds": ["wf-2"]}}]
        sub = {"wf-2": [{"type": "converter", "data": {}}]}
        placement = workflow_placement(nodes, resolve_workflow=lambda wid: sub.get(wid))
        self.assertEqual(placement, Placement.MAIN_ONLY)

    def test_a_dynamic_sub_workflow_id_pins_the_graph(self) -> None:
        nodes = [{"type": "execute", "data": {"executeWorkflowId": "$userInput.body.wf"}}]
        placement = workflow_placement(nodes, resolve_workflow=lambda _: None)
        self.assertEqual(placement, Placement.MAIN_ONLY)

    def test_an_unresolvable_sub_workflow_pins_the_graph(self) -> None:
        nodes = [{"type": "execute", "data": {"executeWorkflowId": "wf-missing"}}]
        placement = workflow_placement(nodes, resolve_workflow=lambda _: None)
        self.assertEqual(placement, Placement.MAIN_ONLY)

    def test_a_cycle_terminates(self) -> None:
        nodes = [{"type": "execute", "data": {"executeWorkflowId": "wf-1"}}]
        sub = {"wf-1": [{"type": "execute", "data": {"executeWorkflowId": "wf-1"}}]}
        placement = workflow_placement(nodes, resolve_workflow=lambda wid: sub.get(wid))
        self.assertEqual(placement, Placement.ANYWHERE)


class RegistryCoverageTests(unittest.TestCase):
    """Every executable node type must declare where it may run.

    There is no default. A new node type without an entry fails the build here,
    the same way TestExpressionOperatorCoverage guards the expression registry.
    """

    def test_every_registered_node_type_has_a_placement(self) -> None:
        missing = sorted(set(handler_module_names()) - set(NODE_PLACEMENT))
        self.assertEqual(
            missing,
            [],
            "Node types with no entry in NODE_PLACEMENT: "
            f"{missing}. Add each one to app/services/cluster/node_placement.py "
            "and read the placement rule in AGENTS.md before choosing.",
        )

    def test_no_placement_entry_is_stale(self) -> None:
        unknown = sorted(set(NODE_PLACEMENT) - set(handler_module_names()))
        self.assertEqual(unknown, [], f"NODE_PLACEMENT names types that no longer exist: {unknown}")
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_node_placement.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.cluster'`.

- [x] **Step 3: Expose the registry's node type names**

`app/services/node_execution/registry.py` keeps `_HANDLER_MODULES` private. Add a public accessor at the end of the file so the coverage test does not reach into a private name:

```python
def handler_module_names() -> tuple[str, ...]:
    """Every node type that has an execution handler."""
    return tuple(_HANDLER_MODULES)
```

- [x] **Step 4: Write the placement module**

Create `backend/app/services/cluster/__init__.py` as an empty file, then `backend/app/services/cluster/node_placement.py`:

```python
"""Where a run may execute in a multi-instance cluster.

Pure module: no database, no settings, no I/O. A node is MAIN_ONLY when it
reads or writes FILE_STORAGE_DIR, leaves state on local disk that a later run
reads back, or depends on something installed per instance. See the placement
rule in AGENTS.md before adding an entry.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum


class Placement(str, Enum):
    MAIN_ONLY = "main_only"
    ANYWHERE = "anywhere"


_MAIN = Placement.MAIN_ONLY
_ANY = Placement.ANYWHERE

# Every node type in node_execution/registry.py appears here. The coverage test
# in tests/test_cluster_node_placement.py fails the build if one is missing.
NODE_PLACEMENT: dict[str, Placement] = {
    "agent": _ANY,  # narrowed to MAIN_ONLY by _agent_placement when skills are attached
    "bigquery": _ANY,
    "chartOutput": _ANY,
    "clickhouse": _ANY,
    "code": _ANY,
    "codex": _MAIN,
    "condition": _ANY,
    "consoleLog": _ANY,
    "converter": _MAIN,
    "crawler": _ANY,
    "cron": _ANY,
    "dataTable": _ANY,
    "disableNode": _ANY,
    "discord": _ANY,
    "discordTrigger": _ANY,
    "drive": _MAIN,
    "errorHandler": _ANY,
    "execute": _ANY,
    "fileUploadTrigger": _MAIN,
    "github": _ANY,
    "googleDrive": _MAIN,
    "googleSheets": _ANY,
    "grist": _ANY,
    "heym": _ANY,
    "heymTrigger": _ANY,
    "htmlOutputMapper": _ANY,
    "http": _ANY,
    "imapTrigger": _ANY,
    "jira": _ANY,
    "jsonOutputMapper": _ANY,
    "linear": _ANY,
    "llm": _ANY,
    "loop": _ANY,
    "mcpCall": _ANY,
    "merge": _ANY,
    "notion": _ANY,
    "opencodeGo": _MAIN,
    "output": _ANY,
    "playwright": _ANY,
    "plugin": _MAIN,
    "pluginTrigger": _MAIN,
    "rabbitmq": _ANY,
    "rag": _ANY,
    "redis": _ANY,
    "s3": _ANY,
    "sendEmail": _MAIN,
    "sentry": _ANY,
    "set": _ANY,
    "slack": _ANY,
    "slackTrigger": _ANY,
    "sticky": _ANY,
    "supabase": _ANY,
    "switch": _ANY,
    "telegram": _ANY,
    "telegramTrigger": _ANY,
    "textInput": _ANY,
    "throwError": _ANY,
    "variable": _ANY,
    "wait": _ANY,
    "websocketSend": _ANY,
    "websocketTrigger": _ANY,
}


def _agent_placement(data: dict) -> Placement:
    """An agent pins the run only when a skill is attached.

    Skill code reads and writes Heym Drive through _load_skill_drive_files /
    _persist_skill_files in llm_service.py. Python tools, MCP tools and
    sub-workflow tools have no local file dependency.
    """
    return _MAIN if (data.get("skills") or []) else _ANY


_CONDITIONAL: dict[str, Callable[[dict], Placement]] = {"agent": _agent_placement}


def node_placement(node: dict) -> Placement:
    """Where this single node may run. An unlisted type is MAIN_ONLY.

    Unlisted means a plugin-provided type, which is loaded per instance and
    therefore main-only anyway. Registry types can never be unlisted: the
    coverage test fails the build first.
    """
    node_type = str(node.get("type") or "")
    data = node.get("data") or {}
    conditional = _CONDITIONAL.get(node_type)
    if conditional is not None:
        return conditional(data)
    return NODE_PLACEMENT.get(node_type, _MAIN)


def _sub_workflow_ids(node: dict) -> list[str]:
    """Workflow ids this node can reach, and whether any is only known at runtime."""
    node_type = str(node.get("type") or "")
    data = node.get("data") or {}
    if node_type == "execute":
        target = str(data.get("executeWorkflowId") or "")
        return [target] if target else []
    if node_type == "agent":
        return [wid for wid in (data.get("subWorkflowIds") or []) if isinstance(wid, str)]
    return []


def workflow_placement(
    nodes: list[dict],
    *,
    resolve_workflow: Callable[[str], list[dict] | None],
    _seen: frozenset[str] = frozenset(),
) -> Placement:
    """Where a whole graph may run, following sub-workflows.

    One MAIN_ONLY node anywhere in the reachable graph pins the entire run. A
    target that cannot be resolved statically - an expression, or a workflow the
    caller could not load - also pins it, because its contents are unknown.
    """
    for node in nodes:
        if node_placement(node) is _MAIN:
            return _MAIN
        for wf_id in _sub_workflow_ids(node):
            if "$" in wf_id:
                return _MAIN
            if wf_id in _seen:
                continue
            sub_nodes = resolve_workflow(wf_id)
            if sub_nodes is None:
                return _MAIN
            if (
                workflow_placement(
                    sub_nodes, resolve_workflow=resolve_workflow, _seen=_seen | {wf_id}
                )
                is _MAIN
            ):
                return _MAIN
    return _ANY
```

- [x] **Step 5: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_node_placement.py -v`

Expected: PASS, 17 tests. If `test_every_registered_node_type_has_a_placement` fails, the failure message names the missing types — add them to `NODE_PLACEMENT` rather than weakening the test.

- [x] **Step 6: Format, lint, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/services/cluster backend/app/services/node_execution/registry.py backend/tests/test_cluster_node_placement.py
git commit -m "feat(cluster): declare per-node execution placement"
```

---

## Task 2: Instance identity and configuration

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/app/services/cluster/identity.py`
- Test: `backend/tests/test_cluster_identity.py`

- [x] **Step 1: Write the failing test**

```python
"""Instance identity, role, and the compatibility fingerprint."""

import unittest
from unittest.mock import patch

from app.services.cluster import identity


class InstanceIdentityTests(unittest.TestCase):
    def test_explicit_id_is_used_verbatim(self) -> None:
        with patch.object(identity.settings, "instance_id", "eu-worker-1"):
            self.assertEqual(identity.instance_id(), "eu-worker-1")

    def test_id_falls_back_to_a_slug_of_the_name(self) -> None:
        with (
            patch.object(identity.settings, "instance_id", ""),
            patch.object(identity.settings, "instance_name", "EU Worker 1"),
        ):
            self.assertEqual(identity.instance_id(), "eu-worker-1")

    def test_id_falls_back_to_the_role_when_nothing_is_set(self) -> None:
        with (
            patch.object(identity.settings, "instance_id", ""),
            patch.object(identity.settings, "instance_name", ""),
            patch.object(identity.settings, "instance_role", "main"),
        ):
            self.assertEqual(identity.instance_id(), "main")

    def test_identity_does_not_depend_on_the_process(self) -> None:
        """Eight uvicorn processes must resolve to one identity."""
        with patch.object(identity.settings, "instance_id", "worker-a"):
            self.assertEqual(identity.instance_id(), identity.instance_id())

    def test_is_main_follows_the_role(self) -> None:
        with patch.object(identity.settings, "instance_role", "main"):
            self.assertTrue(identity.is_main())
        with patch.object(identity.settings, "instance_role", "worker"):
            self.assertFalse(identity.is_main())

    def test_an_unrecognised_role_is_not_main(self) -> None:
        with patch.object(identity.settings, "instance_role", "MAIN "):
            self.assertTrue(identity.is_main())
        with patch.object(identity.settings, "instance_role", "nonsense"):
            self.assertFalse(identity.is_main())


class KeysFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_stable_for_the_same_keys(self) -> None:
        with (
            patch.object(identity.settings, "encryption_key", "k1"),
            patch.object(identity.settings, "secret_key", "k2"),
        ):
            self.assertEqual(identity.keys_fingerprint(), identity.keys_fingerprint())

    def test_a_different_encryption_key_changes_the_fingerprint(self) -> None:
        with (
            patch.object(identity.settings, "encryption_key", "k1"),
            patch.object(identity.settings, "secret_key", "k2"),
        ):
            first = identity.keys_fingerprint()
        with (
            patch.object(identity.settings, "encryption_key", "different"),
            patch.object(identity.settings, "secret_key", "k2"),
        ):
            self.assertNotEqual(identity.keys_fingerprint(), first)

    def test_a_different_secret_key_changes_the_fingerprint(self) -> None:
        with (
            patch.object(identity.settings, "encryption_key", "k1"),
            patch.object(identity.settings, "secret_key", "k2"),
        ):
            first = identity.keys_fingerprint()
        with (
            patch.object(identity.settings, "encryption_key", "k1"),
            patch.object(identity.settings, "secret_key", "different"),
        ):
            self.assertNotEqual(identity.keys_fingerprint(), first)

    def test_fingerprint_never_contains_a_key(self) -> None:
        with (
            patch.object(identity.settings, "encryption_key", "super-secret-value"),
            patch.object(identity.settings, "secret_key", "another-secret-value"),
        ):
            printed = identity.keys_fingerprint()
        self.assertNotIn("super-secret-value", printed)
        self.assertNotIn("another-secret-value", printed)
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_identity.py -v`

Expected: FAIL with `ImportError: cannot import name 'identity'`.

- [x] **Step 3: Add the settings**

In `backend/app/config.py`, next to the other instance settings around line 74:

```python
    instance_id: str = Field(default="", validation_alias="HEYM_INSTANCE_ID")
    instance_name: str = Field(default="", validation_alias="HEYM_INSTANCE_NAME")
    instance_role: str = Field(default="main", validation_alias="HEYM_INSTANCE_ROLE")
    cluster_enabled: bool = Field(default=False, validation_alias="HEYM_CLUSTER_ENABLED")
```

`instance_role` defaults to `main` so an existing single-instance deployment keeps behaving as main with no configuration change.

- [x] **Step 4: Write the identity module**

Create `backend/app/services/cluster/identity.py`:

```python
"""Who this instance is, from the environment only.

Identity must not come from the process: the release image runs 8 uvicorn
workers (docker/release-entrypoint.sh) that share one instance row, and
distributed_lock.py's pid-based worker id is a different concept entirely.
"""

from __future__ import annotations

import hashlib
import re

from app.config import settings

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    return _SLUG_RE.sub("-", value.strip().lower()).strip("-")


def instance_id() -> str:
    """This instance's stable id, identical in every one of its processes."""
    if settings.instance_id.strip():
        return settings.instance_id.strip()
    if settings.instance_name.strip():
        return _slugify(settings.instance_name)
    return _slugify(settings.instance_role) or "main"


def instance_name() -> str:
    """The label first shown for this instance; the admin UI may rename it."""
    return settings.instance_name.strip() or instance_id()


def is_main() -> bool:
    """Whether this instance owns file storage, plugins, and ingress."""
    return settings.instance_role.strip().lower() == "main"


def keys_fingerprint() -> str:
    """A comparable digest of the two keys every instance must share.

    Instances with different ENCRYPTION_KEY values cannot decrypt each other's
    credentials, and the resulting run failures name nothing useful. Comparing
    digests turns that into a visible incompatibility. The keys themselves are
    never stored or returned.
    """
    enc = hashlib.sha256(settings.encryption_key.encode()).hexdigest()[:16]
    sec = hashlib.sha256(settings.secret_key.encode()).hexdigest()[:16]
    return f"{enc}{sec}"
```

- [x] **Step 5: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_identity.py -v`

Expected: PASS, 11 tests.

- [x] **Step 6: Format, lint, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/config.py backend/app/services/cluster/identity.py backend/tests/test_cluster_identity.py
git commit -m "feat(cluster): env-pinned instance identity and key fingerprint"
```

---

## Task 3: Instance registry table and heartbeat

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/116_add_cluster_instances.py`
- Create: `backend/app/services/cluster/registry.py`
- Test: `backend/tests/test_cluster_registry.py`

- [x] **Step 1: Write the failing test**

```python
"""Liveness, compatibility, and the candidate pool."""

import unittest
from datetime import datetime, timedelta, timezone

from app.services.cluster.registry import (
    HEARTBEAT_INTERVAL_SECONDS,
    LIVENESS_WINDOW_SECONDS,
    InstanceView,
    candidate_instances,
    is_compatible_with,
    is_live,
)


def _view(**overrides: object) -> InstanceView:
    base = dict(
        id="worker-a",
        name="Worker A",
        role="worker",
        enabled=True,
        weight=30,
        version="1.2.3",
        schema_revision="116_add_cluster_instances",
        keys_fingerprint="aaaabbbb",
        docker_ok=True,
        db_latency_ms=3.0,
        heartbeat_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return InstanceView(**base)  # type: ignore[arg-type]


class LivenessTests(unittest.TestCase):
    def test_a_fresh_heartbeat_is_live(self) -> None:
        self.assertTrue(is_live(_view(), now=datetime.now(timezone.utc)))

    def test_one_missed_beat_is_still_live(self) -> None:
        now = datetime.now(timezone.utc)
        stale = _view(heartbeat_at=now - timedelta(seconds=HEARTBEAT_INTERVAL_SECONDS + 1))
        self.assertTrue(is_live(stale, now=now))

    def test_a_heartbeat_past_the_window_is_dead(self) -> None:
        now = datetime.now(timezone.utc)
        dead = _view(heartbeat_at=now - timedelta(seconds=LIVENESS_WINDOW_SECONDS + 1))
        self.assertFalse(is_live(dead, now=now))


class CompatibilityTests(unittest.TestCase):
    def test_matching_instances_are_compatible(self) -> None:
        self.assertTrue(is_compatible_with(_view(), _view(id="main", role="main")))

    def test_a_different_version_is_incompatible(self) -> None:
        main = _view(id="main", role="main")
        self.assertFalse(is_compatible_with(_view(version="1.2.2"), main))

    def test_a_different_schema_revision_is_incompatible(self) -> None:
        main = _view(id="main", role="main")
        self.assertFalse(is_compatible_with(_view(schema_revision="115_add_sso_settings"), main))

    def test_a_different_key_fingerprint_is_incompatible(self) -> None:
        main = _view(id="main", role="main")
        self.assertFalse(is_compatible_with(_view(keys_fingerprint="ccccdddd"), main))


class CandidatePoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.main = _view(id="main", role="main", weight=70)

    def test_pool_holds_live_enabled_compatible_instances(self) -> None:
        pool = candidate_instances([self.main, _view()], now=self.now)
        self.assertEqual([i.id for i in pool], ["main", "worker-a"])

    def test_a_disabled_instance_is_excluded(self) -> None:
        pool = candidate_instances([self.main, _view(enabled=False)], now=self.now)
        self.assertEqual([i.id for i in pool], ["main"])

    def test_a_dead_instance_is_excluded(self) -> None:
        dead = _view(heartbeat_at=self.now - timedelta(seconds=LIVENESS_WINDOW_SECONDS + 1))
        pool = candidate_instances([self.main, dead], now=self.now)
        self.assertEqual([i.id for i in pool], ["main"])

    def test_an_incompatible_instance_is_excluded(self) -> None:
        pool = candidate_instances([self.main, _view(version="0.9.0")], now=self.now)
        self.assertEqual([i.id for i in pool], ["main"])

    def test_a_zero_weight_instance_is_excluded(self) -> None:
        pool = candidate_instances([self.main, _view(weight=0)], now=self.now)
        self.assertEqual([i.id for i in pool], ["main"])

    def test_an_empty_pool_when_main_is_missing(self) -> None:
        """Without a main row there is no compatibility reference, so nobody runs."""
        self.assertEqual(candidate_instances([_view()], now=self.now), [])
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_registry.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.cluster.registry'`.

- [x] **Step 3: Add the model**

Append to `backend/app/db/models.py`:

```python
class ClusterInstance(Base):
    """One Heym deployment sharing this database. Upserted by all its processes."""

    __tablename__ = "cluster_instances"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="worker")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    schema_revision: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    keys_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    docker_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    db_latency_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [x] **Step 4: Write the migration**

Create `backend/alembic/versions/116_add_cluster_instances.py`:

```python
"""add cluster_instances

Revision ID: 116_add_cluster_instances
Revises: 115_add_sso_settings
Create Date: 2026-08-27 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "116_add_cluster_instances"
down_revision: Union[str, None] = "115_add_sso_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cluster_instances",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, server_default=""),
        sa.Column("role", sa.String(16), nullable=False, server_default="worker"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.String(64), nullable=False, server_default=""),
        sa.Column("schema_revision", sa.String(64), nullable=False, server_default=""),
        sa.Column("keys_fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("docker_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("db_latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_cluster_instances_heartbeat_at", "cluster_instances", ["heartbeat_at"])


def downgrade() -> None:
    op.drop_index("ix_cluster_instances_heartbeat_at", table_name="cluster_instances")
    op.drop_table("cluster_instances")
```

- [x] **Step 5: Write the registry module**

Create `backend/app/services/cluster/registry.py`:

```python
"""The cluster_instances table: heartbeat writes and candidate-pool reads."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db.models import ClusterInstance
from app.db.session import async_session_maker
from app.services.cluster import identity

logger = logging.getLogger("cluster")

# Properties of the mechanism, not deployment configuration.
HEARTBEAT_INTERVAL_SECONDS = 10
LIVENESS_WINDOW_SECONDS = 30
_DOCKER_SOCKET = "/var/run/docker.sock"


@dataclass(frozen=True)
class InstanceView:
    id: str
    name: str
    role: str
    enabled: bool
    weight: int
    version: str
    schema_revision: str
    keys_fingerprint: str
    docker_ok: bool
    db_latency_ms: float
    heartbeat_at: datetime


def is_live(instance: InstanceView, *, now: datetime) -> bool:
    """Whether this instance beat recently enough to be given work."""
    return instance.heartbeat_at >= now - timedelta(seconds=LIVENESS_WINDOW_SECONDS)


def is_compatible_with(instance: InstanceView, main: InstanceView) -> bool:
    """Whether this instance can safely execute work main would have executed.

    A version or schema difference means it may not know a node type. A key
    fingerprint difference means it cannot decrypt credentials at all, and the
    resulting failures name nothing useful - so it is excluded up front.
    """
    return (
        instance.version == main.version
        and instance.schema_revision == main.schema_revision
        and instance.keys_fingerprint == main.keys_fingerprint
    )


def find_main(instances: list[InstanceView]) -> InstanceView | None:
    for instance in instances:
        if instance.role == "main":
            return instance
    return None


def candidate_instances(instances: list[InstanceView], *, now: datetime) -> list[InstanceView]:
    """Instances eligible to receive an ANYWHERE run, in stable id order."""
    main = find_main(instances)
    if main is None:
        return []
    eligible = [
        i
        for i in instances
        if i.enabled and i.weight > 0 and is_live(i, now=now) and is_compatible_with(i, main)
    ]
    return sorted(eligible, key=lambda i: i.id)


def _docker_reachable() -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect(_DOCKER_SOCKET)
        return True
    except OSError:
        return False


async def _schema_revision() -> str:
    async with async_session_maker() as db:
        result = await db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        row = result.first()
        return str(row[0]) if row else ""


async def write_heartbeat() -> None:
    """Upsert this instance's row. Safe to call from all 8 processes."""
    started = time.perf_counter()
    revision = await _schema_revision()
    latency_ms = (time.perf_counter() - started) * 1000

    values = dict(
        id=identity.instance_id(),
        role="main" if identity.is_main() else "worker",
        version=settings.resolved_version,
        schema_revision=revision,
        keys_fingerprint=identity.keys_fingerprint(),
        docker_ok=_docker_reachable(),
        db_latency_ms=latency_ms,
        heartbeat_at=datetime.now(timezone.utc),
    )
    # name, enabled and weight are owned by the admin UI: set on insert, never
    # overwritten by a heartbeat, or a restart would undo the operator's changes.
    stmt = (
        pg_insert(ClusterInstance)
        .values(
            **values,
            name=identity.instance_name(),
            enabled=True,
            weight=100 if identity.is_main() else 0,
        )
        .on_conflict_do_update(index_elements=[ClusterInstance.id], set_=values)
    )
    async with async_session_maker() as db:
        await db.execute(stmt)
        await db.commit()


async def list_instances() -> list[InstanceView]:
    async with async_session_maker() as db:
        result = await db.execute(select(ClusterInstance))
        return [
            InstanceView(
                id=row.id,
                name=row.name,
                role=row.role,
                enabled=row.enabled,
                weight=row.weight,
                version=row.version,
                schema_revision=row.schema_revision,
                keys_fingerprint=row.keys_fingerprint,
                docker_ok=row.docker_ok,
                db_latency_ms=row.db_latency_ms,
                heartbeat_at=row.heartbeat_at,
            )
            for row in result.scalars().all()
        ]


class ClusterHeartbeatService:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Cluster heartbeat started (instance=%s)", identity.instance_id())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await write_heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cluster heartbeat failed")
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


heartbeat_service = ClusterHeartbeatService()
```

- [x] **Step 6: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_registry.py -v`

Expected: PASS, 13 tests.

- [x] **Step 7: Apply the migration**

```bash
cd backend && uv run alembic upgrade head && uv run alembic current
```

Expected: `116_add_cluster_instances (head)`.

- [x] **Step 8: Format, lint, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/db/models.py backend/alembic/versions/116_add_cluster_instances.py backend/app/services/cluster/registry.py backend/tests/test_cluster_registry.py
git commit -m "feat(cluster): instance registry with heartbeat and compatibility gate"
```

---

## Task 4: Weighted selection

**Files:**
- Create: `backend/app/services/cluster/weights.py`
- Test: `backend/tests/test_cluster_weights.py`

- [x] **Step 1: Write the failing test**

```python
"""Renormalization across live instances and quota-accurate selection."""

import unittest

from app.services.cluster.weights import (
    COUNTER_RESCALE_THRESHOLD,
    normalized_weights,
    pick_instance,
    rescale_counters,
)


class NormalizationTests(unittest.TestCase):
    def test_full_pool_keeps_the_configured_split(self) -> None:
        shares = normalized_weights({"main": 70, "a": 15, "b": 15})
        self.assertAlmostEqual(shares["main"], 0.70)
        self.assertAlmostEqual(shares["a"], 0.15)

    def test_a_missing_instance_is_renormalized_away(self) -> None:
        """main=70 a=15 b=15 with a dead -> main 70/85, b 15/85."""
        shares = normalized_weights({"main": 70, "b": 15})
        self.assertAlmostEqual(shares["main"], 70 / 85)
        self.assertAlmostEqual(shares["b"], 15 / 85)

    def test_a_single_instance_takes_everything(self) -> None:
        self.assertEqual(normalized_weights({"main": 70}), {"main": 1.0})

    def test_an_empty_pool_yields_no_shares(self) -> None:
        self.assertEqual(normalized_weights({}), {})


class SelectionTests(unittest.TestCase):
    def test_the_first_pick_goes_to_the_largest_share(self) -> None:
        winner = pick_instance({"main": 70, "a": 30}, counters={})
        self.assertEqual(winner, "main")

    def test_a_long_run_converges_on_the_configured_split(self) -> None:
        counters: dict[str, int] = {}
        for _ in range(100):
            winner = pick_instance({"main": 70, "a": 30}, counters=counters)
            counters[winner] = counters.get(winner, 0) + 1
        self.assertEqual(counters["main"], 70)
        self.assertEqual(counters["a"], 30)

    def test_main_only_runs_spend_mains_quota(self) -> None:
        """30 forced runs against main=70 leave main only 40 of the next 70."""
        counters = {"main": 30}
        for _ in range(70):
            winner = pick_instance({"main": 70, "a": 30}, counters=counters)
            counters[winner] = counters.get(winner, 0) + 1
        self.assertEqual(counters["main"], 70)
        self.assertEqual(counters["a"], 30)

    def test_an_overflowing_main_starves_of_anywhere_work(self) -> None:
        """90 forced runs against main=70: every remaining run goes elsewhere."""
        counters = {"main": 90}
        for _ in range(10):
            winner = pick_instance({"main": 70, "a": 30}, counters=counters)
            counters[winner] = counters.get(winner, 0) + 1
        self.assertEqual(counters["main"], 90)
        self.assertEqual(counters["a"], 10)

    def test_an_empty_pool_returns_none(self) -> None:
        self.assertIsNone(pick_instance({}, counters={}))

    def test_selection_is_deterministic_for_the_same_state(self) -> None:
        weights = {"main": 50, "a": 50}
        self.assertEqual(
            pick_instance(weights, counters={"main": 1}),
            pick_instance(weights, counters={"main": 1}),
        )


class RescaleTests(unittest.TestCase):
    def test_counters_below_the_threshold_are_untouched(self) -> None:
        counters = {"main": 5, "a": 3}
        self.assertEqual(rescale_counters(counters), {"main": 5, "a": 3})

    def test_counters_are_halved_past_the_threshold(self) -> None:
        counters = {"main": COUNTER_RESCALE_THRESHOLD, "a": COUNTER_RESCALE_THRESHOLD // 2}
        rescaled = rescale_counters(counters)
        self.assertEqual(rescaled["main"], COUNTER_RESCALE_THRESHOLD // 2)
        self.assertEqual(rescaled["a"], COUNTER_RESCALE_THRESHOLD // 4)

    def test_rescaling_preserves_the_relative_split(self) -> None:
        counters = {"main": COUNTER_RESCALE_THRESHOLD, "a": COUNTER_RESCALE_THRESHOLD // 5}
        rescaled = rescale_counters(counters)
        self.assertAlmostEqual(rescaled["main"] / rescaled["a"], 5.0, places=1)
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_weights.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.cluster.weights'`.

- [x] **Step 3: Write the weights module**

Create `backend/app/services/cluster/weights.py`:

```python
"""Smooth weighted round-robin over per-instance assignment counters.

Every assigned run increments a counter, including a MAIN_ONLY run that main was
forced to take. That single rule is what makes a percentage describe total load:
forced work spends main's quota, so the next ANYWHERE runs fall to the workers.
The consequence, which the UI and docs state: main's percentage is a ceiling,
not a floor.
"""

from __future__ import annotations

COUNTER_RESCALE_THRESHOLD = 1_000_000


def normalized_weights(weights: dict[str, int]) -> dict[str, float]:
    """Configured weights as shares of the live pool, summing to 1."""
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {instance_id: weight / total for instance_id, weight in weights.items()}


def pick_instance(weights: dict[str, int], *, counters: dict[str, int]) -> str | None:
    """The instance furthest below its share. Ties break on id, so it is deterministic."""
    shares = normalized_weights(weights)
    if not shares:
        return None
    total = sum(counters.get(instance_id, 0) for instance_id in shares) + 1
    return max(
        sorted(shares),
        key=lambda instance_id: shares[instance_id] * total - counters.get(instance_id, 0),
    )


def rescale_counters(counters: dict[str, int]) -> dict[str, int]:
    """Halve every counter once the largest gets big, preserving the ratios."""
    if not counters or max(counters.values()) < COUNTER_RESCALE_THRESHOLD:
        return counters
    return {instance_id: value // 2 for instance_id, value in counters.items()}
```

- [x] **Step 4: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_weights.py -v`

Expected: PASS, 12 tests.

- [x] **Step 5: Format, lint, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/services/cluster/weights.py backend/tests/test_cluster_weights.py
git commit -m "feat(cluster): quota-accurate weighted instance selection"
```

---

## Task 5: Run queue table and claim

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/117_add_workflow_run_queue.py`
- Create: `backend/app/services/cluster/run_queue.py`
- Test: `backend/tests/test_cluster_run_queue.py`

- [x] **Step 1: Write the failing test**

```python
"""Enqueue shape, expiry, and the guarantee that no credential is stored."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from app.services.cluster.run_queue import (
    STATUS_QUEUED,
    STATUS_SKIPPED_LATE,
    STATUS_WAITING_FOR_MAIN,
    QueuedRun,
    build_queue_values,
    is_expired,
    next_status,
)


class StatusTests(unittest.TestCase):
    def test_a_targeted_run_is_queued(self) -> None:
        self.assertEqual(next_status(target_instance_id="worker-a"), STATUS_QUEUED)

    def test_a_run_with_no_target_waits_for_main(self) -> None:
        self.assertEqual(next_status(target_instance_id=None), STATUS_WAITING_FOR_MAIN)


class ExpiryTests(unittest.TestCase):
    def test_a_row_inside_the_grace_window_is_not_expired(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertFalse(is_expired(not_after=now + timedelta(seconds=1), now=now))

    def test_a_row_past_the_grace_window_is_expired(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertTrue(is_expired(not_after=now - timedelta(seconds=1), now=now))

    def test_the_expired_status_names_the_reason(self) -> None:
        self.assertEqual(STATUS_SKIPPED_LATE, "skipped_late")


class QueueValueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run = QueuedRun(
            workflow_id=uuid.uuid4(),
            execution_id=uuid.uuid4(),
            placement="anywhere",
            inputs={"body": {"x": 1}},
            trigger_source="API",
            actor_user_id=uuid.uuid4(),
            credentials_owner_id=uuid.uuid4(),
            test_run=False,
            timeout_seconds=None,
        )

    def test_values_carry_the_credentials_owner_not_a_context(self) -> None:
        values = build_queue_values(self.run, target_instance_id="worker-a", grace_seconds=600)
        self.assertEqual(values["credentials_owner_id"], self.run.credentials_owner_id)

    def test_values_never_contain_a_resolved_credential(self) -> None:
        """A queue row is readable by anything with database access."""
        values = build_queue_values(self.run, target_instance_id="worker-a", grace_seconds=600)
        self.assertNotIn("credentials_context", values)
        self.assertNotIn("credentials", values)

    def test_not_after_is_the_grace_window_from_now(self) -> None:
        values = build_queue_values(self.run, target_instance_id="worker-a", grace_seconds=600)
        delta = values["not_after"] - values["enqueued_at"]
        self.assertAlmostEqual(delta.total_seconds(), 600, delta=1)

    def test_a_run_with_no_target_is_stored_as_waiting(self) -> None:
        values = build_queue_values(self.run, target_instance_id=None, grace_seconds=600)
        self.assertEqual(values["status"], STATUS_WAITING_FOR_MAIN)
        self.assertIsNone(values["target_instance_id"])
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_run_queue.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.cluster.run_queue'`.

- [x] **Step 3: Add the models**

Append to `backend/app/db/models.py`:

```python
class WorkflowRunQueue(Base):
    """A background run waiting for, or claimed by, one instance."""

    __tablename__ = "workflow_run_queue"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    placement: Mapped[str] = mapped_column(String(16), nullable=False)
    target_instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    trigger_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    credentials_owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    test_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timeout_seconds: Mapped[float | None] = mapped_column(nullable=True)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by_process: Mapped[str | None] = mapped_column(String(128), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ClusterDispatchState(Base):
    """A single row holding per-instance assignment counters, locked on assignment."""

    __tablename__ = "cluster_dispatch_state"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="singleton")
    counters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [x] **Step 4: Write the migration**

Create `backend/alembic/versions/117_add_workflow_run_queue.py`:

```python
"""add workflow_run_queue and cluster_dispatch_state

Revision ID: 117_add_workflow_run_queue
Revises: 116_add_cluster_instances
Create Date: 2026-08-27 10:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "117_add_workflow_run_queue"
down_revision: Union[str, None] = "116_add_cluster_instances"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_run_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("placement", sa.String(16), nullable=False),
        sa.Column("target_instance_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("trigger_source", sa.String(50), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("credentials_owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("test_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("timeout_seconds", sa.Float(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("not_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by_process", sa.String(128), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_workflow_run_queue_claim",
        "workflow_run_queue",
        ["target_instance_id", "status", "enqueued_at"],
    )
    op.create_index("ix_workflow_run_queue_status", "workflow_run_queue", ["status"])

    op.create_table(
        "cluster_dispatch_state",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("counters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute("INSERT INTO cluster_dispatch_state (id, counters) VALUES ('singleton', '{}')")


def downgrade() -> None:
    op.drop_table("cluster_dispatch_state")
    op.drop_index("ix_workflow_run_queue_status", table_name="workflow_run_queue")
    op.drop_index("ix_workflow_run_queue_claim", table_name="workflow_run_queue")
    op.drop_table("workflow_run_queue")
```

- [x] **Step 5: Write the run queue module**

Create `backend/app/services/cluster/run_queue.py`:

```python
"""Enqueue, claim, and retire background runs through Postgres.

The queue row never holds a resolved credentials context. It carries
credentials_owner_id and the executing instance calls
get_credentials_context() itself, which it can do because every instance in a
cluster shares one ENCRYPTION_KEY.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text, update

from app.config import settings
from app.db.models import ClusterDispatchState, WorkflowRunQueue
from app.db.session import async_session_maker
from app.services.cluster import registry
from app.services.cluster.weights import pick_instance, rescale_counters

logger = logging.getLogger("cluster")

STATUS_QUEUED = "queued"
STATUS_WAITING_FOR_MAIN = "waiting_for_main"
STATUS_CLAIMED = "claimed"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED_LATE = "skipped_late"


@dataclass(frozen=True)
class QueuedRun:
    workflow_id: uuid.UUID
    execution_id: uuid.UUID
    placement: str
    inputs: dict
    trigger_source: str | None
    actor_user_id: uuid.UUID | None
    credentials_owner_id: uuid.UUID | None
    test_run: bool
    timeout_seconds: float | None


def next_status(*, target_instance_id: str | None) -> str:
    """A run with no reachable target waits instead of failing."""
    return STATUS_QUEUED if target_instance_id else STATUS_WAITING_FOR_MAIN


def is_expired(*, not_after: datetime, now: datetime) -> bool:
    return now > not_after


def build_queue_values(
    run: QueuedRun, *, target_instance_id: str | None, grace_seconds: int
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "id": uuid.uuid4(),
        "workflow_id": run.workflow_id,
        "execution_id": run.execution_id,
        "placement": run.placement,
        "target_instance_id": target_instance_id,
        "status": next_status(target_instance_id=target_instance_id),
        "inputs": run.inputs,
        "trigger_source": run.trigger_source,
        "actor_user_id": run.actor_user_id,
        "credentials_owner_id": run.credentials_owner_id,
        "test_run": run.test_run,
        "timeout_seconds": run.timeout_seconds,
        "enqueued_at": now,
        "not_after": now + timedelta(seconds=grace_seconds),
    }


async def choose_target(placement: str) -> str | None:
    """Pick the instance for this run and charge it, in one locked transaction.

    A MAIN_ONLY run is not selected - its target is always main - but it still
    increments main's counter, so the forced work spends main's quota.
    """
    async with async_session_maker() as db:
        state = (
            await db.execute(
                select(ClusterDispatchState)
                .where(ClusterDispatchState.id == "singleton")
                .with_for_update()
            )
        ).scalar_one_or_none()
        if state is None:
            return None

        instances = await registry.list_instances()
        now = datetime.now(timezone.utc)
        counters = rescale_counters(dict(state.counters or {}))

        if placement == "main_only":
            main = registry.find_main(instances)
            target = main.id if main and registry.is_live(main, now=now) else None
        else:
            pool = registry.candidate_instances(instances, now=now)
            target = pick_instance({i.id: i.weight for i in pool}, counters=counters)

        if target is not None:
            counters[target] = counters.get(target, 0) + 1
            state.counters = counters
        await db.commit()
        return target


async def enqueue(run: QueuedRun) -> str | None:
    """Write the queue row and return the instance it was assigned to."""
    target = await choose_target(run.placement)
    values = build_queue_values(
        run, target_instance_id=target, grace_seconds=settings.cron_misfire_grace_seconds
    )
    async with async_session_maker() as db:
        await db.execute(WorkflowRunQueue.__table__.insert().values(**values))
        await db.commit()
    return target


async def claim_next(instance_id: str) -> WorkflowRunQueue | None:
    """Take one queued row for this instance. Concurrent claimers skip each other."""
    async with async_session_maker() as db:
        row = (
            await db.execute(
                select(WorkflowRunQueue)
                .where(
                    WorkflowRunQueue.target_instance_id == instance_id,
                    WorkflowRunQueue.status == STATUS_QUEUED,
                )
                .order_by(WorkflowRunQueue.enqueued_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row.status = STATUS_CLAIMED
        row.claimed_at = datetime.now(timezone.utc)
        row.claimed_by_process = f"{instance_id}-{os.getpid()}"
        await db.commit()
        db.expunge(row)
        return row


async def complete(execution_id: uuid.UUID, *, result: dict | None, error: str | None) -> None:
    async with async_session_maker() as db:
        await db.execute(
            update(WorkflowRunQueue)
            .where(WorkflowRunQueue.execution_id == execution_id)
            .values(
                status=STATUS_FAILED if error else STATUS_DONE,
                result=result,
                error=error,
                finished_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def expire_late_rows() -> int:
    """Retire rows past their grace window instead of replaying a backlog.

    Without this, a main instance returning after a long outage would run every
    queued MAIN_ONLY job at once - the mirror image of the cron duplicate-fire
    incident that cron_misfire_grace_seconds already guards against.
    """
    async with async_session_maker() as db:
        result = await db.execute(
            update(WorkflowRunQueue)
            .where(
                WorkflowRunQueue.status.in_([STATUS_QUEUED, STATUS_WAITING_FOR_MAIN]),
                WorkflowRunQueue.not_after < datetime.now(timezone.utc),
            )
            .values(
                status=STATUS_SKIPPED_LATE,
                error="Skipped: not claimed inside the misfire grace window",
                finished_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        return result.rowcount or 0


async def release_waiting_for_main(main_instance_id: str) -> int:
    """Hand waiting rows to main once it is live again."""
    async with async_session_maker() as db:
        result = await db.execute(
            update(WorkflowRunQueue)
            .where(
                WorkflowRunQueue.status == STATUS_WAITING_FOR_MAIN,
                WorkflowRunQueue.not_after >= datetime.now(timezone.utc),
            )
            .values(status=STATUS_QUEUED, target_instance_id=main_instance_id)
        )
        await db.commit()
        return result.rowcount or 0


async def notify_queue(target_instance_id: str) -> None:
    async with async_session_maker() as db:
        await db.execute(
            text("SELECT pg_notify('heym_run_queue', :payload)"),
            {"payload": target_instance_id},
        )
        await db.commit()
```

- [x] **Step 6: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_run_queue.py -v`

Expected: PASS, 9 tests.

- [x] **Step 7: Apply the migration**

```bash
cd backend && uv run alembic upgrade head && uv run alembic current
```

Expected: `117_add_workflow_run_queue (head)`.

- [x] **Step 8: Format, lint, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/db/models.py backend/alembic/versions/117_add_workflow_run_queue.py backend/app/services/cluster/run_queue.py backend/tests/test_cluster_run_queue.py
git commit -m "feat(cluster): Postgres-backed run queue with misfire grace"
```

---

## Task 6: Queue wake-ups over LISTEN/NOTIFY

**Files:**
- Create: `backend/app/services/cluster/run_queue_bus.py`
- Test: `backend/tests/test_cluster_run_queue_bus.py`

This mirrors `app/services/execution_cancel_bus.py`, which already runs a
`LISTEN/NOTIFY` loop in this codebase. Read that file before writing this one.

- [x] **Step 1: Write the failing test**

```python
"""Payload routing for queue wake-ups."""

import unittest

from app.services.cluster.run_queue_bus import QueueWakeBus, is_for_me


class PayloadRoutingTests(unittest.TestCase):
    def test_a_payload_naming_this_instance_wakes_it(self) -> None:
        self.assertTrue(is_for_me("worker-a", instance_id="worker-a"))

    def test_a_payload_for_another_instance_is_ignored(self) -> None:
        self.assertFalse(is_for_me("worker-b", instance_id="worker-a"))

    def test_whitespace_is_tolerated(self) -> None:
        self.assertTrue(is_for_me("  worker-a  ", instance_id="worker-a"))

    def test_an_empty_payload_is_ignored(self) -> None:
        self.assertFalse(is_for_me("", instance_id="worker-a"))


class WakeBusTests(unittest.TestCase):
    def test_a_matching_payload_sets_the_wake_flag(self) -> None:
        bus = QueueWakeBus(instance_id="worker-a")
        self.assertTrue(bus.handle_payload("worker-a"))

    def test_a_foreign_payload_does_not_set_the_wake_flag(self) -> None:
        bus = QueueWakeBus(instance_id="worker-a")
        self.assertFalse(bus.handle_payload("worker-b"))
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_run_queue_bus.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.cluster.run_queue_bus'`.

- [x] **Step 3: Write the bus**

Create `backend/app/services/cluster/run_queue_bus.py`:

```python
"""Wake this instance when a run is enqueued for it.

Mirrors execution_cancel_bus.py: a Postgres LISTEN connection turns a
pg_notify into an in-process event, so the claim loop does not have to poll
tightly. Polling still runs as a slow fallback, so a dropped LISTEN connection
degrades latency rather than stalling the queue.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

logger = logging.getLogger("cluster")

CHANNEL = "heym_run_queue"
POLL_FALLBACK_SECONDS = 5.0


def is_for_me(payload: str, *, instance_id: str) -> bool:
    return payload.strip() == instance_id


class QueueWakeBus:
    def __init__(self, instance_id: str) -> None:
        self._instance_id = instance_id
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def handle_payload(self, payload: str) -> bool:
        """Set the wake flag when the payload names this instance."""
        if not is_for_me(payload, instance_id=self._instance_id):
            return False
        self._wake.set()
        return True

    async def wait_for_work(self) -> None:
        """Block until notified, or until the fallback poll interval elapses."""
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=POLL_FALLBACK_SECONDS)
        self._wake.clear()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _listen_loop(self) -> None:
        from app.db.session import engine

        while self._running:
            try:
                raw = await engine.raw_connection()
                driver_conn = raw.driver_connection
                driver_conn.add_listener(
                    CHANNEL, lambda _c, _p, _ch, payload: self.handle_payload(payload)
                )
                while self._running:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Queue wake listener dropped; retrying", exc_info=True)
                await asyncio.sleep(POLL_FALLBACK_SECONDS)
```

- [x] **Step 4: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_run_queue_bus.py -v`

Expected: PASS, 6 tests.

- [x] **Step 5: Format, lint, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/services/cluster/run_queue_bus.py backend/tests/test_cluster_run_queue_bus.py
git commit -m "feat(cluster): LISTEN/NOTIFY wake-ups for the run queue"
```

---

## Task 7: The dispatch seam

**Files:**
- Create: `backend/app/services/cluster/dispatch.py`
- Modify: `backend/app/main.py`
- Modify the eleven call sites listed in Step 6
- Test: `backend/tests/test_cluster_dispatch.py`

- [x] **Step 1: Write the failing test**

```python
"""When a run is kept in-process and when it is enqueued."""

import unittest

from app.services.cluster.dispatch import should_run_in_process


class InProcessDecisionTests(unittest.TestCase):
    def test_a_single_instance_install_never_enqueues(self) -> None:
        self.assertTrue(
            should_run_in_process(cluster_enabled=False, placement="anywhere", is_main=True)
        )

    def test_a_main_only_run_on_main_stays_in_process(self) -> None:
        self.assertTrue(
            should_run_in_process(cluster_enabled=True, placement="main_only", is_main=True)
        )

    def test_a_main_only_run_on_a_worker_is_enqueued(self) -> None:
        self.assertFalse(
            should_run_in_process(cluster_enabled=True, placement="main_only", is_main=False)
        )

    def test_an_anywhere_run_on_main_is_enqueued(self) -> None:
        """Main must go through the queue or it would never share the load."""
        self.assertFalse(
            should_run_in_process(cluster_enabled=True, placement="anywhere", is_main=True)
        )

    def test_an_anywhere_run_on_a_worker_is_enqueued(self) -> None:
        self.assertFalse(
            should_run_in_process(cluster_enabled=True, placement="anywhere", is_main=False)
        )

    def test_a_disabled_cluster_keeps_main_only_work_in_process(self) -> None:
        self.assertTrue(
            should_run_in_process(cluster_enabled=False, placement="main_only", is_main=True)
        )
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_dispatch.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.cluster.dispatch'`.

- [x] **Step 3: Write the dispatch module**

Create `backend/app/services/cluster/dispatch.py`:

```python
"""The one seam where a background run either executes here or is enqueued.

Callers that today call execute_workflow() call dispatch_workflow() instead.
Streaming callers (execute_workflow_streaming) are untouched: their SSE events
go to the caller's own HTTP response and cannot cross an instance boundary.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.config import settings
from app.services.cluster import identity, run_queue
from app.services.cluster.node_placement import Placement, workflow_placement
from app.services.workflow_executor import ExecutionResult, execute_workflow

logger = logging.getLogger("cluster")

_RESULT_POLL_SECONDS = 0.25


def should_run_in_process(*, cluster_enabled: bool, placement: str, is_main: bool) -> bool:
    """Whether to execute here rather than enqueue.

    With no cluster, nothing is ever enqueued and a single-instance install
    behaves exactly as before, with no added latency. With a cluster, only a
    MAIN_ONLY run already on main skips the queue - an ANYWHERE run on main goes
    through it, or main would never hand work to anyone.
    """
    if not cluster_enabled:
        return True
    return placement == Placement.MAIN_ONLY.value and is_main


def resolve_placement(nodes: list[dict], workflow_cache: dict[str, dict] | None) -> str:
    """Placement for this graph, resolving sub-workflows from the executor's cache."""
    cache = workflow_cache or {}

    def resolve(workflow_id: str) -> list[dict] | None:
        entry = cache.get(workflow_id)
        return entry.get("nodes") if entry else None

    return workflow_placement(nodes, resolve_workflow=resolve).value


async def dispatch_workflow(
    *,
    workflow_id: uuid.UUID,
    nodes: list[dict],
    edges: list[dict],
    inputs: dict,
    workflow_cache: dict[str, dict] | None = None,
    trigger_source: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    credentials_owner_id: uuid.UUID | None = None,
    test_run: bool = False,
    timeout_seconds: float | None = None,
    **executor_kwargs: object,
) -> ExecutionResult | None:
    """Run here, or enqueue and wait for whichever instance takes it.

    Returns None when the run was enqueued and the caller does not need to block
    (fire-and-forget triggers); otherwise returns the ExecutionResult.
    """
    placement = resolve_placement(nodes, workflow_cache)
    if should_run_in_process(
        cluster_enabled=settings.cluster_enabled,
        placement=placement,
        is_main=identity.is_main(),
    ):
        # Charge the counter even here: forced main work must spend main's quota.
        await run_queue.choose_target(placement)
        return await asyncio.to_thread(
            execute_workflow,
            workflow_id=workflow_id,
            nodes=nodes,
            edges=edges,
            inputs=inputs,
            workflow_cache=workflow_cache,
            test_run=test_run,
            actor_user_id=actor_user_id,
            timeout_seconds=timeout_seconds,
            **executor_kwargs,  # type: ignore[arg-type]
        )

    execution_id = uuid.uuid4()
    queued = run_queue.QueuedRun(
        workflow_id=workflow_id,
        execution_id=execution_id,
        placement=placement,
        inputs=inputs,
        trigger_source=trigger_source,
        actor_user_id=actor_user_id,
        credentials_owner_id=credentials_owner_id,
        test_run=test_run,
        timeout_seconds=timeout_seconds,
    )
    target = await run_queue.enqueue(queued)
    if target:
        await run_queue.notify_queue(target)
    logger.info(
        "Dispatched workflow %s as %s to %s", workflow_id, placement, target or "waiting_for_main"
    )
    return None
```

- [x] **Step 4: Write the claim worker**

Append to `backend/app/services/cluster/dispatch.py`:

```python
class RunQueueWorker:
    """Claims queued rows for this instance and executes them.

    All 8 uvicorn processes run one of these. FOR UPDATE SKIP LOCKED resolves
    the race between them, and the percentage stays meaningful because it is
    applied per instance at enqueue time, not per process at claim time.
    """

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._bus: object | None = None

    async def start(self) -> None:
        if not settings.cluster_enabled or self._task is not None:
            return
        from app.services.cluster.run_queue_bus import QueueWakeBus

        bus = QueueWakeBus(identity.instance_id())
        await bus.start()
        self._bus = bus
        self._running = True
        self._task = asyncio.create_task(self._run_loop(bus))

    async def stop(self) -> None:
        self._running = False
        if self._bus is not None:
            await self._bus.stop()  # type: ignore[attr-defined]
            self._bus = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self, bus: object) -> None:
        while self._running:
            try:
                await bus.wait_for_work()  # type: ignore[attr-defined]
                while self._running:
                    row = await run_queue.claim_next(identity.instance_id())
                    if row is None:
                        break
                    asyncio.create_task(self._execute_claimed(row))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Run queue worker loop failed")
                await asyncio.sleep(1)

    async def _execute_claimed(self, row: WorkflowRunQueue) -> None:
        """Load the graph here rather than carrying it through the queue.

        A queue row holds run parameters only. The workflow itself is read from
        the database at claim time, so an edited workflow is never executed from
        a stale copy, and the row stays small.
        """
        from app.db.session import async_session_maker
        from app.services.credential_access import get_credentials_context

        try:
            async with async_session_maker() as db:
                workflow = (
                    await db.execute(select(Workflow).where(Workflow.id == row.workflow_id))
                ).scalar_one_or_none()
                if workflow is None:
                    await run_queue.complete(
                        row.execution_id, result=None, error="Workflow no longer exists"
                    )
                    return
                credentials_context = await get_credentials_context(db, row.credentials_owner_id)
                nodes = list(workflow.nodes or [])
                edges = list(workflow.edges or [])

            result = await asyncio.to_thread(
                execute_workflow,
                workflow_id=row.workflow_id,
                nodes=nodes,
                edges=edges,
                inputs=row.inputs,
                credentials_context=credentials_context,
                test_run=row.test_run,
                actor_user_id=row.actor_user_id,
                timeout_seconds=row.timeout_seconds,
                execution_id=str(row.execution_id),
            )
            await run_queue.complete(row.execution_id, result=dict(result), error=None)
        except Exception as exc:
            logger.exception("Claimed run failed")
            await run_queue.complete(row.execution_id, result=None, error=str(exc))


run_queue_worker = RunQueueWorker()
```

Add these to the imports at the top of `dispatch.py`:

```python
from sqlalchemy import select

from app.db.models import Workflow, WorkflowRunQueue
```

- [x] **Step 5: Wire the call sites**

Replace the `execute_workflow(...)` call with `await dispatch_workflow(...)` at each of these, keeping every existing argument and adding `credentials_owner_id`:

| File | Line | Trigger |
|---|---|---|
| `backend/app/api/workflows.py` | 2888 endpoint body | API / webhook |
| `backend/app/api/mcp.py` | 1057, 1262 | MCP tool call |
| `backend/app/api/mcp_servers.py` | 560 | MCP server tool call |
| `backend/app/services/cron_scheduler.py` | 112 | Cron |
| `backend/app/api/telegram.py` | 154 | Telegram |
| `backend/app/api/slack.py` | 153 | Slack |
| `backend/app/api/discord.py` | 273 | Discord |
| `backend/app/services/imap_trigger_service.py` | 440 | IMAP |
| `backend/app/services/rabbitmq_consumer.py` | 350 | RabbitMQ |
| `backend/app/services/websocket_trigger_service.py` | 428 | WebSocket |
| `backend/app/services/heym_event_dispatcher.py` | 243 | Heym event bus |

Do **not** touch `execute_workflow_streaming` call sites (`api/workflows.py:3767`, `api/portal.py:466`) or the sub-workflow call in `node_execution/nodes/execute_node.py:79`. A sub-workflow runs inside its parent's process and must not be enqueued separately.

- [x] **Step 6: Start the services**

In `backend/app/main.py`, alongside the existing `lock_service` and recovery service startup:

```python
    await heartbeat_service.start()
    await run_queue_worker.start()
```

and in the shutdown path:

```python
    await run_queue_worker.stop()
    await heartbeat_service.stop()
```

Add the imports `from app.services.cluster.dispatch import run_queue_worker` and `from app.services.cluster.registry import heartbeat_service`.

- [x] **Step 7: Add expiry and release to the leader loop**

In `backend/app/services/cron_scheduler.py`, inside the existing leader-gated pass, after the cron slot cleanup:

```python
                await run_queue.expire_late_rows()
                main = registry.find_main(await registry.list_instances())
                if main is not None and registry.is_live(main, now=datetime.now(timezone.utc)):
                    await run_queue.release_waiting_for_main(main.id)
```

This runs on the leader, which may be a worker while main is down — that is exactly what makes the waiting rows drain when main comes back.

- [x] **Step 8: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_dispatch.py -v`

Expected: PASS, 6 tests.

- [x] **Step 9: Run the full backend suite**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./run_tests.sh`

Expected: PASS. Never run this concurrently with `check.sh` — each starts 189 parallel pytest processes.

- [x] **Step 10: Format, lint, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/services/cluster/dispatch.py backend/app/main.py backend/app/api backend/app/services backend/tests/test_cluster_dispatch.py
git commit -m "feat(cluster): route background runs through the dispatch seam"
```

---

## Task 8: Execution attribution

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/118_add_execution_instance_attribution.py`
- Modify: `backend/app/services/workflow_executor.py`
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_cluster_attribution.py`

- [x] **Step 1: Write the failing test**

```python
"""What the executor records about the instance that ran a workflow."""

import unittest
from unittest.mock import patch

from app.services.cluster import identity
from app.services.cluster.attribution import attribution_fields


class AttributionTests(unittest.TestCase):
    def test_a_clustered_run_records_id_and_name(self) -> None:
        with (
            patch.object(identity.settings, "cluster_enabled", True),
            patch.object(identity.settings, "instance_id", "worker-a"),
            patch.object(identity.settings, "instance_name", "Worker A"),
        ):
            fields = attribution_fields()
        self.assertEqual(fields["executed_by_instance_id"], "worker-a")
        self.assertEqual(fields["executed_by_instance_name"], "Worker A")

    def test_a_single_instance_run_records_nothing(self) -> None:
        """History on a single-instance install must look exactly as it does today."""
        with patch.object(identity.settings, "cluster_enabled", False):
            fields = attribution_fields()
        self.assertIsNone(fields["executed_by_instance_id"])
        self.assertIsNone(fields["executed_by_instance_name"])

    def test_the_name_is_a_snapshot_not_a_reference(self) -> None:
        """Renaming an instance later must not rewrite old history."""
        with (
            patch.object(identity.settings, "cluster_enabled", True),
            patch.object(identity.settings, "instance_id", "worker-a"),
            patch.object(identity.settings, "instance_name", "Old Name"),
        ):
            first = attribution_fields()
        with (
            patch.object(identity.settings, "cluster_enabled", True),
            patch.object(identity.settings, "instance_id", "worker-a"),
            patch.object(identity.settings, "instance_name", "New Name"),
        ):
            second = attribution_fields()
        self.assertEqual(first["executed_by_instance_name"], "Old Name")
        self.assertEqual(second["executed_by_instance_name"], "New Name")
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_attribution.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.cluster.attribution'`.

- [x] **Step 3: Write the attribution helper**

Create `backend/app/services/cluster/attribution.py`:

```python
"""What the executing instance stamps onto a run's history row."""

from __future__ import annotations

from app.config import settings
from app.services.cluster import identity


def attribution_fields() -> dict[str, str | None]:
    """Instance id and a snapshot of its label, or nulls outside a cluster.

    The name is snapshotted rather than joined so history keeps its meaning
    after an instance is renamed or removed from the cluster.
    """
    if not settings.cluster_enabled:
        return {"executed_by_instance_id": None, "executed_by_instance_name": None}
    return {
        "executed_by_instance_id": identity.instance_id(),
        "executed_by_instance_name": identity.instance_name(),
    }
```

- [x] **Step 4: Add the columns to both models**

In `backend/app/db/models.py`, add to `ExecutionHistory` (after `recovered`) and to `ActiveWorkflowExecution` (after `recoverable`):

```python
    executed_by_instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    executed_by_instance_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
```

- [x] **Step 5: Write the migration**

Create `backend/alembic/versions/118_add_execution_instance_attribution.py`:

```python
"""add executing-instance attribution to execution history

Revision ID: 118_add_execution_instance_attribution
Revises: 117_add_workflow_run_queue
Create Date: 2026-08-27 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "118_add_execution_instance_attribution"
down_revision: Union[str, None] = "117_add_workflow_run_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("execution_history", "active_workflow_executions")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("executed_by_instance_id", sa.String(128), nullable=True))
        op.add_column(table, sa.Column("executed_by_instance_name", sa.String(128), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "executed_by_instance_name")
        op.drop_column(table, "executed_by_instance_id")
```

Existing rows stay `NULL`. There is nothing to backfill: history written before this change genuinely has no instance to name.

- [x] **Step 6: Stamp the fields when history is written**

In `backend/app/services/workflow_executor.py`, find every `ExecutionHistory(` construction and add:

```python
            **attribution_fields(),
```

with `from app.services.cluster.attribution import attribution_fields` at the top. Do the same for every `ActiveWorkflowExecution(` construction.

- [x] **Step 7: Expose the fields in the history response schema**

In `backend/app/models/schemas.py`, on the execution-history response model:

```python
    executed_by_instance_id: str | None = None
    executed_by_instance_name: str | None = None
```

- [x] **Step 8: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_attribution.py -v`

Expected: PASS, 3 tests.

- [x] **Step 9: Apply the migration and commit**

```bash
cd backend && uv run alembic upgrade head && uv run ruff format . && uv run ruff check .
git add backend/app/db/models.py backend/alembic/versions/118_add_execution_instance_attribution.py backend/app/services backend/app/models/schemas.py backend/tests/test_cluster_attribution.py
git commit -m "feat(cluster): record the instance that executed each run"
```

---

## Task 9: Admin API

**Files:**
- Create: `backend/app/api/admin_cluster.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_cluster_admin_api.py`

- [x] **Step 1: Write the failing test**

```python
"""Weight validation and the placement-ratio summary."""

import unittest

from app.api.admin_cluster import placement_ratio, validate_weight_map


class WeightValidationTests(unittest.TestCase):
    def test_enabled_weights_totalling_100_are_accepted(self) -> None:
        validate_weight_map({"main": (True, 70), "a": (True, 30)})

    def test_a_total_below_100_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_weight_map({"main": (True, 70), "a": (True, 20)})

    def test_a_total_above_100_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_weight_map({"main": (True, 70), "a": (True, 40)})

    def test_disabled_instances_are_excluded_from_the_total(self) -> None:
        validate_weight_map({"main": (True, 100), "a": (False, 40)})

    def test_a_negative_weight_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_weight_map({"main": (True, 110), "a": (True, -10)})

    def test_no_enabled_instance_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_weight_map({"main": (False, 0)})


class PlacementRatioTests(unittest.TestCase):
    def test_ratio_is_reported_as_percentages(self) -> None:
        ratio = placement_ratio(main_only=25, anywhere=75)
        self.assertEqual(ratio, {"mainOnlyPercent": 25, "anywherePercent": 75})

    def test_no_runs_reports_zero_rather_than_dividing(self) -> None:
        self.assertEqual(placement_ratio(main_only=0, anywhere=0), {"mainOnlyPercent": 0, "anywherePercent": 0})

    def test_an_all_main_only_workload_is_visible(self) -> None:
        """The number that tells an operator the cluster cannot help them."""
        self.assertEqual(placement_ratio(main_only=40, anywhere=0)["mainOnlyPercent"], 100)
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_admin_api.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.admin_cluster'`.

- [x] **Step 3: Add the schemas**

In `backend/app/models/schemas.py`:

```python
class ClusterInstanceResponse(BaseModel):
    id: str
    name: str
    role: str
    enabled: bool
    weight: int
    version: str
    docker_ok: bool
    db_latency_ms: float
    live: bool
    compatible: bool
    heartbeat_at: datetime | None = None


class ClusterInstanceUpdate(BaseModel):
    name: str
    enabled: bool
    weight: int


class ClusterSettingsResponse(BaseModel):
    cluster_enabled: bool
    instances: list[ClusterInstanceResponse]
    placement_ratio: dict[str, int]
```

- [x] **Step 4: Write the router**

Create `backend/app/api/admin_cluster.py`:

```python
"""Admin-only cluster configuration, gated by HEYM_ADMIN_EMAILS."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_instance_admin
from app.config import settings
from app.db.models import ClusterInstance, User, WorkflowRunQueue
from app.db.session import get_db
from app.models.schemas import (
    ClusterInstanceResponse,
    ClusterInstanceUpdate,
    ClusterSettingsResponse,
)
from app.services.cluster import registry

router = APIRouter()


def validate_weight_map(weights: dict[str, tuple[bool, int]]) -> None:
    """Enabled weights must be non-negative and total exactly 100.

    Validated as a whole map so the cluster never sits in a half-saved,
    invalid split.
    """
    if any(weight < 0 for _enabled, weight in weights.values()):
        raise ValueError("Weights cannot be negative.")
    enabled_total = sum(weight for enabled, weight in weights.values() if enabled)
    if not any(enabled for enabled, _weight in weights.values()):
        raise ValueError("At least one instance must be enabled.")
    if enabled_total != 100:
        raise ValueError(f"Enabled instance weights must total 100, got {enabled_total}.")


def placement_ratio(*, main_only: int, anywhere: int) -> dict[str, int]:
    """How much of the recent workload could not leave main."""
    total = main_only + anywhere
    if total == 0:
        return {"mainOnlyPercent": 0, "anywherePercent": 0}
    main_percent = round(main_only * 100 / total)
    return {"mainOnlyPercent": main_percent, "anywherePercent": 100 - main_percent}


@router.get("", response_model=ClusterSettingsResponse)
async def read_cluster(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ClusterSettingsResponse:
    require_instance_admin(current_user)
    instances = await registry.list_instances()
    now = datetime.now(timezone.utc)
    main = registry.find_main(instances)

    since = now - timedelta(hours=24)
    counts = dict(
        (
            await db.execute(
                select(WorkflowRunQueue.placement, func.count())
                .where(WorkflowRunQueue.enqueued_at >= since)
                .group_by(WorkflowRunQueue.placement)
            )
        ).all()
    )

    return ClusterSettingsResponse(
        cluster_enabled=settings.cluster_enabled,
        instances=[
            ClusterInstanceResponse(
                id=i.id,
                name=i.name,
                role=i.role,
                enabled=i.enabled,
                weight=i.weight,
                version=i.version,
                docker_ok=i.docker_ok,
                db_latency_ms=i.db_latency_ms,
                live=registry.is_live(i, now=now),
                compatible=main is not None and registry.is_compatible_with(i, main),
                heartbeat_at=i.heartbeat_at,
            )
            for i in sorted(instances, key=lambda i: (i.role != "main", i.id))
        ],
        placement_ratio=placement_ratio(
            main_only=counts.get("main_only", 0), anywhere=counts.get("anywhere", 0)
        ),
    )


@router.put("/instances", response_model=ClusterSettingsResponse)
async def update_instances(
    updates: dict[str, ClusterInstanceUpdate],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClusterSettingsResponse:
    require_instance_admin(current_user)
    try:
        validate_weight_map({k: (v.enabled, v.weight) for k, v in updates.items()})
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    for instance_id, update in updates.items():
        row = (
            await db.execute(select(ClusterInstance).where(ClusterInstance.id == instance_id))
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown instance: {instance_id}"
            )
        row.name = update.name.strip() or row.id
        row.enabled = update.enabled
        row.weight = update.weight
    await db.commit()
    return await read_cluster(current_user=current_user, db=db)


@router.delete("/instances/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instance(
    instance_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    require_instance_admin(current_user)
    row = (
        await db.execute(select(ClusterInstance).where(ClusterInstance.id == instance_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown instance")
    if row.role == "main":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The main instance cannot be removed."
        )
    await db.delete(row)
    await db.commit()
```

- [x] **Step 5: Mount the router**

In `backend/app/main.py`, beside the SSO admin router at line 314:

```python
app.include_router(admin_cluster.router, prefix="/api/admin/cluster", tags=["Cluster Admin"])
```

with `admin_cluster` added to the api import list.

- [x] **Step 6: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_admin_api.py -v`

Expected: PASS, 9 tests.

- [x] **Step 7: Format, lint, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/api/admin_cluster.py backend/app/main.py backend/app/models/schemas.py backend/tests/test_cluster_admin_api.py
git commit -m "feat(cluster): admin API for instances, weights and placement ratio"
```

---

## Task 10: Admin UI

**Files:**
- Create: `frontend/src/types/cluster.ts`
- Create: `frontend/src/services/cluster.ts`
- Create: `frontend/src/components/Layout/settings/ClusterInstanceRow.vue`
- Create: `frontend/src/components/Layout/settings/ClusterSettingsTab.vue`
- Modify: `frontend/src/components/Layout/UserSettingsDialog.vue`

Follow `SsoSettingsTab.vue` exactly: same `ref` state shape, same load/save error handling, same `SettingsToggle` component. Keep `ClusterSettingsTab.vue` under 300 lines by putting row rendering in `ClusterInstanceRow.vue`.

- [x] **Step 1: Add the types**

Create `frontend/src/types/cluster.ts`:

```typescript
export interface ClusterInstance {
  id: string;
  name: string;
  role: string;
  enabled: boolean;
  weight: number;
  version: string;
  docker_ok: boolean;
  db_latency_ms: number;
  live: boolean;
  compatible: boolean;
  heartbeat_at: string | null;
}

export interface ClusterPlacementRatio {
  mainOnlyPercent: number;
  anywherePercent: number;
}

export interface ClusterSettings {
  cluster_enabled: boolean;
  instances: ClusterInstance[];
  placement_ratio: ClusterPlacementRatio;
}

export interface ClusterInstanceUpdate {
  name: string;
  enabled: boolean;
  weight: number;
}
```

- [x] **Step 2: Add the API client**

Create `frontend/src/services/cluster.ts`:

```typescript
import api from "@/services/api";

import type { ClusterInstanceUpdate, ClusterSettings } from "@/types/cluster";

export async function getClusterSettings(): Promise<ClusterSettings> {
  const { data } = await api.get<ClusterSettings>("/admin/cluster");
  return data;
}

export async function saveClusterInstances(
  updates: Record<string, ClusterInstanceUpdate>,
): Promise<ClusterSettings> {
  const { data } = await api.put<ClusterSettings>("/admin/cluster/instances", updates);
  return data;
}

export async function removeClusterInstance(instanceId: string): Promise<void> {
  await api.delete(`/admin/cluster/instances/${instanceId}`);
}
```

Check the import style in `frontend/src/services/sso.ts` and match it — if that file imports `api` differently, use its form.

- [x] **Step 3: Write the row component**

Create `frontend/src/components/Layout/settings/ClusterInstanceRow.vue`:

```vue
<script setup lang="ts">
import Input from "@/components/ui/Input.vue";
import SettingsToggle from "@/components/Layout/settings/SettingsToggle.vue";

import type { ClusterInstance } from "@/types/cluster";

const props = defineProps<{ instance: ClusterInstance }>();

const emit = defineEmits<{
  (e: "update", value: { name: string; enabled: boolean; weight: number }): void;
}>();

function emitUpdate(patch: Partial<{ name: string; enabled: boolean; weight: number }>): void {
  emit("update", {
    name: props.instance.name,
    enabled: props.instance.enabled,
    weight: props.instance.weight,
    ...patch,
  });
}

function statusLabel(instance: ClusterInstance): string {
  if (!instance.compatible) return "Incompatible";
  if (!instance.live) return "Offline";
  return "Live";
}

function statusClass(instance: ClusterInstance): string {
  if (!instance.compatible) return "text-destructive";
  if (!instance.live) return "text-muted-foreground";
  return "text-emerald-600 dark:text-emerald-400";
}
</script>

<template>
  <div class="grid grid-cols-6 items-center gap-3 border-b border-border py-2 text-sm">
    <Input
      :model-value="instance.name"
      class="col-span-2"
      @update:model-value="(v: string) => emitUpdate({ name: v })"
    />
    <span class="text-muted-foreground">{{ instance.role }}</span>
    <span :class="statusClass(instance)">
      {{ statusLabel(instance) }} · {{ Math.round(instance.db_latency_ms) }} ms
    </span>
    <SettingsToggle
      :model-value="instance.enabled"
      @update:model-value="(v: boolean) => emitUpdate({ enabled: v })"
    />
    <Input
      type="number"
      min="0"
      max="100"
      :model-value="String(instance.weight)"
      @update:model-value="(v: string) => emitUpdate({ weight: Number(v) || 0 })"
    />
  </div>
</template>
```

Check `SettingsToggle.vue`'s prop and event names before wiring it and match them.

- [x] **Step 4: Write the tab**

Create `frontend/src/components/Layout/settings/ClusterSettingsTab.vue`:

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RefreshCw } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import ClusterInstanceRow from "@/components/Layout/settings/ClusterInstanceRow.vue";
import { getClusterSettings, saveClusterInstances } from "@/services/cluster";
import type { ClusterInstance, ClusterInstanceUpdate, ClusterSettings } from "@/types/cluster";

const config = ref<ClusterSettings | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref<string | null>(null);

const enabledTotal = computed((): number =>
  (config.value?.instances ?? [])
    .filter((i: ClusterInstance) => i.enabled)
    .reduce((sum: number, i: ClusterInstance) => sum + i.weight, 0),
);

const canSave = computed((): boolean => enabledTotal.value === 100);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    config.value = await getClusterSettings();
  } catch {
    error.value = "Failed to load cluster settings.";
  } finally {
    loading.value = false;
  }
}

function applyUpdate(instanceId: string, patch: ClusterInstanceUpdate): void {
  const target = config.value?.instances.find((i: ClusterInstance) => i.id === instanceId);
  if (!target) return;
  target.name = patch.name;
  target.enabled = patch.enabled;
  target.weight = patch.weight;
}

async function handleSave(): Promise<void> {
  if (!config.value || !canSave.value) return;
  saving.value = true;
  error.value = null;
  try {
    const updates: Record<string, ClusterInstanceUpdate> = {};
    for (const instance of config.value.instances) {
      updates[instance.id] = {
        name: instance.name,
        enabled: instance.enabled,
        weight: instance.weight,
      };
    }
    config.value = await saveClusterInstances(updates);
  } catch {
    error.value = "Failed to save cluster settings.";
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-start justify-between gap-4">
      <p class="text-sm text-muted-foreground">
        Share background workflow execution across the instances connected to this database.
        Work that touches files, coding-agent workspaces, or plugins always runs on the main
        instance.
      </p>
      <Button variant="outline" size="sm" :disabled="loading" @click="load">
        <RefreshCw class="mr-2 h-4 w-4" />
        Refresh
      </Button>
    </div>

    <p v-if="!config?.cluster_enabled" class="text-sm text-muted-foreground">
      Load distribution is off. Set <code>HEYM_CLUSTER_ENABLED=true</code> on the main instance
      to turn it on.
    </p>

    <p v-if="config" class="text-sm text-muted-foreground">
      Over the last 24 hours, {{ config.placement_ratio.mainOnlyPercent }}% of runs could only
      execute on the main instance. Percentages cannot move that work.
    </p>

    <div v-if="config" class="rounded-md border border-border p-3">
      <div
        class="grid grid-cols-6 gap-3 border-b border-border pb-2 text-xs uppercase text-muted-foreground"
      >
        <span class="col-span-2">Name</span>
        <span>Role</span>
        <span>Status</span>
        <span>Enabled</span>
        <span>Weight</span>
      </div>
      <ClusterInstanceRow
        v-for="instance in config.instances"
        :key="instance.id"
        :instance="instance"
        @update="(patch) => applyUpdate(instance.id, patch)"
      />
    </div>

    <p v-if="!canSave" class="text-sm text-destructive">
      Enabled weights total {{ enabledTotal }}. They must total 100 before you can save.
    </p>
    <p v-if="error" class="text-sm text-destructive">{{ error }}</p>

    <Button :disabled="!canSave || saving" @click="handleSave">Save</Button>
  </div>
</template>
```

- [x] **Step 5: Register the tab**

In `frontend/src/components/Layout/UserSettingsDialog.vue`, mirroring the SSO tab at lines 26, 41, 447 and 865:

```typescript
import ClusterSettingsTab from "@/components/Layout/settings/ClusterSettingsTab.vue";
```

add `| "cluster"` to the tab union, add a tab button beside the SSO one, and:

```vue
      <div v-else-if="activeTab === 'cluster' && authStore.user?.is_admin">
        <ClusterSettingsTab />
      </div>
```

- [x] **Step 6: Verify**

```bash
cd frontend && bun run lint && bun run typecheck && bun run test
```

Expected: all PASS. Per the repository's standing preference there are no new frontend unit tests for this UI; behavior is covered by the E2E spec in Task 12.

- [x] **Step 7: Commit**

```bash
git add frontend/src/types/cluster.ts frontend/src/services/cluster.ts frontend/src/components/Layout/settings frontend/src/components/Layout/UserSettingsDialog.vue
git commit -m "feat(cluster): Settings tab for instances and weights"
```

---

## Task 11: Instance name and instance filter in the execution dialogs

Both history dialogs already filter by trigger source, and they do it
differently: the canvas dialog sends the filter to the server and refetches
(`ExecutionHistoryDialog.vue:170`, `:241`, `:357`), while the home dialog
filters the loaded page in memory (`ExecutionHistoryAllDialog.vue:180-189`).
Mirror each dialog's own approach. Making the instance filter behave differently
from the trigger-source filter sitting next to it in the same dialog would be
worse than either choice on its own.

Both dropdowns build their options from the entries already loaded rather than
from a separate endpoint. Do the same for instances: an instance that has left
the cluster still appears while its runs are on screen, and no extra request is
needed. The option's **value is the instance id** and its **label is the name**,
because two instances can be renamed to the same label but their ids never
collide.

**Files:**
- Modify: `backend/alembic/versions/118_add_execution_instance_attribution.py`
- Modify: `backend/app/api/workflows.py:3455`
- Modify: `frontend/src/services/api.ts` (the `getHistory` client)
- Modify: `frontend/src/stores/workflow.ts:437`, `:472`
- Modify: `frontend/src/components/Panels/ExecutionHistoryDialog.vue`
- Modify: `frontend/src/components/Panels/ExecutionHistoryAllDialog.vue`
- Modify: the execution history TypeScript types
- Test: `backend/tests/test_cluster_history_filter.py`

- [x] **Step 1: Write the failing test**

```python
"""The instance filter on the per-workflow history endpoint."""

import unittest
import uuid

from sqlalchemy import select

from app.db.models import ExecutionHistory
from app.api.workflows import apply_instance_filter


class InstanceFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = select(ExecutionHistory).where(
            ExecutionHistory.workflow_id == uuid.uuid4()
        )

    def test_no_instance_leaves_the_query_untouched(self) -> None:
        self.assertIs(apply_instance_filter(self.base, None), self.base)

    def test_an_empty_instance_leaves_the_query_untouched(self) -> None:
        self.assertIs(apply_instance_filter(self.base, "   "), self.base)

    def test_an_instance_id_adds_a_where_clause(self) -> None:
        filtered = apply_instance_filter(self.base, "worker-a")
        self.assertIn("executed_by_instance_id", str(filtered))

    def test_the_filter_matches_on_id_not_name(self) -> None:
        """Names are snapshots and can repeat; ids cannot."""
        filtered = str(apply_instance_filter(self.base, "worker-a"))
        self.assertNotIn("executed_by_instance_name", filtered)
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_history_filter.py -v`

Expected: FAIL with `ImportError: cannot import name 'apply_instance_filter'`.

- [x] **Step 3: Index the column**

The filter runs against `execution_history`, which grows without bound, so it
needs an index. In `backend/alembic/versions/118_add_execution_instance_attribution.py`,
add to `upgrade()` after the `add_column` loop:

```python
    op.create_index(
        "ix_execution_history_executed_by_instance_id",
        "execution_history",
        ["executed_by_instance_id"],
    )
```

and to `downgrade()`, before the `drop_column` loop:

```python
    op.drop_index(
        "ix_execution_history_executed_by_instance_id", table_name="execution_history"
    )
```

Add `index=True` to the `executed_by_instance_id` column on `ExecutionHistory`
in `backend/app/db/models.py` so the model matches the migration. Leave the
`ActiveWorkflowExecution` copy unindexed — that table holds only in-flight runs
and is small.

If migration 118 has already been applied, re-run it:

```bash
cd backend && uv run alembic downgrade 117_add_workflow_run_queue && uv run alembic upgrade head
```

- [x] **Step 4: Add the filter helper and the query parameter**

In `backend/app/api/workflows.py`, beside the other history helpers:

```python
def apply_instance_filter(query: Select, instance_id: str | None) -> Select:
    """Narrow a history query to one executing instance.

    Filters on the id rather than the stored name: the name is a snapshot taken
    when the run finished, so two rows can carry different names for the same
    instance after a rename, and different instances can share a name.
    """
    cleaned = (instance_id or "").strip()
    if not cleaned:
        return query
    return query.where(ExecutionHistory.executed_by_instance_id == cleaned)
```

Import `Select` from `sqlalchemy.sql` if it is not already imported.

Then extend `get_execution_history` at line 3455:

```python
    instance_id: str | None = Query(default=None),
```

and apply it to both the count query and the page query, next to the existing
`trigger_source` filter at line 3494:

```python
    total_query = apply_instance_filter(total_query, instance_id)
    history_query = apply_instance_filter(history_query, instance_id)
```

Applying it to the count query as well is what keeps pagination honest — a
filtered list with an unfiltered total shows a "load more" button that loads
nothing.

- [x] **Step 5: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_cluster_history_filter.py -v`

Expected: PASS, 4 tests.

- [x] **Step 6: Format, lint, commit the backend half**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/api/workflows.py backend/app/db/models.py backend/alembic/versions/118_add_execution_instance_attribution.py backend/tests/test_cluster_history_filter.py
git commit -m "feat(cluster): filter workflow history by executing instance"
```

- [x] **Step 7: Extend the TypeScript types**

```bash
cd frontend && grep -rn "trigger_source" src/types/ | head
```

Add to every execution-history interface that already carries `trigger_source`
— both the per-workflow entry and the all-history entry:

```typescript
  executed_by_instance_id?: string | null;
  executed_by_instance_name?: string | null;
```

- [x] **Step 8: Pass the filter through the API client and the store**

In `frontend/src/services/api.ts`, add an optional `instanceId` argument to
`getHistory` and send it as the `instance_id` query parameter, following how the
existing `trigger_source` parameter is sent.

In `frontend/src/stores/workflow.ts`, extend both options objects — line 437 and
line 472 — so the filter survives pagination:

```typescript
  async function fetchExecutionHistory(
    triggerSource?: string,
    {
      keepDetails = false,
      search,
      instanceId,
    }: { keepDetails?: boolean; search?: string; instanceId?: string } = {},
  ): Promise<void> {
```

```typescript
  async function fetchMoreExecutionHistory(
    triggerSource?: string,
    { search, instanceId }: { search?: string; instanceId?: string } = {},
  ): Promise<void> {
```

Pass `instanceId` into both `workflowApi.getHistory(...)` calls. Forgetting the
second one gives a filtered first page and an unfiltered second page.

- [x] **Step 9: Add the filter to the canvas dialog**

In `frontend/src/components/Panels/ExecutionHistoryDialog.vue`, beside
`selectedTriggerSource` at line 60:

```typescript
const selectedInstanceId = ref<string | undefined>(undefined);
```

Add the options computed, mirroring `triggerSourceOptions` at line 121 but
keyed by id and labelled by name:

```typescript
const instanceOptions = computed<Array<{ value: string | undefined; label: string }>>(() => {
  const names = new Map<string, string>();

  for (const entry of executionHistoryList.value) {
    const id = entry.executed_by_instance_id?.trim();
    if (!id || names.has(id)) continue;
    // History is newest first, so the first name seen for an id is the latest one.
    names.set(id, entry.executed_by_instance_name?.trim() || id);
  }

  const selectedId = selectedInstanceId.value?.trim();
  if (selectedId && !names.has(selectedId)) {
    names.set(selectedId, selectedId);
  }

  return [
    { value: undefined, label: "All Instances" },
    ...Array.from(names.entries())
      .sort(([, left], [, right]) => left.localeCompare(right))
      .map(([id, name]) => ({ value: id, label: name })),
  ];
});
```

Include it in `hasActiveFilters` at line 146, clear it wherever
`selectedTriggerSource` is cleared (lines 232 and 321), pass
`{ instanceId: selectedInstanceId.value }` in the fetch calls at lines 170 and
357, and add a watcher beside the one at line 241:

```typescript
watch(selectedInstanceId, async () => {
  await workflowStore.fetchExecutionHistory(selectedTriggerSource.value, {
    search: searchQuery.value.trim() || undefined,
    instanceId: selectedInstanceId.value,
  });
});
```

Render the select beside the trigger-source one at line 668, using the same
component and the same visibility rule so it stays hidden on a single-instance
install:

```vue
        <Select
          v-if="instanceOptions.length > 1 || selectedInstanceId"
          v-model="selectedInstanceId"
          :options="instanceOptions"
        />
```

Match the surrounding `Select` usage — copy the props actually used on the
trigger-source select on line 668, since it may take more than `options`.

- [x] **Step 10: Add the filter to the home dialog**

In `frontend/src/components/Panels/ExecutionHistoryAllDialog.vue`, add the same
`selectedInstanceId` ref and the same `instanceOptions` computed, but built over
`executionHistory.value` rather than `executionHistoryList.value`.

This dialog filters in memory, so extend `filteredExecutionHistory` at line 180
instead of refetching:

```typescript
const filteredExecutionHistory = computed<AllExecutionHistoryEntryLight[]>(() => {
  let entries = executionHistory.value;

  if (selectedTriggerSource.value) {
    entries = entries.filter((entry) => entry.trigger_source === selectedTriggerSource.value);
  }

  if (selectedInstanceId.value) {
    entries = entries.filter(
      (entry) => entry.executed_by_instance_id === selectedInstanceId.value,
    );
  }

  return entries;
});
```

Add it to `hasActiveFilters` at line 191 and render the select beside the
trigger-source one at line 812 with the same visibility rule.

Like the trigger-source filter it sits next to, this one applies to the entries
already loaded, not to the whole table.

- [x] **Step 11: Render the instance chip in both dialogs**

Beside the existing trigger-source chip (`ExecutionHistoryDialog.vue:859`,
`ExecutionHistoryAllDialog.vue:1006`):

```vue
                <span
                  v-if="entry.executed_by_instance_name"
                  :title="entry.executed_by_instance_id ?? ''"
                  class="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
                >
                  {{ entry.executed_by_instance_name }}
                </span>
```

The `v-if` is what keeps a single-instance install visually unchanged: the
fields are null, no chip renders, and the select stays hidden.

- [x] **Step 12: Verify**

```bash
cd frontend && bun run lint && bun run typecheck && bun run test
```

Expected: all PASS.

- [x] **Step 13: Commit**

```bash
git add frontend/src/components/Panels frontend/src/types frontend/src/services/api.ts frontend/src/stores/workflow.ts
git commit -m "feat(cluster): filter and label run history by executing instance"
```

---

## Task 12: End-to-end coverage

**Files:**
- Create: `frontend/e2e/cluster-settings.spec.ts`

- [x] **Step 1: Write the spec**

```typescript
import { expect, test } from "@playwright/test";

import { prepareAuthenticatedPage } from "./support";

test.describe("Cluster settings", () => {
  test("weights that do not total 100 cannot be saved", async ({ page }) => {
    await prepareAuthenticatedPage(page);
    await page.getByRole("button", { name: "Settings" }).click();
    await page.getByRole("button", { name: "Instances" }).click();

    const weightInput = page.getByRole("spinbutton").first();
    await weightInput.fill("50");

    await expect(page.getByText(/must total 100/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  test("the placement ratio is shown", async ({ page }) => {
    await prepareAuthenticatedPage(page);
    await page.getByRole("button", { name: "Settings" }).click();
    await page.getByRole("button", { name: "Instances" }).click();

    await expect(page.getByText(/could only\s+execute on the main instance/)).toBeVisible();
  });
});

test.describe("Run history instance filter", () => {
  test("the instance filter is hidden on a single-instance install", async ({ page }) => {
    await prepareAuthenticatedPage(page);
    await page.getByRole("button", { name: "History" }).click();

    // No run carries an instance, so neither the chip nor the select renders.
    await expect(page.getByRole("combobox", { name: /instance/i })).toHaveCount(0);
  });
});
```

The second spec is the one that protects existing users: it fails if the new
select ever renders on an install that has no cluster.

Open `frontend/e2e/support.ts` first and match how other specs open the settings dialog — the selectors above assume accessible names that may differ.

- [x] **Step 2: Run the spec**

```bash
./run_e2e.sh cluster-settings
```

Expected: PASS. If unrelated specs fail, re-run them in isolation before believing a regression — `getByLabel('Name')` collisions make the full suite flaky locally.

- [x] **Step 3: Commit**

```bash
git add frontend/e2e/cluster-settings.spec.ts
git commit -m "test(cluster): e2e coverage for the instances settings tab"
```

---

## Task 13: Documentation, AGENTS.md rule, release tour

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Create: `frontend/src/docs/content/reference/cluster.md`
- Modify: `frontend/src/docs/content/reference/features.md`
- Modify: `frontend/src/docs/manifest.ts`
- Modify: `frontend/src/docs/content/reference/user-settings.md`
- Modify: `.env.example`, `ENVIRONMENT-VARIABLES.md`
- Modify: `frontend/src/features/release-tour/releaseRegistry.ts`
- Modify: `frontend/src/features/release-tour/tourVisuals.ts`
- Create: `frontend/src/features/release-tour/components/visuals/ClusterInstancesTourVisual.vue`

- [x] **Step 1: Add the AGENTS.md rule**

Insert into `AGENTS.md` at the end of the `### Node and operation integration` section:

```markdown
### Node placement in a multi-instance cluster
Every node type must declare where it may run.
`backend/app/services/cluster/node_placement.py` holds one entry per node type;
`backend/tests/test_cluster_node_placement.py` fails the build when a node
registered in `node_execution/registry.py` has no entry. There is no default —
a missing entry is a build failure, not a silent fallback to the main instance.

Declare `MAIN_ONLY` when the node:
- reads or writes `FILE_STORAGE_DIR` (Heym Drive, attachments, generated files),
- leaves state on local disk that a later run reads back (coding-agent
  workspaces resumed through `workspace_path`),
- depends on something installed per instance rather than baked into the image
  (plugins).

Declare `ANYWHERE` otherwise — including nodes that open a Docker sandbox. Every
instance in a cluster runs the same image with its own Docker socket, so a
sandbox is not a reason to pin a run to the main instance.

When placement depends on configuration rather than node type — `agent` with a
skill tool attached — express it as a predicate over the node's own data in the
same module. Never branch on node type in the scheduler.
```

- [x] **Step 2: Add the environment variables**

In `.env.example` and `ENVIRONMENT-VARIABLES.md`:

```
# Load distribution across instances sharing this database.
HEYM_CLUSTER_ENABLED=false
HEYM_INSTANCE_ROLE=main
HEYM_INSTANCE_NAME=
HEYM_INSTANCE_ID=
```

Document that every instance must share identical `SECRET_KEY` and
`ENCRYPTION_KEY` values, and that ingress must point only at the main instance.

- [x] **Step 3: Write the docs page**

Create `frontend/src/docs/content/reference/cluster.md` covering, in this order:
roles and the four environment variables; that leader election is separate from
the main role; the placement rule with the MAIN_ONLY table from the design doc;
how to choose percentages, including that main's percentage is a ceiling and
that MAIN_ONLY work spends its quota; the 24-hour placement ratio and what a high
value means; that both history dialogs name and can filter by the executing
instance, and that the home dialog's filter applies to the loaded page while the
canvas dialog's is applied by the server; the key-alignment requirement; the
egress-IP warning for IP-allowlisted APIs; and the constraint that ingress
points only at main.

Do not describe how to build a highly available deployment.

- [x] **Step 4: Register the page and add the feature entry**

In `frontend/src/docs/manifest.ts`, register `reference/cluster` beside the `sso`
entry. In `frontend/src/docs/content/reference/features.md`, add a
`### [Load Distribution](./cluster.md)` section next to `### [Single Sign-On](./sso.md)`
at line 640, with a matching See-also line. Add the Instances tab to
`frontend/src/docs/content/reference/user-settings.md`.

- [x] **Step 5: Add the README entry**

In `README.md`, after the `**OIDC SSO Login**` bullet at line 193:

```markdown
- **Load Distribution** — Run two or more Heym instances against one database and split background workflow execution between them by percentage, configured from **Settings → Instances**. Postgres is the only channel between instances; no broker and no direct connection between them is required
```

Add a sentence to **Production Readiness** (line 380) pointing at the cluster docs page. Do not modify the **No Enterprise Gatekeeping** section.

- [x] **Step 6: Build the tour visual**

Create `frontend/src/features/release-tour/components/visuals/ClusterInstancesTourVisual.vue`
as mock UI only: a three-row instances table with Tailwind semantic tokens, using
`useCycleStep` to animate one instance going offline and the remaining weights
renormalizing. No production API calls, no host-page state, no motion library.

Register it in `frontend/src/features/release-tour/tourVisuals.ts`:

```typescript
import ClusterInstancesTourVisual from "@/features/release-tour/components/visuals/ClusterInstancesTourVisual.vue";
```

```typescript
  "cluster-instances": ClusterInstancesTourVisual,
```

- [x] **Step 7: Add the release entry**

The newest release `2026.09` has already shipped (`tourEnabled: true`), so this
starts a new entry at the top of `RELEASE_REGISTRY` in
`frontend/src/features/release-tour/releaseRegistry.ts`:

```typescript
  {
    releaseId: "2026.10",
    publishedAt: new Date("2026-08-27T00:00:00Z"),
    headline: "Share the load across more than one instance",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: false,
      sectionOrder: ["cluster-load-distribution"],
    },
    sections: [
      {
        id: "cluster-load-distribution",
        title: "Split execution across instances",
        blocks: [
          {
            type: "prose",
            markdown:
              "Point a second Heym instance at the same database and it joins as a worker. Background runs - cron, webhooks, MCP tool calls, chat triggers - are shared between the instances by a percentage you set under **Settings → Instances**. The instances never talk to each other directly: Postgres carries the work, so a worker needs no open port and no route back to the main instance.",
          },
          {
            type: "prose",
            markdown:
              "Work that touches local files, a coding-agent workspace, or an installed plugin always runs on the main instance, and the settings panel shows how much of your last 24 hours that was. Every run in History now names the instance that executed it, and both history dialogs let you filter down to one instance.",
          },
        ],
        tour: {
          description:
            "Add worker instances against the same database and split background execution between them by percentage, with per-instance status, latency, and version in one table.",
          useCases: [
            "Keep heavy agent and crawler runs off the machine serving the UI",
            "Take an instance out of rotation for maintenance without stopping work",
            "See which instance executed any run, and filter history down to one",
          ],
          tourVisual: "cluster-instances",
          docTarget: {
            categoryId: "reference",
            slug: "cluster",
            title: "Load Distribution",
          },
        },
      },
    ],
  },
```

Flip `tourEnabled` to `true` in the release commit, not before.

- [x] **Step 8: Keep the E2E seed aligned**

`frontend/e2e/support.ts` seeds the current tour as seen so the auto-open panel
does not intercept clicks. Update the seeded versioned id to match the new
`releaseId`, as described in the release-tour section of `AGENTS.md`.

- [x] **Step 9: Verify the registry test still passes**

```bash
cd frontend && bun run test -- releaseTourMapper
```

Expected: PASS. A `tourVisual` key with no entry in `tourVisuals.ts` fails here
rather than silently falling back to the neutral visual.

- [x] **Step 10: Full verification**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh
```

Expected: PASS. Commit any formatting-only diffs together with the change.

- [x] **Step 11: Commit**

```bash
git add AGENTS.md README.md .env.example ENVIRONMENT-VARIABLES.md frontend/src/docs frontend/src/features/release-tour frontend/e2e/support.ts
git commit -m "docs(cluster): load distribution docs, placement rule, release tour"
```

---

## Manual verification

The automated tests cover the pure logic. These two need two real processes.

- [x] **Two instances, one database**

Start a second backend against the same Postgres with
`HEYM_INSTANCE_ROLE=worker HEYM_INSTANCE_NAME="Worker A" HEYM_CLUSTER_ENABLED=true`
and the same `SECRET_KEY` and `ENCRYPTION_KEY`, on a different port. Open
**Settings → Instances**: both rows appear, both Live, with a latency reading.
Set 50/50, save, then trigger a webhook workflow twenty times and confirm History
names both instances roughly evenly.

- [x] **Key mismatch is visible**

Restart the worker with a different `ENCRYPTION_KEY`. Its row must show
Incompatible and stop receiving work; every run returns to main. This is the
failure this design exists to make visible — confirm the operator can see the
cause without reading logs.
