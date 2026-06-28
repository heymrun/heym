# Workflow Run Crash-Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a backend restart, re-run interrupted workflow executions from scratch with their original inputs (or mark them `skipped`/`failed`), writing a proper terminal history entry, controlled by a per-workflow toggle (default on).

**Architecture:** Persist enough on `active_workflow_executions` to replay a run (inputs, trigger_source, actor_user_id, attempt, recoverable). A leader-gated background service (`execution_recovery`) atomically claims orphaned rows (heartbeat stale >60s, or backdated on graceful shutdown) and re-runs / skips / fails them in parallel. A per-workflow `auto_recover_runs` flag (canvas run panel toggle) gates re-run vs skip.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Postgres advisory-lock leader election (`distributed_lock`), Vue 3 + TS, pytest (unittest + AsyncMock).

**Spec:** `docs/superpowers/specs/2026-06-28-workflow-run-crash-recovery-design.md`

---

## File Structure

- `backend/app/db/models.py` — new columns on `ActiveWorkflowExecution`; `Workflow.auto_recover_runs`.
- `backend/alembic/versions/086_add_run_recovery_fields.py` — **new** migration.
- `backend/app/services/execution_cancellation.py` — extend `register_execution` + registry upsert; add `mark_own_executions_orphaned`, `claim_orphaned_executions`; drop the blind 300s delete.
- `backend/app/services/execution_recovery.py` — **new** leader-gated recovery loop + `decide_recovery_action`.
- `backend/app/services/workflow_executor.py` — sub-workflow registrations pass `recoverable=False`.
- `backend/app/api/{workflows,portal,mcp,mcp_servers,discord,slack,telegram}.py` — pass recovery fields to `register_execution` (or add registration).
- `backend/app/services/{cron_scheduler,imap_trigger_service,websocket_trigger_service,rabbitmq_consumer}.py` — register executions with recovery fields.
- `backend/app/main.py` — start recovery service; mark own rows orphaned on shutdown.
- `backend/app/models/schemas.py` — `auto_recover_runs` on `WorkflowUpdate`/`WorkflowResponse`.
- `frontend/src/types/workflow.ts`, `frontend/src/services/api.ts`, `frontend/src/components/Panels/DebugPanel.vue` — toggle + `skipped` badge.
- `backend/tests/test_execution_recovery.py` — **new**.

---

## Task 1: DB schema — recovery columns + workflow toggle

**Files:**
- Modify: `backend/app/db/models.py` (`ActiveWorkflowExecution` ~line 521, `Workflow` ~line 254)
- Create: `backend/alembic/versions/086_add_run_recovery_fields.py`

- [ ] **Step 1: Add columns to `ActiveWorkflowExecution`**

In `backend/app/db/models.py`, inside `class ActiveWorkflowExecution`, after the `cancel_requested_at` column add:

```python
    inputs: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    trigger_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recoverable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
```

- [ ] **Step 2: Add the workflow toggle column**

In `class Workflow`, alongside `sse_enabled`/`mcp_enabled`, add:

