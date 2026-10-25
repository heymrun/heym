# Per-Workflow Concurrency Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let workflow editors cap concurrent production runs per workflow. Runs over the cap wait in a durable, cluster-wide FIFO queue. HTTP and MCP callers get an execution id, a status URL and their queue position immediately, and poll for the result.

**Architecture:** A new `workflow_concurrency_slots` table counts running production runs. Waiting runs are `held` rows in the existing `workflow_run_queue`. Admission, release and promotion run in one service module, under a per-workflow `pg_advisory_xact_lock`. Promotion turns a held row into an ordinary `queued` run. The existing `RunQueueWorker`, now started on every install, executes it and writes history. The gate sits in `dispatch_workflow` (every trigger), the SSE execute endpoint and both Portal execute endpoints.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, PostgreSQL 16 advisory locks and sequences, Alembic, pytest with `unittest`, Vue 3 `<script setup>`, Pinia, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-25-workflow-concurrency-limit-design.md`. Read it first.

---

## Ground rules for every task

- Backend commands run from `backend/`. Frontend commands run from `frontend/`.
- Backend tests use `unittest.TestCase` / `unittest.IsolatedAsyncioTestCase`, as `AGENTS.md` requires.
- Real-Postgres tests skip when no database is reachable. To run them locally, start a throwaway database first:
  ```bash
  docker run -d --rm --name heym-concurrency-pg -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=heym -p 6543:5432 postgres:16
  export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:6543/heym
  cd backend && uv run alembic upgrade head
  ```
  Docker on this machine is OrbStack (`orb start`). Export `SECRET_KEY=test-secret-key-for-tests-only-32-bytes` when it is not set.
- After every backend task: `uv run ruff check . && uv run ruff format --check .`
- After every frontend task: `bun run lint && bun run typecheck`.
- Commit after every task. Commit messages end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Recent public-repo
  PRs went out without attribution, so confirm with the user before pushing.
- No Turkish text in code, comments or docs.

## File map

| File | Responsibility |
|---|---|
| `backend/alembic/versions/143_workflow_concurrency.py` (new) | Settings columns, slots table, sequence, queue columns |
| `backend/app/db/models.py` | `Workflow` settings columns, `WorkflowConcurrencySlot`, `WorkflowRunQueue` columns |
| `backend/app/models/schemas.py` | `WorkflowUpdate` / `WorkflowResponse` fields, `ActiveExecutionItem` queued fields, `WorkflowExecutionStatusResponse` |
| `backend/app/services/workflow_concurrency.py` (new) | All admission, release, promotion, expiry, cancel, status and listing logic |
| `backend/app/services/queued_run_stream.py` (new) | SSE generator for a held run (SSE endpoint and Portal) |
| `backend/app/services/mcp_execution_status.py` (new) | `heym_execution_status` tool definition, queued tool text, tool call |
| `backend/app/services/cluster/run_queue.py` | New statuses, `run_options` on `QueuedRun`, `is_terminal` |
| `backend/app/services/cluster/dispatch.py` | Gate in `dispatch_workflow`, worker changes |
| `backend/app/services/workflow_executor.py` | `ExecutionResult.allow_downstream_futures()` |
| `backend/app/services/cron_scheduler.py` | Concurrency sweep; run-queue sweeps without a cluster |
| `backend/app/main.py` | Unchanged; `RunQueueWorker.start` stops gating on the cluster flag |
| `backend/app/api/workflows.py` | Settings save and promote, HTTP 202/429, status endpoint, SSE gate, cancel of held runs |
| `backend/app/api/portal.py` | Portal stream and non-stream gate, cancel of held runs |
| `backend/app/api/mcp.py`, `backend/app/api/mcp_servers.py` | Queued tool result, status tool |
| `backend/app/services/active_execution_overview.py` | Queued rows in `/executions/active` |
| `backend/app/services/execution_recovery.py` | Release on `_finalize` |
| 12 trigger call sites | Pass `concurrency_limit` to `dispatch_workflow` |
| `frontend/src/types/workflow.ts`, `frontend/src/services/api.ts` | Fields, queued SSE callback |
| `frontend/src/components/Panels/propertiesPanel/concurrencySettings.ts` (new) | Pure helpers for the settings form |
| `frontend/src/components/Panels/propertiesPanel/WorkflowConcurrencySettings.vue` (new) | Settings form |
| `frontend/src/components/Panels/propertiesPanel/useWorkflowConcurrencySettings.ts` (new) | Optimistic save with rollback |
| `frontend/src/components/Panels/activeExecutionStatus.ts` (new) | Label for running / pending / queued rows |
| `frontend/src/components/Panels/ActiveExecutionStatusLabel.vue` (new) | Shared badge used by both history dialogs |
| `frontend/src/stores/quickDrawer.ts`, `frontend/src/views/ChatPortalView.vue` | Waiting display |
| `frontend/src/features/release-tour/*` | New release, visual, trim to five sections |
| `frontend/e2e/workflow-concurrency.spec.ts` (new) | Settings persistence and a queued run in History |
| `frontend/src/docs/content/**` | Documentation |

---

### Task 0: Branch and baseline

- [ ] **Step 1: Update and branch**

```bash
git checkout main && git pull --ff-only
git checkout -b feat/workflow-concurrency-limit
```

- [ ] **Step 2: Baseline the suites you will touch**

```bash
cd backend && SECRET_KEY=${SECRET_KEY:-test-secret-key-for-tests-only-32-bytes} uv run pytest tests/test_cluster_dispatch.py tests/test_cluster_run_queue.py tests/test_workflow_http_method.py tests/test_sse_streaming.py -q
```
Expected: all pass. If anything fails before you change code, stop and report it.

---

### Task 1: Migration and ORM models

**Files:**
- Create: `backend/alembic/versions/143_workflow_concurrency.py`
- Modify: `backend/app/db/models.py` (`Workflow` near line 343, `WorkflowRunQueue` near line 2586, new class after it)
- Test: `backend/tests/test_workflow_concurrency_models.py`

- [ ] **Step 1: Write the failing test**

```python
"""The concurrency columns and table exist with the shapes the service relies on."""

import unittest

from app.db.models import Workflow, WorkflowConcurrencySlot, WorkflowRunQueue


class ConcurrencyModelTests(unittest.TestCase):
    def test_workflow_has_three_nullable_settings(self) -> None:
        for name in ("concurrency_limit", "concurrency_max_queue", "concurrency_max_wait_seconds"):
            column = Workflow.__table__.c[name]
            self.assertTrue(column.nullable, name)

    def test_slot_is_keyed_by_execution_and_cascades_with_the_workflow(self) -> None:
        table = WorkflowConcurrencySlot.__table__
        self.assertEqual([c.name for c in table.primary_key.columns], ["execution_id"])
        (fk,) = table.c.workflow_id.foreign_keys
        self.assertEqual(fk.ondelete, "CASCADE")

    def test_queue_rows_carry_concurrency_fields(self) -> None:
        columns = WorkflowRunQueue.__table__.c
        for name in ("concurrency_seq", "expires_at", "status_token_hash", "run_options"):
            self.assertTrue(columns[name].nullable, name)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_workflow_concurrency_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'WorkflowConcurrencySlot'`.

- [ ] **Step 3: Add the ORM fields**

In `backend/app/db/models.py`, add `BigInteger` to the `sqlalchemy` import if it is missing. Under `workflow_timeout_seconds` in `class Workflow`:

```python
    # Production runs allowed at once; NULL turns the limit off.
    concurrency_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    concurrency_max_queue: Mapped[int | None] = mapped_column(Integer, nullable=True)
    concurrency_max_wait_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

At the end of `class WorkflowRunQueue`:

```python
    # Set only for runs that waited for a concurrency slot; the FIFO order.
    concurrency_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # hash_secret() of the status token an anonymous caller polls with.
    status_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Executor extras a held run must carry: conversation_history, llm_session_id,
    # run_error_workflow, holds_concurrency_slot.
    run_options: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
```

Directly after `class WorkflowRunQueue`:

```python
class WorkflowConcurrencySlot(Base):
    """One production run holding one of its workflow's concurrency slots."""

    __tablename__ = "workflow_concurrency_slots"

    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 4: Write the migration**

```python
"""per-workflow concurrency limit

Revision ID: 143_workflow_concurrency
Revises: 142_vsi_text_search_index
Create Date: 2026-10-25 00:00:00.000000

status_token_hash is a new, empty column: there is no plaintext to backfill. The
token it stores the digest of is secrets.token_urlsafe(32), which is shape-distinct
from a SHA-256 hex digest. Downgrade drops the column; nothing can be restored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "143_workflow_concurrency"
down_revision: str | Sequence[str] | None = "142_vsi_text_search_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflows", sa.Column("concurrency_limit", sa.Integer(), nullable=True))
    op.add_column("workflows", sa.Column("concurrency_max_queue", sa.Integer(), nullable=True))
    op.add_column(
        "workflows", sa.Column("concurrency_max_wait_seconds", sa.Integer(), nullable=True)
    )
    op.create_table(
        "workflow_concurrency_slots",
        sa.Column("execution_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_workflow_concurrency_slots_workflow_id",
        "workflow_concurrency_slots",
        ["workflow_id"],
    )
    op.execute("CREATE SEQUENCE IF NOT EXISTS workflow_concurrency_seq")
    op.add_column("workflow_run_queue", sa.Column("concurrency_seq", sa.BigInteger(), nullable=True))
    op.add_column(
        "workflow_run_queue", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "workflow_run_queue", sa.Column("status_token_hash", sa.String(64), nullable=True)
    )
    op.add_column("workflow_run_queue", sa.Column("run_options", sa.JSON(), nullable=True))
    op.create_index(
        "ix_workflow_run_queue_concurrency",
        "workflow_run_queue",
        ["workflow_id", "status", "concurrency_seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_run_queue_concurrency", table_name="workflow_run_queue")
    op.drop_column("workflow_run_queue", "run_options")
    op.drop_column("workflow_run_queue", "status_token_hash")
    op.drop_column("workflow_run_queue", "expires_at")
    op.drop_column("workflow_run_queue", "concurrency_seq")
    op.execute("DROP SEQUENCE IF EXISTS workflow_concurrency_seq")
    op.drop_index(
        "ix_workflow_concurrency_slots_workflow_id", table_name="workflow_concurrency_slots"
    )
    op.drop_table("workflow_concurrency_slots")
    op.drop_column("workflows", "concurrency_max_wait_seconds")
    op.drop_column("workflows", "concurrency_max_queue")
    op.drop_column("workflows", "concurrency_limit")
```

- [ ] **Step 5: Run the test and the migration round trip**

```bash
uv run pytest tests/test_workflow_concurrency_models.py -q
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```
Expected: 3 passed. The migration round trip completes without errors.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/143_workflow_concurrency.py backend/app/db/models.py backend/tests/test_workflow_concurrency_models.py
git commit -m "feat(concurrency): add workflow concurrency settings, slots table and queue columns"
```

---

### Task 2: Settings on the workflow API

**Files:**
- Modify: `backend/app/models/schemas.py` (`WorkflowUpdate` near line 244, `WorkflowResponse` near line 305)
- Modify: `backend/app/api/workflows.py` (`update_workflow`, after the `workflow_timeout_seconds` block near line 1785)
- Test: `backend/tests/test_workflow_concurrency_settings_api.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Editors set the limit through PUT; 0 clears it and negatives are rejected."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.schemas import WorkflowUpdate


def _workflow() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="wf",
        nodes=[],
        edges=[],
        http_method="POST",
        sse_node_config=None,
        updated_at=None,
        auth_type=None,
        auth_header_key=None,
        auth_header_value=None,
        webhook_body_mode=None,
        description=None,
        folder_id=None,
        cache_ttl_seconds=None,
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        sse_enabled=False,
        auto_recover_runs=True,
        error_workflow_id=None,
        minutes_saved_per_run=None,
        workflow_timeout_seconds=None,
        concurrency_limit=None,
        concurrency_max_queue=None,
        concurrency_max_wait_seconds=None,
        kind="workflow",
        portal_enabled=False,
        portal_slug=None,
        mcp_enabled=False,
    )


class ConcurrencySettingsUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def _update(
        self, workflow: SimpleNamespace, data: WorkflowUpdate, *, writable: bool = True
    ) -> AsyncMock:
        from app.api.workflows import update_workflow

        promote = AsyncMock(return_value=0)
        write_check = AsyncMock()
        if not writable:
            write_check.side_effect = HTTPException(status_code=403, detail="read-only")
        with (
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.workflows.require_workflow_write", write_check),
            patch("app.api.workflows.publish_event", AsyncMock()),
            patch("app.api.workflows._build_workflow_response", lambda wf, uid: wf),
            patch("app.api.workflows.workflow_concurrency.promote", promote),
        ):
            await update_workflow(
                workflow_id=workflow.id,
                workflow_data=data,
                current_user=SimpleNamespace(id=uuid.uuid4()),
                db=AsyncMock(),
            )
        return promote

    async def test_positive_values_are_stored(self) -> None:
        workflow = _workflow()
        await self._update(
            workflow,
            WorkflowUpdate(
                concurrency_limit=2, concurrency_max_queue=50, concurrency_max_wait_seconds=300
            ),
        )
        self.assertEqual(workflow.concurrency_limit, 2)
        self.assertEqual(workflow.concurrency_max_queue, 50)
        self.assertEqual(workflow.concurrency_max_wait_seconds, 300)

    async def test_zero_clears_each_field(self) -> None:
        workflow = _workflow()
        workflow.concurrency_limit = 3
        workflow.concurrency_max_queue = 10
        workflow.concurrency_max_wait_seconds = 60
        await self._update(
            workflow,
            WorkflowUpdate(
                concurrency_limit=0, concurrency_max_queue=0, concurrency_max_wait_seconds=0
            ),
        )
        self.assertIsNone(workflow.concurrency_limit)
        self.assertIsNone(workflow.concurrency_max_queue)
        self.assertIsNone(workflow.concurrency_max_wait_seconds)

    async def test_a_change_promotes_waiting_runs_right_away(self) -> None:
        workflow = _workflow()
        promote = await self._update(workflow, WorkflowUpdate(concurrency_limit=4))
        promote.assert_awaited_once_with(workflow.id)

    async def test_an_unrelated_save_does_not_promote(self) -> None:
        promote = await self._update(_workflow(), WorkflowUpdate(name="renamed"))
        promote.assert_not_awaited()

    async def test_a_read_only_collaborator_is_rejected(self) -> None:
        workflow = _workflow()
        with self.assertRaises(HTTPException) as ctx:
            await self._update(workflow, WorkflowUpdate(concurrency_limit=1), writable=False)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIsNone(workflow.concurrency_limit)

    def test_negative_values_fail_validation(self) -> None:
        for field in ("concurrency_limit", "concurrency_max_queue", "concurrency_max_wait_seconds"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                WorkflowUpdate(**{field: -1})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_workflow_concurrency_settings_api.py -q`
Expected: FAIL. `WorkflowUpdate` does not accept the fields yet, and `app.api.workflows` has no `workflow_concurrency`.

- [ ] **Step 3: Add the schema fields**

In `WorkflowUpdate`, under `workflow_timeout_seconds`:

```python
    # 0 clears a field; a positive value sets it.
    concurrency_limit: int | None = Field(None, ge=0)
    concurrency_max_queue: int | None = Field(None, ge=0)
    concurrency_max_wait_seconds: int | None = Field(None, ge=0)
```

In `WorkflowResponse`, under `workflow_timeout_seconds`:

```python
    concurrency_limit: int | None = None
    concurrency_max_queue: int | None = None
    concurrency_max_wait_seconds: int | None = None
```

- [ ] **Step 4: Persist and promote in `update_workflow`**

Create a stub `backend/app/services/workflow_concurrency.py` so the import resolves. Task 3 replaces it.

```python
"""Per-workflow concurrency limit. Filled in by the following tasks."""

import uuid


async def promote(workflow_id: uuid.UUID) -> int:
    """Start held runs that now fit under the limit."""
    return 0
```

In `backend/app/api/workflows.py`, add `from app.services import workflow_concurrency` beside the other `app.services` imports. After the `workflow_timeout_seconds` block in `update_workflow`:

```python
    concurrency_changed = False
    for field_name in (
        "concurrency_limit",
        "concurrency_max_queue",
        "concurrency_max_wait_seconds",
    ):
        value = getattr(workflow_data, field_name)
        if value is not None:
            setattr(workflow, field_name, value if value > 0 else None)
            concurrency_changed = True
```

After `await announce_workflow_saved(...)` and before `audit(...)`:

```python
    if concurrency_changed:
        # A raised or removed limit must not wait for the next sweep to start held runs.
        try:
            await workflow_concurrency.promote(workflow.id)
        except Exception:
            logger.exception("Could not promote held runs for workflow %s", workflow.id)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency_settings_api.py tests/test_workflow_http_method.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/schemas.py backend/app/api/workflows.py backend/app/services/workflow_concurrency.py backend/tests/test_workflow_concurrency_settings_api.py
git commit -m "feat(concurrency): save the concurrency settings from the workflow API"
```

---

### Task 3: Run-queue statuses and the pure admission rules

**Files:**
- Modify: `backend/app/services/cluster/run_queue.py`
- Modify: `backend/app/services/workflow_concurrency.py` (replace the stub)
- Test: `backend/tests/test_workflow_concurrency.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The admission rule, held-row shape, status mapping and token comparison."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from app.services.cluster import run_queue
from app.services.secret_tokens import hash_secret
from app.services.workflow_concurrency import (
    ConcurrencySettings,
    HeldRun,
    decide_admission,
    held_expires_at,
    held_values,
    history_view,
    queued_body,
    status_token_matches,
    status_view,
    Admission,
    QueueInfo,
)


def _cfg(limit: int | None = 1, max_queue: int | None = None, max_wait: int | None = None):
    return ConcurrencySettings(limit=limit, max_queue=max_queue, max_wait_seconds=max_wait)


class DecideAdmissionTests(unittest.TestCase):
    def test_no_limit_means_unlimited(self) -> None:
        self.assertEqual(
            decide_admission(_cfg(limit=None), running=9, waiting=9, has_slot=False), "unlimited"
        )

    def test_a_free_slot_with_an_empty_queue_admits(self) -> None:
        self.assertEqual(decide_admission(_cfg(2), running=1, waiting=0, has_slot=False), "admitted")

    def test_a_full_limit_queues(self) -> None:
        self.assertEqual(decide_admission(_cfg(1), running=1, waiting=0, has_slot=False), "queued")

    def test_nobody_overtakes_a_held_run(self) -> None:
        """FIFO: a slot that just freed belongs to the head of the queue."""
        self.assertEqual(decide_admission(_cfg(2), running=1, waiting=1, has_slot=False), "queued")

    def test_a_full_queue_rejects(self) -> None:
        self.assertEqual(
            decide_admission(_cfg(1, max_queue=2), running=1, waiting=2, has_slot=False),
            "queue_full",
        )

    def test_an_existing_slot_is_admitted_again(self) -> None:
        """Recovery re-runs reuse their execution id and keep the slot."""
        self.assertEqual(decide_admission(_cfg(1), running=1, waiting=3, has_slot=True), "admitted")


class HeldValuesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run = HeldRun(
            workflow_id=uuid.uuid4(),
            execution_id=uuid.uuid4(),
            placement="anywhere",
            inputs={"body": {"x": 1}},
            trigger_source="API",
            actor_user_id=uuid.uuid4(),
            credentials_owner_id=uuid.uuid4(),
            run_options={"run_error_workflow": True},
        )
        self.now = datetime.now(timezone.utc)

    def test_a_held_row_has_no_target_and_is_held(self) -> None:
        values = held_values(self.run, cfg=_cfg(1), now=self.now, token=None)
        self.assertEqual(values["status"], run_queue.STATUS_HELD)
        self.assertIsNone(values["target_instance_id"])
        self.assertFalse(values["test_run"])

    def test_the_token_is_stored_only_as_a_digest(self) -> None:
        values = held_values(self.run, cfg=_cfg(1), now=self.now, token="plain-token")
        self.assertEqual(values["status_token_hash"], hash_secret("plain-token"))
        self.assertNotIn("plain-token", repr(values))

    def test_a_held_row_never_carries_a_resolved_credential(self) -> None:
        values = held_values(self.run, cfg=_cfg(1), now=self.now, token=None)
        self.assertNotIn("credentials_context", values)
        self.assertEqual(values["credentials_owner_id"], self.run.credentials_owner_id)

    def test_expiry_follows_max_wait(self) -> None:
        self.assertIsNone(held_expires_at(_cfg(1), self.now))
        self.assertEqual(held_expires_at(_cfg(1, max_wait=30), self.now), self.now + timedelta(seconds=30))


class StatusTokenTests(unittest.TestCase):
    def test_the_plaintext_matches_its_digest(self) -> None:
        self.assertTrue(status_token_matches(hash_secret("abc"), "abc"))

    def test_the_stored_digest_is_not_a_token(self) -> None:
        digest = hash_secret("abc")
        self.assertFalse(status_token_matches(digest, digest))

    def test_missing_values_never_match(self) -> None:
        self.assertFalse(status_token_matches(None, "abc"))
        self.assertFalse(status_token_matches(hash_secret("abc"), None))


class StatusViewTests(unittest.TestCase):
    def test_held_reads_as_queued(self) -> None:
        self.assertEqual(status_view(row_status="held", result=None, error=None)["status"], "queued")

    def test_in_flight_rows_read_as_running(self) -> None:
        for status in ("queued", "waiting_for_main", "claimed"):
            with self.subTest(status=status):
                self.assertEqual(status_view(row_status=status, result=None, error=None)["status"], "running")

    def test_a_done_row_reports_the_run_status_and_outputs(self) -> None:
        view = status_view(
            row_status="done",
            result={"status": "success", "outputs": {"a": 1}, "execution_time_ms": 12.0},
            error=None,
        )
        self.assertEqual(view, {"status": "success", "outputs": {"a": 1}, "error": None, "execution_time_ms": 12.0})

    def test_an_expired_row_says_why(self) -> None:
        view = status_view(
            row_status="expired",
            result={"status": "expired", "outputs": {"error": "waited too long"}, "execution_time_ms": 0.0},
            error=None,
        )
        self.assertEqual(view["status"], "expired")
        self.assertEqual(view["error"], "waited too long")

    def test_a_failed_row_is_an_error(self) -> None:
        view = status_view(row_status="failed", result=None, error="boom")
        self.assertEqual((view["status"], view["error"]), ("error", "boom"))

    def test_history_view_reads_the_error_from_outputs(self) -> None:
        view = history_view(status="error", outputs={"error": "bad"}, execution_time_ms=3.0)
        self.assertEqual((view["status"], view["error"]), ("error", "bad"))


class QueuedBodyTests(unittest.TestCase):
    def test_the_body_names_the_status_url_and_queue(self) -> None:
        workflow_id, execution_id = uuid.uuid4(), uuid.uuid4()
        admission = Admission(
            kind="queued",
            execution_id=execution_id,
            queue=QueueInfo(position=2, size=5, running=1, limit=1),
            status_token="tok",
        )
        body = queued_body(admission, workflow_id=workflow_id, base_url="https://h.example")
        self.assertEqual(body["status"], "queued")
        self.assertEqual(
            body["status_url"],
            f"https://h.example/api/workflows/{workflow_id}/executions/{execution_id}/status",
        )
        self.assertEqual(body["queue"], {"position": 2, "size": 5, "running": 1, "limit": 1})
        self.assertEqual(body["status_token"], "tok")

    def test_no_token_key_without_a_token(self) -> None:
        admission = Admission(
            kind="queued", execution_id=uuid.uuid4(), queue=QueueInfo(1, 1, 1, 1)
        )
        body = queued_body(admission, workflow_id=uuid.uuid4(), base_url="https://h.example")
        self.assertNotIn("status_token", body)


class RunQueueStatusTests(unittest.TestCase):
    def test_expired_and_cancelled_are_terminal_and_held_is_not(self) -> None:
        self.assertTrue(run_queue.is_terminal(run_queue.STATUS_EXPIRED))
        self.assertTrue(run_queue.is_terminal(run_queue.STATUS_CANCELLED))
        self.assertFalse(run_queue.is_terminal(run_queue.STATUS_HELD))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_workflow_concurrency.py -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Extend `run_queue.py`**

Under the existing status constants:

```python
# A run waiting for a concurrency slot. Not claimable until promoted to queued.
STATUS_HELD = "held"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"
```

Add a field to `QueuedRun` after `trace_context`:

```python
    run_options: dict | None = None
```

In `build_queue_values`, add the key `"run_options": run.run_options,`. Replace `is_terminal` with:

```python
def is_terminal(status: str) -> bool:
    return status in {
        STATUS_DONE,
        STATUS_FAILED,
        STATUS_SKIPPED_LATE,
        STATUS_EXPIRED,
        STATUS_CANCELLED,
    }
```

- [ ] **Step 4: Write the pure part of `workflow_concurrency.py`**

Replace the stub with the module header and pure functions below. Tasks 4 and 5 append the database functions. Keep the temporary `promote` stub at the bottom until Task 4 replaces it.

```python
"""Per-workflow concurrency limit: admit, hold, release and promote production runs.

A slot is a row in ``workflow_concurrency_slots``; a run waiting for one is a
``workflow_run_queue`` row with status ``held``. Every transaction that changes
either for one workflow first takes that workflow's advisory lock, so the counts
are exact across every process and every cluster instance.

Promotion turns a held row into an ordinary queued run, so the run queue worker
executes, persists and recovers it exactly like an offloaded cluster run.
"""

from __future__ import annotations

import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func

from app.services.cluster import identity, run_queue
from app.services.secret_tokens import hash_secret

logger = logging.getLogger("concurrency")

HISTORY_STATUS_QUEUE_FULL = "queue_full"
QUEUE_FULL_MESSAGE = "Concurrency queue is full"
EXPIRED_MESSAGE = "Waited longer than the workflow's max wait for a concurrency slot"
CANCELLED_MESSAGE = "Execution was cancelled"
RUN_TOKEN_HEADER = "X-Heym-Run-Token"
# Same grace as a stranded claim: registration reaches the database asynchronously.
STALE_SLOT_GRACE_SECONDS = 120
SEQUENCE_NAME = "workflow_concurrency_seq"
IN_FLIGHT_STATUSES = (
    run_queue.STATUS_QUEUED,
    run_queue.STATUS_WAITING_FOR_MAIN,
    run_queue.STATUS_CLAIMED,
)

AdmissionKind = Literal["unlimited", "admitted", "queued", "queue_full"]


@dataclass(frozen=True)
class ConcurrencySettings:
    limit: int | None
    max_queue: int | None
    max_wait_seconds: int | None


@dataclass(frozen=True)
class QueueInfo:
    position: int
    size: int
    running: int
    limit: int | None

    def as_dict(self) -> dict[str, int | None]:
        return {
            "position": self.position,
            "size": self.size,
            "running": self.running,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class Admission:
    kind: AdmissionKind
    execution_id: uuid.UUID
    queue: QueueInfo | None = None
    # Plaintext, minted for anonymous workflows only. Returned to the caller once.
    status_token: str | None = None

    @property
    def runs_now(self) -> bool:
        return self.kind in ("unlimited", "admitted")

    @property
    def holds_slot(self) -> bool:
        return self.kind == "admitted"


@dataclass(frozen=True)
class HeldRun:
    """Everything a held row needs so the worker can run it later without the caller."""

    workflow_id: uuid.UUID
    execution_id: uuid.UUID
    placement: str
    inputs: dict
    trigger_source: str | None
    actor_user_id: uuid.UUID | None
    credentials_owner_id: uuid.UUID | None
    timeout_seconds: float | None = None
    return_on_chart_output: bool = False
    run_options: dict | None = None
    mint_status_token: bool = False
    trace_context: dict[str, str] | None = None


def decide_admission(
    cfg: ConcurrencySettings, *, running: int, waiting: int, has_slot: bool
) -> AdmissionKind:
    """The admission rule. Strict FIFO: nobody overtakes a held run."""
    if cfg.limit is None:
        return "unlimited"
    if has_slot:
        return "admitted"
    if running < cfg.limit and waiting == 0:
        return "admitted"
    if cfg.max_queue is not None and waiting >= cfg.max_queue:
        return "queue_full"
    return "queued"


def held_expires_at(cfg: ConcurrencySettings, now: datetime) -> datetime | None:
    """Fixed at enqueue, so changing the setting later does not move runs already waiting."""
    if not cfg.max_wait_seconds:
        return None
    return now + timedelta(seconds=cfg.max_wait_seconds)


def held_values(
    run: HeldRun, *, cfg: ConcurrencySettings, now: datetime, token: str | None
) -> dict[str, Any]:
    """The queue row for a held run. Holds a credentials owner, never a credential."""
    return {
        "id": uuid.uuid4(),
        "workflow_id": run.workflow_id,
        "execution_id": run.execution_id,
        "placement": run.placement,
        "target_instance_id": None,
        "status": run_queue.STATUS_HELD,
        "inputs": run.inputs,
        "trace_context": run.trace_context,
        "trigger_source": run.trigger_source,
        "actor_user_id": run.actor_user_id,
        "credentials_owner_id": run.credentials_owner_id,
        "test_run": False,
        "timeout_seconds": run.timeout_seconds,
        "return_on_chart_output": run.return_on_chart_output,
        "enqueued_at": now,
        # Not read while held; promotion sets the real claim deadline.
        "not_after": now,
        "concurrency_seq": func.nextval(SEQUENCE_NAME),
        "expires_at": held_expires_at(cfg, now),
        "status_token_hash": hash_secret(token) if token else None,
        "run_options": run.run_options,
    }


def status_token_matches(stored_hash: str | None, presented: str | None) -> bool:
    """Compare digests only: the stored digest itself must never work as a token."""
    if not stored_hash or not presented:
        return False
    return hmac.compare_digest(stored_hash, hash_secret(presented))


def terminal_summary(
    *, execution_id: uuid.UUID, workflow_id: uuid.UUID, status: str, message: str
) -> dict[str, Any]:
    """The run-queue result for a held run that never executed."""
    return {
        "execution_id": str(execution_id),
        "workflow_id": str(workflow_id),
        "status": status,
        "outputs": {"error": message},
        "execution_time_ms": 0.0,
        "history_written": True,
        "error": None,
        "instance": identity.instance_name(),
    }


def _error_text(status: str, outputs: Any, fallback: str | None) -> str | None:
    if status in ("error", "expired", "cancelled") and isinstance(outputs, dict):
        message = outputs.get("error")
        if isinstance(message, str) and message:
            return message
    return fallback


def status_view(*, row_status: str, result: dict | None, error: str | None) -> dict[str, Any]:
    """Map one queue row to the public status fields."""
    if row_status == run_queue.STATUS_HELD:
        return {"status": "queued", "outputs": None, "error": None, "execution_time_ms": None}
    if row_status in IN_FLIGHT_STATUSES:
        return {"status": "running", "outputs": None, "error": None, "execution_time_ms": None}
    if result is None:
        return {
            "status": "error",
            "outputs": None,
            "error": error or "The run finished without a result",
            "execution_time_ms": None,
        }
    status = str(result.get("status") or "error")
    outputs = result.get("outputs")
    return {
        "status": status,
        "outputs": outputs,
        "error": _error_text(status, outputs, result.get("error") or error),
        "execution_time_ms": result.get("execution_time_ms"),
    }


def history_view(*, status: str, outputs: Any, execution_time_ms: float | None) -> dict[str, Any]:
    """Map an execution history row to the public status fields."""
    return {
        "status": status,
        "outputs": outputs,
        "error": _error_text(status, outputs, None),
        "execution_time_ms": execution_time_ms,
    }


def status_url(*, base_url: str, workflow_id: uuid.UUID, execution_id: uuid.UUID) -> str:
    return f"{base_url.rstrip('/')}/api/workflows/{workflow_id}/executions/{execution_id}/status"


def queued_body(admission: Admission, *, workflow_id: uuid.UUID, base_url: str) -> dict[str, Any]:
    """The 202 body: where to poll, and where this run stands right now."""
    body: dict[str, Any] = {
        "status": "queued",
        "execution_id": str(admission.execution_id),
        "status_url": status_url(
            base_url=base_url, workflow_id=workflow_id, execution_id=admission.execution_id
        ),
        "queue": admission.queue.as_dict() if admission.queue else None,
    }
    if admission.status_token:
        body["status_token"] = admission.status_token
    return body
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency.py tests/test_cluster_run_queue.py tests/test_cluster_dispatch.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/cluster/run_queue.py backend/app/services/workflow_concurrency.py backend/tests/test_workflow_concurrency.py
git commit -m "feat(concurrency): admission rules, held row shape and status mapping"
```

---

### Task 4: Admit, release and promote on Postgres

**Files:**
- Modify: `backend/app/services/workflow_concurrency.py` (append)
- Create: `backend/tests/workflow_concurrency_fixtures.py` (shared real-Postgres base, not collected as a test)
- Test: `backend/tests/test_workflow_concurrency_postgres.py`

- [ ] **Step 1: Write the shared fixture**

```python
"""A migrated PostgreSQL database with one throwaway user and workflow per test.

Like test_cluster_trace_context_postgres.py, only connection failures skip; a
reachable database with an outdated schema must fail.
"""

import asyncio
import unittest
import uuid

from asyncpg import CannotConnectNowError, PostgresConnectionError
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError

from app.db.models import (
    ExecutionHistory,
    User,
    Workflow,
    WorkflowConcurrencySlot,
    WorkflowRunQueue,
)
from app.db.session import async_session_maker, engine
from app.services.workflow_concurrency import HeldRun


class ConcurrencyPostgresCase(unittest.IsolatedAsyncioTestCase):
    limit: int | None = 1
    max_queue: int | None = None
    max_wait_seconds: int | None = None

    async def asyncSetUp(self) -> None:
        await engine.dispose()
        try:
            async with asyncio.timeout(10):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except (OSError, TimeoutError, PostgresConnectionError, CannotConnectNowError) as exc:
            await engine.dispose()
            self.skipTest(f"PostgreSQL is unavailable ({type(exc).__name__})")
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", "") or ""
            if not exc.connection_invalidated and not sqlstate.startswith("08") and sqlstate != "57P03":
                raise
            await engine.dispose()
            self.skipTest("PostgreSQL connection is unavailable")
        self.user_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.addAsyncCleanup(self._remove_fixture)
        async with async_session_maker() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"concurrency-{self.user_id.hex}@example.com",
                    hashed_password="test-only",
                    name="Concurrency fixture",
                )
            )
            db.add(
                Workflow(
                    id=self.workflow_id,
                    owner_id=self.user_id,
                    name="Concurrency fixture",
                    nodes=[],
                    edges=[],
                    concurrency_limit=self.limit,
                    concurrency_max_queue=self.max_queue,
                    concurrency_max_wait_seconds=self.max_wait_seconds,
                )
            )
            await db.commit()

    async def _remove_fixture(self) -> None:
        async with async_session_maker() as db:
            await db.execute(delete(WorkflowConcurrencySlot).where(WorkflowConcurrencySlot.workflow_id == self.workflow_id))
            await db.execute(delete(WorkflowRunQueue).where(WorkflowRunQueue.workflow_id == self.workflow_id))
            await db.execute(delete(ExecutionHistory).where(ExecutionHistory.workflow_id == self.workflow_id))
            await db.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            await db.execute(delete(User).where(User.id == self.user_id))
            await db.commit()
        await engine.dispose()

    def held_run(self, **overrides: object) -> HeldRun:
        values: dict[str, object] = {
            "workflow_id": self.workflow_id,
            "execution_id": uuid.uuid4(),
            "placement": "anywhere",
            "inputs": {"body": {}},
            "trigger_source": "API",
            "actor_user_id": self.user_id,
            "credentials_owner_id": self.user_id,
        }
        values.update(overrides)
        return HeldRun(**values)  # type: ignore[arg-type]

    async def set_limit(self, limit: int | None) -> None:
        async with async_session_maker() as db:
            workflow = await db.get(Workflow, self.workflow_id)
            assert workflow is not None
            workflow.concurrency_limit = limit
            await db.commit()

    async def queue_row(self, execution_id: uuid.UUID) -> WorkflowRunQueue | None:
        from sqlalchemy import select

        async with async_session_maker() as db:
            return (
                await db.execute(select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == execution_id))
            ).scalar_one_or_none()

    async def slot_count(self) -> int:
        from sqlalchemy import func, select

        async with async_session_maker() as db:
            return int(
                (
                    await db.execute(
                        select(func.count()).select_from(WorkflowConcurrencySlot).where(
                            WorkflowConcurrencySlot.workflow_id == self.workflow_id
                        )
                    )
                ).scalar_one()
            )
```

- [ ] **Step 2: Write the failing tests**

```python
"""Admission, release and FIFO promotion against a real database."""

import asyncio
from unittest.mock import patch

from app.services import workflow_concurrency
from app.services.cluster import run_queue
# backend/tests is not a package; pytest's default "prepend" import mode puts the
# test directory on sys.path, so the shared fixture imports by its bare name.
from workflow_concurrency_fixtures import ConcurrencyPostgresCase


class AdmitTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_the_first_run_is_admitted_and_holds_a_slot(self) -> None:
        admission = await workflow_concurrency.admit(self.held_run())
        self.assertEqual(admission.kind, "admitted")
        self.assertEqual(await self.slot_count(), 1)

    async def test_later_runs_queue_with_increasing_positions(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        second = await workflow_concurrency.admit(self.held_run())
        third = await workflow_concurrency.admit(self.held_run())
        self.assertEqual(second.kind, "queued")
        self.assertEqual((second.queue.position, second.queue.size), (1, 1))
        self.assertEqual((third.queue.position, third.queue.size, third.queue.running, third.queue.limit), (2, 2, 1, 1))
        row = await self.queue_row(third.execution_id)
        self.assertEqual(row.status, run_queue.STATUS_HELD)
        self.assertIsNotNone(row.concurrency_seq)

    async def test_re_admitting_a_slot_holder_is_idempotent(self) -> None:
        run = self.held_run()
        await workflow_concurrency.admit(run)
        again = await workflow_concurrency.admit(run)
        self.assertEqual(again.kind, "admitted")
        self.assertEqual(await self.slot_count(), 1)

    async def test_a_token_is_minted_only_when_asked(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        plain = await workflow_concurrency.admit(self.held_run())
        anonymous = await workflow_concurrency.admit(self.held_run(mint_status_token=True))
        self.assertIsNone(plain.status_token)
        self.assertTrue(anonymous.status_token)
        row = await self.queue_row(anonymous.execution_id)
        self.assertNotEqual(row.status_token_hash, anonymous.status_token)


class UnlimitedTests(ConcurrencyPostgresCase):
    limit = None

    async def test_no_limit_takes_no_slot(self) -> None:
        admission = await workflow_concurrency.admit(self.held_run())
        self.assertEqual(admission.kind, "unlimited")
        self.assertEqual(await self.slot_count(), 0)


class QueueFullTests(ConcurrencyPostgresCase):
    limit = 1
    max_queue = 1

    async def test_the_queue_rejects_past_max_queue(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        await workflow_concurrency.admit(self.held_run())
        rejected = await workflow_concurrency.admit(self.held_run())
        self.assertEqual(rejected.kind, "queue_full")
        self.assertIsNone(await self.queue_row(rejected.execution_id))


class ReleaseTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_release_promotes_the_head_in_fifo_order(self) -> None:
        first = await workflow_concurrency.admit(self.held_run())
        second = await workflow_concurrency.admit(self.held_run())
        third = await workflow_concurrency.admit(self.held_run())
        with patch.object(workflow_concurrency.settings, "cluster_enabled", False):
            await workflow_concurrency.release(first.execution_id)
        promoted = await self.queue_row(second.execution_id)
        waiting = await self.queue_row(third.execution_id)
        self.assertEqual(promoted.status, run_queue.STATUS_QUEUED)
        self.assertIsNotNone(promoted.target_instance_id)
        self.assertEqual(waiting.status, run_queue.STATUS_HELD)
        self.assertEqual(await self.slot_count(), 1)

    async def test_release_without_a_slot_is_a_no_op(self) -> None:
        import uuid

        await workflow_concurrency.release(uuid.uuid4())
        self.assertEqual(await self.slot_count(), 0)

    async def test_raising_the_limit_promotes_several(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = [await workflow_concurrency.admit(self.held_run()) for _ in range(3)]
        await self.set_limit(3)
        with patch.object(workflow_concurrency.settings, "cluster_enabled", False):
            promoted = await workflow_concurrency.promote(self.workflow_id)
        self.assertEqual(promoted, 2)
        statuses = [(await self.queue_row(a.execution_id)).status for a in held]
        self.assertEqual(statuses, ["queued", "queued", "held"])

    async def test_turning_the_limit_off_drains_the_queue_without_slots(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = [await workflow_concurrency.admit(self.held_run()) for _ in range(2)]
        await self.set_limit(None)
        with patch.object(workflow_concurrency.settings, "cluster_enabled", False):
            await workflow_concurrency.promote(self.workflow_id)
        self.assertEqual([(await self.queue_row(a.execution_id)).status for a in held], ["queued", "queued"])
        self.assertEqual(await self.slot_count(), 1)


class RaceTests(ConcurrencyPostgresCase):
    limit = 3

    async def test_concurrent_admissions_never_exceed_the_limit(self) -> None:
        admissions = await asyncio.gather(
            *(workflow_concurrency.admit(self.held_run()) for _ in range(8))
        )
        kinds = sorted(a.kind for a in admissions)
        self.assertEqual(kinds.count("admitted"), 3)
        self.assertEqual(kinds.count("queued"), 5)
        positions = sorted(a.queue.position for a in admissions if a.kind == "queued")
        self.assertEqual(positions, [1, 2, 3, 4, 5])
        self.assertEqual(await self.slot_count(), 3)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_workflow_concurrency_postgres.py -q`
Expected: FAIL with `AttributeError: module 'app.services.workflow_concurrency' has no attribute 'admit'`. If every test is skipped, the database is not running; start it as described in the ground rules.

- [ ] **Step 4: Append the database code to `workflow_concurrency.py`**

Extend the imports at the top of the module (keep the import order rules):

```python
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, exists, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.config import settings
from app.db.models import (
    ActiveWorkflowExecution,
    ExecutionHistory,
    Workflow,
    WorkflowConcurrencySlot,
    WorkflowRunQueue,
)
from app.db.session import async_session_maker
from app.services.cluster.attribution import attribution_fields
```

Delete the temporary `promote` stub and append:

```python
async def _lock(db: AsyncSession, workflow_id: uuid.UUID) -> None:
    """Serialize every slot and held-row change for one workflow, cluster-wide."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"heym.concurrency:{workflow_id}"},
    )


async def _settings(db: AsyncSession, workflow_id: uuid.UUID) -> ConcurrencySettings | None:
    row = (
        await db.execute(
            select(
                Workflow.concurrency_limit,
                Workflow.concurrency_max_queue,
                Workflow.concurrency_max_wait_seconds,
            ).where(Workflow.id == workflow_id)
        )
    ).first()
    if row is None:
        return None
    return ConcurrencySettings(limit=row[0], max_queue=row[1], max_wait_seconds=row[2])


async def _running(db: AsyncSession, workflow_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(WorkflowConcurrencySlot)
                .where(WorkflowConcurrencySlot.workflow_id == workflow_id)
            )
        ).scalar_one()
    )


async def _waiting(db: AsyncSession, workflow_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(WorkflowRunQueue)
                .where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.status == run_queue.STATUS_HELD,
                )
            )
        ).scalar_one()
    )


async def admit(run: HeldRun) -> Admission:
    """Decide whether a production run starts now, waits for a slot, or is turned away."""
    now = datetime.now(timezone.utc)
    async with async_session_maker() as db:
        await _lock(db, run.workflow_id)
        cfg = await _settings(db, run.workflow_id)
        if cfg is None or cfg.limit is None:
            await db.commit()
            return Admission(kind="unlimited", execution_id=run.execution_id)
        has_slot = await db.get(WorkflowConcurrencySlot, run.execution_id) is not None
        running = await _running(db, run.workflow_id)
        waiting = await _waiting(db, run.workflow_id)
        kind = decide_admission(cfg, running=running, waiting=waiting, has_slot=has_slot)
        if kind == "admitted":
            if not has_slot:
                db.add(
                    WorkflowConcurrencySlot(
                        execution_id=run.execution_id,
                        workflow_id=run.workflow_id,
                        acquired_at=now,
                    )
                )
            await db.commit()
            return Admission(kind="admitted", execution_id=run.execution_id)
        if kind == "queue_full":
            await db.commit()
            return Admission(
                kind="queue_full",
                execution_id=run.execution_id,
                queue=QueueInfo(position=0, size=waiting, running=running, limit=cfg.limit),
            )
        token = secrets.token_urlsafe(32) if run.mint_status_token else None
        try:
            await db.execute(
                WorkflowRunQueue.__table__.insert().values(
                    **held_values(run, cfg=cfg, now=now, token=token)
                )
            )
        except StatementError as error:
            # Inputs can hold request data; keep them out of the exception text.
            error.hide_parameters = True
            raise
        await db.commit()
    return Admission(
        kind="queued",
        execution_id=run.execution_id,
        queue=QueueInfo(position=waiting + 1, size=waiting + 1, running=running, limit=cfg.limit),
        status_token=token,
    )


async def _promotion_target(placement: str) -> str | None:
    if settings.cluster_enabled:
        return await run_queue.choose_target(placement)
    return identity.instance_id()


async def _close_held_locked(
    db: AsyncSession, row: WorkflowRunQueue, *, status: str, message: str, now: datetime
) -> None:
    """Retire a held run that will never execute, with a history row that says why."""
    row.status = status
    row.finished_at = now
    row.result = terminal_summary(
        execution_id=row.execution_id, workflow_id=row.workflow_id, status=status, message=message
    )
    await db.execute(
        pg_insert(ExecutionHistory)
        .values(
            id=row.execution_id,
            workflow_id=row.workflow_id,
            inputs=row.inputs,
            outputs={"error": message},
            node_results=[],
            status=status,
            execution_time_ms=0.0,
            trigger_source=row.trigger_source,
            **attribution_fields(),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    workflow = await db.get(Workflow, row.workflow_id)
    if workflow is not None:
        await upsert_workflow_analytics_snapshot(
            db,
            workflow_id=row.workflow_id,
            owner_id=workflow.owner_id,
            workflow_name_snapshot=workflow.name,
            status=status,
            execution_time_ms=0.0,
        )
    await db.flush()
    # Wakes any dispatcher waiting on this run; delivered when the transaction commits.
    await db.execute(
        text("SELECT pg_notify('heym_run_done', :payload)"), {"payload": str(row.execution_id)}
    )


async def _promote_locked(db: AsyncSession, workflow_id: uuid.UUID) -> int:
    """Hand free slots to the oldest held runs. Caller holds the workflow lock."""
    cfg = await _settings(db, workflow_id)
    if cfg is None:
        return 0
    now = datetime.now(timezone.utc)
    promoted = 0
    while True:
        if cfg.limit is not None and await _running(db, workflow_id) >= cfg.limit:
            return promoted
        head = (
            await db.execute(
                select(WorkflowRunQueue)
                .where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.status == run_queue.STATUS_HELD,
                )
                .order_by(WorkflowRunQueue.concurrency_seq)
                .limit(1)
            )
        ).scalar_one_or_none()
        if head is None:
            return promoted
        if head.expires_at is not None and head.expires_at <= now:
            await _close_held_locked(
                db, head, status=run_queue.STATUS_EXPIRED, message=EXPIRED_MESSAGE, now=now
            )
            continue
        if cfg.limit is not None:
            db.add(
                WorkflowConcurrencySlot(
                    execution_id=head.execution_id, workflow_id=workflow_id, acquired_at=now
                )
            )
        target = await _promotion_target(head.placement)
        head.target_instance_id = target
        head.status = run_queue.next_status(target_instance_id=target)
        head.not_after = now + timedelta(seconds=settings.cron_misfire_grace_seconds)
        await db.flush()
        if target:
            await db.execute(
                text("SELECT pg_notify('heym_run_queue', :payload)"), {"payload": target}
            )
        promoted += 1


async def release(execution_id: uuid.UUID) -> None:
    """Free this run's slot, if it holds one, and start whoever is next."""
    async with async_session_maker() as db:
        workflow_id = (
            await db.execute(
                select(WorkflowConcurrencySlot.workflow_id).where(
                    WorkflowConcurrencySlot.execution_id == execution_id
                )
            )
        ).scalar_one_or_none()
        if workflow_id is None:
            return
        await _lock(db, workflow_id)
        await db.execute(
            delete(WorkflowConcurrencySlot).where(
                WorkflowConcurrencySlot.execution_id == execution_id
            )
        )
        await _promote_locked(db, workflow_id)
        await db.commit()


async def promote(workflow_id: uuid.UUID) -> int:
    """Start held runs that now fit under the limit, for example after a settings save."""
    async with async_session_maker() as db:
        await _lock(db, workflow_id)
        promoted = await _promote_locked(db, workflow_id)
        await db.commit()
    return promoted
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency_postgres.py tests/test_workflow_concurrency.py -q`
Expected: all pass (none skipped while the database is up).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workflow_concurrency.py backend/tests/workflow_concurrency_fixtures.py backend/tests/test_workflow_concurrency_postgres.py
git commit -m "feat(concurrency): admit, release and FIFO promotion under a per-workflow advisory lock"
```

---

### Task 5: Cancel, expiry, stale slots, status body and held listing

**Files:**
- Modify: `backend/app/services/workflow_concurrency.py` (append)
- Test: `backend/tests/test_workflow_concurrency_maintenance.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Retiring held runs, reclaiming dead slots, and reading one run's status."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import select, update

from app.db.models import ExecutionHistory, WorkflowConcurrencySlot, WorkflowRunQueue
from app.db.session import async_session_maker
from app.services import workflow_concurrency
from app.services.cluster import run_queue
from workflow_concurrency_fixtures import ConcurrencyPostgresCase


async def _history_status(execution_id: uuid.UUID) -> str | None:
    async with async_session_maker() as db:
        return (
            await db.execute(select(ExecutionHistory.status).where(ExecutionHistory.id == execution_id))
        ).scalar_one_or_none()


class CancelHeldTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_a_held_run_is_cancelled_with_a_history_row(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run())
        self.assertTrue(await workflow_concurrency.cancel_held(self.workflow_id, held.execution_id))
        self.assertEqual((await self.queue_row(held.execution_id)).status, run_queue.STATUS_CANCELLED)
        self.assertEqual(await _history_status(held.execution_id), "cancelled")

    async def test_a_running_run_is_not_a_held_run(self) -> None:
        running = await workflow_concurrency.admit(self.held_run())
        self.assertFalse(await workflow_concurrency.cancel_held(self.workflow_id, running.execution_id))


class ExpiryTests(ConcurrencyPostgresCase):
    limit = 1
    max_wait_seconds = 60

    async def test_maintain_expires_overdue_held_runs(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run())
        async with async_session_maker() as db:
            await db.execute(
                update(WorkflowRunQueue)
                .where(WorkflowRunQueue.execution_id == held.execution_id)
                .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
            )
            await db.commit()
        await workflow_concurrency.maintain()
        self.assertEqual((await self.queue_row(held.execution_id)).status, run_queue.STATUS_EXPIRED)
        self.assertEqual(await _history_status(held.execution_id), "expired")


class StaleSlotTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_a_slot_nobody_is_running_is_reclaimed_and_the_head_promoted(self) -> None:
        dead = await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run())
        async with async_session_maker() as db:
            await db.execute(
                update(WorkflowConcurrencySlot)
                .where(WorkflowConcurrencySlot.execution_id == dead.execution_id)
                .values(acquired_at=datetime.now(timezone.utc) - timedelta(minutes=10))
            )
            await db.commit()
        with patch.object(workflow_concurrency.settings, "cluster_enabled", False):
            await workflow_concurrency.maintain()
        self.assertEqual((await self.queue_row(held.execution_id)).status, run_queue.STATUS_QUEUED)

    async def test_a_young_slot_is_left_alone(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run())
        await workflow_concurrency.maintain()
        self.assertEqual((await self.queue_row(held.execution_id)).status, run_queue.STATUS_HELD)


class StatusBodyTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_a_held_run_reports_its_queue_position(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run())
        body = await workflow_concurrency.build_status_body(self.workflow_id, held.execution_id)
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["queue"], {"position": 1, "size": 1, "running": 1, "limit": 1})

    async def test_an_unknown_execution_is_none(self) -> None:
        self.assertIsNone(await workflow_concurrency.build_status_body(self.workflow_id, uuid.uuid4()))

    async def test_history_answers_when_there_is_no_queue_row(self) -> None:
        execution_id = uuid.uuid4()
        async with async_session_maker() as db:
            db.add(
                ExecutionHistory(
                    id=execution_id,
                    workflow_id=self.workflow_id,
                    inputs={},
                    outputs={"answer": 42},
                    node_results=[],
                    status="success",
                    execution_time_ms=5.0,
                    trigger_source="API",
                )
            )
            await db.commit()
        body = await workflow_concurrency.build_status_body(self.workflow_id, execution_id)
        self.assertEqual((body["status"], body["outputs"]), ("success", {"answer": 42}))

    async def test_the_token_digest_is_readable_for_the_endpoint(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run(mint_status_token=True))
        digest = await workflow_concurrency.status_token_hash_for(self.workflow_id, held.execution_id)
        self.assertTrue(workflow_concurrency.status_token_matches(digest, held.status_token))


class HeldListingTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_the_owner_sees_held_runs_with_positions(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        first = await workflow_concurrency.admit(self.held_run())
        second = await workflow_concurrency.admit(self.held_run())
        async with async_session_maker() as db:
            records = await workflow_concurrency.list_held_runs_for_user(db, self.user_id)
        mine = [r for r in records if r.workflow_id == self.workflow_id]
        self.assertEqual([(r.execution_id, r.position, r.size) for r in mine], [(first.execution_id, 1, 2), (second.execution_id, 2, 2)])

    async def test_a_stranger_sees_nothing(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        await workflow_concurrency.admit(self.held_run())
        async with async_session_maker() as db:
            records = await workflow_concurrency.list_held_runs_for_user(db, uuid.uuid4())
        self.assertFalse([r for r in records if r.workflow_id == self.workflow_id])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_workflow_concurrency_maintenance.py -q`
Expected: FAIL with `AttributeError` (`cancel_held`, `maintain`, ...).

- [ ] **Step 3: Append the implementation**

Add `from app.services.workflow_access import workflow_access_clause` to the imports, then append:

```python
@dataclass(frozen=True)
class HeldRunRecord:
    execution_id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    enqueued_at: datetime
    inputs: dict
    position: int
    size: int


async def cancel_held(workflow_id: uuid.UUID, execution_id: uuid.UUID) -> bool:
    """Cancel a run that is still waiting. False when it is not held (or not this workflow's)."""
    async with async_session_maker() as db:
        await _lock(db, workflow_id)
        row = (
            await db.execute(
                select(WorkflowRunQueue).where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.execution_id == execution_id,
                    WorkflowRunQueue.status == run_queue.STATUS_HELD,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            await db.commit()
            return False
        await _close_held_locked(
            db,
            row,
            status=run_queue.STATUS_CANCELLED,
            message=CANCELLED_MESSAGE,
            now=datetime.now(timezone.utc),
        )
        await db.commit()
        return True


async def record_queue_full(
    *, workflow_id: uuid.UUID, execution_id: uuid.UUID, inputs: dict, trigger_source: str | None
) -> None:
    """A history row for a run the full queue turned away, like rate limiting writes."""
    async with async_session_maker() as db:
        workflow = await db.get(Workflow, workflow_id)
        if workflow is None:
            return
        db.add(
            ExecutionHistory(
                id=execution_id,
                workflow_id=workflow_id,
                inputs=inputs,
                outputs={"error": QUEUE_FULL_MESSAGE},
                node_results=[],
                status=HISTORY_STATUS_QUEUE_FULL,
                execution_time_ms=0.0,
                trigger_source=trigger_source,
            )
        )
        await upsert_workflow_analytics_snapshot(
            db,
            workflow_id=workflow_id,
            owner_id=workflow.owner_id,
            workflow_name_snapshot=workflow.name,
            status=HISTORY_STATUS_QUEUE_FULL,
            execution_time_ms=0.0,
        )
        await db.commit()


def _stale_slot_clause(cutoff: datetime) -> Any:
    """A slot that nothing is executing: no active run and no queued, claimable row."""
    return and_(
        WorkflowConcurrencySlot.acquired_at < cutoff,
        ~exists().where(
            ActiveWorkflowExecution.execution_id == WorkflowConcurrencySlot.execution_id
        ),
        ~exists().where(
            WorkflowRunQueue.execution_id == WorkflowConcurrencySlot.execution_id,
            WorkflowRunQueue.status.in_(IN_FLIGHT_STATUSES),
        ),
    )


async def _maintain_workflow(workflow_id: uuid.UUID, *, now: datetime, cutoff: datetime) -> None:
    async with async_session_maker() as db:
        await _lock(db, workflow_id)
        reclaimed = (
            (
                await db.execute(
                    delete(WorkflowConcurrencySlot)
                    .where(
                        WorkflowConcurrencySlot.workflow_id == workflow_id,
                        _stale_slot_clause(cutoff),
                    )
                    .returning(WorkflowConcurrencySlot.execution_id)
                )
            )
            .scalars()
            .all()
        )
        for execution_id in reclaimed:
            logger.warning("Reclaimed the concurrency slot of run %s: nothing is running it", execution_id)
        overdue = (
            (
                await db.execute(
                    select(WorkflowRunQueue).where(
                        WorkflowRunQueue.workflow_id == workflow_id,
                        WorkflowRunQueue.status == run_queue.STATUS_HELD,
                        WorkflowRunQueue.expires_at.is_not(None),
                        WorkflowRunQueue.expires_at <= now,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in overdue:
            await _close_held_locked(
                db, row, status=run_queue.STATUS_EXPIRED, message=EXPIRED_MESSAGE, now=now
            )
        await _promote_locked(db, workflow_id)
        await db.commit()


async def maintain() -> None:
    """Leader pass: retire overdue held runs, reclaim dead slots, start whoever fits."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=STALE_SLOT_GRACE_SECONDS)
    async with async_session_maker() as db:
        held = select(WorkflowRunQueue.workflow_id).where(
            WorkflowRunQueue.status == run_queue.STATUS_HELD
        )
        stale = select(WorkflowConcurrencySlot.workflow_id).where(_stale_slot_clause(cutoff))
        workflow_ids = set((await db.execute(held.union(stale))).scalars().all())
    for workflow_id in workflow_ids:
        try:
            await _maintain_workflow(workflow_id, now=now, cutoff=cutoff)
        except Exception:
            logger.exception("Concurrency maintenance failed for workflow %s", workflow_id)


async def _queue_info(db: AsyncSession, workflow_id: uuid.UUID, concurrency_seq: int) -> QueueInfo:
    cfg = await _settings(db, workflow_id)
    position = int(
        (
            await db.execute(
                select(func.count())
                .select_from(WorkflowRunQueue)
                .where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.status == run_queue.STATUS_HELD,
                    WorkflowRunQueue.concurrency_seq <= concurrency_seq,
                )
            )
        ).scalar_one()
    )
    return QueueInfo(
        position=position,
        size=await _waiting(db, workflow_id),
        running=await _running(db, workflow_id),
        limit=cfg.limit if cfg else None,
    )


async def build_status_body(
    workflow_id: uuid.UUID, execution_id: uuid.UUID
) -> dict[str, Any] | None:
    """The status URL's body: the queue row when there is one, else the history row."""
    base: dict[str, Any] = {
        "execution_id": str(execution_id),
        "workflow_id": str(workflow_id),
        "queue": None,
    }
    async with async_session_maker() as db:
        row = (
            await db.execute(
                select(WorkflowRunQueue).where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.execution_id == execution_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            body = {**base, **status_view(row_status=row.status, result=row.result, error=row.error)}
            if row.status == run_queue.STATUS_HELD and row.concurrency_seq is not None:
                body["queue"] = (await _queue_info(db, workflow_id, row.concurrency_seq)).as_dict()
            return body
        history = (
            await db.execute(
                select(
                    ExecutionHistory.status,
                    ExecutionHistory.outputs,
                    ExecutionHistory.execution_time_ms,
                ).where(
                    ExecutionHistory.id == execution_id,
                    ExecutionHistory.workflow_id == workflow_id,
                )
            )
        ).first()
    if history is None:
        return None
    return {**base, **history_view(status=history[0], outputs=history[1], execution_time_ms=history[2])}


async def status_token_hash_for(workflow_id: uuid.UUID, execution_id: uuid.UUID) -> str | None:
    async with async_session_maker() as db:
        return (
            await db.execute(
                select(WorkflowRunQueue.status_token_hash).where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.execution_id == execution_id,
                )
            )
        ).scalar_one_or_none()


async def list_held_runs_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[HeldRunRecord]:
    """Held runs of every workflow the user can reach, in queue order, with positions."""
    rows = (
        await db.execute(
            select(
                WorkflowRunQueue.execution_id,
                WorkflowRunQueue.workflow_id,
                Workflow.name,
                WorkflowRunQueue.enqueued_at,
                WorkflowRunQueue.inputs,
            )
            .join(Workflow, Workflow.id == WorkflowRunQueue.workflow_id)
            .where(
                WorkflowRunQueue.status == run_queue.STATUS_HELD,
                workflow_access_clause(user_id),
            )
            .order_by(WorkflowRunQueue.workflow_id, WorkflowRunQueue.concurrency_seq)
        )
    ).all()
    sizes: dict[uuid.UUID, int] = {}
    for row in rows:
        sizes[row[1]] = sizes.get(row[1], 0) + 1
    seen: dict[uuid.UUID, int] = {}
    records: list[HeldRunRecord] = []
    for execution_id, workflow_id, name, enqueued_at, inputs in rows:
        seen[workflow_id] = seen.get(workflow_id, 0) + 1
        records.append(
            HeldRunRecord(
                execution_id=execution_id,
                workflow_id=workflow_id,
                workflow_name=name,
                enqueued_at=enqueued_at,
                inputs=inputs or {},
                position=seen[workflow_id],
                size=sizes[workflow_id],
            )
        )
    return records


def holds_slot(row: Any) -> bool:
    """Whether a claimed queue row must give a slot back when it finishes."""
    options = getattr(row, "run_options", None) or {}
    return getattr(row, "concurrency_seq", None) is not None or bool(
        options.get("holds_concurrency_slot")
    )


def is_concurrency_row(row: Any) -> bool:
    """A row that waited for a slot: its caller may be gone, so the worker finishes it."""
    return getattr(row, "concurrency_seq", None) is not None
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency_maintenance.py tests/test_workflow_concurrency_postgres.py tests/test_workflow_concurrency.py tests/test_models_importable.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_concurrency.py backend/tests/test_workflow_concurrency_maintenance.py
git commit -m "feat(concurrency): cancel, expiry, stale-slot reclaim, status body and held listing"
```

---

### Task 6: Worker and sweep: run queued concurrency rows on every install

**Files:**
- Modify: `backend/app/services/workflow_executor.py` (`ExecutionResult`, near line 1771)
- Modify: `backend/app/services/cluster/dispatch.py` (`RunQueueWorker.start`, `_execute_claimed`, `_finalize_claimed_allow_downstream`)
- Modify: `backend/app/services/cron_scheduler.py` (`_maintain_run_queue`, line 676)
- Test: `backend/tests/test_workflow_concurrency_worker.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The worker finishes concurrency rows completely, since their caller may be gone."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.cluster.dispatch import RunQueueWorker


def _row(*, concurrency_seq: int | None = 7, run_options: dict | None = None) -> SimpleNamespace:
    workflow_id = uuid.uuid4()
    return SimpleNamespace(
        id=None,
        execution_id=uuid.uuid4(),
        workflow_id=workflow_id,
        inputs={},
        trigger_source="API",
        actor_user_id=uuid.uuid4(),
        credentials_owner_id=uuid.uuid4(),
        test_run=False,
        timeout_seconds=None,
        return_on_chart_output=False,
        concurrency_seq=concurrency_seq,
        run_options=run_options,
    )


class ClaimedConcurrencyRowTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, row: SimpleNamespace, status: str = "success") -> dict[str, AsyncMock]:
        workflow = SimpleNamespace(id=row.workflow_id, owner_id=uuid.uuid4(), name="wf", nodes=[], edges=[])
        db = MagicMock()
        db.get = AsyncMock(return_value=None)
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow))
        db.commit = AsyncMock()
        session_factory = MagicMock()
        session_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        result = SimpleNamespace(
            status=status,
            outputs={},
            node_results=[],
            execution_time_ms=1.0,
            sub_workflow_executions=[],
            allow_downstream_pending=False,
        )
        mocks = {
            "execute": AsyncMock(return_value=result),
            "release": AsyncMock(),
            "error_workflow": AsyncMock(),
        }
        with (
            patch("app.db.session.async_session_maker", session_factory),
            patch("app.api.workflows.get_credentials_context", new=AsyncMock(return_value={})),
            patch("app.api.workflows.collect_referenced_workflows", new=AsyncMock(return_value={})),
            patch("app.api.workflows._persist_global_variables_from_execution", new=AsyncMock()),
            patch("app.services.global_variables_service.get_global_variables_context", new=AsyncMock(return_value={})),
            patch("app.services.cluster.dispatch.register_execution"),
            patch("app.services.cluster.dispatch.asyncio.to_thread", mocks["execute"]),
            patch("app.services.cluster.dispatch.persist_run_history", new=AsyncMock()),
            patch("app.services.cluster.dispatch.run_queue.complete", new=AsyncMock()),
            patch("app.services.cluster.dispatch.run_queue.notify_done", new=AsyncMock()),
            patch("app.services.cluster.dispatch.workflow_concurrency.release", mocks["release"]),
            patch("app.services.cluster.dispatch.run_error_workflow_for_failed_run", mocks["error_workflow"]),
        ):
            await RunQueueWorker()._execute_claimed(row)
        return mocks

    async def test_the_slot_is_released_after_the_run(self) -> None:
        row = _row()
        mocks = await self._run(row)
        mocks["release"].assert_awaited_once_with(row.execution_id)

    async def test_a_plain_cluster_row_does_not_touch_slots(self) -> None:
        mocks = await self._run(_row(concurrency_seq=None))
        mocks["release"].assert_not_awaited()

    async def test_an_offloaded_slot_holder_releases(self) -> None:
        row = _row(concurrency_seq=None, run_options={"holds_concurrency_slot": True})
        mocks = await self._run(row)
        mocks["release"].assert_awaited_once_with(row.execution_id)

    async def test_portal_options_reach_the_executor(self) -> None:
        history = [{"role": "user", "content": "hi"}]
        mocks = await self._run(_row(run_options={"conversation_history": history, "llm_session_id": "conv-1"}))
        kwargs = mocks["execute"].await_args.kwargs
        self.assertEqual(kwargs["conversation_history"], history)
        self.assertEqual(kwargs["llm_session_id"], "conv-1")

    async def test_the_worker_fires_the_error_workflow_for_a_queued_failure(self) -> None:
        mocks = await self._run(_row(), status="error")
        mocks["error_workflow"].assert_awaited_once()

    async def test_the_recursion_guard_is_honoured(self) -> None:
        mocks = await self._run(_row(run_options={"run_error_workflow": False}), status="error")
        mocks["error_workflow"].assert_not_awaited()


class WorkerStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_worker_starts_without_a_cluster(self) -> None:
        bus = MagicMock()
        bus.start = AsyncMock()
        bus.stop = AsyncMock()
        bus.wait_for_work = AsyncMock(side_effect=AssertionError("stop"))
        worker = RunQueueWorker()
        with (
            patch("app.services.cluster.dispatch.settings.cluster_enabled", False),
            patch("app.services.cluster.run_queue_bus.QueueWakeBus", return_value=bus),
        ):
            await worker.start()
            self.assertIsNotNone(worker._task)
            await worker.stop()


class AllowDownstreamFuturesTests(unittest.TestCase):
    def test_futures_are_listed_without_being_consumed(self) -> None:
        from concurrent.futures import Future

        from app.services.workflow_executor import ExecutionResult

        future: Future = Future()
        result = ExecutionResult(workflow_id=uuid.uuid4(), status="success", outputs={}, node_results=[], execution_time_ms=0.0)
        result._allow_downstream_pending.append(future)
        self.assertEqual(result.allow_downstream_futures(), (future,))
        self.assertTrue(result.allow_downstream_pending)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_workflow_concurrency_worker.py -q`
Expected: FAIL. `dispatch` has no `workflow_concurrency`, and `allow_downstream_futures` is missing.

- [ ] **Step 3: Add `allow_downstream_futures` to `ExecutionResult`**

In `backend/app/services/workflow_executor.py`, directly after the `allow_downstream_pending` property:

```python
    def allow_downstream_futures(self) -> tuple[Future, ...]:
        """The background branches still running, without taking them from join_allow_downstream()."""
        return tuple(self._allow_downstream_pending)
```

- [ ] **Step 4: Change the worker in `dispatch.py`**

Add `from app.services import workflow_concurrency` to the imports.

`RunQueueWorker.start`: remove the `settings.cluster_enabled` condition. Keep the `self._task is not None` guard:

```python
    async def start(self) -> None:
        # Always on: concurrency-queued runs reach this queue without a cluster too.
        if self._task is not None:
            return
```

In `_execute_claimed`, replace the `execute_workflow` call's keyword list so the run options travel. Add these two lines before `token = tracing.attach_queue_context(...)`:

```python
            options = getattr(row, "run_options", None) or {}
            extra_kwargs = {
                key: options[key]
                for key in ("conversation_history", "llm_session_id")
                if options.get(key) is not None
            }
```

and add `**extra_kwargs,` as the last argument of the `asyncio.to_thread(execute_workflow, ...)` call.

After the non-pending branch's `await run_queue.complete(row.execution_id, result=summarize(result, row.execution_id), error=None)`, add:

```python
            # The caller may have stopped waiting (202, MCP), so the error workflow is
            # fired here, once, and never by the dispatcher. run_error_workflow=False is
            # the error workflow's own recursion guard.
            if workflow_concurrency.is_concurrency_row(row) and options.get(
                "run_error_workflow", True
            ):
                await run_error_workflow_for_failed_run(
                    result,
                    workflow_id=row.workflow_id,
                    execution_id=row.execution_id,
                    test_run=False,
                    enabled=True,
                    actor_user_id=row.actor_user_id or row.credentials_owner_id,
                )
```

In the generic `except Exception as exc:` block, after `await run_queue.complete(...)`:

```python
            if workflow_concurrency.is_concurrency_row(row):
                # Nobody may be waiting to record this failure; the insert is conditional.
                with contextlib.suppress(Exception):
                    await record_failed_dispatch(
                        execution_id=row.execution_id,
                        workflow_id=row.workflow_id,
                        inputs=row.inputs,
                        trigger_source=row.trigger_source,
                        message=str(exc) or "The run failed before it produced a result",
                    )
```

In the `finally` of `_execute_claimed`, inside `if not defer_cleanup:`, after `complete_execution(...)` and before `notify_done`:

```python
                if workflow_concurrency.holds_slot(row):
                    with contextlib.suppress(Exception):
                        await workflow_concurrency.release(row.execution_id)
```

In `_finalize_claimed_allow_downstream`'s `finally`, after the `complete_execution(...)` suppress block:

```python
            if workflow_concurrency.holds_slot(row):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await workflow_concurrency.release(row.execution_id)
```

`options` is defined inside the `try`. Initialize `options: dict = {}` at the top of `_execute_claimed`, next to `cancel_event = None`, so the code that reads it never sees an unbound name.

- [ ] **Step 5: Run the concurrency sweep on every install**

Replace `_maintain_run_queue` in `backend/app/services/cron_scheduler.py`:

```python
    async def _maintain_run_queue(self) -> None:
        """Retire stale queued runs, run the concurrency pass, and release waiting_for_main.

        Runs on the leader. The run queue now carries concurrency-queued runs on a
        single instance too, so only the hand-back to a returning main stays
        cluster-only. Expiring first stops a long outage from replaying its whole
        backlog at once.
        """
        try:
            await workflow_concurrency.maintain()
        except Exception:
            logger.exception("Concurrency maintenance failed")
        try:
            expired = await run_queue.expire_late_rows()
            if expired:
                logger.info("Retired %d run queue rows past the misfire grace window", expired)
            for execution_id in await run_queue.expire_stranded_claims():
                logger.warning(
                    "Retired run %s: the instance that claimed it stopped before finishing",
                    execution_id,
                )
                await run_queue.notify_done(execution_id)
            if not settings.cluster_enabled:
                return
            instances = await registry.list_instances()
            main = registry.find_main(instances)
            if main is not None and registry.is_live(main, now=datetime.now(timezone.utc)):
                released = await run_queue.release_waiting_for_main(main.id)
                if released:
                    logger.info("Released %d runs waiting for the main instance", released)
        except Exception:
            logger.exception("Run queue maintenance failed")
```

Add `from app.services import workflow_concurrency` to its imports.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency_worker.py tests/test_cluster_dispatch.py tests/test_cluster_allow_downstream.py tests/test_cluster_pending_runs.py tests/test_cron_scheduler*.py -q`
Expected: all pass. If an existing cron test asserted that `_maintain_run_queue` returns early without a cluster, update it to the new behaviour: the concurrency pass and the expiry sweeps run, the `waiting_for_main` hand-back does not.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/workflow_executor.py backend/app/services/cluster/dispatch.py backend/app/services/cron_scheduler.py backend/tests/test_workflow_concurrency_worker.py
git commit -m "feat(concurrency): worker runs concurrency-queued rows on every install and releases slots"
```

---

### Task 7: The gate in `dispatch_workflow`

**Files:**
- Modify: `backend/app/services/cluster/dispatch.py` (`dispatch_workflow`)
- Test: `backend/tests/test_workflow_concurrency_dispatch.py`

- [ ] **Step 1: Write the failing tests**

```python
"""dispatch_workflow admits, queues, rejects, and always gives the slot back."""

import asyncio
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.cluster import dispatch
from app.services.workflow_concurrency import Admission, QueueInfo

NODES = [{"id": "a", "type": "set", "data": {"label": "a"}}]


def _result(status: str = "success", futures: tuple = ()) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        outputs={},
        node_results=[],
        allow_downstream_pending=bool(futures),
        allow_downstream_futures=lambda: futures,
    )


class DispatchGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.workflow_id = uuid.uuid4()
        self.execution_id = uuid.uuid4()

    async def _dispatch(self, admission: Admission | None, *, execute=None, **kwargs):
        admit = AsyncMock(return_value=admission)
        # Kept on self so a test whose dispatch raises can still inspect it.
        release = self.release = AsyncMock()
        execute = execute or (lambda **_: _result())
        with (
            patch.object(dispatch.settings, "cluster_enabled", False),
            patch("app.services.cluster.dispatch.workflow_concurrency.admit", admit),
            patch("app.services.cluster.dispatch.workflow_concurrency.release", release),
            patch("app.services.cluster.dispatch.workflow_concurrency.record_queue_full", AsyncMock()) as full,
            patch("app.services.cluster.dispatch.execute_workflow", side_effect=execute),
            patch("app.services.cluster.dispatch.run_error_workflow_for_failed_run", AsyncMock()),
            patch("app.services.cluster.dispatch.wait_for_result", AsyncMock(return_value=_result())) as wait,
        ):
            result = await dispatch.dispatch_workflow(
                workflow_id=self.workflow_id,
                nodes=NODES,
                edges=[],
                inputs={},
                execution_id=self.execution_id,
                trigger_source="API",
                **kwargs,
            )
            await asyncio.sleep(0)
        return result, admit, release, full, wait

    async def test_no_limit_never_calls_admit(self) -> None:
        _, admit, release, _, _ = await self._dispatch(None)
        admit.assert_not_awaited()
        release.assert_not_awaited()

    async def test_an_exempt_editor_test_run_is_not_gated(self) -> None:
        _, admit, _, _, _ = await self._dispatch(None, concurrency_limit=1, concurrency_exempt=True, test_run=True)
        admit.assert_not_awaited()

    async def test_an_admitted_run_releases_after_executing(self) -> None:
        _, admit, release, _, _ = await self._dispatch(
            Admission(kind="admitted", execution_id=self.execution_id), concurrency_limit=1
        )
        admit.assert_awaited_once()
        release.assert_awaited_once_with(self.execution_id)

    async def test_a_raising_run_still_releases(self) -> None:
        def boom(**_):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            await self._dispatch(Admission(kind="admitted", execution_id=self.execution_id), execute=boom, concurrency_limit=1)
        self.release.assert_awaited_once_with(self.execution_id)

    async def test_a_hitl_pause_releases_immediately(self) -> None:
        _, _, release, _, _ = await self._dispatch(
            Admission(kind="admitted", execution_id=self.execution_id),
            execute=lambda **_: _result("pending"),
            concurrency_limit=1,
        )
        release.assert_awaited_once_with(self.execution_id)

    async def test_allow_downstream_keeps_the_slot_until_the_branch_joins(self) -> None:
        from concurrent.futures import Future

        # Exercised directly: the release runs after dispatch returns, so the patch
        # has to stay active until the branch finishes.
        branch: Future = Future()
        release = AsyncMock()
        with patch("app.services.cluster.dispatch.workflow_concurrency.release", release):
            await dispatch.release_slot_when_done(_result(futures=(branch,)), self.execution_id)
            await asyncio.sleep(0.05)
            release.assert_not_awaited()
            branch.set_result(None)
            for _ in range(100):
                if release.await_count:
                    break
                await asyncio.sleep(0.01)
        release.assert_awaited_once_with(self.execution_id)

    async def test_a_queued_run_returns_the_admission_when_asked(self) -> None:
        admission = Admission(kind="queued", execution_id=self.execution_id, queue=QueueInfo(1, 1, 1, 1))
        result, _, release, _, _ = await self._dispatch(admission, concurrency_limit=1, on_queued="return")
        self.assertIs(result, admission)
        release.assert_not_awaited()

    async def test_a_queued_background_run_waits_for_its_result(self) -> None:
        admission = Admission(kind="queued", execution_id=self.execution_id, queue=QueueInfo(1, 1, 1, 1))
        result, _, _, _, wait = await self._dispatch(admission, concurrency_limit=1)
        wait.assert_awaited_once()
        self.assertEqual(result.status, "success")

    async def test_a_full_queue_records_history_and_reports_queue_full(self) -> None:
        admission = Admission(kind="queue_full", execution_id=self.execution_id, queue=QueueInfo(0, 5, 1, 1))
        result, _, _, full, _ = await self._dispatch(admission, concurrency_limit=1)
        full.assert_awaited_once()
        self.assertEqual(result.status, "queue_full")
        self.assertTrue(result.history_written)

    async def test_held_runs_carry_the_error_workflow_guard(self) -> None:
        admission = Admission(kind="queued", execution_id=self.execution_id, queue=QueueInfo(1, 1, 1, 1))
        _, admit, _, _, _ = await self._dispatch(admission, concurrency_limit=1, run_error_workflow=False, on_queued="return")
        held = admit.await_args.args[0]
        self.assertEqual(held.run_options["run_error_workflow"], False)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_workflow_concurrency_dispatch.py -q`
Expected: FAIL with `TypeError: dispatch_workflow() got an unexpected keyword argument 'concurrency_limit'`.

- [ ] **Step 3: Implement the gate**

At module level in `dispatch.py`, after `_RESULT_POLL_SECONDS`:

```python
# Slot releases that wait for allowDownstream branches; kept so they are not collected.
_SLOT_RELEASE_TASKS: set[asyncio.Task[None]] = set()


def queue_full_result() -> OffloadedRun:
    """What a waiting caller gets when the queue turned its run away. History is written."""
    return OffloadedRun(
        status=workflow_concurrency.HISTORY_STATUS_QUEUE_FULL,
        outputs={"error": workflow_concurrency.QUEUE_FULL_MESSAGE},
        history_written=True,
        reported=True,
    )


async def _release_after_branches(futures: tuple[Any, ...], execution_id: uuid.UUID) -> None:
    try:
        await asyncio.to_thread(concurrent.futures.wait, futures)
    finally:
        await workflow_concurrency.release(execution_id)


async def release_slot_when_done(result: Any, execution_id: uuid.UUID) -> None:
    """Give the slot back now, or once allowDownstream branches have finished."""
    futures_of = getattr(result, "allow_downstream_futures", None)
    futures = tuple(futures_of()) if callable(futures_of) else ()
    if not futures:
        await workflow_concurrency.release(execution_id)
        return
    task = asyncio.create_task(_release_after_branches(futures, execution_id))
    _SLOT_RELEASE_TASKS.add(task)
    task.add_done_callback(_SLOT_RELEASE_TASKS.discard)
```

Add `import concurrent.futures` and `from typing import Literal` to the imports. Add `OffloadedRun` to the `run_history` import list, and add `from app.services import workflow_concurrency`.

New keyword parameters on `dispatch_workflow`, before `**executor_kwargs`:

```python
    concurrency_limit: int | None = None,
    concurrency_exempt: bool = False,
    on_queued: Literal["wait", "return"] = "wait",
    run_options: dict | None = None,
    mint_status_token: bool = False,
```

Update the docstring to describe them. Directly after `placement = resolve_placement(nodes, workflow_cache)`, insert:

```python
    admission: workflow_concurrency.Admission | None = None
    if concurrency_limit is not None and not concurrency_exempt:
        held_options = {**(run_options or {}), "run_error_workflow": run_error_workflow}
        admission = await workflow_concurrency.admit(
            workflow_concurrency.HeldRun(
                workflow_id=workflow_id,
                execution_id=run_id,
                placement=placement,
                inputs=inputs,
                trigger_source=trigger_source,
                actor_user_id=actor_user_id,
                credentials_owner_id=credentials_owner_id,
                timeout_seconds=timeout_seconds,
                return_on_chart_output=bool(executor_kwargs.get("return_on_chart_output", False)),
                run_options=held_options,
                mint_status_token=mint_status_token,
                trace_context=tracing.capture_queue_context(),
            )
        )
        if admission.kind == "queue_full":
            await workflow_concurrency.record_queue_full(
                workflow_id=workflow_id,
                execution_id=run_id,
                inputs=inputs,
                trigger_source=trigger_source,
            )
            clear_execution(run_id, handle=handle)
            return admission if on_queued == "return" else queue_full_result()
        if admission.kind == "queued":
            # The worker registers the run when it claims it; until then it is queued, not running.
            clear_execution(run_id, handle=handle)
            if on_queued == "return":
                return admission
            if not wait_for_completion:
                return None
            # The worker writes history and fires the error workflow for queued runs.
            return await wait_for_result(run_id, timeout_seconds=timeout_seconds)
    holds_slot = admission is not None and admission.holds_slot
```

In the in-process branch (`if should_run_in_process(...)`), make sure stale-slot detection can see the run, and release when it ends. Insert this before `call_kwargs = dict(...)`:

```python
        registered_here: Any = None
        if holds_slot and handle is None and cancel_event is None:
            # Without a registry row the sweep would take a long, healthy run's slot.
            cancel_event = register_execution(
                workflow_id=workflow_id,
                execution_id=run_id,
                inputs=inputs,
                trigger_source=trigger_source,
                actor_user_id=actor_user_id,
            )
            registered_here = getattr(cancel_event, "_execution_handle", None)
```

Wrap the execution lines in a `try`:

```python
        try:
            if run_in_thread:
                result = await asyncio.to_thread(execute_workflow, **call_kwargs)
            else:
                result = execute_workflow(**call_kwargs)
        except BaseException:
            if holds_slot:
                await workflow_concurrency.release(run_id)
            raise
        finally:
            if registered_here is not None:
                clear_execution(run_id, handle=registered_here)
        if holds_slot:
            await release_slot_when_done(result, run_id)
```

In the offload branch, an admitted run hands its slot to the worker. Change the `QueuedRun(...)` construction to pass:

```python
        run_options={"holds_concurrency_slot": True} if holds_slot else None,
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency_dispatch.py tests/test_cluster_dispatch.py tests/test_cluster_allow_downstream.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cluster/dispatch.py backend/tests/test_workflow_concurrency_dispatch.py
git commit -m "feat(concurrency): gate production runs in dispatch_workflow and release slots"
```

---

### Task 8: Pass the limit at every dispatch call site

**Files (modify each `dispatch_workflow(...)` call):**

| File:line | Workflow variable |
|---|---|
| `backend/app/api/telegram.py:159` | `fresh_workflow` |
| `backend/app/api/discord.py:278` | `fresh_workflow` |
| `backend/app/api/slack.py:266` | `fresh_workflow` |
| `backend/app/services/trigger_run_dispatch.py:82` | `fresh_workflow` |
| `backend/app/services/heym_event_dispatcher.py:248` | `fresh_workflow` |
| `backend/app/services/websocket_trigger_service.py:433` | `workflow` |
| `backend/app/services/rabbitmq_consumer.py:355` | `workflow` |
| `backend/app/services/cron_scheduler.py:233` | `workflow` |
| `backend/app/services/error_workflow_runner.py:100` | `target` |
| `backend/app/services/dashboard_data.py:415` and `:495` | `workflow` |

The HTTP and MCP sites are handled in Tasks 9 and 14.

- Test: `backend/tests/test_workflow_concurrency_call_sites.py`

- [ ] **Step 1: Write the failing test**

```python
"""Every trigger hands the workflow's limit to dispatch_workflow, or nothing is gated."""

import ast
import pathlib
import unittest

CALL_SITES = [
    "app/api/telegram.py",
    "app/api/discord.py",
    "app/api/slack.py",
    "app/api/workflows.py",
    "app/api/mcp.py",
    "app/api/mcp_servers.py",
    "app/services/trigger_run_dispatch.py",
    "app/services/heym_event_dispatcher.py",
    "app/services/websocket_trigger_service.py",
    "app/services/rabbitmq_consumer.py",
    "app/services/cron_scheduler.py",
    "app/services/error_workflow_runner.py",
    "app/services/dashboard_data.py",
]


class CallSiteTests(unittest.TestCase):
    def test_every_dispatch_call_passes_concurrency_limit(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        missing: list[str] = []
        for relative in CALL_SITES:
            tree = ast.parse((root / relative).read_text())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "dispatch_workflow"
                    and "concurrency_limit" not in {k.arg for k in node.keywords}
                ):
                    missing.append(f"{relative}:{node.lineno}")
        self.assertEqual(missing, [])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_workflow_concurrency_call_sites.py -q`
Expected: FAIL listing every call site.

- [ ] **Step 3: Add the keyword at each site in the table**

For example in `cron_scheduler.py`:

```python
                result = await dispatch_workflow(
                    workflow_id=workflow.id,
                    ...
                    cancel_event=cancel_event,
                    concurrency_limit=workflow.concurrency_limit,
                )
```

Use the variable from the table at each site: `concurrency_limit=<variable>.concurrency_limit`. In `error_workflow_runner.py`, keep its existing `run_error_workflow=False`. Task 7 stores that guard on the held row.

Leave `workflows.py`, `mcp.py` and `mcp_servers.py` failing in this test until Tasks 9 and 14.

- [ ] **Step 4: Run the affected suites**

Run: `uv run pytest tests/test_cron_scheduler*.py tests/test_trigger_run_dispatch*.py tests/test_error_workflow*.py tests/test_dashboard*.py tests/test_slack*.py tests/test_telegram*.py tests/test_discord*.py tests/test_rabbitmq*.py tests/test_websocket_trigger*.py tests/test_heym_event*.py -q`
Expected: all pass. Tests that build a workflow as a `SimpleNamespace` without `concurrency_limit` fail with `AttributeError`. Add `concurrency_limit=None` to those fixtures; do not use `getattr` at the call site.

- [ ] **Step 5: Commit**

```bash
git add -A backend/app backend/tests
git commit -m "feat(concurrency): pass each workflow's limit from every trigger"
```

---

### Task 9: HTTP execute endpoint: exemption, 202 and 429

**Files:**
- Modify: `backend/app/api/workflows.py` (`execute_workflow_endpoint`, from line 3182)
- Test: `backend/tests/test_workflow_concurrency_api.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The webhook answers 202 with a status URL when the limit is full, and 429 when the queue is."""

import json
import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request

from app.api.workflows import execute_workflow_endpoint
from app.services.workflow_concurrency import Admission, QueueInfo
from app.services.workflow_executor import ExecutionResult


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _request(query: bytes = b"") -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "server": ("heym.example", 443),
            "path": "/api/workflows/x/execute",
            "headers": [(b"host", b"heym.example")],
            "query_string": query,
        },
        receive,
    )


class ExecuteEndpointConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def _workflow(self, *, anonymous: bool = False) -> SimpleNamespace:
        from app.db.models import WorkflowAuthType

        return SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="wf",
            nodes=[{"id": "o", "type": "output", "data": {"label": "o", "message": "ok"}}],
            edges=[],
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_enabled=False,
            http_method="POST",
            auth_type=WorkflowAuthType.anonymous if anonymous else WorkflowAuthType.jwt,
            concurrency_limit=1,
            workflow_timeout_seconds=None,
        )

    async def _call(self, workflow, dispatch_result, *, query: bytes = b"", session_user=None, has_access=True):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        dispatch = AsyncMock(return_value=dispatch_result)
        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock(return_value=session_user)),
            patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=has_access)),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows.dispatch_workflow", dispatch),
            patch("app.api.workflows.ExecutionHistory", side_effect=lambda **kw: SimpleNamespace(id=uuid.uuid4())),
        ):
            response = await execute_workflow_endpoint(
                workflow_id=workflow.id, request=_request(query), current_user=session_user, db=db
            )
        return response, dispatch

    async def test_a_queued_run_answers_202_with_location_and_queue(self) -> None:
        workflow = self._workflow()
        execution_id = uuid.uuid4()
        admission = Admission(kind="queued", execution_id=execution_id, queue=QueueInfo(2, 5, 1, 1))
        response, dispatch = await self._call(workflow, admission)
        self.assertEqual(response.status_code, 202)
        body = json.loads(response.body)
        self.assertEqual(body["queue"], {"position": 2, "size": 5, "running": 1, "limit": 1})
        self.assertEqual(response.headers["location"], body["status_url"])
        self.assertTrue(body["status_url"].endswith(f"/api/workflows/{workflow.id}/executions/{execution_id}/status"))
        self.assertEqual(dispatch.await_args.kwargs["on_queued"], "return")
        self.assertEqual(dispatch.await_args.kwargs["concurrency_limit"], 1)

    async def test_only_anonymous_workflows_mint_a_status_token(self) -> None:
        _, dispatch = await self._call(self._workflow(anonymous=True), Admission(kind="queued", execution_id=uuid.uuid4(), queue=QueueInfo(1, 1, 1, 1), status_token="t"))
        self.assertTrue(dispatch.await_args.kwargs["mint_status_token"])
        _, dispatch = await self._call(self._workflow(), Admission(kind="queued", execution_id=uuid.uuid4(), queue=QueueInfo(1, 1, 1, 1)))
        self.assertFalse(dispatch.await_args.kwargs["mint_status_token"])

    async def test_a_full_queue_is_429(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._call(self._workflow(), Admission(kind="queue_full", execution_id=uuid.uuid4(), queue=QueueInfo(0, 3, 1, 1)))
        self.assertEqual(ctx.exception.status_code, 429)

    async def test_an_editor_test_run_is_exempt(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        result = ExecutionResult(workflow_id=uuid.uuid4(), status="success", outputs={}, node_results=[], execution_time_ms=1.0)
        _, dispatch = await self._call(self._workflow(), result, query=b"test_run=true", session_user=user)
        self.assertTrue(dispatch.await_args.kwargs["concurrency_exempt"])

    async def test_test_run_without_a_session_is_gated(self) -> None:
        result = ExecutionResult(workflow_id=uuid.uuid4(), status="success", outputs={}, node_results=[], execution_time_ms=1.0)
        _, dispatch = await self._call(self._workflow(), result, query=b"test_run=true", session_user=None)
        self.assertFalse(dispatch.await_args.kwargs["concurrency_exempt"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_workflow_concurrency_api.py -q`
Expected: FAIL. `on_queued` is not passed and the endpoint does not return 202.

- [ ] **Step 3: Implement**

In `execute_workflow_endpoint`, capture the session user before `validate_workflow_auth` replaces it:

```python
    session_user = current_user
    current_user = await validate_workflow_auth(workflow, request, current_user, db)
```

After the `register_execution(...)` block and before `await db.commit()`, compute the exemption:

```python
    # Only the editor's own test runs skip the queue; ?test_run=true alone does not.
    concurrency_exempt = bool(
        test_run
        and session_user is not None
        and await user_has_workflow_access(db, workflow, session_user.id)
    )
```

Pass these to the `dispatch_workflow` call:

```python
            concurrency_limit=getattr(workflow, "concurrency_limit", None),
            concurrency_exempt=concurrency_exempt,
            on_queued="return",
            mint_status_token=workflow.auth_type == WorkflowAuthType.anonymous,
```

Use `getattr` here only. Older endpoint tests build workflows without the field, and Task 8's other call sites read real ORM rows. Directly after the `try/except/finally` around `dispatch_workflow`, insert:

```python
    if isinstance(execution_result, workflow_concurrency.Admission):
        if execution_result.kind == "queue_full":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=workflow_concurrency.QUEUE_FULL_MESSAGE,
            )
        body = workflow_concurrency.queued_body(
            execution_result, workflow_id=workflow.id, base_url=build_public_base_url(request)
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=body,
            headers={"Location": body["status_url"], "Retry-After": "5"},
        )
```

Make sure `WorkflowAuthType` and `user_has_workflow_access` are imported in `workflows.py`; both are already used in the file.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency_api.py tests/test_workflow_http_method.py tests/test_workflow_execution_api.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/workflows.py backend/tests/test_workflow_concurrency_api.py
git commit -m "feat(concurrency): webhook answers 202 with a status URL, or 429 when the queue is full"
```

---

### Task 10: Status endpoint and the anonymous run token

**Files:**
- Modify: `backend/app/models/schemas.py` (new `WorkflowExecutionStatusResponse`, `WorkflowExecutionQueueInfo`)
- Modify: `backend/app/api/workflows.py` (new route next to `/{workflow_id}/executions/{execution_id}/stream`)
- Test: `backend/tests/test_advisory_concurrency_status_token.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The status URL authenticates like the webhook; anonymous runs need their run token.

A stored digest must never authenticate, and the token is read from a header only.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request

from app.db.models import WorkflowAuthType
from app.services.secret_tokens import hash_secret


def _request(headers: dict[str, str] | None = None, query: bytes = b"") -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "query_string": query,
        },
        receive,
    )


class StatusEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, *, auth_type, headers=None, query=b"", stored_hash=None, validate=None):
        from app.api.workflows import get_workflow_execution_status

        workflow = SimpleNamespace(id=uuid.uuid4(), auth_type=auth_type)
        db = AsyncMock()
        db.get = AsyncMock(return_value=workflow)
        body = {"execution_id": "e", "workflow_id": str(workflow.id), "status": "queued", "queue": None, "outputs": None, "error": None, "execution_time_ms": None}
        with (
            patch("app.api.workflows.validate_workflow_auth", validate or AsyncMock()),
            patch("app.api.workflows.workflow_concurrency.status_token_hash_for", AsyncMock(return_value=stored_hash)),
            patch("app.api.workflows.workflow_concurrency.build_status_body", AsyncMock(return_value=body)),
        ):
            return await get_workflow_execution_status(
                workflow_id=workflow.id,
                execution_id=uuid.uuid4(),
                request=_request(headers, query),
                current_user=None,
                db=db,
            )

    async def test_an_anonymous_run_is_read_with_its_token(self) -> None:
        response = await self._call(auth_type=WorkflowAuthType.anonymous, headers={"X-Heym-Run-Token": "tok"}, stored_hash=hash_secret("tok"))
        self.assertEqual(response.status, "queued")

    async def test_an_anonymous_run_without_a_token_is_not_found(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._call(auth_type=WorkflowAuthType.anonymous, stored_hash=hash_secret("tok"))
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_the_stored_digest_does_not_authenticate(self) -> None:
        digest = hash_secret("tok")
        with self.assertRaises(HTTPException) as ctx:
            await self._call(auth_type=WorkflowAuthType.anonymous, headers={"X-Heym-Run-Token": digest}, stored_hash=digest)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_a_token_in_the_query_string_is_ignored(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._call(auth_type=WorkflowAuthType.anonymous, query=b"token=tok", stored_hash=hash_secret("tok"))
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_a_wrong_token_looks_like_an_unknown_run(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._call(auth_type=WorkflowAuthType.anonymous, headers={"X-Heym-Run-Token": "nope"}, stored_hash=hash_secret("tok"))
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_jwt_workflows_use_the_webhook_auth(self) -> None:
        validate = AsyncMock(side_effect=HTTPException(status_code=401, detail="JWT authentication required"))
        with self.assertRaises(HTTPException) as ctx:
            await self._call(auth_type=WorkflowAuthType.jwt, validate=validate)
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_header_auth_workflows_pass_through_validation(self) -> None:
        validate = AsyncMock()
        response = await self._call(auth_type=WorkflowAuthType.header_auth, validate=validate)
        validate.assert_awaited_once()
        self.assertEqual(response.status, "queued")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_advisory_concurrency_status_token.py -q`
Expected: FAIL with `ImportError: cannot import name 'get_workflow_execution_status'`.

- [ ] **Step 3: Add the response schema**

In `schemas.py`, near `ActiveExecutionItem`:

```python
class WorkflowExecutionQueueInfo(BaseModel):
    position: int
    size: int
    running: int
    limit: int | None


class WorkflowExecutionStatusResponse(BaseModel):
    """One run's state for callers that got a 202, or an MCP client polling."""

    execution_id: str
    workflow_id: str
    status: str
    queue: WorkflowExecutionQueueInfo | None = None
    outputs: Any | None = None
    error: str | None = None
    execution_time_ms: float | None = None
```

Make sure `Any` is imported in `schemas.py`.

- [ ] **Step 4: Add the route**

In `workflows.py`, directly before `@router.get("/{workflow_id}/executions/{execution_id}/stream")`:

```python
@router.get(
    "/{workflow_id}/executions/{execution_id}/status",
    response_model=WorkflowExecutionStatusResponse,
)
async def get_workflow_execution_status(
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    request: Request,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> WorkflowExecutionStatusResponse:
    """Status of one run, read with the credential that started it.

    An anonymous workflow has no credential to check, so its queued runs are read with
    the run token the 202 returned, from a header only. Anything that does not match
    is a 404, so the response never tells a guesser that an execution exists.
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    workflow = await db.get(Workflow, workflow_id)
    if workflow is None:
        raise not_found
    if workflow.auth_type == WorkflowAuthType.anonymous:
        stored_hash = await workflow_concurrency.status_token_hash_for(workflow_id, execution_id)
        presented = request.headers.get(workflow_concurrency.RUN_TOKEN_HEADER)
        if not workflow_concurrency.status_token_matches(stored_hash, presented):
            raise not_found
    else:
        await validate_workflow_auth(workflow, request, current_user, db)
    body = await workflow_concurrency.build_status_body(workflow_id, execution_id)
    if body is None:
        raise not_found
    return WorkflowExecutionStatusResponse.model_validate(body)
```

Add `WorkflowExecutionStatusResponse` to the `app.models.schemas` import in `workflows.py`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_advisory_concurrency_status_token.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/schemas.py backend/app/api/workflows.py backend/tests/test_advisory_concurrency_status_token.py
git commit -m "feat(concurrency): execution status URL with webhook auth and an anonymous run token"
```

---

### Task 11: Cancel held runs and list them as active

**Files:**
- Modify: `backend/app/api/workflows.py` (`cancel_workflow_execution`, line 4499)
- Modify: `backend/app/models/schemas.py` (`ActiveExecutionItem`)
- Modify: `backend/app/services/active_execution_overview.py` (`collect_active_executions_for_user`)
- Test: `backend/tests/test_workflow_concurrency_active.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Held runs show up as queued with their position, and Cancel removes them."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.workflow_concurrency import HeldRunRecord


class ActiveOverviewQueuedTests(unittest.IsolatedAsyncioTestCase):
    async def test_held_runs_are_listed_as_queued(self) -> None:
        from app.services import active_execution_overview

        record = HeldRunRecord(
            execution_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            workflow_name="wf",
            enqueued_at=datetime.now(timezone.utc),
            inputs={},
            position=2,
            size=3,
        )
        with (
            patch.object(active_execution_overview, "list_persisted_active_executions_for_user", AsyncMock(return_value=[])),
            patch.object(active_execution_overview, "list_active_executions", return_value=[]),
            patch.object(active_execution_overview, "list_pending_review_executions_for_user", AsyncMock(return_value=[])),
            patch.object(active_execution_overview.workflow_concurrency, "list_held_runs_for_user", AsyncMock(return_value=[record])),
        ):
            items = await active_execution_overview.collect_active_executions_for_user(AsyncMock(), uuid.uuid4())
        (item,) = items
        self.assertEqual((item.status, item.queue_position, item.queue_size), ("queued", 2, 3))


class CancelHeldEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_finds_a_held_run_first(self) -> None:
        from app.api.workflows import cancel_workflow_execution

        workflow = SimpleNamespace(id=uuid.uuid4(), name="wf", owner_id=uuid.uuid4())
        with (
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.workflows.cancel_pending_review_execution", AsyncMock(return_value=False)),
            patch("app.api.workflows.workflow_concurrency.cancel_held", AsyncMock(return_value=True)) as cancel_held,
            patch("app.api.workflows.cancel_active_execution") as cancel_local,
        ):
            result = await cancel_workflow_execution(
                workflow_id=workflow.id,
                execution_id=uuid.uuid4(),
                current_user=SimpleNamespace(id=uuid.uuid4(), email="a@b.c"),
                db=AsyncMock(),
            )
        self.assertEqual(result, {"status": "cancel_requested"})
        cancel_held.assert_awaited_once()
        cancel_local.assert_not_called()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_workflow_concurrency_active.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`ActiveExecutionItem` in `schemas.py`:

```python
    status: Literal["running", "pending", "queued"] = "running"
    pending_kind: Literal["hitl", "codex"] | None = None
    queue_position: int | None = None
    queue_size: int | None = None
```

In `active_execution_overview.py`, add `from app.services import workflow_concurrency`. Before the final `return sorted(...)`:

```python
    held_runs = (
        await _read("held runs", workflow_concurrency.list_held_runs_for_user(db, user_id)) or []
    )
    for record in held_runs:
        if record.execution_id in items_by_execution_id:
            continue
        items_by_execution_id[record.execution_id] = ActiveExecutionItem(
            execution_id=str(record.execution_id),
            workflow_id=str(record.workflow_id),
            workflow_name=record.workflow_name,
            started_at=record.enqueued_at,
            inputs=record.inputs,
            status="queued",
            queue_position=record.position,
            queue_size=record.size,
        )
```

In `cancel_workflow_execution`, after the `cancel_pending_review_execution` block:

```python
    if await workflow_concurrency.cancel_held(workflow_id, execution_id):
        audit(
            action="workflow.cancel_execution",
            actor=current_user,
            target_type="workflow",
            target_id=workflow.id,
            target_name=workflow.name,
            execution_id=str(execution_id),
            owner_id=str(workflow.owner_id),
            queued=True,
        )
        return {"status": "cancel_requested"}
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency_active.py tests/test_active_execution*.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/workflows.py backend/app/models/schemas.py backend/app/services/active_execution_overview.py backend/tests/test_workflow_concurrency_active.py
git commit -m "feat(concurrency): list held runs as queued and cancel them"
```

---

### Task 12: SSE: the queued stream and the `/execute/stream` gate

**Files:**
- Create: `backend/app/services/queued_run_stream.py`
- Modify: `backend/app/api/workflows.py` (`execute_workflow_stream`, from line 3882)
- Test: `backend/tests/test_workflow_concurrency_stream.py`

- [ ] **Step 1: Write the failing tests**

```python
"""A held run's SSE stream: queued updates, then started, then the result."""

import json
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from app.services import queued_run_stream


def _frames(chunks: list[str]) -> list[dict]:
    return [json.loads(c[len("data: "):]) for c in chunks if c.startswith("data: ")]


class QueuedRunStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_updates_then_started_then_complete(self) -> None:
        workflow_id, execution_id = uuid.uuid4(), uuid.uuid4()
        bodies = [
            {"status": "queued", "queue": {"position": 2, "size": 2, "running": 1, "limit": 1}},
            {"status": "queued", "queue": {"position": 2, "size": 2, "running": 1, "limit": 1}},
            {"status": "queued", "queue": {"position": 1, "size": 1, "running": 1, "limit": 1}},
            {"status": "running", "queue": None},
            {"status": "success", "queue": None, "outputs": {"a": 1}, "execution_time_ms": 9.0},
        ]
        with (
            patch.object(queued_run_stream.workflow_concurrency, "build_status_body", AsyncMock(side_effect=bodies)),
            patch.object(queued_run_stream, "POLL_SECONDS", 0),
        ):
            chunks = [c async for c in queued_run_stream.queued_run_events(workflow_id=workflow_id, execution_id=execution_id, is_disconnected=AsyncMock(return_value=False))]
        frames = _frames(chunks)
        self.assertEqual([f["type"] for f in frames], ["queued", "queued", "execution_started", "execution_complete"])
        self.assertEqual(frames[1]["position"], 1)
        self.assertEqual(frames[-1]["outputs"], {"a": 1})
        self.assertEqual(frames[-1]["execution_history_id"], str(execution_id))

    async def test_a_disconnect_stops_watching_without_cancelling(self) -> None:
        with patch.object(queued_run_stream.workflow_concurrency, "build_status_body", AsyncMock(return_value={"status": "queued", "queue": {"position": 1, "size": 1, "running": 1, "limit": 1}})):
            chunks = [c async for c in queued_run_stream.queued_run_events(workflow_id=uuid.uuid4(), execution_id=uuid.uuid4(), is_disconnected=AsyncMock(return_value=True))]
        self.assertEqual([f["type"] for f in _frames(chunks)], ["queued"])

    async def test_simple_response_sends_only_outputs_at_the_end(self) -> None:
        with (
            patch.object(queued_run_stream.workflow_concurrency, "build_status_body", AsyncMock(return_value={"status": "success", "queue": None, "outputs": {"a": 1}, "execution_time_ms": 1.0})),
            patch.object(queued_run_stream, "POLL_SECONDS", 0),
        ):
            chunks = [c async for c in queued_run_stream.queued_run_events(workflow_id=uuid.uuid4(), execution_id=uuid.uuid4(), is_disconnected=AsyncMock(return_value=False), simple_response=True)]
        self.assertEqual(_frames(chunks)[-1], {"outputs": {"a": 1}})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_workflow_concurrency_stream.py -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `queued_run_stream.py`**

```python
"""The SSE stream of a run that is waiting for a concurrency slot.

The run executes in the run queue worker, possibly in another process, so this stream
only watches it: queue updates while held, ``execution_started`` once claimed, and one
``execution_complete`` from the status body at the end. Node events and token deltas
are not streamed for a queued run. A disconnect stops watching; the run still executes.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.services import workflow_concurrency

POLL_SECONDS = 2.0
HEARTBEAT = ": heartbeat\n\n"
TERMINAL_STATUSES = frozenset({"success", "error", "pending", "cancelled", "expired"})


def _frame(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def queued_run_events(
    *,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    is_disconnected: Callable[[], Awaitable[bool]],
    simple_response: bool = False,
) -> AsyncIterator[str]:
    """Yield SSE frames for one held run until it ends or the client leaves."""
    last_queue: dict[str, Any] | None = None
    started = False
    while True:
        body = await workflow_concurrency.build_status_body(workflow_id, execution_id)
        status = (body or {}).get("status")
        if body is None:
            yield _frame({"type": "execution_complete", "workflow_id": str(workflow_id), "status": "error", "outputs": {"error": "Execution not found"}, "node_results": [], "execution_time_ms": 0.0, "execution_history_id": None})
            return
        if status == "queued":
            queue = body.get("queue")
            if queue != last_queue:
                last_queue = queue
                yield _frame({"type": "queued", "execution_id": str(execution_id), **(queue or {})})
        elif status == "running" and not started:
            started = True
            yield _frame({"type": "execution_started", "execution_id": str(execution_id)})
        elif status in TERMINAL_STATUSES:
            if simple_response:
                yield _frame({"outputs": body.get("outputs") or {}})
            else:
                yield _frame(
                    {
                        "type": "execution_complete",
                        "workflow_id": str(workflow_id),
                        "status": status,
                        "outputs": body.get("outputs") or {},
                        "node_results": [],
                        "execution_time_ms": body.get("execution_time_ms") or 0.0,
                        "execution_history_id": str(execution_id),
                    }
                )
            return
        if await is_disconnected():
            return
        await asyncio.sleep(POLL_SECONDS)
        yield HEARTBEAT
```

The terminal frame carries `node_results: []` on purpose. A queued run's node results stay in its history row and are not sent to an SSE caller.

- [ ] **Step 4: Gate `/execute/stream`**

In `execute_workflow_stream`:

1. Capture `session_user = current_user` before `current_user = await validate_workflow_auth(...)`.
2. After `public_base_url = build_public_base_url(request)` and before `import queue`, insert:

```python
    execution_id = uuid.uuid4()
    concurrency_exempt = bool(
        test_run
        and session_user is not None
        and await user_has_workflow_access(db, workflow, session_user.id)
    )
    holds_slot = False
    if getattr(workflow, "concurrency_limit", None) is not None and not concurrency_exempt:
        admission = await workflow_concurrency.admit(
            workflow_concurrency.HeldRun(
                workflow_id=workflow.id,
                execution_id=execution_id,
                placement=resolve_placement(execution_graph.nodes, workflow_cache),
                inputs=enriched_inputs,
                trigger_source=trigger_source,
                actor_user_id=credentials_owner_id,
                credentials_owner_id=credentials_owner_id,
                timeout_seconds=getattr(workflow, "workflow_timeout_seconds", None),
                run_options={"run_error_workflow": True},
            )
        )
        if admission.kind == "queue_full":
            await workflow_concurrency.record_queue_full(
                workflow_id=workflow.id,
                execution_id=execution_id,
                inputs=enriched_inputs,
                trigger_source=trigger_source,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=workflow_concurrency.QUEUE_FULL_MESSAGE,
            )
        if admission.kind == "queued":
            return StreamingResponse(
                queued_run_events(
                    workflow_id=workflow.id,
                    execution_id=execution_id,
                    is_disconnected=request.is_disconnected,
                    simple_response=simple_response,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        holds_slot = admission.holds_slot
```

3. Delete the now-duplicate `execution_id = uuid.uuid4()` line that follows `import queue`.
4. In `finalize_execution`, add a final step after the persist `try/except`:

```python
        if holds_slot:
            try:
                await workflow_concurrency.release(execution_id)
            except Exception:
                logger.exception("Could not release the concurrency slot of %s", execution_id)
```

Import `queued_run_events` from `app.services.queued_run_stream` and `resolve_placement` from `app.services.cluster.dispatch`.

- [ ] **Step 5: Add an endpoint-level test**

Append to `tests/test_workflow_concurrency_stream.py`. The request and result helpers are local copies of the ones in `test_workflow_execution_api.py`, because `tests/` is not a package:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

from starlette.requests import Request

from app.services.workflow_concurrency import Admission, QueueInfo


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _stream_request() -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/workflows/test/execute/stream",
            "headers": [(b"x-simple-response", b"false")],
            "query_string": b"",
        },
        receive,
    )


class StreamEndpointQueuedTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_held_run_gets_the_queued_stream_and_never_executes_here(self) -> None:
        from app.api.workflows import execute_workflow_stream

        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="wf",
            nodes=[{"id": "n1", "type": "textInput", "data": {"label": "Input"}}],
            edges=[],
            sse_enabled=True,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_node_config={},
            workflow_timeout_seconds=None,
            concurrency_limit=1,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        admission = Admission(kind="queued", execution_id=uuid.uuid4(), queue=QueueInfo(1, 1, 1, 1))

        async def fake_events(**_kwargs: object):
            yield 'data: {"type": "queued"}\n\n'

        register = MagicMock()
        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", register),
            patch("app.api.workflows.workflow_concurrency.admit", AsyncMock(return_value=admission)),
            patch("app.api.workflows.queued_run_events", fake_events),
        ):
            response = await execute_workflow_stream(
                workflow_id=workflow.id, request=_stream_request(), current_user=None, db=db
            )
            chunks = [chunk async for chunk in response.body_iterator]
        self.assertEqual(chunks, ['data: {"type": "queued"}\n\n'])
        register.assert_not_called()
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency_stream.py tests/test_sse_streaming.py tests/test_execute_do_not_wait_stream_release.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/queued_run_stream.py backend/app/api/workflows.py backend/tests/test_workflow_concurrency_stream.py
git commit -m "feat(concurrency): queued SSE stream for /execute/stream and Quick Drawer"
```

---

### Task 13: Portal

**Files:**
- Modify: `backend/app/api/portal.py` (`portal_execute` line 237, `portal_execute_stream` line 430, `portal_cancel_execution` line 797)
- Test: `backend/tests/test_workflow_concurrency_portal.py`

- [ ] **Step 1: Write the failing tests**

Model the tests on the existing Portal tests (`grep -l portal_execute backend/tests`). Cover three behaviours:

```python
"""Portal runs queue too: the stream watches, the plain endpoint waits, cancel reaches held runs."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.workflow_concurrency import Admission, QueueInfo


class PortalConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_held_run_carries_the_conversation(self) -> None:
        from app.api import portal

        captured = {}

        async def admit(run):
            captured["run"] = run
            return Admission(kind="queued", execution_id=run.execution_id, queue=QueueInfo(1, 1, 1, 1))

        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4(), nodes=[{"id": "o", "type": "output", "data": {}}], edges=[], concurrency_limit=1, workflow_timeout_seconds=None)
        execute_data = SimpleNamespace(inputs={"q": "hi"}, conversation_history=[SimpleNamespace(role="user", content="earlier")], conversation_id=uuid.uuid4())
        with patch.object(portal.workflow_concurrency, "admit", side_effect=admit):
            admission = await portal._admit_portal_run(
                workflow=workflow,
                execution_id=uuid.uuid4(),
                enriched_inputs={"body": {"q": "hi"}},
                execute_data=execute_data,
                workflow_cache={},
            )
        options = captured["run"].run_options
        self.assertEqual(options["conversation_history"], [{"role": "user", "content": "earlier"}])
        self.assertEqual(options["llm_session_id"], str(execute_data.conversation_id))
        self.assertEqual(admission.kind, "queued")

    async def test_no_limit_skips_admission(self) -> None:
        from app.api import portal

        workflow = SimpleNamespace(id=uuid.uuid4(), concurrency_limit=None)
        with patch.object(portal.workflow_concurrency, "admit", AsyncMock()) as admit:
            self.assertIsNone(
                await portal._admit_portal_run(
                    workflow=workflow,
                    execution_id=uuid.uuid4(),
                    enriched_inputs={},
                    execute_data=SimpleNamespace(conversation_history=[], conversation_id=None),
                    workflow_cache={},
                )
            )
        admit.assert_not_awaited()
```

Add a cancel test following `CancelHeldEndpointTests` in Task 11: `portal_cancel_execution` returns `{"status": "cancel_requested"}` when `workflow_concurrency.cancel_held` returns `True`.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_workflow_concurrency_portal.py -q`
Expected: FAIL with `AttributeError: _admit_portal_run`.

- [ ] **Step 3: Implement the shared helper in `portal.py`**

```python
async def _admit_portal_run(
    *,
    workflow: Workflow,
    execution_id: uuid.UUID,
    enriched_inputs: dict,
    execute_data: PortalExecuteRequest,
    workflow_cache: dict,
) -> workflow_concurrency.Admission | None:
    """Admit a Portal run. None when the workflow has no limit."""
    if workflow.concurrency_limit is None:
        return None
    history = [{"role": m.role, "content": m.content} for m in execute_data.conversation_history]
    run_options: dict = {"run_error_workflow": True}
    if history:
        run_options["conversation_history"] = history
    if execute_data.conversation_id:
        run_options["llm_session_id"] = str(execute_data.conversation_id)
    return await workflow_concurrency.admit(
        workflow_concurrency.HeldRun(
            workflow_id=workflow.id,
            execution_id=execution_id,
            placement=resolve_placement(workflow.nodes or [], workflow_cache),
            inputs=enriched_inputs,
            trigger_source="portal",
            actor_user_id=workflow.owner_id,
            credentials_owner_id=workflow.owner_id,
            timeout_seconds=workflow.workflow_timeout_seconds,
            run_options=run_options,
        )
    )
```

Import `workflow_concurrency`, `resolve_placement` (from `app.services.cluster.dispatch`), `wait_for_result` (same module) and `queued_run_events`.

Also add module-level helpers for releasing the stream's slot. The executor thread keeps running after the client disconnects and Starlette cancels the generator, so the release waits on the thread's future in a detached task, not in the generator:

```python
_SLOT_RELEASE_TASKS: set[asyncio.Task[None]] = set()


async def _release_slot_after(future: "asyncio.Future[Any]", execution_id: uuid.UUID) -> None:
    """Give the concurrency slot back once the executor thread ends, even after a disconnect."""
    try:
        await asyncio.shield(future)
    except BaseException:
        pass
    finally:
        with contextlib.suppress(Exception):
            await workflow_concurrency.release(execution_id)
```

Import `contextlib` and `typing.Any` if `portal.py` does not already.

- [ ] **Step 4: Gate `portal_execute_stream`**

`execution_id = uuid.uuid4()` sits directly above `cancel_event = register_execution(...)`. Insert the block between those two lines:

```python
    admission = await _admit_portal_run(
        workflow=workflow,
        execution_id=execution_id,
        enriched_inputs=enriched_inputs,
        execute_data=execute_data,
        workflow_cache=workflow_cache,
    )
    if admission is not None and admission.kind == "queue_full":
        await workflow_concurrency.record_queue_full(
            workflow_id=workflow.id, execution_id=execution_id, inputs=enriched_inputs, trigger_source="portal"
        )
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=workflow_concurrency.QUEUE_FULL_MESSAGE)
    if admission is not None and admission.kind == "queued":
        return StreamingResponse(
            queued_run_events(workflow_id=workflow.id, execution_id=execution_id, is_disconnected=request.is_disconnected),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
    holds_slot = admission is not None and admission.holds_slot
```

In `event_generator`, directly after `future = loop.run_in_executor(pool, run_executor)`:

```python
            if holds_slot:
                task = asyncio.create_task(_release_slot_after(future, execution_id))
                _SLOT_RELEASE_TASKS.add(task)
                task.add_done_callback(_SLOT_RELEASE_TASKS.discard)
```

Add a test to `test_workflow_concurrency_portal.py` for the helper:

```python
class PortalSlotReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_slot_is_released_when_the_executor_ends(self) -> None:
        import asyncio

        from app.api import portal

        future = asyncio.get_running_loop().create_future()
        execution_id = uuid.uuid4()
        with patch.object(portal.workflow_concurrency, "release", AsyncMock()) as release:
            task = asyncio.create_task(portal._release_slot_after(future, execution_id))
            await asyncio.sleep(0)
            release.assert_not_awaited()
            future.set_result(None)
            await task
        release.assert_awaited_once_with(execution_id)

    async def test_a_failed_executor_still_releases(self) -> None:
        import asyncio

        from app.api import portal

        future = asyncio.get_running_loop().create_future()
        future.set_exception(RuntimeError("boom"))
        with patch.object(portal.workflow_concurrency, "release", AsyncMock()) as release:
            await portal._release_slot_after(future, uuid.uuid4())
        release.assert_awaited_once()
```

- [ ] **Step 5: Gate `portal_execute`**

Here too `execution_id = uuid.uuid4()` sits directly above `cancel_event = register_execution(...)`. Insert between those two lines:

```python
    admission = await _admit_portal_run(
        workflow=workflow,
        execution_id=execution_id,
        enriched_inputs=enriched_inputs,
        execute_data=execute_data,
        workflow_cache=workflow_cache,
    )
    if admission is not None and admission.kind == "queue_full":
        await workflow_concurrency.record_queue_full(
            workflow_id=workflow.id, execution_id=execution_id, inputs=enriched_inputs, trigger_source="portal"
        )
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=workflow_concurrency.QUEUE_FULL_MESSAGE)
    if admission is not None and admission.kind == "queued":
        # A Portal browser has no use for a status URL: wait here like a background trigger.
        waited = await wait_for_result(execution_id, timeout_seconds=workflow.workflow_timeout_seconds)
        return WorkflowExecuteResponse(
            workflow_id=workflow.id,
            status=waited.status,
            outputs=waited.outputs,
            node_results=[],
            execution_time_ms=waited.execution_time_ms,
            execution_history_id=execution_id if waited.history_written else None,
        )
    holds_slot = admission is not None and admission.holds_slot
```

Change the `finally: clear_active_execution(execution_id)` around the in-process run to also release:

```python
    finally:
        clear_active_execution(execution_id)
        if holds_slot:
            with contextlib.suppress(Exception):
                await workflow_concurrency.release(execution_id)
```

- [ ] **Step 6: Cancel held Portal runs**

In `portal_cancel_execution`, after the workflow is loaded and the session validated, and before `cancel_active_execution(...)`:

```python
    if await workflow_concurrency.cancel_held(workflow.id, execution_id):
        return {"status": "cancel_requested"}
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency_portal.py tests/test_portal*.py -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/portal.py backend/tests/test_workflow_concurrency_portal.py
git commit -m "feat(concurrency): queue Portal runs and cancel held ones"
```

---

### Task 14: MCP: queued result and `heym_execution_status`

**Files:**
- Create: `backend/app/services/mcp_execution_status.py`
- Modify: `backend/app/api/mcp.py` (`build_tools_with_chat` line 606, REST `call_mcp_tool` line 1063, JSON-RPC `tools/list` and `tools/call` lines 1302-1400)
- Modify: `backend/app/api/mcp_servers.py` (`list_named_server_tools` line 388, JSON-RPC `tools/list` and `tools/call` lines 500-600)
- Test: `backend/tests/test_workflow_concurrency_mcp.py`

- [ ] **Step 1: Write the failing tests**

```python
"""MCP gets a queued result to poll, and the status tool sees only exposed workflows."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import mcp_execution_status
from app.services.workflow_concurrency import Admission, QueueInfo


def _wf(limit: int | None = 1) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), concurrency_limit=limit)


class ToolListingTests(unittest.TestCase):
    def test_listed_only_when_an_exposed_workflow_has_a_limit(self) -> None:
        self.assertTrue(mcp_execution_status.should_list([_wf(None), _wf(2)]))
        self.assertFalse(mcp_execution_status.should_list([_wf(None)]))

    def test_the_tool_takes_an_execution_id(self) -> None:
        tool = mcp_execution_status.build_execution_status_tool()
        self.assertEqual(tool.name, "heym_execution_status")
        self.assertIn("execution_id", tool.inputSchema.model_dump()["properties"])


class QueuedTextTests(unittest.TestCase):
    def test_a_queued_admission_is_a_non_error_with_a_next_step(self) -> None:
        execution_id = uuid.uuid4()
        text, is_error = mcp_execution_status.admission_tool_text(Admission(kind="queued", execution_id=execution_id, queue=QueueInfo(2, 3, 1, 1)))
        payload = json.loads(text)
        self.assertFalse(is_error)
        self.assertEqual(payload["execution_id"], str(execution_id))
        self.assertEqual(payload["queue"]["position"], 2)
        self.assertIn("heym_execution_status", payload["next_step"])

    def test_a_full_queue_is_an_error(self) -> None:
        text, is_error = mcp_execution_status.admission_tool_text(Admission(kind="queue_full", execution_id=uuid.uuid4()))
        self.assertTrue(is_error)
        self.assertIn("full", text)


class StatusToolCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_exposed_workflows_run_is_found(self) -> None:
        workflow = _wf()
        body = {"execution_id": "e", "workflow_id": str(workflow.id), "status": "running"}
        with (
            patch.object(mcp_execution_status, "_workflow_of_execution", AsyncMock(return_value=workflow.id)),
            patch.object(mcp_execution_status.workflow_concurrency, "build_status_body", AsyncMock(return_value=body)),
        ):
            text, is_error = await mcp_execution_status.run_execution_status_tool([workflow], {"execution_id": str(uuid.uuid4())})
        self.assertFalse(is_error)
        self.assertEqual(json.loads(text)["status"], "running")

    async def test_another_workflows_run_is_not_found(self) -> None:
        with patch.object(mcp_execution_status, "_workflow_of_execution", AsyncMock(return_value=uuid.uuid4())):
            text, is_error = await mcp_execution_status.run_execution_status_tool([_wf()], {"execution_id": str(uuid.uuid4())})
        self.assertTrue(is_error)
        self.assertIn("not found", text.lower())

    async def test_a_malformed_id_is_an_error(self) -> None:
        text, is_error = await mcp_execution_status.run_execution_status_tool([_wf()], {"execution_id": "nope"})
        self.assertTrue(is_error)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_workflow_concurrency_mcp.py -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `mcp_execution_status.py`**

```python
"""MCP side of the concurrency limit: the queued tool result and heym_execution_status."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from app.db.models import ExecutionHistory, WorkflowRunQueue
from app.db.session import async_session_maker
from app.models.schemas import MCPTool, MCPToolInputSchema
from app.services import workflow_concurrency

MCP_EXECUTION_STATUS_TOOL_NAME = "heym_execution_status"
NEXT_STEP = (
    f"Call {MCP_EXECUTION_STATUS_TOOL_NAME} with this execution_id every 5-10 seconds "
    "until status is success, error, cancelled or expired."
)


def should_list(workflows: Sequence[Any]) -> bool:
    """Offer the tool only where a run can actually be queued."""
    return any(getattr(w, "concurrency_limit", None) is not None for w in workflows)


def build_execution_status_tool() -> MCPTool:
    return MCPTool(
        name=MCP_EXECUTION_STATUS_TOOL_NAME,
        description=(
            "Get the status of a workflow run that was queued because the workflow reached "
            "its concurrency limit. Returns status (queued, running, success, error, "
            "cancelled, expired), the queue position while queued, and the outputs when done."
        ),
        inputSchema=MCPToolInputSchema(
            type="object",
            properties={
                "execution_id": {
                    "type": "string",
                    "description": "The execution_id returned by the queued tool call.",
                }
            },
            required=["execution_id"],
        ),
    )


def admission_tool_text(admission: workflow_concurrency.Admission) -> tuple[str, bool]:
    """Tool text for a run that did not start: (text, is_error)."""
    if admission.kind == "queue_full":
        return workflow_concurrency.QUEUE_FULL_MESSAGE, True
    payload = {
        "status": "queued",
        "execution_id": str(admission.execution_id),
        "queue": admission.queue.as_dict() if admission.queue else None,
        "next_step": NEXT_STEP,
    }
    return json.dumps(payload, indent=2), False


async def _workflow_of_execution(execution_id: uuid.UUID) -> uuid.UUID | None:
    async with async_session_maker() as db:
        workflow_id = (
            await db.execute(
                select(WorkflowRunQueue.workflow_id).where(
                    WorkflowRunQueue.execution_id == execution_id
                )
            )
        ).scalar_one_or_none()
        if workflow_id is not None:
            return workflow_id
        return (
            await db.execute(
                select(ExecutionHistory.workflow_id).where(ExecutionHistory.id == execution_id)
            )
        ).scalar_one_or_none()


async def run_execution_status_tool(
    workflows: Sequence[Any], arguments: dict[str, Any]
) -> tuple[str, bool]:
    """Status of one run of a workflow this MCP surface exposes: (text, is_error)."""
    not_found = ("Execution not found", True)
    try:
        execution_id = uuid.UUID(str(arguments.get("execution_id", "")))
    except ValueError:
        return "execution_id must be a UUID", True
    workflow_id = await _workflow_of_execution(execution_id)
    if workflow_id is None or workflow_id not in {w.id for w in workflows}:
        return not_found
    body = await workflow_concurrency.build_status_body(workflow_id, execution_id)
    if body is None:
        return not_found
    return json.dumps(body, indent=2, ensure_ascii=False, default=str), False
```

Check how `MCPToolInputSchema` is declared in `schemas.py` and match its field names. `workflow_to_mcp_tool` in `mcp.py` builds one; follow it.

- [ ] **Step 4: Wire it into the MCP surfaces**

1. `build_tools_with_chat` in `mcp.py` (shared by both surfaces):

```python
    tools = [workflow_to_mcp_tool(w) for w in workflows]
    if mcp_execution_status.should_list(workflows):
        tools.append(mcp_execution_status.build_execution_status_tool())
```

2. REST `call_mcp_tool` in `mcp.py`: after the `heym_chat` branch, load `workflows = await get_user_mcp_workflows(db, mcp_user.id)` once (the code below already does; hoist it) and add:

```python
    if tool_name == mcp_execution_status.MCP_EXECUTION_STATUS_TOOL_NAME:
        text, is_error = await mcp_execution_status.run_execution_status_tool(workflows, arguments)
        return MCPToolResult(content=[MCPTextContent(text=text)], isError=is_error)
```

Pass `concurrency_limit=target_workflow.concurrency_limit, on_queued="return"` to its `dispatch_workflow` call, and directly after the call:

```python
        if isinstance(execution_result, workflow_concurrency.Admission):
            text, is_error = mcp_execution_status.admission_tool_text(execution_result)
            return MCPToolResult(content=[MCPTextContent(text=text)], isError=is_error)
```

3. JSON-RPC `tools/call` in `mcp.py` gets the same three changes as the REST path: the status-tool branch, the `concurrency_limit=target_workflow.concurrency_limit, on_queued="return"` keywords on its `dispatch_workflow` call, and the `Admission` check directly after that call. Its returns use `_mcp_tool_result_jsonrpc_response(msg.id, text, is_error=is_error)`.
4. `mcp_servers.py` JSON-RPC `tools/call` gets the same three changes. It uses `workflows = await _get_server_workflows(db, mcp_server.id)` for the status tool's scope and `_mcp_tool_result_jsonrpc_response` for its returns.

Add `from app.services import mcp_execution_status, workflow_concurrency` to both API modules.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency_mcp.py tests/test_workflow_concurrency_call_sites.py tests/test_mcp*.py tests/test_advisory_mcp*.py -q`
Expected: all pass, and `test_workflow_concurrency_call_sites.py` is green for every file. Existing MCP tests that build workflows without `concurrency_limit` need `concurrency_limit=None` added to their fixtures.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/mcp_execution_status.py backend/app/api/mcp.py backend/app/api/mcp_servers.py backend/tests
git commit -m "feat(concurrency): queued MCP results and the heym_execution_status tool"
```

---

### Task 15: Release on execution recovery

**Files:**
- Modify: `backend/app/services/execution_recovery.py` (`_finalize`, line 190)
- Test: `backend/tests/test_workflow_concurrency_recovery.py`

- [ ] **Step 1: Write the failing test**

Read `_finalize` first. Then write a test, using the mocking style already in `tests/test_execution_recovery*.py`, that calls `_finalize` for an orphan and asserts `app.services.execution_recovery.workflow_concurrency.release` was awaited with `orphan.execution_id`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_workflow_concurrency_recovery.py -q`
Expected: FAIL (`release` not awaited).

- [ ] **Step 3: Implement**

At the end of `_finalize` (after its history and queue updates):

```python
        # A recovered or skipped run is over either way; its slot goes to the next in line.
        try:
            await workflow_concurrency.release(orphan.execution_id)
        except Exception:
            logger.exception("Could not release the concurrency slot of %s", orphan.execution_id)
```

Import `from app.services import workflow_concurrency`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_workflow_concurrency_recovery.py tests/test_execution_recovery*.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/execution_recovery.py backend/tests/test_workflow_concurrency_recovery.py
git commit -m "feat(concurrency): give a recovered run's slot back"
```

---

### Task 16: Backend full check

- [ ] **Step 1: Run the whole backend suite with Postgres up**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:6543/heym SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh
```
Expected: lint, typecheck and all backend tests pass. `check.sh` applies `ruff format`; commit any formatting-only diff:

```bash
git add -A && git commit -m "style: ruff format"
```

---

### Task 17: Frontend types, API and queued SSE callback

**Files:**
- Modify: `frontend/src/types/workflow.ts` (Workflow near line 48; `ActiveExecutionItem` line 1267)
- Modify: `frontend/src/services/api.ts` (`update` Pick list line 619; `executeStream` options and event loop near line 1065)

- [ ] **Step 1: Types**

In `Workflow`:

```ts
  workflow_timeout_seconds: number | null;
  /** Production runs allowed at once; null turns the limit off. */
  concurrency_limit?: number | null;
  concurrency_max_queue?: number | null;
  concurrency_max_wait_seconds?: number | null;
