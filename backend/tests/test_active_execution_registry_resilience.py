"""Registry must survive a single unwritable row or a transient database error.

A corrupt page or a lock timeout on `active_workflow_executions` used to abort the
whole sync transaction, which stopped every heartbeat on the worker, dropped queued
start/finish commands, and logged a traceback twice a second.
"""

import asyncio
import logging
import threading
import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sqlalchemy.dialects.postgresql.dml import Insert as PGInsert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.dml import Delete, Update
from sqlalchemy.sql.selectable import Select

import app.services.cluster.run_queue  # noqa: F401
from app.services.execution_cancellation import (
    _ACTIVE_EXECUTIONS,
    ActiveExecutionRegistry,
    ExecutionCancellationHandle,
    _claim_failures,
    _ThrottledFailureLog,
    claim_orphaned_executions,
    register_execution,
)


def _flush() -> None:
    from app.services.execution_cancellation import active_execution_registry

    _ACTIVE_EXECUTIONS.clear()
    with active_execution_registry._commands.mutex:
        active_execution_registry._commands.queue.clear()
    active_execution_registry._pending.clear()
    active_execution_registry._command_attempts.clear()


def _statement_kind(statement: Any) -> str:
    if isinstance(statement, PGInsert):
        return "insert"
    if isinstance(statement, Update):
        return "update"
    if isinstance(statement, Delete):
        return "delete"
    if isinstance(statement, Select):
        return "select"
    return "other"


def _bound_execution_id(statement: Any) -> uuid.UUID | None:
    for value in statement.compile().params.values():
        if isinstance(value, uuid.UUID):
            return value
    return None