```python
    auto_recover_runs: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

- [ ] **Step 3: Write the migration**

Create `backend/alembic/versions/086_add_run_recovery_fields.py`:

```python
"""add run crash-recovery fields

Revision ID: 086_add_run_recovery_fields
Revises: 085_backfill_linear_cred_type
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "086_add_run_recovery_fields"
down_revision: str | None = "085_backfill_linear_cred_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "active_workflow_executions",
        sa.Column("inputs", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "active_workflow_executions",
        sa.Column("trigger_source", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "active_workflow_executions",
        sa.Column("actor_user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "active_workflow_executions",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "active_workflow_executions",
        sa.Column("recoverable", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index(
        "ix_active_workflow_executions_recoverable",
        "active_workflow_executions",
        ["recoverable"],
    )
    op.add_column(
        "workflows",
        sa.Column("auto_recover_runs", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("workflows", "auto_recover_runs")
    op.drop_index(
        "ix_active_workflow_executions_recoverable",
        table_name="active_workflow_executions",
    )
    op.drop_column("active_workflow_executions", "recoverable")
    op.drop_column("active_workflow_executions", "attempt")
    op.drop_column("active_workflow_executions", "actor_user_id")
    op.drop_column("active_workflow_executions", "trigger_source")
    op.drop_column("active_workflow_executions", "inputs")
```

- [ ] **Step 4: Apply and verify the migration**

Run: `cd backend && uv run alembic upgrade head`
Expected: completes; `uv run alembic heads` shows `086_add_run_recovery_fields (head)`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/086_add_run_recovery_fields.py
git commit -m "feat(recovery): add run crash-recovery DB columns and workflow toggle"
```

---

## Task 2: Persist recovery context through `register_execution`

**Files:**
- Modify: `backend/app/services/execution_cancellation.py`
- Test: `backend/tests/test_execution_cancellation.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_execution_cancellation.py`:

```python
class RegisterExecutionRecoveryFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        _flush()

    def test_handle_carries_recovery_fields(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        actor = uuid.uuid4()
        register_execution(
            workflow_id=wf_id,
            execution_id=ex_id,
            inputs={"a": 1},
            trigger_source="schedule",
            actor_user_id=actor,
            recoverable=True,
        )
        handle = _ACTIVE_EXECUTIONS[ex_id]
        self.assertEqual(handle.inputs, {"a": 1})
        self.assertEqual(handle.trigger_source, "schedule")
        self.assertEqual(handle.actor_user_id, actor)
        self.assertTrue(handle.recoverable)

    def test_defaults_are_safe(self) -> None:
        register_execution(workflow_id=uuid.uuid4(), execution_id=uuid.uuid4())
        handle = next(iter(_ACTIVE_EXECUTIONS.values()))
        self.assertEqual(handle.inputs, {})
        self.assertIsNone(handle.trigger_source)
        self.assertIsNone(handle.actor_user_id)
        self.assertTrue(handle.recoverable)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_execution_cancellation.py::RegisterExecutionRecoveryFieldsTests -v`
Expected: FAIL (`TypeError: unexpected keyword argument 'inputs'`).

- [ ] **Step 3: Extend the dataclasses and `register_execution`**

In `execution_cancellation.py`, extend `ExecutionCancellationHandle`:

```python
@dataclass
class ExecutionCancellationHandle:
    workflow_id: uuid.UUID
    execution_id: uuid.UUID
    event: threading.Event
    started_at: datetime = field(default_factory=_utcnow)
    inputs: dict = field(default_factory=dict)
    trigger_source: str | None = None
    actor_user_id: uuid.UUID | None = None
    recoverable: bool = True
```

Extend `_RegistryCommand`:

```python
@dataclass(frozen=True)
class _RegistryCommand:
    action: Literal["start", "finish"]
    execution_id: uuid.UUID
    workflow_id: uuid.UUID | None = None
    started_at: datetime | None = None
    inputs: dict | None = None
    trigger_source: str | None = None
    actor_user_id: uuid.UUID | None = None
    recoverable: bool = True
```

Replace `register_execution` signature/body:

```python
def register_execution(
    *,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    event: threading.Event | None = None,
    started_at: datetime | None = None,
    inputs: dict | None = None,
    trigger_source: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    recoverable: bool = True,
) -> threading.Event:
    if event is None:
        event = threading.Event()
    started_at = started_at or _utcnow()
    handle = ExecutionCancellationHandle(
        workflow_id=workflow_id,
        execution_id=execution_id,
        event=event,
        started_at=started_at,
        inputs=inputs or {},
        trigger_source=trigger_source,
        actor_user_id=actor_user_id,
        recoverable=recoverable,
    )
    with _LOCK:
        _ACTIVE_EXECUTIONS[execution_id] = handle
    active_execution_registry.record_started(handle)
    return event
```

Update `record_started` to forward the new fields:

```python
    def record_started(self, handle: ExecutionCancellationHandle) -> None:
        if not self._running:
            return
        self._commands.put(
            _RegistryCommand(
                action="start",
                execution_id=handle.execution_id,
                workflow_id=handle.workflow_id,
                started_at=handle.started_at,
                inputs=handle.inputs,
                trigger_source=handle.trigger_source,
                actor_user_id=handle.actor_user_id,
                recoverable=handle.recoverable,
            )
        )
        self._wake()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_execution_cancellation.py::RegisterExecutionRecoveryFieldsTests -v`
Expected: PASS.

- [ ] **Step 5: Persist new columns in the upsert (no test — covered by Task 6/7 integration)**

In `_drain_commands`, replace the `pg_insert(...).values(...)` / `.on_conflict_do_update(...)` block with:

```python
                stmt = (
                    pg_insert(ActiveWorkflowExecution)
                    .values(
                        execution_id=command.execution_id,
                        workflow_id=command.workflow_id,
                        worker_id=_WORKER_ID,
                        started_at=started_at,
                        heartbeat_at=now,
                        cancel_requested_at=None,
                        inputs=command.inputs or {},
                        trigger_source=command.trigger_source,
                        actor_user_id=command.actor_user_id,
                        attempt=0,
                        recoverable=command.recoverable,
                    )
                    .on_conflict_do_update(
                        index_elements=["execution_id"],
                        set_={
                            "workflow_id": command.workflow_id,
                            "worker_id": _WORKER_ID,
                            "started_at": started_at,
                            "heartbeat_at": now,
                            "cancel_requested_at": None,
                            "inputs": command.inputs or {},
                            "trigger_source": command.trigger_source,
                            "actor_user_id": command.actor_user_id,
                        },
                    )
                )
```

Note: `set_` intentionally **omits** `attempt` and `recoverable` so a recovery re-run (re-registering the same `execution_id`) preserves the claimed attempt count and recoverable flag.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/execution_cancellation.py backend/tests/test_execution_cancellation.py
git commit -m "feat(recovery): persist inputs/trigger/actor/recoverable on active executions"
```

---

## Task 3: Mark sub-workflows as non-recoverable

**Files:**
- Modify: `backend/app/services/workflow_executor.py:3609` and `:7459`

- [ ] **Step 1: Pass `recoverable=False` at both sub-execution registrations**

At each `_register_sub_execution(...)` call (lines ~3609 and ~7459), add `recoverable=False`. Example for line 3609:

```python
        _register_sub_execution(
            workflow_id=uuid.UUID(workflow_id_str),
            execution_id=_sub_execution_id,
            event=sub_cancel_event,
            recoverable=False,
        )
```

Apply the same `recoverable=False` argument to the call near line 7459 (keep its existing keyword arguments unchanged).

- [ ] **Step 2: Verify it imports/loads**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "import app.services.workflow_executor"`
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/workflow_executor.py
git commit -m "feat(recovery): exclude sub-workflows from crash recovery"
```

---

## Task 4: Recovery decision function (pure, TDD)

**Files:**
- Create: `backend/app/services/execution_recovery.py`
- Test: `backend/tests/test_execution_recovery.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_execution_recovery.py`:

```python
import unittest

from app.services.execution_recovery import MAX_RECOVERY_ATTEMPTS, decide_recovery_action


class DecideRecoveryActionTests(unittest.TestCase):
    def test_rerun_when_enabled_and_within_attempts(self) -> None:
        action = decide_recovery_action(attempt=1, auto_recover=True, workflow_exists=True)
        self.assertEqual(action, "rerun")

    def test_skipped_when_toggle_off(self) -> None:
        action = decide_recovery_action(attempt=1, auto_recover=False, workflow_exists=True)
        self.assertEqual(action, "skipped")

    def test_failed_when_attempts_exhausted(self) -> None:
        action = decide_recovery_action(
            attempt=MAX_RECOVERY_ATTEMPTS + 1, auto_recover=True, workflow_exists=True
        )
        self.assertEqual(action, "failed")

    def test_failed_when_workflow_missing(self) -> None:
        action = decide_recovery_action(attempt=1, auto_recover=True, workflow_exists=False)
        self.assertEqual(action, "failed")

    def test_missing_workflow_beats_skip(self) -> None:
        action = decide_recovery_action(attempt=1, auto_recover=False, workflow_exists=False)
        self.assertEqual(action, "failed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_execution_recovery.py::DecideRecoveryActionTests -v`
Expected: FAIL (`ModuleNotFoundError: app.services.execution_recovery`).

- [ ] **Step 3: Create the module with the pure function**

Create `backend/app/services/execution_recovery.py`:

```python
"""Leader-gated recovery of workflow executions interrupted by a restart."""

import logging
from typing import Literal

logger = logging.getLogger(__name__)

# Retry once: the original run is attempt 0; the first recovery makes it 1.
MAX_RECOVERY_ATTEMPTS = 1

RecoveryAction = Literal["rerun", "skipped", "failed"]


def decide_recovery_action(
    *, attempt: int, auto_recover: bool, workflow_exists: bool
) -> RecoveryAction:
    """Decide what to do with a claimed orphan. `attempt` is post-claim-increment."""
    if not workflow_exists:
        return "failed"
    if attempt > MAX_RECOVERY_ATTEMPTS:
        return "failed"
    if not auto_recover:
        return "skipped"
    return "rerun"
```

This file is replaced in full by Task 6 (which adds the service class and the
`RECOVERY_STALE_AFTER_SECONDS` import); `decide_recovery_action` and
`MAX_RECOVERY_ATTEMPTS` keep the exact definitions above.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_execution_recovery.py::DecideRecoveryActionTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/execution_recovery.py backend/tests/test_execution_recovery.py
git commit -m "feat(recovery): add pure recovery-decision function"
```

---

## Task 5: Graceful-shutdown marking + atomic orphan claim

**Files:**
- Modify: `backend/app/services/execution_cancellation.py`
- Test: `backend/tests/test_execution_recovery.py`

- [ ] **Step 1: Write the failing test (uses AsyncMock for the DB session)**

Append to `backend/tests/test_execution_recovery.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.execution_cancellation import (
    claim_orphaned_executions,
    mark_own_executions_orphaned,
)


class MarkOwnExecutionsOrphanedTests(unittest.IsolatedAsyncioTestCase):
    async def test_backdates_only_own_recoverable_rows(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(rowcount=2))
        session.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch(
            "app.services.execution_cancellation.async_session_maker", return_value=cm
        ):
            count = await mark_own_executions_orphaned()
        self.assertEqual(count, 2)
        session.execute.assert_awaited_once()
        session.commit.assert_awaited_once()


class ClaimOrphanedExecutionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_claims_only_rows_won_atomically(self) -> None:
        ex_won = uuid.uuid4()
        ex_lost = uuid.uuid4()
        wf = uuid.uuid4()
        now = datetime.now(timezone.utc)
        candidate = MagicMock(
            execution_id=ex_won,
            workflow_id=wf,
            inputs={"x": 1},
            trigger_source="schedule",
            actor_user_id=None,
            attempt=0,
        )
        candidate_lost = MagicMock(
            execution_id=ex_lost,
            workflow_id=wf,
            inputs={},
            trigger_source=None,
            actor_user_id=None,
            attempt=0,
        )
        select_result = MagicMock()
        select_result.all.return_value = [candidate, candidate_lost]
        # First claim wins (rowcount=1), second loses (rowcount=0).
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                select_result,
                MagicMock(rowcount=1),
                MagicMock(rowcount=0),
            ]
        )
        session.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch(
            "app.services.execution_cancellation.async_session_maker", return_value=cm
        ):
            claimed = await claim_orphaned_executions(now=now)
        self.assertEqual([c.execution_id for c in claimed], [ex_won])
        self.assertEqual(claimed[0].attempt, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_execution_recovery.py::MarkOwnExecutionsOrphanedTests tests/test_execution_recovery.py::ClaimOrphanedExecutionsTests -v`
Expected: FAIL (`ImportError: cannot import name 'claim_orphaned_executions'`).

- [ ] **Step 3: Implement marking + claim, and a `ClaimedOrphan` dataclass**

In `execution_cancellation.py`, add near `ActiveExecutionRecord`:

```python
@dataclass(frozen=True)
class ClaimedOrphan:
    """An orphaned execution this worker has atomically claimed for recovery."""

    execution_id: uuid.UUID
    workflow_id: uuid.UUID
    inputs: dict
    trigger_source: str | None
    actor_user_id: uuid.UUID | None
    attempt: int
```

Add `RECOVERY_STALE_AFTER_SECONDS` import-free constant reuse by importing in the recovery module instead; here add the two functions at module level (after `cleanup_stale_persisted_executions`):

```python
async def mark_own_executions_orphaned() -> int:
    """Backdate this worker's recoverable rows so the next leader recovers them now."""
    from sqlalchemy import update

    from app.db.models import ActiveWorkflowExecution
    from app.db.session import async_session_maker

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    async with async_session_maker() as session:
        result = await session.execute(
            update(ActiveWorkflowExecution)
            .where(
                ActiveWorkflowExecution.worker_id == _WORKER_ID,
                ActiveWorkflowExecution.recoverable.is_(True),
            )
            .values(heartbeat_at=epoch)
        )
        await session.commit()
    return result.rowcount or 0