```

Next to the Workflow interface:

```ts
export interface WorkflowConcurrencyPatch {
  concurrency_limit?: number | null;
  concurrency_max_queue?: number | null;
  concurrency_max_wait_seconds?: number | null;
}

export interface QueuedRunEvent {
  execution_id: string;
  position: number;
  size: number;
  running: number;
  limit: number | null;
}
```

`ActiveExecutionItem`:

```ts
  /** running = live worker; pending = waiting on HITL / Codex review; queued = waiting for a concurrency slot */
  status?: "running" | "pending" | "queued";
  pending_kind?: "hitl" | "codex" | null;
  queue_position?: number | null;
  queue_size?: number | null;
```

- [ ] **Step 2: API**

Add `| "concurrency_limit" | "concurrency_max_queue" | "concurrency_max_wait_seconds"` to the `update` Pick list. The server clears a field on `0`, so callers send `0`, not `null`. Widen the value type:

```ts
    > & {
      base_updated_at?: string;
      concurrency_limit?: number | null;
      concurrency_max_queue?: number | null;
      concurrency_max_wait_seconds?: number | null;
    },
```

In `executeStream`, extend the `options` parameter type with `onQueued?: (data: QueuedRunEvent) => void`. In the event loop, add a branch before `execution_started`:

```ts
              if (data.type === "queued") {
                options?.onQueued?.({
                  execution_id: data.execution_id,
                  position: data.position,
                  size: data.size,
                  running: data.running,
                  limit: data.limit ?? null,
                });
              } else if (data.type === "execution_started") {
```

- [ ] **Step 3: Verify**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/services/api.ts
git commit -m "feat(concurrency): frontend types and queued SSE callback"
```

---

### Task 18: Properties panel settings

**Files:**
- Create: `frontend/src/components/Panels/propertiesPanel/concurrencySettings.ts`
- Create: `frontend/src/components/Panels/propertiesPanel/concurrencySettings.test.ts`
- Create: `frontend/src/components/Panels/propertiesPanel/useWorkflowConcurrencySettings.ts`
- Create: `frontend/src/components/Panels/propertiesPanel/WorkflowConcurrencySettings.vue`
- Modify: `frontend/src/components/Panels/propertiesPanel/WorkflowSettingsPanel.vue`

- [ ] **Step 1: Write the failing Vitest**

```ts
import { describe, expect, it } from "vitest";

import {
  parsePositiveInteger,
  toConcurrencyUpdatePayload,
  togglePatch,
} from "@/components/Panels/propertiesPanel/concurrencySettings";

describe("parsePositiveInteger", () => {
  it("returns null for empty, zero, negative and non-numeric input", () => {
    expect(parsePositiveInteger("")).toBeNull();
    expect(parsePositiveInteger("0")).toBeNull();
    expect(parsePositiveInteger("-3")).toBeNull();
    expect(parsePositiveInteger("abc")).toBeNull();
  });

  it("floors positive numbers", () => {
    expect(parsePositiveInteger("2.7")).toBe(2);
  });
});

describe("togglePatch", () => {
  it("turns the limit on at 1 and off at null", () => {
    expect(togglePatch(null)).toEqual({ concurrency_limit: 1 });
    expect(togglePatch(3)).toEqual({ concurrency_limit: null });
  });
});

describe("toConcurrencyUpdatePayload", () => {
  it("sends 0 to clear a field, because the server clears on 0", () => {
    expect(toConcurrencyUpdatePayload({ concurrency_limit: null, concurrency_max_queue: 5 })).toEqual({
      concurrency_limit: 0,
      concurrency_max_queue: 5,
    });
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && bun run test -- src/components/Panels/propertiesPanel/concurrencySettings.test.ts`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `concurrencySettings.ts`**

```ts
import type { WorkflowConcurrencyPatch } from "@/types/workflow";

/** A positive whole number, or null for empty and invalid input. */
export function parsePositiveInteger(raw: string): number | null {
  if (raw.trim() === "") return null;
  const parsed = Math.floor(Number(raw));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/** Switching on starts at one run at a time; switching off clears the limit. */
export function togglePatch(currentLimit: number | null): WorkflowConcurrencyPatch {
  return { concurrency_limit: currentLimit === null ? 1 : null };
}

/** The PUT body: the server clears a field on 0, not on null. */
export function toConcurrencyUpdatePayload(
  patch: WorkflowConcurrencyPatch,
): Record<string, number> {
  const payload: Record<string, number> = {};
  for (const [key, value] of Object.entries(patch)) {
    payload[key] = value ?? 0;
  }
  return payload;
}
```

- [ ] **Step 4: Write the composable**

```ts
import { computed, type ComputedRef } from "vue";

import type { WorkflowConcurrencyPatch } from "@/types/workflow";
import { toConcurrencyUpdatePayload } from "@/components/Panels/propertiesPanel/concurrencySettings";
import { workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";

export interface WorkflowConcurrencySettingsState {
  limit: ComputedRef<number | null>;
  maxQueue: ComputedRef<number | null>;
  maxWaitSeconds: ComputedRef<number | null>;
  readOnly: ComputedRef<boolean>;
  save: (patch: WorkflowConcurrencyPatch) => Promise<void>;
}

/** Editors (owner and write shares) change the limit; read-only viewers see it. */
export function useWorkflowConcurrencySettings(): WorkflowConcurrencySettingsState {
  const workflowStore = useWorkflowStore();

  const limit = computed(() => workflowStore.currentWorkflow?.concurrency_limit ?? null);
  const maxQueue = computed(() => workflowStore.currentWorkflow?.concurrency_max_queue ?? null);
  const maxWaitSeconds = computed(
    () => workflowStore.currentWorkflow?.concurrency_max_wait_seconds ?? null,
  );
  const readOnly = computed(() => workflowStore.isReadOnly);

  async function save(patch: WorkflowConcurrencyPatch): Promise<void> {
    const wf = workflowStore.currentWorkflow;
    if (!wf || workflowStore.isReadOnly) return;
    const previous: WorkflowConcurrencyPatch = {
      concurrency_limit: wf.concurrency_limit ?? null,
      concurrency_max_queue: wf.concurrency_max_queue ?? null,
      concurrency_max_wait_seconds: wf.concurrency_max_wait_seconds ?? null,
    };
    Object.assign(wf, patch);
    try {
      await workflowApi.update(wf.id, toConcurrencyUpdatePayload(patch));
    } catch {
      Object.assign(wf, previous);
    }
  }

  return { limit, maxQueue, maxWaitSeconds, readOnly, save };
}
```

- [ ] **Step 5: Write the component**

```vue
<script setup lang="ts">
import { Layers } from "lucide-vue-next";

import {
  parsePositiveInteger,
  togglePatch,
} from "@/components/Panels/propertiesPanel/concurrencySettings";
import { useWorkflowConcurrencySettings } from "@/components/Panels/propertiesPanel/useWorkflowConcurrencySettings";

const { limit, maxQueue, maxWaitSeconds, readOnly, save } = useWorkflowConcurrencySettings();

function onLimit(raw: string): void {
  void save({ concurrency_limit: parsePositiveInteger(raw) ?? 1 });
}

function onMaxQueue(raw: string): void {
  void save({ concurrency_max_queue: parsePositiveInteger(raw) });
}

function onMaxWait(raw: string): void {
  void save({ concurrency_max_wait_seconds: parsePositiveInteger(raw) });
}
</script>

<template>
  <div
    class="border-t border-border/40 pt-4 pb-4"
    data-testid="workflow-concurrency-settings"
  >
    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-2 min-w-0">
        <Layers class="w-4 h-4 text-muted-foreground shrink-0" />
        <span class="text-sm font-medium">Concurrency limit</span>
      </div>
      <button
        type="button"
        role="switch"
        data-testid="workflow-concurrency-toggle"
        :aria-checked="limit !== null"
        :disabled="readOnly"
        class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        :class="limit !== null ? 'bg-primary' : 'bg-muted-foreground/30'"
        @click="save(togglePatch(limit))"
      >
        <span
          class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
          :class="limit !== null ? 'translate-x-4' : 'translate-x-0.5'"
        />
      </button>
    </div>
    <p class="text-xs text-muted-foreground mt-2 leading-relaxed">
      Production runs (webhooks, cron, MCP, Portal, triggers) above the limit wait in a
      first-in, first-out queue. Editor test runs always start right away.
    </p>

    <div
      v-if="limit !== null"
      class="mt-3 space-y-3"
    >
      <label class="block">
        <span class="text-xs font-medium">Max concurrent runs</span>
        <input
          data-testid="workflow-concurrency-limit"
          type="number"
          min="1"
          step="1"
          class="mt-1 w-full text-sm rounded-md border border-border bg-background px-2 py-1.5 disabled:opacity-50"
          :value="limit"
          :disabled="readOnly"
          @change="onLimit(($event.target as HTMLInputElement).value)"
        >
      </label>
      <label class="block">
        <span class="text-xs font-medium">Max queue size (optional)</span>
        <input
          data-testid="workflow-concurrency-max-queue"
          type="number"
          min="1"
          step="1"
          class="mt-1 w-full text-sm rounded-md border border-border bg-background px-2 py-1.5 disabled:opacity-50"
          :value="maxQueue ?? ''"
          :disabled="readOnly"
          placeholder="Empty = no limit"
          @change="onMaxQueue(($event.target as HTMLInputElement).value)"
        >
      </label>
      <label class="block">
        <span class="text-xs font-medium">Max wait (seconds, optional)</span>
        <input
          data-testid="workflow-concurrency-max-wait"
          type="number"
          min="1"
          step="1"
          class="mt-1 w-full text-sm rounded-md border border-border bg-background px-2 py-1.5 disabled:opacity-50"
          :value="maxWaitSeconds ?? ''"
          :disabled="readOnly"
          placeholder="Empty = wait as long as it takes"
          @change="onMaxWait(($event.target as HTMLInputElement).value)"
        >
      </label>
      <p class="text-xs text-muted-foreground leading-relaxed">
        A full queue answers 429. A run that waits longer than the max wait is
        recorded as expired.
      </p>
    </div>
  </div>
</template>
```

- [ ] **Step 6: Render it in `WorkflowSettingsPanel.vue`**

Import `WorkflowConcurrencySettings` and place `<WorkflowConcurrencySettings />` between the "Workflow timeout" block and the "Auto-recover runs" block.

- [ ] **Step 7: Run the checks**

Run: `cd frontend && bun run test -- src/components/Panels/propertiesPanel/concurrencySettings.test.ts && bun run lint && bun run typecheck`
Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Panels/propertiesPanel
git commit -m "feat(concurrency): concurrency limit in the workflow properties panel"
```

---

### Task 19: Queued rows in History and the active badge

**Files:**
- Create: `frontend/src/components/Panels/activeExecutionStatus.ts`
- Create: `frontend/src/components/Panels/activeExecutionStatus.test.ts`
- Create: `frontend/src/components/Panels/ActiveExecutionStatusLabel.vue`
- Modify: `frontend/src/components/Panels/ExecutionHistoryDialog.vue` (active row near line 876)
- Modify: `frontend/src/components/Panels/ExecutionHistoryAllDialog.vue` (its active row block)
- Modify: `frontend/src/components/Layout/ActiveWorkflowsDropdown.vue` (status text)

- [ ] **Step 1: Write the failing Vitest**

```ts
import { describe, expect, it } from "vitest";

import { activeExecutionStatus } from "@/components/Panels/activeExecutionStatus";

describe("activeExecutionStatus", () => {
  it("labels a queued run with its position", () => {
    expect(activeExecutionStatus({ status: "queued", queue_position: 2, queue_size: 5 })).toEqual({
      kind: "queued",
      label: "Queued 2/5",
      canOpenLive: false,
    });
  });

  it("keeps running runs live", () => {
    expect(activeExecutionStatus({ status: "running" })).toEqual({
      kind: "running",
      label: "Running",
      canOpenLive: true,
    });
  });

  it("treats a missing status as running", () => {
    expect(activeExecutionStatus({}).kind).toBe("running");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && bun run test -- src/components/Panels/activeExecutionStatus.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement the helper and the label**

`activeExecutionStatus.ts`:

```ts
import type { ActiveExecutionItem } from "@/types/workflow";

export interface ActiveExecutionStatusView {
  kind: "running" | "pending" | "queued";
  label: string;
  canOpenLive: boolean;
}

/** How a row in the active section of the history dialogs reads. */
export function activeExecutionStatus(
  item: Pick<ActiveExecutionItem, "status" | "queue_position" | "queue_size">,
): ActiveExecutionStatusView {
  if (item.status === "queued") {
    const position = item.queue_position ?? "?";
    const size = item.queue_size ?? "?";
    return { kind: "queued", label: `Queued ${position}/${size}`, canOpenLive: false };
  }
  if (item.status === "pending") {
    return { kind: "pending", label: "Pending review", canOpenLive: true };
  }
  return { kind: "running", label: "Running", canOpenLive: true };
}
```

`ActiveExecutionStatusLabel.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import { Clock, Loader2 } from "lucide-vue-next";

import type { ActiveExecutionItem } from "@/types/workflow";
import { activeExecutionStatus } from "@/components/Panels/activeExecutionStatus";

const props = defineProps<{ item: ActiveExecutionItem }>();

const view = computed(() => activeExecutionStatus(props.item));
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5"
    :data-testid="`active-execution-status-${item.execution_id}`"
  >
    <Clock
      v-if="view.kind === 'queued'"
      class="w-3 h-3 text-amber-500 shrink-0"
    />
    <Loader2
      v-else
      class="w-3 h-3 text-blue-400 animate-spin shrink-0"
    />
    <span
      class="text-xs font-medium"
      :class="view.kind === 'queued' ? 'text-amber-500' : 'text-blue-400'"
    >{{ view.label }}</span>
  </span>
</template>
```

- [ ] **Step 4: Use the label in both dialogs and the dropdown**

In `ExecutionHistoryDialog.vue`, replace the `<Loader2 .../>` and `<span ...>Running</span>` pair in the active row with `<ActiveExecutionStatusLabel :item="active" />`. Add `v-if="activeExecutionStatus(active).canOpenLive"` to the "Open live" `Button`. Make the same change in `ExecutionHistoryAllDialog.vue`'s active rows. Before editing `ActiveWorkflowsDropdown.vue`, read how it labels pending runs. Then make queued rows show `activeExecutionStatus(item).label` the same way, and leave every other row's rendering unchanged.

- [ ] **Step 5: Badges for the two new history statuses**

Both history dialogs render a text badge from `frontend/src/lib/executionHistoryStatus.ts`. First add these cases to `frontend/src/lib/executionHistoryStatus.test.ts` inside `describe("getHistoryStatusBadgeClass")`:

```ts
  it("badges runs that never executed because of the concurrency limit", () => {
    expect(getHistoryStatusBadgeClass("expired")).toContain("amber");
    expect(getHistoryStatusBadgeClass("queue_full")).toContain("orange");
  });
```

Run `bun run test -- src/lib/executionHistoryStatus.test.ts` and confirm it fails. Then add to `BADGE_CLASSES`:

```ts
  expired: "bg-amber-500/20 text-amber-500",
  queue_full: "bg-orange-500/20 text-orange-500",
```

The filter list (`HISTORY_STATUS_OPTIONS`) stays as it is. Like pending and skipped, these are rare and covered by All Statuses.

- [ ] **Step 6: Run the checks**

Run: `cd frontend && bun run test -- src/components/Panels/activeExecutionStatus.test.ts src/lib/executionHistoryStatus.test.ts && bun run lint && bun run typecheck`
Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Panels frontend/src/components/Layout/ActiveWorkflowsDropdown.vue frontend/src/lib/executionHistoryStatus.ts frontend/src/lib/executionHistoryStatus.test.ts
git commit -m "feat(concurrency): show queued runs in History with their position"
```

---

### Task 20: Quick Drawer and Portal waiting display

**Files:**
- Modify: `frontend/src/types/quickDrawer.ts` (`QuickDrawerRunState`)
- Modify: `frontend/src/stores/quickDrawer.ts` (`executeStream` call near line 560-626)
- Modify: `frontend/src/components/Layout/QuickWorkflowRunResult.vue` (status line near line 63)
- Modify: `frontend/src/views/ChatPortalView.vue` (event loop near line 493)
- Create: `frontend/src/stores/quickDrawerQueue.ts` and `frontend/src/stores/quickDrawerQueue.test.ts`

- [ ] **Step 1: Write the failing Vitest**

```ts
import { describe, expect, it } from "vitest";

import { queueLabel, normalizeRunStatus } from "@/stores/quickDrawerQueue";

describe("queueLabel", () => {
  it("reads like the history badge", () => {
    expect(queueLabel({ execution_id: "e", position: 2, size: 5, running: 1, limit: 1 })).toBe(
      "Waiting in queue (2/5)",
    );
  });
});

describe("normalizeRunStatus", () => {
  it("maps a run that never executed to error", () => {
    expect(normalizeRunStatus("expired")).toBe("error");
    expect(normalizeRunStatus("cancelled")).toBe("error");
    expect(normalizeRunStatus("queue_full")).toBe("error");
  });

  it("keeps the statuses the drawer already knows", () => {
    expect(normalizeRunStatus("success")).toBe("success");
    expect(normalizeRunStatus("awaiting_file_upload")).toBe("pending");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && bun run test -- src/stores/quickDrawerQueue.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement**

`quickDrawerQueue.ts`:

```ts
import type { QueuedRunEvent } from "@/types/workflow";
import type { QuickDrawerRunState } from "@/types/quickDrawer";

export function queueLabel(event: QueuedRunEvent): string {
  return `Waiting in queue (${event.position}/${event.size})`;
}

/** Statuses a queued run can end in that the drawer has no state for read as errors. */
export function normalizeRunStatus(status: string): QuickDrawerRunState["status"] {
  if (status === "awaiting_file_upload") return "pending";
  if (status === "success" || status === "error" || status === "pending") return status;
  return "error";
}
```

Add `queueMessage: string | null;` to `QuickDrawerRunState` and `queueMessage: null` to `createEmptyRunState()`. In the `executeStream` call, pass `onQueued` through the options object (the last argument, which already holds `triggerSource`):

```ts
      {
        triggerSource: "Quick Drawer",
        onQueued: (event) => {
          runState.value = { ...runState.value, executionId: event.execution_id, queueMessage: queueLabel(event) };
        },
      },
```

In the `execution_started` callback and in `onComplete`, set `queueMessage: null`. In `onComplete`, replace `status: result.status === "awaiting_file_upload" ? "pending" : result.status` with `status: normalizeRunStatus(result.status)`. In `QuickWorkflowRunResult.vue`, when `runState.status === 'running' && runState.queueMessage`, show `runState.queueMessage` in place of the word "running".

In `ChatPortalView.vue`, add a branch before `execution_started`:

```ts
        if (data.type === "queued" && typeof data.execution_id === "string") {
          activeExecutionId.value = data.execution_id;
          if (showProgress) {
            currentProgress.value = [`Waiting in queue (${data.position}/${data.size})`];
          }
        } else if (data.type === "execution_started" && typeof data.execution_id === "string") {
```

Also, in the `execution_complete` branch, pass `data.node_results || []` to `extractImages`, because queued runs send an empty list.

- [ ] **Step 4: Run the checks**

Run: `cd frontend && bun run test -- src/stores/quickDrawerQueue.test.ts src/stores/quickDrawer.test.ts && bun run lint && bun run typecheck`
Expected: pass. Update `quickDrawer.test.ts` fixtures for the new `queueMessage` field if TypeScript asks.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores frontend/src/types/quickDrawer.ts frontend/src/components/Layout/QuickWorkflowRunResult.vue frontend/src/views/ChatPortalView.vue
git commit -m "feat(concurrency): show the queue position in Quick Drawer and Portal"
```

---

### Task 21: Release tour

**Files:**
- Modify: `frontend/src/features/release-tour/releaseRegistry.ts`
- Create: `frontend/src/features/release-tour/components/visuals/ConcurrencyLimitTourVisual.vue`
- Delete: `frontend/src/features/release-tour/components/visuals/HeymWorkTourVisual.vue`
- Modify: `frontend/src/features/release-tour/tourVisuals.ts`

- [ ] **Step 1: Add the release entry at the top of `RELEASE_REGISTRY`**

```ts
  {
    releaseId: "2026.22",
    publishedAt: new Date("2026-10-26T12:00:00Z"),
    headline: "Limit how many runs of a workflow execute at once",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: false,
      sectionOrder: ["concurrency-limit"],
    },
    sections: [
      {
        id: "concurrency-limit",
        title: "Run a workflow one at a time, or N at a time",
        publishedAt: new Date("2026-10-26T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Turn on **Concurrency limit** in the workflow's **Properties** panel and enter how many production runs may execute at once. Webhook, cron, MCP, Portal and trigger runs above the limit wait in a first-in, first-out queue. Editor test runs always start right away.",
          },
          {
            type: "prose",
            markdown:
              "A webhook call that has to wait gets **202 Accepted** at once, with an `execution_id`, a status URL and its place in the queue. Poll the status URL with the same credentials until the result arrives. MCP clients get the same answer and poll with **heym_execution_status**. Optional **Max queue size** and **Max wait** fields bound the queue.",
          },
        ],
        tour: {
          description:
            "Cap concurrent runs per workflow. Extra runs wait in order, and callers get an execution id to collect the result.",
          useCases: [
            "Process webhooks one at a time so two runs never update the same record",
            "Keep a rate-limited API from seeing more than two calls at once",
            "Let an MCP client queue work and pick up the result later",
          ],
          tourVisual: "concurrency-limit",
          docTarget: {
            categoryId: "reference",
            slug: "webhooks",
            title: "Webhooks",
          },
        },
      },
    ],
  },
```

- [ ] **Step 2: Trim to five sections**

Remove the `heym-work` section from release `2026.19`. If it was that release's only section, remove the whole `2026.19` entry. Delete `HeymWorkTourVisual.vue` and its import and registration in `tourVisuals.ts`. Search for other references (`grep -rn "HeymWorkTourVisual\|\"heym-work\"" frontend/src frontend/e2e`) and update any test that expects them.

- [ ] **Step 3: Write the visual**

```vue
<script setup lang="ts">
import { computed } from "vue";
import { CheckCircle2, Clock, Loader2 } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: three requests arrive · 1: one runs, two wait · 2: the first finishes, #1 starts.
const step = useCycleStep(3, 1800);

interface MockRun {
  id: string;
  source: string;
  state: "running" | "queued" | "done";
  position?: number;
}

const runs = computed<MockRun[]>(() => {
  if (step.value === 0) {
    return [
      { id: "a", source: "Webhook", state: "running" },
      { id: "b", source: "Cron", state: "queued", position: 1 },
      { id: "c", source: "MCP", state: "queued", position: 2 },
    ];
  }
  if (step.value === 1) {
    return [
      { id: "a", source: "Webhook", state: "running" },
      { id: "b", source: "Cron", state: "queued", position: 1 },
      { id: "c", source: "MCP", state: "queued", position: 2 },
    ];
  }
  return [
    { id: "a", source: "Webhook", state: "done" },
    { id: "b", source: "Cron", state: "running" },
    { id: "c", source: "MCP", state: "queued", position: 1 },
  ];
});

const caption = computed<string>(() => {
  if (step.value === 0) return "Three runs arrive at once";
  if (step.value === 1) return "Limit 1: the others wait in order";
  return "One finishes, the next starts";
});
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      Concurrency limit
      <span class="ml-auto rounded bg-primary/15 px-1.5 text-[10px] leading-4 text-primary">1 at a time</span>
    </div>

    <TransitionGroup
      tag="div"
      class="space-y-1.5"
      move-class="transition-transform duration-500"
    >
      <div
        v-for="run in runs"
        :key="run.id"
        class="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] leading-4 transition-colors duration-500"
        :class="run.state === 'running' ? 'border-primary/50 bg-primary/10' : 'border-border bg-background'"
      >
        <Loader2
          v-if="run.state === 'running'"
          class="h-3 w-3 animate-spin text-primary"
        />
        <CheckCircle2
          v-else-if="run.state === 'done'"
          class="h-3 w-3 text-emerald-500"
        />
        <Clock
          v-else
          class="h-3 w-3 text-amber-500"
        />
        <span class="text-foreground">{{ run.source }}</span>
        <span
          class="ml-auto rounded px-1.5 text-[10px]"
          :class="run.state === 'queued' ? 'bg-amber-500/15 text-amber-600' : 'text-muted-foreground'"
        >
          {{ run.state === "queued" ? `#${run.position}` : run.state }}
        </span>
      </div>
    </TransitionGroup>

    <div class="mt-auto rounded-md bg-muted/50 px-2.5 py-1.5 font-mono text-[10px] leading-4 text-muted-foreground">
      202 · {"status": "queued", "queue": {"position": 1}}
    </div>
    <p class="text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
```

Register it in `tourVisuals.ts`: `"concurrency-limit": ConcurrencyLimitTourVisual,`.

- [ ] **Step 4: Run the checks**

Run: `cd frontend && bun run test -- src/features/release-tour && bun run lint && bun run typecheck`
Expected: pass. The registry test confirms that every `tourVisual` key resolves.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/features/release-tour
git commit -m "feat(release-tour): announce the per-workflow concurrency limit"
```

---

### Task 22: Playwright E2E

**Files:**
- Create: `frontend/e2e/workflow-concurrency.spec.ts`

- [ ] **Step 1: Write the spec**

```ts
import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

const WAIT_NODES = [
  { id: "in", type: "textInput", position: { x: 80, y: 160 }, data: { label: "start", value: "hi" } },
  { id: "wait", type: "wait", position: { x: 340, y: 160 }, data: { label: "pause", duration: 5000 } },
  { id: "out", type: "output", position: { x: 600, y: 160 }, data: { label: "done", message: "ok" } },
];
const WAIT_EDGES = [
  { id: "e1", source: "in", target: "wait" },
  { id: "e2", source: "wait", target: "out" },
];

test("the concurrency limit is set in Properties and survives a reload", async ({ page }) => {
  const workflow = await createWorkflow(page, `Concurrency Settings ${Date.now()}`);
  try {
    await page.goto(`/workflows/${workflow.id}`);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    const settings = page.getByTestId("workflow-concurrency-settings");
    await expect(settings).toBeVisible();

    const saved = page.waitForResponse(
      (r) => r.request().method() === "PUT" && new URL(r.url()).pathname === `/api/workflows/${workflow.id}`,
    );
    await settings.getByTestId("workflow-concurrency-toggle").click();
    await saved;
    const limitInput = settings.getByTestId("workflow-concurrency-limit");
    await limitInput.fill("2");
    const savedLimit = page.waitForResponse((r) => r.request().method() === "PUT");
    await limitInput.press("Tab");
    await savedLimit;

    await page.reload();
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await expect(page.getByTestId("workflow-concurrency-limit")).toHaveValue("2");
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("a second production run waits in the queue and shows in History", async ({ page }) => {
  const workflow = await createWorkflow(page, `Concurrency Queue ${Date.now()}`, WAIT_NODES, WAIT_EDGES);
  try {
    const update = await page.request.put(`/api/workflows/${workflow.id}`, { data: { concurrency_limit: 1 } });
    expect(update.ok()).toBeTruthy();

    const first = page.request.post(`/api/workflows/${workflow.id}/execute`, { data: { inputs: {} } });
    await expect.poll(async () => {
      const active = await page.request.get("/api/workflows/executions/active");
      const items = (await active.json()) as { workflow_id: string }[];
      return items.filter((i) => i.workflow_id === workflow.id).length;
    }).toBe(1);

    const second = await page.request.post(`/api/workflows/${workflow.id}/execute`, { data: { inputs: {} } });
    expect(second.status()).toBe(202);
    const body = (await second.json()) as { execution_id: string; status_url: string; queue: { position: number } };
    expect(body.queue.position).toBe(1);

    await page.goto(`/workflows/${workflow.id}`);
    await page.getByRole("button", { name: "History", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
    await expect(page.getByTestId(`active-execution-status-${body.execution_id}`)).toContainText("Queued 1/1");

    await first;
    await expect.poll(async () => {
      const status = await page.request.get(new URL(body.status_url).pathname);
      return ((await status.json()) as { status: string }).status;
    }, { timeout: 30_000 }).toBe("success");
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
```

If the floating AI assistant covers the panel in the editor, close it first with `await page.getByTitle("Close", { exact: true }).click()`, as `assistant-data-tables.spec.ts` does.

- [ ] **Step 2: Run it**

Run from the repo root: `./run_e2e.sh frontend/e2e/workflow-concurrency.spec.ts`. If the script takes no file filter, run `./run_e2e.sh` and read this spec's results.
Expected: both tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/workflow-concurrency.spec.ts
git commit -m "test(e2e): concurrency limit settings and a queued run in History"
```

---

### Task 23: Documentation

**Files:** under `frontend/src/docs/content/`. Read `.cursor/skills/heym-documentation/SKILL.md` first and follow it.

- [ ] **Step 1: Write the docs**

- `reference/features.md`: add a `### Concurrency Limit` section directly after `### Workflow Timeout`. Write it as one paragraph, in the style of that section. Cover: where the setting lives (workflow-level Properties panel, editors only), that it is off by default, what is gated and what is not (editor test runs, sub-workflows, Evals, resumes), FIFO order, the 202/status URL/429 behaviour, Max queue size and Max wait, and that it is counted cluster-wide. In the webhook paragraph near line 578, add one sentence: with a concurrency limit, a webhook that has to wait gets 202 with a status URL.
- `reference/webhooks.md`: a "Concurrency limit and queued runs" section with the 202 body, the `Location` header, the status endpoint and its response table, `X-Heym-Run-Token` for anonymous workflows, and 429.
- `reference/sse-streaming.md`: the `queued` event, and that queued runs send `execution_started` and `execution_complete` but no node events or token deltas.
- `reference/portal.md` and `reference/quick-drawer.md`: the "Waiting in queue (n/m)" state.
- `tabs/mcp-tab.md`: the queued tool result and the `heym_execution_status` tool, including when it is listed.
- `reference/execution-history.md`: Queued rows with Cancel, and the `expired` and `queue_full` statuses.
- `reference/triggers.md`: background triggers wait in the queue, and what is not gated.
- `reference/cluster.md`: the limit is counted across all instances, and the run queue worker now runs on every install.

Do not use em dashes in new prose.

- [ ] **Step 2: Verify**

Run: `cd frontend && bun run lint && bun run typecheck && bun run test -- src/docs`
Expected: pass. Manifest and link tests stay green.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/docs
git commit -m "docs: per-workflow concurrency limit"
```

---

### Task 24: Final verification and hand-off

- [ ] **Step 1: Full checks**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:6543/heym SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh
cd frontend && bun run test
cd .. && ./run_e2e.sh
```
Expected: everything passes. Commit any `ruff format` diff.

- [ ] **Step 2: Manual smoke on a running instance (`./run.sh`)**

1. Set the limit to 1 on a workflow with a 10-second Wait node and anonymous auth.
2. Fire three `curl -X POST .../execute` calls in parallel. The first blocks and returns the result. The other two return 202 with positions 1 and 2, a `status_token` and a `Location`.
3. Poll the second call's status URL with `-H "X-Heym-Run-Token: <token>"`: `queued` → `running` → `success`. Without the header the URL answers 404.
4. Open History. Queued rows show `Queued n/m`, and Cancel on one turns it into `cancelled`.
5. Set Max wait to 5 seconds, queue three runs, and confirm the last one becomes `expired`.
6. Through an MCP client, call the workflow twice quickly. The second call gets the queued JSON, and `heym_execution_status` reports progress.

- [ ] **Step 3: Hand off**

Do not push. Report to the user with the test output and the smoke results. Ask before opening the PR whether it should carry no attribution, like the recent public-repo PRs (#794, #800).

---

## Self-review notes

- Spec coverage: settings (T1, T2), slots and the queue (T1, T4), admission, release and promotion (T4), expiry, stale slots, cancel and the sweep (T5, T6), worker on every install (T6), dispatch gate and every trigger (T7, T8), HTTP 202/429 (T9), status URL and token (T10), active list and cancel (T11), SSE (T12), Portal (T13), MCP (T14), recovery (T15), UI (T17-T20), release tour (T21), E2E (T22), docs (T23).
- Names used across tasks: `Admission`, `QueueInfo`, `HeldRun`, `HeldRunRecord`, `admit`, `release`, `promote`, `cancel_held`, `record_queue_full`, `maintain`, `build_status_body`, `status_token_hash_for`, `status_token_matches`, `list_held_runs_for_user`, `holds_slot`, `is_concurrency_row`, `queued_body`, `RUN_TOKEN_HEADER`, `queued_run_events`, `release_slot_when_done`, `queue_full_result`, `_SLOT_RELEASE_TASKS`, `allow_downstream_futures`.