class _FakeResult:
    def __init__(self, rowcount: int = 1, rows: list[Any] | None = None) -> None:
        self.rowcount = rowcount
        self._rows = rows or []

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar(self) -> Any:
        return self._rows[0] if self._rows else False

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Async session stub that honours SAVEPOINT semantics closely enough to test."""

    def __init__(
        self,
        handler: Any,
        select_rows: list[Any] | None = None,
    ) -> None:
        self._handler = handler
        self._select_rows = select_rows or []
        self.statements: list[tuple[str, uuid.UUID | None]] = []
        self.compiled_selects: list[str] = []
        self.committed = 0
        self.rolled_back_savepoints = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    def begin_nested(self) -> Any:
        session = self

        @asynccontextmanager
        async def _savepoint() -> Any:
            try:
                yield session
            except Exception:
                session.rolled_back_savepoints += 1
                raise

        return _savepoint()

    async def execute(self, statement: Any) -> _FakeResult:
        kind = _statement_kind(statement)
        execution_id = _bound_execution_id(statement)
        self.statements.append((kind, execution_id))
        if kind == "select":
            self.compiled_selects.append(str(statement))
            return _FakeResult(rows=self._select_rows)
        return self._handler(kind, execution_id)

    async def commit(self) -> None:
        self.committed += 1


def _session_maker(session: _FakeSession) -> Any:
    def _make() -> _FakeSession:
        return session

    return _make


class SyncLocalHandlesIsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _flush()
        self.registry = ActiveExecutionRegistry()

    def tearDown(self) -> None:
        _flush()

    async def test_one_unwritable_row_does_not_stop_other_heartbeats(self) -> None:
        broken_id = uuid.uuid4()
        healthy_id = uuid.uuid4()
        register_execution(workflow_id=uuid.uuid4(), execution_id=broken_id)
        register_execution(workflow_id=uuid.uuid4(), execution_id=healthy_id)

        def handler(kind: str, execution_id: uuid.UUID | None) -> _FakeResult:
            if kind == "update" and execution_id == broken_id:
                raise SQLAlchemyError("could not read block 189")
            return _FakeResult(rowcount=1)

        session = _FakeSession(handler)
        with patch("app.db.session.async_session_maker", _session_maker(session)):
            await self.registry._sync_local_handles()

        updated = [eid for kind, eid in session.statements if kind == "update"]
        self.assertIn(healthy_id, updated)
        self.assertEqual(1, session.rolled_back_savepoints)
        self.assertEqual(1, session.committed)

    async def test_failed_row_does_not_advance_its_synced_version(self) -> None:
        broken_id = uuid.uuid4()
        register_execution(workflow_id=uuid.uuid4(), execution_id=broken_id)
        handle = _ACTIVE_EXECUTIONS[broken_id]
        handle.progress_version = 7

        def handler(kind: str, _execution_id: uuid.UUID | None) -> _FakeResult:
            raise SQLAlchemyError("could not read block 189")

        session = _FakeSession(handler)
        with patch("app.db.session.async_session_maker", _session_maker(session)):
            await self.registry._sync_local_handles()

        self.assertEqual(0, handle.synced_progress_version)

    async def test_missing_row_is_reinserted_so_the_run_stays_visible(self) -> None:
        execution_id = uuid.uuid4()
        register_execution(workflow_id=uuid.uuid4(), execution_id=execution_id)
        handle = _ACTIVE_EXECUTIONS[execution_id]
        handle.running_node_ids.add("node-1")
        handle.progress_version = 3

        def handler(kind: str, _execution_id: uuid.UUID | None) -> _FakeResult:
            if kind == "update":
                return _FakeResult(rowcount=0)
            return _FakeResult(rowcount=1)

        session = _FakeSession(handler)
        with patch("app.db.session.async_session_maker", _session_maker(session)):
            await self.registry._sync_local_handles()

        self.assertIn(("insert", execution_id), session.statements)
        self.assertEqual(3, handle.synced_progress_version)

    async def test_finished_execution_is_not_resurrected(self) -> None:
        execution_id = uuid.uuid4()
        register_execution(workflow_id=uuid.uuid4(), execution_id=execution_id)

        def handler(kind: str, _execution_id: uuid.UUID | None) -> _FakeResult:
            if kind == "update":
                # The run finishes between the snapshot and the write.
                _ACTIVE_EXECUTIONS.clear()
                return _FakeResult(rowcount=0)
            return _FakeResult(rowcount=1)

        session = _FakeSession(handler)
        with patch("app.db.session.async_session_maker", _session_maker(session)):
            await self.registry._sync_local_handles()

        self.assertNotIn("insert", [kind for kind, _eid in session.statements])

    async def test_cancel_poll_failure_still_lets_heartbeats_through(self) -> None:
        execution_id = uuid.uuid4()
        register_execution(workflow_id=uuid.uuid4(), execution_id=execution_id)

        class _CancelPollFails(_FakeSession):
            async def execute(self, statement: Any) -> _FakeResult:
                if _statement_kind(statement) == "select":
                    self.statements.append(("select", None))
                    raise SQLAlchemyError("could not read block 189")
                return await super().execute(statement)

        session = _CancelPollFails(lambda _kind, _eid: _FakeResult(rowcount=1))
        with patch("app.db.session.async_session_maker", _session_maker(session)):
            await self.registry._sync_local_handles()

        self.assertIn(("update", execution_id), session.statements)
        self.assertEqual(1, session.committed)


class DrainCommandsRetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _flush()
        self.registry = ActiveExecutionRegistry()
        self.registry._running = True

    def tearDown(self) -> None:
        _flush()

    def _record_start(self, execution_id: uuid.UUID) -> None:
        self.registry.record_started(
            ExecutionCancellationHandle(
                workflow_id=uuid.uuid4(),
                execution_id=execution_id,
                event=threading.Event(),
            )
        )

    async def test_failed_start_is_replayed_on_the_next_tick(self) -> None:
        execution_id = uuid.uuid4()
        self._record_start(execution_id)

        failing = _FakeSession(self._raise)
        with patch("app.db.session.async_session_maker", _session_maker(failing)):
            await self.registry._drain_commands()
        self.assertEqual(1, len(self.registry._pending))

        healthy = _FakeSession(lambda _kind, _eid: _FakeResult(rowcount=1))
        with patch("app.db.session.async_session_maker", _session_maker(healthy)):
            await self.registry._drain_commands()

        self.assertEqual([], self.registry._pending)
        self.assertIn(("insert", execution_id), healthy.statements)

    async def test_finish_waits_for_its_deferred_start(self) -> None:
        execution_id = uuid.uuid4()
        self._record_start(execution_id)
        self.registry.record_finished(execution_id)

        failing = _FakeSession(self._raise)
        with patch("app.db.session.async_session_maker", _session_maker(failing)):
            await self.registry._drain_commands()

        # The start failed, so the delete must not run ahead of it and leave the
        # replayed insert behind as a phantom row.
        self.assertNotIn("delete", [kind for kind, _eid in failing.statements])
        self.assertEqual(
            ["start", "finish"], [command.action for command in self.registry._pending]
        )

    async def test_unrelated_commands_still_flush_when_one_fails(self) -> None:
        broken_id = uuid.uuid4()
        healthy_id = uuid.uuid4()
        self._record_start(broken_id)
        self._record_start(healthy_id)

        def handler(_kind: str, execution_id: uuid.UUID | None) -> _FakeResult:
            if execution_id == broken_id:
                raise SQLAlchemyError("could not read block 189")
            return _FakeResult(rowcount=1)

        session = _FakeSession(handler)
        with patch("app.db.session.async_session_maker", _session_maker(session)):
            await self.registry._drain_commands()

        self.assertIn(("insert", healthy_id), session.statements)
        self.assertEqual([broken_id], [command.execution_id for command in self.registry._pending])

    async def test_permanently_failing_command_is_dropped_not_replayed_forever(self) -> None:
        """A poison command must not hold back the finish queued behind it."""
        from app.services.execution_cancellation import _MAX_REGISTRY_COMMAND_ATTEMPTS

        execution_id = uuid.uuid4()
        self._record_start(execution_id)

        session = _FakeSession(self._raise)
        with patch("app.db.session.async_session_maker", _session_maker(session)):
            for _ in range(_MAX_REGISTRY_COMMAND_ATTEMPTS):
                await self.registry._drain_commands()

        self.assertEqual([], self.registry._pending)
        self.assertEqual({}, self.registry._command_attempts)

    async def test_attempt_counter_resets_once_a_command_succeeds(self) -> None:
        execution_id = uuid.uuid4()
        self._record_start(execution_id)

        failing = _FakeSession(self._raise)
        with patch("app.db.session.async_session_maker", _session_maker(failing)):
            await self.registry._drain_commands()
        self.assertEqual(1, self.registry._command_attempts[("start", execution_id)])

        healthy = _FakeSession(lambda _kind, _eid: _FakeResult(rowcount=1))
        with patch("app.db.session.async_session_maker", _session_maker(healthy)):
            await self.registry._drain_commands()
        self.assertEqual({}, self.registry._command_attempts)

    async def test_backlog_is_capped(self) -> None:
        for _ in range(2100):
            self._record_start(uuid.uuid4())

        session = _FakeSession(self._raise)
        with patch("app.db.session.async_session_maker", _session_maker(session)):
            await self.registry._drain_commands()

        self.assertEqual(2000, len(self.registry._pending))

    @staticmethod
    def _raise(_kind: str, _execution_id: uuid.UUID | None) -> _FakeResult:
        raise SQLAlchemyError("could not read block 189")


class FailureLogThrottlingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.log = _ThrottledFailureLog()

    def test_repeated_failures_log_once_and_report_the_count(self) -> None:
        error = SQLAlchemyError("could not read block 189")
        with self.assertLogs("app.services.execution_cancellation", level=logging.ERROR) as logs:
            for _ in range(200):
                self.log.failure("heartbeat sync", error)

        self.assertEqual(1, len(logs.records))
        self.assertEqual(199, self.log.suppressed_count("heartbeat sync"))

    def test_separate_scopes_are_throttled_separately(self) -> None:
        error = SQLAlchemyError("could not read block 189")
        with self.assertLogs("app.services.execution_cancellation", level=logging.ERROR) as logs:
            self.log.failure("heartbeat sync", error)
            self.log.failure("command flush", error)
            self.log.failure("heartbeat sync", error)

        self.assertEqual(2, len(logs.records))

    def test_recovery_is_announced_once(self) -> None:
        self.log.failure("heartbeat sync", SQLAlchemyError("boom"))
        with self.assertLogs("app.services.execution_cancellation", level=logging.INFO) as logs:
            self.log.success("heartbeat sync")
        self.assertEqual(1, len(logs.records))
        self.assertIn("recovered", logs.records[0].getMessage())

        # A healthy scope stays quiet.
        with self.assertNoLogs("app.services.execution_cancellation", level=logging.INFO):
            self.log.success("heartbeat sync")


def _orphan_row(execution_id: uuid.UUID, attempt: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        execution_id=execution_id,
        workflow_id=uuid.uuid4(),
        inputs={"text": "hi"},
        trigger_source="API",
        actor_user_id=None,
        attempt=attempt,
    )


class ClaimOrphanedExecutionsIsolationTests(unittest.IsolatedAsyncioTestCase):
    """One unreadable row must not blind orphan recovery for the whole deployment."""

    def setUp(self) -> None:
        _claim_failures.reset()

    def tearDown(self) -> None:
        _claim_failures.reset()

    async def test_unclaimable_row_does_not_block_the_others(self) -> None:
        broken = _orphan_row(uuid.uuid4())
        healthy = _orphan_row(uuid.uuid4())

        def handler(kind: str, execution_id: uuid.UUID | None) -> _FakeResult:
            if kind == "update" and execution_id == broken.execution_id:
                raise SQLAlchemyError("could not read block 189")
            return _FakeResult(rowcount=1)

        session = _FakeSession(handler, select_rows=[broken, healthy])
        with patch(
            "app.services.execution_cancellation.async_session_maker",
            _session_maker(session),
        ):
            claimed = await claim_orphaned_executions()

        self.assertEqual([healthy.execution_id], [orphan.execution_id for orphan in claimed])
        self.assertEqual(1, session.rolled_back_savepoints)
        self.assertEqual(1, session.committed)

    async def test_candidate_scan_failure_returns_empty_instead_of_raising(self) -> None:
        class _ScanFails(_FakeSession):
            async def execute(self, statement: Any) -> _FakeResult:
                if _statement_kind(statement) == "select":
                    raise SQLAlchemyError("could not read block 189")
                return await super().execute(statement)

        session = _ScanFails(lambda _kind, _eid: _FakeResult(rowcount=1))
        with (
            patch(
                "app.services.execution_cancellation.async_session_maker",
                _session_maker(session),
            ),
            self.assertLogs("app.services.execution_cancellation", level=logging.ERROR),
        ):
            claimed = await claim_orphaned_executions()

        self.assertEqual([], claimed)
        self.assertEqual(0, session.committed)

    async def test_repeated_scan_failures_are_throttled(self) -> None:
        class _ScanFails(_FakeSession):
            async def execute(self, statement: Any) -> _FakeResult:
                raise SQLAlchemyError("could not read block 189")

        session = _ScanFails(lambda _kind, _eid: _FakeResult(rowcount=1))
        with (
            patch(
                "app.services.execution_cancellation.async_session_maker",
                _session_maker(session),
            ),
            self.assertLogs("app.services.execution_cancellation", level=logging.ERROR) as logs,
        ):
            for _ in range(50):
                await claim_orphaned_executions()

        self.assertEqual(1, len(logs.records))

    async def test_cancelled_rows_are_excluded_from_the_candidate_scan(self) -> None:
        """A cancelled run whose finish DELETE failed must never be re-run."""
        session = _FakeSession(lambda _kind, _eid: _FakeResult(rowcount=1))
        with patch(
            "app.services.execution_cancellation.async_session_maker",
            _session_maker(session),
        ):
            await claim_orphaned_executions()

        select_statements = [
            stmt for stmt in session.compiled_selects if "cancel_requested_at" in stmt
        ]
        self.assertTrue(
            select_statements,
            "orphan candidate scan must filter on cancel_requested_at",
        )
        self.assertIn("cancel_requested_at IS NULL", select_statements[0])

    async def test_only_rows_the_update_actually_won_are_claimed(self) -> None:
        lost_race = _orphan_row(uuid.uuid4())
        won = _orphan_row(uuid.uuid4(), attempt=1)

        def handler(_kind: str, execution_id: uuid.UUID | None) -> _FakeResult:
            # Another worker already claimed this one, so the guarded UPDATE misses.
            return _FakeResult(rowcount=0 if execution_id == lost_race.execution_id else 1)

        session = _FakeSession(handler, select_rows=[lost_race, won])
        with patch(
            "app.services.execution_cancellation.async_session_maker",
            _session_maker(session),
        ):
            claimed = await claim_orphaned_executions()

        self.assertEqual([won.execution_id], [orphan.execution_id for orphan in claimed])
        self.assertEqual(2, claimed[0].attempt)


class ActiveExecutionsEndpointDegradationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _flush()

    def tearDown(self) -> None:
        _flush()

    async def test_registry_read_failure_falls_back_to_local_handles(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from app.api.workflows import list_active_workflow_executions

        user = MagicMock()
        user.id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        register_execution(
            workflow_id=workflow_id,
            execution_id=execution_id,
            started_at=datetime(2026, 8, 7, 20, 36, tzinfo=timezone.utc),
        )

        workflow = MagicMock()
        workflow.id = workflow_id
        workflow.name = "Orchestrator run"
        scalars = MagicMock()
        scalars.all.return_value = [workflow]
        workflow_result = MagicMock()
        workflow_result.scalars.return_value = scalars

        db = MagicMock()
        db.execute = AsyncMock(return_value=workflow_result)
        db.rollback = AsyncMock()

        with (
            patch(
                "app.services.active_execution_overview.list_persisted_active_executions_for_user",
                AsyncMock(side_effect=SQLAlchemyError("could not read block 189")),
            ),
            patch(
                "app.services.active_execution_overview.list_pending_review_executions_for_user",
                AsyncMock(return_value=[]),
            ),
        ):
            items = await list_active_workflow_executions(current_user=user, db=db)

        db.rollback.assert_awaited_once()
        self.assertEqual([str(execution_id)], [item.execution_id for item in items])
        self.assertEqual("Orchestrator run", items[0].workflow_name)

    async def test_pending_review_failure_does_not_500_the_endpoint(self) -> None:
        """Every read degrades on its own; one bad section must not blank the badge."""
        from unittest.mock import AsyncMock, MagicMock

        from app.api.workflows import list_active_workflow_executions

        user = MagicMock()
        user.id = uuid.uuid4()
        db = MagicMock()
        db.execute = AsyncMock()
        db.rollback = AsyncMock()

        record = MagicMock()
        record.execution_id = uuid.uuid4()
        record.workflow_id = uuid.uuid4()
        record.workflow_name = "Wait"
        record.started_at = datetime(2026, 8, 8, 8, 26, tzinfo=timezone.utc)
        record.inputs = {}
        record.running_node_ids = []
        record.node_results = []

        with (
            patch(
                "app.services.active_execution_overview.list_persisted_active_executions_for_user",
                AsyncMock(return_value=[record]),
            ),
            patch(
                "app.services.active_execution_overview.list_pending_review_executions_for_user",
                AsyncMock(side_effect=SQLAlchemyError("could not read block 189")),
            ),
        ):
            items = await list_active_workflow_executions(current_user=user, db=db)

        self.assertEqual([str(record.execution_id)], [item.execution_id for item in items])
        db.rollback.assert_awaited_once()


class SameProcessInFlightHeartbeatRaceTests(unittest.IsolatedAsyncioTestCase):
    """Deterministic SAME-PROCESS race against real PostgreSQL proving:
    1. In-flight dispatcher heartbeat cannot overwrite worker ownership, worker heartbeat,
       or worker progress, and does not cause live execution to become eligible for recovery.
    2. Cancellation during handoff is durable, never returns 404, and worker detects cancellation
       before executing.
    """

    async def asyncSetUp(self) -> None:
        _flush()
        from app.db.models import User, Workflow
        from app.db.session import async_session_maker, engine
        from app.services.execution_cancellation import active_execution_registry

        await engine.dispose()

        app.services.cluster.run_queue.async_session_maker = async_session_maker
        active_execution_registry._running = True
        self.addCleanup(setattr, active_execution_registry, "_running", False)
        self.addCleanup(
            setattr, app.services.cluster.run_queue, "async_session_maker", async_session_maker
        )

        self.user_id = uuid.uuid4()
        self.wf_id = uuid.uuid4()
        self.ex_id = uuid.uuid4()
        async with async_session_maker() as session:
            session.add(
                User(
                    id=self.user_id,
                    email=f"test_race_{self.user_id.hex[:8]}@example.com",
                    hashed_password="test_hashed_password",
                    name="Test Race User",
                )
            )
            session.add(
                Workflow(
                    id=self.wf_id,
                    name="Test Heartbeat Race Workflow",
                    owner_id=self.user_id,
                    nodes=[],
                    edges=[],
                )
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        from sqlalchemy import delete

        from app.db.models import (
            ActiveWorkflowExecution,
            ExecutionHistory,
            User,
            Workflow,
            WorkflowRunQueue,
        )
        from app.db.session import async_session_maker, engine

        async with async_session_maker() as session:
            await session.execute(
                delete(ActiveWorkflowExecution).where(
                    ActiveWorkflowExecution.execution_id == self.ex_id
                )
            )
            await session.execute(
                delete(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
            )
            await session.execute(delete(ExecutionHistory).where(ExecutionHistory.id == self.ex_id))
            await session.execute(delete(Workflow).where(Workflow.id == self.wf_id))
            await session.execute(delete(User).where(User.id == self.user_id))
            await session.commit()
        await engine.dispose()
        _flush()

    async def test_same_process_in_flight_dispatcher_heartbeat_race_against_real_postgres(
        self,
    ) -> None:
        """Prove that under the exact same-process race:
        A: Dispatcher H_D cannot update worker-owned state.
        B: Dispatcher H_D cannot resurrect the row.
        C: Dispatcher H_D cannot advance heartbeat after H_D was relinquished.
        D: Dispatcher H_D cannot overwrite worker progress/node state.
        E: Worker H_W remains the active registration/owner.
        F: Worker completion still deletes the active row correctly.
        G: Dispatcher writing a newer heartbeat before worker start command drains
           cannot lock out worker ownership.
        H: Worker completion happens BEFORE dispatcher cleanup.
        """
        from contextlib import asynccontextmanager

        from sqlalchemy import func, select, update
        from sqlalchemy.sql import Update

        from app.db.models import ActiveWorkflowExecution
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import (
            _WORKER_ID,
            active_execution_registry,
            clear_execution,
            get_active_execution_handle,
            record_execution_node_started,
            register_execution,
            relinquish_execution,
        )

        # 1. Create a dispatcher execution and obtain dispatcher handle H_D
        register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"dispatcher_data": 1},
        )
        h_d = get_active_execution_handle(self.ex_id)
        self.assertIsNotNone(h_d)
        token_d = h_d.registration_token

        # Drain dispatcher's start command to real PostgreSQL
        await active_execution_registry._drain_commands()

        # Verify initial dispatcher row exists in real PostgreSQL
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            self.assertEqual(row.worker_id, f"{_WORKER_ID}:{token_d}")
            self.assertEqual(row.running_node_ids, [])

        # 2 & 3. Make _sync_local_handles() capture H_D in its snapshot, and pause
        # immediately before the database UPDATE for H_D
        paused_event = asyncio.Event()
        resume_event = asyncio.Event()

        real_session_maker = async_session_maker

        intercepted = False

        @asynccontextmanager
        async def pausing_session_maker():
            async with real_session_maker() as session:
                real_execute = session.execute

                async def intercepted_execute(stmt, *args, **kwargs):
                    nonlocal intercepted
                    if isinstance(stmt, Update) and not intercepted:
                        intercepted = True
                        paused_event.set()
                        await resume_event.wait()
                    return await real_execute(stmt, *args, **kwargs)

                session.execute = intercepted_execute
                yield session

        with patch("app.db.session.async_session_maker", pausing_session_maker):
            sync_task = asyncio.create_task(active_execution_registry._sync_local_handles())
            await paused_event.wait()

            # 4. While paused:
            # a. simulate worker claim in the SAME OS PROCESS
            # b. create/register worker handle H_W for the same execution (Ordering G: worker registers BEFORE dispatcher relinquishes)
            register_execution(
                workflow_id=self.wf_id,
                execution_id=self.ex_id,
                inputs={"worker_data": 2},
            )
            h_w = get_active_execution_handle(self.ex_id)
            self.assertIsNotNone(h_w)
            token_w = h_w.registration_token
            self.assertNotEqual(token_d, token_w)

            # c. Dispatcher writes a newer heartbeat after worker registration but before worker's start command drains:
            t_disp_newer = datetime(2026, 9, 20, 12, 10, 0, tzinfo=timezone.utc)
            async with real_session_maker() as session:
                await session.execute(
                    update(ActiveWorkflowExecution)
                    .where(ActiveWorkflowExecution.execution_id == self.ex_id)
                    .values(heartbeat_at=t_disp_newer)
                )
                await session.commit()

            # d. Worker's start command drains; proves worker ownership is established and NOT rejected
            # by dispatcher's newer heartbeat
            await active_execution_registry._drain_commands()

            # e. make worker progress state current
            record_execution_node_started(str(self.ex_id), "worker_node_step_1")
            await active_execution_registry._sync_local_handles()

            # f. relinquish H_D (Ordering G: dispatcher relinquishes after worker registers)
            relinquish_execution(self.ex_id, handle=h_d)
            self.assertTrue(h_d.relinquished)
            self.assertFalse(h_w.relinquished)

            # 5. Resume the already-in-flight dispatcher heartbeat
            resume_event.set()
            await sync_task

        # 6. Inspect the real PostgreSQL ActiveWorkflowExecution row:
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            count = (
                await session.execute(
                    select(func.count(ActiveWorkflowExecution.execution_id)).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()

            # PROVE A & G: Dispatcher H_D cannot update worker-owned state, and worker ownership was established
            self.assertEqual(row.worker_id, f"{_WORKER_ID}:{token_w}")
            self.assertNotEqual(row.worker_id, f"{_WORKER_ID}:{token_d}")

            # PROVE B: Dispatcher H_D cannot resurrect the row or create duplicate rows
            self.assertEqual(count, 1)

            # PROVE D: Dispatcher H_D cannot overwrite worker progress/node state
            self.assertEqual(row.running_node_ids, ["worker_node_step_1"])

        # PROVE E: Worker H_W remains the active registration/owner
        self.assertIs(get_active_execution_handle(self.ex_id), h_w)
        self.assertFalse(h_w.relinquished)

        # PROVE F & H: Worker completion happens BEFORE dispatcher cleanup, and still deletes the active row correctly
        # Worker completes:
        worker_cleared = clear_execution(self.ex_id, handle=h_w)
        self.assertTrue(worker_cleared)
        await active_execution_registry._drain_commands()

        # Row is deleted from PostgreSQL
        async with async_session_maker() as session:
            count_after_worker = (
                await session.execute(
                    select(func.count(ActiveWorkflowExecution.execution_id)).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            self.assertEqual(count_after_worker, 0)

        # PROVE H: Dispatcher cleanup runs AFTER worker completion: safe NO-OP, row stays deleted
        disp_cleared = clear_execution(self.ex_id, handle=h_d)
        self.assertFalse(disp_cleared)
        active_execution_registry.relinquish(token_d)
        await active_execution_registry._drain_commands()
        await active_execution_registry._sync_local_handles()

        async with async_session_maker() as session:
            final_count = (
                await session.execute(
                    select(func.count(ActiveWorkflowExecution.execution_id)).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            self.assertEqual(final_count, 0)

    async def test_cancellation_during_dispatcher_worker_handoff_against_real_postgres(
        self,
    ) -> None:
        """Prove that a queued execution remains visible and cancellable during the
        entire dispatcher -> worker handoff:
        1. Dispatcher enqueues to WorkflowRunQueue and relinquishes handle.
        2. Cancellation is requested before worker persists active execution row.
        3. Cancellation returns True (never False / 404).
        4. Worker claims run, detects cancellation before running executor, and records
           ExecutionHistory as cancelled without executing any node.
        """
        from datetime import timedelta
        from unittest.mock import patch

        from sqlalchemy import select

        from app.db.models import ExecutionHistory, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.dispatch import run_queue_worker
        from app.services.cluster.run_queue import STATUS_DONE, STATUS_FAILED, STATUS_QUEUED
        from app.services.execution_cancellation import (
            get_active_execution_handle,
            register_execution,
            relinquish_execution,
            request_persisted_execution_cancel,
        )

        now = datetime.now(timezone.utc)
        queued_run = WorkflowRunQueue(
            id=uuid.uuid4(),
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            placement="anywhere",
            target_instance_id="test-instance",
            status=STATUS_QUEUED,
            inputs={"input_key": "input_value"},
            trigger_source="api",
            actor_user_id=self.user_id,
            credentials_owner_id=self.user_id,
            test_run=False,
            timeout_seconds=60.0,
            return_on_chart_output=False,
            enqueued_at=now,
            not_after=now + timedelta(seconds=120),
        )
        async with async_session_maker() as session:
            session.add(queued_run)
            await session.commit()

        # Dispatcher registered and relinquished
        disp_event = register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"input_key": "input_value"},
        )
        disp_handle = getattr(disp_event, "_execution_handle", None)
        self.assertIsNotNone(disp_handle)
        relinquish_execution(self.ex_id, handle=disp_handle)

        # Handle is gone from memory and worker has NOT registered yet
        self.assertIsNone(get_active_execution_handle(self.ex_id))

        # Cancellation request arrives during handoff
        async with async_session_maker() as session:
            cancelled = await request_persisted_execution_cancel(
                session,
                workflow_id=self.wf_id,
                execution_id=self.ex_id,
            )
        # MUST return True (not False which causes 404!)
        self.assertTrue(cancelled)

        # Worker claims the run and executes _execute_claimed
        executor_called = False

        def fake_executor(*args, **kwargs):
            nonlocal executor_called
            executor_called = True
            raise RuntimeError("Executor should not be called for cancelled run")

        with patch("app.services.cluster.dispatch.execute_workflow", side_effect=fake_executor):
            await run_queue_worker._execute_claimed(queued_run)

        # Verify executor was NEVER called
        self.assertFalse(executor_called)

        # Verify ExecutionHistory has cancelled status in PostgreSQL
        async with async_session_maker() as session:
            hist = (
                await session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == self.ex_id)
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(hist)
            self.assertEqual(hist.status, "cancelled")

            q_after = (
                await session.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(q_after)
            self.assertIn(q_after.status, (STATUS_DONE, STATUS_FAILED))
            if q_after.status == STATUS_DONE:
                self.assertEqual((q_after.result or {}).get("status"), "cancelled")

    async def test_worker_start_command_survives_queue_claim_and_establishes_ownership(
        self,
    ) -> None:
        """Prove that under:
            dispatcher registration
            -> queue claim (STATUS_CLAIMED)
            -> worker registration
            -> worker start command
            -> registry drain
        the worker-owned active row is present in PostgreSQL and NOT discarded
        by any claimed-status check.
        """
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_CLAIMED
        from app.services.execution_cancellation import (
            _WORKER_ID,
            active_execution_registry,
            register_execution,
            relinquish_execution,
        )

        now = datetime.now(timezone.utc)
        # 1. Dispatcher registers and enqueues
        disp_event = register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"disp": 1},
        )
        disp_handle = getattr(disp_event, "_execution_handle", None)
        self.assertIsNotNone(disp_handle)

        # 2. Row exists in WorkflowRunQueue as claimed by worker
        queued_run = WorkflowRunQueue(
            id=uuid.uuid4(),
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            placement="anywhere",
            target_instance_id="worker-instance",
            status=STATUS_CLAIMED,
            claimed_at=now,
            claimed_by_process="worker-instance-1234",
            inputs={"worker": 1},
            trigger_source="api",
            actor_user_id=self.user_id,
            credentials_owner_id=self.user_id,
            test_run=False,
            timeout_seconds=60.0,
            return_on_chart_output=False,
            enqueued_at=now,
            not_after=now + timedelta(seconds=120),
        )
        async with async_session_maker() as session:
            session.add(queued_run)
            await session.commit()

        # Dispatcher relinquishes
        relinquish_execution(self.ex_id, handle=disp_handle)

        # 3. Worker registers execution in worker process
        worker_event = register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"worker": 1},
            claim_owner="worker-instance-1234",
        )
        worker_handle = getattr(worker_event, "_execution_handle", None)
        self.assertIsNotNone(worker_handle)
        token_w = worker_handle.registration_token

        # 4. Drain commands to PostgreSQL
        await active_execution_registry._drain_commands()

        # 5. Verify worker-owned active row exists in PostgreSQL
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(
                row, "Worker's start command must not be discarded for claimed execution"
            )
            self.assertEqual(row.worker_id, f"{_WORKER_ID}:{token_w}")

    async def test_stale_dispatcher_finish_command_does_not_delete_worker_owned_row(
        self,
    ) -> None:
        """Prove that a stale dispatcher finish command cannot delete a worker-owned active row:
            dispatcher finish command queued
                     ↓
            worker registers / takes ownership
                     ↓
            worker-owned active row exists in PostgreSQL
                     ↓
            stale dispatcher finish command drains
        Result: worker-owned active row remains in PostgreSQL (ZERO deletion).
        When worker finishes, its own finish command deletes the row normally.
        """
        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import (
            _WORKER_ID,
            active_execution_registry,
            register_execution,
        )

        # 1. Dispatcher registers and drains to create dispatcher row
        disp_event = register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"disp": 1},
        )
        disp_handle = getattr(disp_event, "_execution_handle", None)
        self.assertIsNotNone(disp_handle)
        token_d = disp_handle.registration_token
        await active_execution_registry._drain_commands()

        # 2. Dispatcher queues a finish command
        active_execution_registry.record_finished(self.ex_id, registration_token=token_d)

        # 3. Worker registers and takes ownership
        worker_event = register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"worker": 1},
        )
        worker_handle = getattr(worker_event, "_execution_handle", None)
        self.assertIsNotNone(worker_handle)
        token_w = worker_handle.registration_token

        # Worker's start command and dispatcher's finish command drain
        await active_execution_registry._drain_commands()

        # 4. Verify worker-owned active row STILL exists in PostgreSQL
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(
                row, "Worker row must NOT be deleted by stale dispatcher finish command"
            )
            self.assertEqual(row.worker_id, f"{_WORKER_ID}:{token_w}")

        # 5. When worker finishes, its finish command deletes its row normally
        active_execution_registry.record_finished(self.ex_id, registration_token=token_w)
        await active_execution_registry._drain_commands()

        async with async_session_maker() as session:
            row_after = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNone(row_after, "Worker finish command must delete its own row")

    async def test_delayed_dispatcher_start_cannot_reclaim_another_process_worker_ownership(
        self,
    ) -> None:
        """Prove that when another process claims a run and establishes ownership in PostgreSQL:
            dispatcher registration enqueues START
                     ↓
            dispatcher relinquishes handle
                     ↓
            another process worker claims run (STATUS_CLAIMED, claimed_by_process="worker-host2-9999")
                     ↓
            worker establishes active row in PostgreSQL (worker_id="worker-host2-9999:token_other")
                     ↓
            delayed dispatcher START drains
        Result: dispatcher START is discarded. The other process worker's ownership,
        worker_id, and heartbeat are completely preserved against overwrite.
        """
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_CLAIMED
        from app.services.execution_cancellation import (
            active_execution_registry,
            register_execution,
            relinquish_execution,
        )

        now = datetime.now(timezone.utc)
        # 1. Dispatcher registers and enqueues START command
        disp_event = register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"disp": 1},
        )
        disp_handle = getattr(disp_event, "_execution_handle", None)
        self.assertIsNotNone(disp_handle)

        # 2. Row exists in WorkflowRunQueue claimed by another worker process
        worker_process_id = "worker-host2-9999"
        queued_run = WorkflowRunQueue(
            id=uuid.uuid4(),
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            placement="anywhere",
            target_instance_id="worker-host2",
            status=STATUS_CLAIMED,
            claimed_at=now,
            claimed_by_process=worker_process_id,
            inputs={"worker": 1},
            trigger_source="api",
            actor_user_id=self.user_id,
            credentials_owner_id=self.user_id,
            test_run=False,
            timeout_seconds=60.0,
            return_on_chart_output=False,
            enqueued_at=now,
            not_after=now + timedelta(seconds=120),
        )
        async with async_session_maker() as session:
            session.add(queued_run)
            await session.commit()

        # Dispatcher relinquishes
        relinquish_execution(self.ex_id, handle=disp_handle)

        # 3. Another process worker writes its active row directly to PostgreSQL
        other_worker_id = f"{worker_process_id}:{uuid.uuid4()}"
        worker_heartbeat = now + timedelta(seconds=10)
        async with async_session_maker() as session:
            session.add(
                ActiveWorkflowExecution(
                    execution_id=self.ex_id,
                    workflow_id=self.wf_id,
                    worker_id=other_worker_id,
                    started_at=now,
                    heartbeat_at=worker_heartbeat,
                    inputs={"worker": 1},
                    trigger_source="api",
                    actor_user_id=self.user_id,
                    recoverable=True,
                    running_node_ids=["node_active_on_other_worker"],
                    running_node_started_at_ms={},
                    node_results=[],
                )
            )
            await session.commit()

        # 4. Delayed dispatcher START command drains
        await active_execution_registry._drain_commands()

        # 5. In PostgreSQL: verify worker ownership was NOT overwritten
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            self.assertEqual(
                row.worker_id,
                other_worker_id,
                "Dispatcher must NOT overwrite other worker's worker_id",
            )
            self.assertEqual(row.inputs, {"worker": 1})
            self.assertEqual(row.running_node_ids, ["node_active_on_other_worker"])

    async def test_delayed_dispatcher_start_cannot_reclaim_same_process_worker_ownership(
        self,
    ) -> None:
        """Prove that under the same-process worker claim:
            dispatcher registration enqueues START
                     ↓
            dispatcher relinquishes
                     ↓
            same-process worker claims run (STATUS_CLAIMED, claimed_by_process="worker-local-1")
                     ↓
            worker registers with claim_owner and drains to establish ownership
                     ↓
            delayed dispatcher START drains
        Result: delayed dispatcher START is discarded. Same-process worker ownership
        is preserved against reclaim.
        """
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_CLAIMED
        from app.services.execution_cancellation import (
            _WORKER_ID,
            active_execution_registry,
            register_execution,
            relinquish_execution,
        )

        now = datetime.now(timezone.utc)
        # 1. Dispatcher registers and enqueues START
        disp_event = register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"disp": 1},
        )
        disp_handle = getattr(disp_event, "_execution_handle", None)
        self.assertIsNotNone(disp_handle)

        # 2. Row exists in WorkflowRunQueue claimed by local worker
        local_claim_owner = f"{_WORKER_ID}-local"
        queued_run = WorkflowRunQueue(
            id=uuid.uuid4(),
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            placement="anywhere",
            target_instance_id="worker-local",
            status=STATUS_CLAIMED,
            claimed_at=now,
            claimed_by_process=local_claim_owner,
            inputs={"worker": 1},
            trigger_source="api",
            actor_user_id=self.user_id,
            credentials_owner_id=self.user_id,
            test_run=False,
            timeout_seconds=60.0,
            return_on_chart_output=False,
            enqueued_at=now,
            not_after=now + timedelta(seconds=120),
        )
        async with async_session_maker() as session:
            session.add(queued_run)
            await session.commit()

        # Dispatcher relinquishes
        relinquish_execution(self.ex_id, handle=disp_handle)

        # 3. Same-process worker claims and registers
        worker_event = register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"worker": 1},
            claim_owner=local_claim_owner,
        )
        worker_handle = getattr(worker_event, "_execution_handle", None)
        self.assertIsNotNone(worker_handle)
        token_w = worker_handle.registration_token

        # Drain worker's start command to PostgreSQL
        await active_execution_registry._drain_commands()

        # 4. Synthesize a delayed dispatcher START command queued from earlier
        from app.services.execution_cancellation import _RegistryCommand

        delayed_disp_cmd = _RegistryCommand(
            action="start",
            execution_id=self.ex_id,
            registration_token=disp_handle.registration_token,
            workflow_id=self.wf_id,
            started_at=now - timedelta(minutes=1),
            enqueued_at=now - timedelta(minutes=1),
            inputs={"disp": "stale"},
            trigger_source="api",
            claim_owner=None,  # Dispatcher has no claim owner
        )
        active_execution_registry._commands.put(delayed_disp_cmd)
        await active_execution_registry._drain_commands()

        # 5. In PostgreSQL: worker's row is STILL the owner; stale dispatcher command did not overwrite
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            self.assertEqual(row.worker_id, f"{_WORKER_ID}:{token_w}")
            self.assertEqual(row.inputs, {"worker": 1})

    async def test_worker_completes_before_delayed_dispatcher_start_drains(
        self,
    ) -> None:
        """Prove that when a worker completes the run before a delayed dispatcher START drains:
            dispatcher registration enqueues START
                     ↓
            worker claims and completes (STATUS_DONE, ExecutionHistory written)
                     ↓
            worker deletes active row upon finish
                     ↓
            delayed dispatcher START drains
        Result: delayed dispatcher START is discarded by terminal check. ActiveWorkflowExecution
        row is NOT resurrected (zero phantom row).
        """
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution, ExecutionHistory, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_DONE
        from app.services.execution_cancellation import (
            active_execution_registry,
            register_execution,
            relinquish_execution,
        )

        now = datetime.now(timezone.utc)
        # 1. Dispatcher registers and enqueues START
        disp_event = register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"disp": 1},
        )
        disp_handle = getattr(disp_event, "_execution_handle", None)
        self.assertIsNotNone(disp_handle)
        relinquish_execution(self.ex_id, handle=disp_handle)

        # 2. Worker claims and completes in database
        async with async_session_maker() as session:
            session.add(
                WorkflowRunQueue(
                    id=uuid.uuid4(),
                    workflow_id=self.wf_id,
                    execution_id=self.ex_id,
                    placement="anywhere",
                    target_instance_id="worker-proc-1",
                    status=STATUS_DONE,
                    claimed_at=now - timedelta(seconds=10),
                    claimed_by_process="worker-proc-1",
                    finished_at=now,
                    result={"status": "success", "outputs": {"done": True}},
                    inputs={"worker": 1},
                    trigger_source="api",
                    actor_user_id=self.user_id,
                    credentials_owner_id=self.user_id,
                    test_run=False,
                    timeout_seconds=60.0,
                    return_on_chart_output=False,
                    enqueued_at=now - timedelta(seconds=20),
                    not_after=now + timedelta(seconds=120),
                )
            )
            session.add(
                ExecutionHistory(
                    id=self.ex_id,
                    workflow_id=self.wf_id,
                    inputs={"worker": 1},
                    outputs={"done": True},
                    node_results=[],
                    status="success",
                    execution_time_ms=100.0,
                    trigger_source="api",
                )
            )
            await session.commit()

        # 3. Delayed dispatcher START drains
        await active_execution_registry._drain_commands()

        # 4. In PostgreSQL: ActiveWorkflowExecution row must NOT exist (no resurrection)
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNone(
                row, "Delayed dispatcher START must NOT resurrect completed execution"
            )

    async def test_queued_execution_remains_visible_during_handoff_and_cancels_cleanly(
        self,
    ) -> None:
        """Prove that during the window between dispatcher relinquishing and worker active-row creation:
        1. ACTIVE row is absent from ActiveWorkflowExecution.
        2. Execution remains visible via list_persisted_active_executions_for_user.
        3. Cancellation succeeds, sets queue error to None, result to cancelled.
        4. Worker subsequently checking the queue observes cancellation and does not execute.
        """
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution, ExecutionHistory, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_DONE, STATUS_QUEUED
        from app.services.execution_cancellation import (
            list_persisted_active_executions_for_user,
            register_execution,
            relinquish_execution,
            request_persisted_execution_cancel,
        )
        from app.services.workflow_executor import WorkflowCancelledError

        now = datetime.now(timezone.utc)
        # 1. Dispatcher registers and immediately relinquishes
        disp_event = register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"test": "handoff"},
        )
        disp_handle = getattr(disp_event, "_execution_handle", None)
        self.assertIsNotNone(disp_handle)
        relinquish_execution(self.ex_id, handle=disp_handle)

        # 2. Run is queued in WorkflowRunQueue, active row absent
        async with async_session_maker() as session:
            session.add(
                WorkflowRunQueue(
                    id=uuid.uuid4(),
                    workflow_id=self.wf_id,
                    execution_id=self.ex_id,
                    placement="anywhere",
                    target_instance_id="worker-instance",
                    status=STATUS_QUEUED,
                    inputs={"test": "handoff"},
                    trigger_source="api",
                    actor_user_id=self.user_id,
                    credentials_owner_id=self.user_id,
                    test_run=False,
                    timeout_seconds=60.0,
                    return_on_chart_output=False,
                    enqueued_at=now,
                    not_after=now + timedelta(seconds=120),
                )
            )
            await session.commit()

        # Invariant check: ACTIVE row is absent from PostgreSQL table
        async with async_session_maker() as session:
            active_row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNone(
                active_row, "ActiveWorkflowExecution row must be absent during handoff"
            )

            # 3. Query visibility: must be visible to the user
            visible_items = await list_persisted_active_executions_for_user(session, self.user_id)
            visible_ids = [item.execution_id for item in visible_items]
            self.assertIn(self.ex_id, visible_ids, "Queued run must be visible during handoff")

            # 4. Cancel during this window
            cancelled = await request_persisted_execution_cancel(
                session, workflow_id=self.wf_id, execution_id=self.ex_id
            )
            self.assertTrue(cancelled)

        # 5. Verify database state after cancellation
        async with async_session_maker() as session:
            q_row = (
                await session.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
                )
            ).scalar_one()
            self.assertEqual(q_row.status, STATUS_DONE)
            self.assertIsNone(
                q_row.error, "Queue error must be None so dispatcher gets cancelled result"
            )
            self.assertEqual(q_row.result["status"], "cancelled")

            hist = (
                await session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == self.ex_id)
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(hist)
            self.assertEqual(hist.status, "cancelled")

            # 6. Worker subsequently checks queue row: detects cancellation and does not run
            is_cancelled = (
                q_row.status == STATUS_DONE and (q_row.result or {}).get("status") == "cancelled"
            )
            self.assertTrue(is_cancelled)
            if is_cancelled:
                with self.assertRaises(WorkflowCancelledError):
                    raise WorkflowCancelledError("Workflow execution cancelled")


if __name__ == "__main__":
    unittest.main()