async def claim_orphaned_executions(*, now: datetime | None = None) -> list["ClaimedOrphan"]:
    """Atomically claim recoverable rows whose heartbeat is stale; return the winners."""
    from sqlalchemy import select, update

    from app.db.models import ActiveWorkflowExecution
    from app.db.session import async_session_maker

    now = now or _utcnow()
    cutoff = now - timedelta(seconds=RECOVERY_STALE_AFTER_SECONDS)
    claimed: list[ClaimedOrphan] = []
    async with async_session_maker() as session:
        candidates = (
            await session.execute(
                select(
                    ActiveWorkflowExecution.execution_id,
                    ActiveWorkflowExecution.workflow_id,
                    ActiveWorkflowExecution.inputs,
                    ActiveWorkflowExecution.trigger_source,
                    ActiveWorkflowExecution.actor_user_id,
                    ActiveWorkflowExecution.attempt,
                ).where(
                    ActiveWorkflowExecution.recoverable.is_(True),
                    ActiveWorkflowExecution.heartbeat_at < cutoff,
                )
            )
        ).all()
        for row in candidates:
            result = await session.execute(
                update(ActiveWorkflowExecution)
                .where(
                    ActiveWorkflowExecution.execution_id == row.execution_id,
                    ActiveWorkflowExecution.heartbeat_at < cutoff,
                )
                .values(worker_id=_WORKER_ID, heartbeat_at=now, attempt=row.attempt + 1)
            )
            if (result.rowcount or 0) == 1:
                claimed.append(
                    ClaimedOrphan(
                        execution_id=row.execution_id,
                        workflow_id=row.workflow_id,
                        inputs=row.inputs or {},
                        trigger_source=row.trigger_source,
                        actor_user_id=row.actor_user_id,
                        attempt=row.attempt + 1,
                    )
                )
        await session.commit()
    return claimed
```

Add `RECOVERY_STALE_AFTER_SECONDS = 60` near the top of `execution_cancellation.py` (next to `ACTIVE_EXECUTION_STALE_AFTER_SECONDS`), and update the import in `execution_recovery.py` later to reuse it.

- [ ] **Step 4: Remove the blind stale delete from the registry loop**

In `_run_loop`, delete the block that calls `cleanup_stale_persisted_executions()` and the `self._next_cleanup_at` bookkeeping (lines ~166-168), since recovery now owns stale rows. Leave `cleanup_stale_persisted_executions` defined (still used by tests / as a safety net via the recovery service) but no longer called from this loop.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_execution_recovery.py -v`
Expected: PASS (all decision + marking + claim tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/execution_cancellation.py backend/tests/test_execution_recovery.py
git commit -m "feat(recovery): shutdown orphan-marking and atomic orphan claim"
```

---

## Task 6: Recovery service loop + per-orphan handling

**Files:**
- Modify: `backend/app/services/execution_recovery.py`
- Test: `backend/tests/test_execution_recovery.py`

- [ ] **Step 1: Write the failing test for `_recover_one` branches**

Append to `backend/tests/test_execution_recovery.py`:

```python
from app.services.execution_recovery import ExecutionRecoveryService


def _orphan(attempt: int = 1):
    from app.services.execution_cancellation import ClaimedOrphan

    return ClaimedOrphan(
        execution_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        inputs={"k": "v"},
        trigger_source="schedule",
        actor_user_id=None,
        attempt=attempt,
    )


class RecoverOneTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_toggle_off(self) -> None:
        svc = ExecutionRecoveryService()
        orphan = _orphan(attempt=1)
        with patch.object(
            svc, "_load_workflow", AsyncMock(return_value=MagicMock(auto_recover_runs=False))
        ), patch.object(
            svc, "_finalize", AsyncMock()
        ) as finalize, patch.object(
            svc, "_rerun", AsyncMock()
        ) as rerun:
            await svc._recover_one(orphan)
        finalize.assert_awaited_once()
        self.assertEqual(finalize.await_args.kwargs["status"], "skipped")
        rerun.assert_not_called()

    async def test_fails_when_attempts_exhausted(self) -> None:
        svc = ExecutionRecoveryService()
        orphan = _orphan(attempt=2)
        with patch.object(
            svc, "_load_workflow", AsyncMock(return_value=MagicMock(auto_recover_runs=True))
        ), patch.object(svc, "_finalize", AsyncMock()) as finalize, patch.object(
            svc, "_rerun", AsyncMock()
        ) as rerun:
            await svc._recover_one(orphan)
        self.assertEqual(finalize.await_args.kwargs["status"], "failed")
        rerun.assert_not_called()

    async def test_fails_when_workflow_missing(self) -> None:
        svc = ExecutionRecoveryService()
        orphan = _orphan(attempt=1)
        with patch.object(svc, "_load_workflow", AsyncMock(return_value=None)), patch.object(
            svc, "_finalize", AsyncMock()
        ) as finalize, patch.object(svc, "_rerun", AsyncMock()) as rerun:
            await svc._recover_one(orphan)
        self.assertEqual(finalize.await_args.kwargs["status"], "failed")
        rerun.assert_not_called()

    async def test_reruns_when_enabled(self) -> None:
        svc = ExecutionRecoveryService()
        orphan = _orphan(attempt=1)
        with patch.object(
            svc, "_load_workflow", AsyncMock(return_value=MagicMock(auto_recover_runs=True))
        ), patch.object(svc, "_finalize", AsyncMock()) as finalize, patch.object(
            svc, "_rerun", AsyncMock()
        ) as rerun:
            await svc._recover_one(orphan)
        rerun.assert_awaited_once()
        finalize.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_execution_recovery.py::RecoverOneTests -v`
Expected: FAIL (`ImportError: cannot import name 'ExecutionRecoveryService'`).

- [ ] **Step 3: Implement the service (replace the entire file)**

Replace the **entire** contents of `execution_recovery.py` with the following. It re-states `decide_recovery_action`/`MAX_RECOVERY_ATTEMPTS` unchanged and imports the shared `RECOVERY_STALE_AFTER_SECONDS` from `execution_cancellation`:

```python
import asyncio
import contextlib
import logging
import uuid
from typing import Literal

from app.services.distributed_lock import lock_service
from app.services.execution_cancellation import (
    RECOVERY_STALE_AFTER_SECONDS,  # noqa: F401  (re-exported for callers/tests)
    ClaimedOrphan,
    claim_orphaned_executions,
)

logger = logging.getLogger(__name__)

MAX_RECOVERY_ATTEMPTS = 1
_RECOVERY_GRACE_SECONDS = 5.0
_RECOVERY_POLL_SECONDS = 15.0

RecoveryAction = Literal["rerun", "skipped", "failed"]


def decide_recovery_action(
    *, attempt: int, auto_recover: bool, workflow_exists: bool
) -> RecoveryAction:
    if not workflow_exists:
        return "failed"
    if attempt > MAX_RECOVERY_ATTEMPTS:
        return "failed"
    if not auto_recover:
        return "skipped"
    return "rerun"


class ExecutionRecoveryService:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Execution recovery service started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Execution recovery service stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(_RECOVERY_GRACE_SECONDS)
        while self._running:
            try:
                if lock_service.is_leader:
                    await self._sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Execution recovery sweep failed")
            await asyncio.sleep(_RECOVERY_POLL_SECONDS)

    async def _sweep_once(self) -> None:
        orphans = await claim_orphaned_executions()
        for orphan in orphans:
            asyncio.create_task(self._recover_one(orphan))

    async def _recover_one(self, orphan: ClaimedOrphan) -> None:
        workflow = await self._load_workflow(orphan.workflow_id)
        action = decide_recovery_action(
            attempt=orphan.attempt,
            auto_recover=bool(getattr(workflow, "auto_recover_runs", True)),
            workflow_exists=workflow is not None,
        )
        if action == "rerun":
            await self._rerun(orphan, workflow)
            return
        await self._finalize(orphan=orphan, workflow=workflow, status=action)

    async def _load_workflow(self, workflow_id: uuid.UUID):
        from sqlalchemy import select

        from app.db.models import Workflow
        from app.db.session import async_session_maker

        async with async_session_maker() as session:
            result = await session.execute(select(Workflow).where(Workflow.id == workflow_id))
            return result.scalar_one_or_none()

    async def _finalize(self, *, orphan: ClaimedOrphan, workflow, status: str) -> None:
        """Write a terminal ExecutionHistory entry and drop the active row."""
        from sqlalchemy import delete

        from app.db.models import ActiveWorkflowExecution, ExecutionHistory
        from app.db.session import async_session_maker

        async with async_session_maker() as session:
            session.add(
                ExecutionHistory(
                    workflow_id=orphan.workflow_id,
                    inputs=orphan.inputs,
                    outputs={},
                    node_results=[],
                    status=status,
                    execution_time_ms=0.0,
                    trigger_source=orphan.trigger_source,
                )
            )
            await session.execute(
                delete(ActiveWorkflowExecution).where(
                    ActiveWorkflowExecution.execution_id == orphan.execution_id
                )
            )
            await session.commit()
        logger.info(
            "Recovery finalized execution %s as %s (workflow %s)",
            orphan.execution_id,
            status,
            orphan.workflow_id,
        )

    async def _rerun(self, orphan: ClaimedOrphan, workflow) -> None:
        """Re-run the workflow from scratch with the original inputs."""
        from app.api.analytics import upsert_workflow_analytics_snapshot
        from app.api.workflows import (
            _persist_global_variables_from_execution,
            collect_referenced_workflows,
            get_credentials_context,
        )
        from app.db.models import ExecutionHistory
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import (
            clear_execution,
            register_execution,
        )
        from app.services.global_variables_service import get_global_variables_context
        from app.services.workflow_executor import execute_workflow

        actor_user_id = orphan.actor_user_id or workflow.owner_id
        async with async_session_maker() as session:
            workflow_cache = await collect_referenced_workflows(
                session, workflow.nodes, actor_user_id=actor_user_id
            )
            credentials_context = await get_credentials_context(session, actor_user_id)
            global_variables_context = await get_global_variables_context(session, actor_user_id)

        # Re-register the SAME execution_id so the claimed attempt count is preserved.
        cancel_event = register_execution(
            workflow_id=workflow.id,
            execution_id=orphan.execution_id,
            inputs=orphan.inputs,
            trigger_source=orphan.trigger_source,
            actor_user_id=actor_user_id,
            recoverable=True,
        )
        try:
            result = await asyncio.to_thread(
                execute_workflow,
                workflow_id=workflow.id,
                nodes=workflow.nodes,
                edges=workflow.edges,
                inputs=orphan.inputs,
                workflow_cache=workflow_cache,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=actor_user_id,
                actor_user_id=actor_user_id,
                cancel_event=cancel_event,
            )
        finally:
            clear_execution(orphan.execution_id)

        async with async_session_maker() as session:
            session.add(
                ExecutionHistory(
                    workflow_id=workflow.id,
                    inputs=orphan.inputs,
                    outputs=result.outputs,
                    node_results=result.node_results,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                    trigger_source=orphan.trigger_source,
                )
            )
            await upsert_workflow_analytics_snapshot(
                session,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                workflow_name_snapshot=workflow.name,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
            )
            await _persist_global_variables_from_execution(
                session,
                workflow.owner_id,
                workflow.nodes,
                workflow_cache,
                result.node_results,
                result.sub_workflow_executions,
            )
            await session.commit()
        logger.info(
            "Recovery re-ran execution %s -> %s (workflow %s)",
            orphan.execution_id,
            result.status,
            workflow.id,
        )


execution_recovery_service = ExecutionRecoveryService()
```

`RECOVERY_STALE_AFTER_SECONDS` is the source of truth in `execution_cancellation.py` (added in Task 5 Step 3) and is imported here so the claim cutoff and any callers/tests share one value.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_execution_recovery.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/execution_recovery.py backend/tests/test_execution_recovery.py
git commit -m "feat(recovery): recovery service loop with rerun/skip/fail handling"
```

---

## Task 7: Wire recovery into app lifespan

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Import the service**

Near the other service imports (after `from app.services.execution_cancellation import active_execution_registry` at line ~65) add:

```python
from app.services.execution_cancellation import mark_own_executions_orphaned
from app.services.execution_recovery import execution_recovery_service
```

- [ ] **Step 2: Start it in lifespan**

After `await active_execution_registry.start()` (line ~140) add:

```python
    await execution_recovery_service.start()
```

- [ ] **Step 3: Mark own rows orphaned + stop service on shutdown**

In the shutdown section, replace the line `await active_execution_registry.stop()` (line ~152) with:

```python
    await execution_recovery_service.stop()
    await active_execution_registry.stop()
    with contextlib.suppress(Exception):
        await mark_own_executions_orphaned()
```

Ensure `import contextlib` exists at the top of `main.py` (add if missing).

- [ ] **Step 4: Verify the app imports**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "import app.main"`
Expected: no error.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(recovery): start recovery service and mark own runs on shutdown"
```

---

## Task 8: Make all top-level entry points recoverable

**Files:**
- Modify: `backend/app/api/workflows.py:2349`, `:2957`
- Modify: `backend/app/api/portal.py:409`, `backend/app/api/mcp.py:910`, `:1089`, `backend/app/api/mcp_servers.py:491`
- Modify: `backend/app/services/cron_scheduler.py:159`, `imap_trigger_service.py:429`, `websocket_trigger_service.py:376`, `rabbitmq_consumer.py:336`
- Modify: `backend/app/api/discord.py:230`, `slack.py:142`, `telegram.py:143`

- [ ] **Step 1: Pass recovery fields where `register_execution` is already called**

For each existing `register_execution(workflow_id=..., execution_id=...)` call, add `inputs=`, `trigger_source=`, `actor_user_id=` using the inputs/trigger/actor already in scope at that call site. Example for `workflows.py:2349`:

```python
    cancel_event = register_execution(
        workflow_id=workflow.id,
        execution_id=execution_id,
        inputs=enriched_inputs,
        trigger_source=trigger_source,
        actor_user_id=credentials_owner_id,
    )
```

Apply the analogous change to the other already-registering call sites (`workflows.py:2957`, `portal.py:409`, `mcp.py:910`/`:1089`, `mcp_servers.py:491`), using each site's local inputs/trigger/actor variables. Where a trigger_source string isn't already available, pass the literal that matches that route (e.g. `"portal"`, `"mcp"`).

- [ ] **Step 2: Add registration to trigger paths that call `execute_workflow` directly**

In each of `cron_scheduler.py:159`, `imap_trigger_service.py:429`, `websocket_trigger_service.py:376`, `rabbitmq_consumer.py:336`, `discord.py:230`, `slack.py:142`, `telegram.py:143`, wrap the `execute_workflow(...)` call so it registers first and clears after. Pattern (adapt variable names to each file; `inputs` is the dict already passed to `execute_workflow`):

```python
    from app.services.execution_cancellation import clear_execution, register_execution

    execution_id = uuid.uuid4()
    cancel_event = register_execution(
        workflow_id=workflow.id,
        execution_id=execution_id,
        inputs=inputs,
        trigger_source="<route-trigger-source>",  # e.g. "rabbitmq", "schedule", "imap"
        actor_user_id=workflow.owner_id,
    )
    try:
        result = execute_workflow(
            ...,  # keep all existing keyword args
            cancel_event=cancel_event,
        )
    finally:
        clear_execution(execution_id)
```

Use these `trigger_source` literals: cron → `"schedule"`, imap → `"imap"`, websocket → `"websocket"`, rabbitmq → `"rabbitmq"`, discord → `"discord"`, slack → `"slack"`, telegram → `"telegram"`. If a file already imports `execute_workflow` but not `uuid`, add `import uuid`.

- [ ] **Step 3: Verify imports load**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "import app.api.workflows, app.api.portal, app.api.mcp, app.api.mcp_servers, app.api.discord, app.api.slack, app.api.telegram, app.services.cron_scheduler, app.services.imap_trigger_service, app.services.websocket_trigger_service, app.services.rabbitmq_consumer"`
Expected: no error.

- [ ] **Step 4: Run the existing execution/cancellation suites for regressions**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_execution_cancellation.py tests/test_cancellation_by_trigger.py tests/test_active_executions_api.py tests/test_workflow_execution_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/workflows.py backend/app/api/portal.py backend/app/api/mcp.py backend/app/api/mcp_servers.py backend/app/api/discord.py backend/app/api/slack.py backend/app/api/telegram.py backend/app/services/cron_scheduler.py backend/app/services/imap_trigger_service.py backend/app/services/websocket_trigger_service.py backend/app/services/rabbitmq_consumer.py
git commit -m "feat(recovery): register all top-level executions for crash recovery"
```

---

## Task 9: Expose `auto_recover_runs` in the workflow API

**Files:**
- Modify: `backend/app/models/schemas.py` (`WorkflowUpdate` ~line 174, `WorkflowResponse` ~line 205)
- Modify: `backend/app/api/workflows.py` (`update_workflow` ~line 1133)
- Test: `backend/tests/test_workflow_execution_api.py` (or nearest workflow-CRUD test file)

- [ ] **Step 1: Add the schema fields**

In `WorkflowUpdate` add: `auto_recover_runs: bool | None = None`
In `WorkflowResponse` add: `auto_recover_runs: bool = True`

- [ ] **Step 2: Apply it in `update_workflow`**

After the `sse_enabled` handling (line ~1133-1134) add:

```python
    if workflow_data.auto_recover_runs is not None:
        workflow.auto_recover_runs = workflow_data.auto_recover_runs
```

- [ ] **Step 3: Write a test for round-tripping the flag**

Add to the workflow CRUD test file an async test (mirroring existing update tests) asserting that PUTting `{"auto_recover_runs": false}` persists and that `WorkflowResponse` defaults to `True` when unset. Follow the existing AsyncMock DB pattern in that file. Minimal assertion-level test:

```python
    def test_workflow_response_defaults_auto_recover_true(self) -> None:
        from app.models.schemas import WorkflowResponse

        fields = WorkflowResponse.model_fields
        self.assertIn("auto_recover_runs", fields)
        self.assertEqual(fields["auto_recover_runs"].default, True)
```

- [ ] **Step 4: Run the test**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_execution_api.py -k auto_recover -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/app/api/workflows.py backend/tests/test_workflow_execution_api.py
git commit -m "feat(recovery): expose auto_recover_runs on workflow API"
```

---

## Task 10: Frontend — run-panel toggle + `skipped` status badge

**Files:**
- Modify: `frontend/src/types/workflow.ts` (~line 33)
- Modify: `frontend/src/services/api.ts` (~line 512, update key union)
- Modify: `frontend/src/components/Panels/DebugPanel.vue`
- Modify: history status rendering (search for where `cancelled`/`success` badges are styled)

- [ ] **Step 1: Add the field to the Workflow type**

In `frontend/src/types/workflow.ts`, after `sse_enabled: boolean;` add:

```ts
  auto_recover_runs: boolean;
```

- [ ] **Step 2: Allow updating it via the API client**

In `frontend/src/services/api.ts`, add `| "auto_recover_runs"` to the `Pick<Workflow, ...>` union used by the workflow `update` function (next to `"sse_enabled"`).

- [ ] **Step 3: Add the toggle to the run panel**

In `frontend/src/components/Panels/DebugPanel.vue`, inside the run/results area (near the existing run controls), add a labeled checkbox bound to the current workflow and persisted via the workflow store/`api.workflows.update`. Use the workflow store already imported in the component. Markup:

```vue
<label class="auto-recover-toggle" :title="'Re-run interrupted runs after a server restart'">
  <input
    type="checkbox"
    :checked="workflowStore.currentWorkflow?.auto_recover_runs ?? true"
    @change="onToggleAutoRecover(($event.target as HTMLInputElement).checked)"
  />
  <span>Auto-recover interrupted runs</span>
</label>
```

Add the handler in `<script setup>` (match the component's existing update pattern; `workflowStore` is the Pinia workflow store):

```ts
async function onToggleAutoRecover(value: boolean): Promise<void> {
  const wf = workflowStore.currentWorkflow;
  if (!wf) return;
  await workflowStore.updateWorkflow(wf.id, { auto_recover_runs: value });
}
```

If the store exposes a different update method name, use that; otherwise call `api.workflows.update(wf.id, { auto_recover_runs: value })` and refresh local state. Add minimal CSS for `.auto-recover-toggle` consistent with nearby controls (flex row, gap, small font).

- [ ] **Step 4: Render the `skipped` status**

Find where execution status badges are styled (search the repo for the `cancelled` status badge, e.g. in `ExecutionHistoryAllDialog.vue` / `ExecutionHistoryDialog.vue` / status helper). Add a `skipped` case with a neutral/grey badge and label "Skipped", mirroring the existing `cancelled` entry.

- [ ] **Step 5: Typecheck and lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS (no errors).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/services/api.ts frontend/src/components/Panels/DebugPanel.vue
git commit -m "feat(recovery): canvas run-panel auto-recover toggle and skipped badge"
```

---

## Task 11: Full verification + docs

**Files:**
- Docs via `heym-documentation` skill (feature-doc policy: this is new UX/behavior).

- [ ] **Step 1: Run the full backend check**

Run: `cd /Users/mbakgun/Projects/heym/heymrun && SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: ruff format clean, lint clean, backend tests PASS. Commit any formatting-only diffs.

- [ ] **Step 2: Update documentation**

Invoke the `heym-documentation` skill to document the crash-recovery behavior and the per-workflow "Auto-recover interrupted runs" toggle (run-panel reference + any execution-status docs that enumerate statuses, to add `skipped`).

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "docs(recovery): document workflow run crash-recovery and auto-recover toggle"
```

---

## Self-Review Notes

- **Spec coverage:** persistence (Task 1-2), sub-workflow exclusion (Task 3), decision logic (Task 4), graceful-shutdown marking + 60s claim (Task 5, Task 7), recovery loop/rerun/skip/fail + leader gating + parallel consumption (Task 6-7), all entry points incl. accepted double-exec triggers (Task 8), toggle API (Task 9), UI toggle + `skipped` badge (Task 10), tests + docs (all tasks + Task 11). ✓
- **Retry-once invariant:** original attempt 0 → claim → 1 (`<= MAX` rerun) → re-register preserves attempt (upsert `set_` omits `attempt`) → crash → claim → 2 (`> MAX` failed). ✓
- **Atomic claim:** guarded `UPDATE ... WHERE heartbeat_at < cutoff`, rowcount==1 wins; live workers heartbeat every 0.5s so never matched. ✓
- **Naming consistency:** `decide_recovery_action`, `claim_orphaned_executions`, `mark_own_executions_orphaned`, `ClaimedOrphan`, `ExecutionRecoveryService`, `execution_recovery_service`, `RECOVERY_STALE_AFTER_SECONDS` used identically across tasks. ✓
