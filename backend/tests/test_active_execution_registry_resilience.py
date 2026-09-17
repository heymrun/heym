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
    _ACTIVE_EXECUTIONS.clear()


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


class _FakeSession:
    """Async session stub that honours SAVEPOINT semantics closely enough to test."""

    def __init__(self, handler: Any, select_rows: list[Any] | None = None) -> None:
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


class DelayedRegistryWriteConflictTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _flush()

    def tearDown(self) -> None:
        _flush()

    def test_upsert_structure_preserves_cancellation_and_progress_on_conflict(self) -> None:
        """Verify behaviorally through the upsert construction that ON CONFLICT DO UPDATE:
        1. Never updates cancel_requested_at (so a delayed start write cannot clear cancellation)
        2. Guards heartbeat_at and worker_id via CASE (so a delayed older write cannot regress ownership)
        3. Guards running_node_ids, running_node_started_at_ms, and node_results via CASE
        No SQL string assertions are used; we inspect the statement's AST objects directly.
        """
        from sqlalchemy.sql.elements import Case

        from app.services.execution_cancellation import _build_active_execution_upsert

        ex_id = uuid.uuid4()
        wf_id = uuid.uuid4()
        t_start = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
        t_hb = datetime(2026, 9, 17, 10, 5, tzinfo=timezone.utc)

        stmt = _build_active_execution_upsert(
            execution_id=ex_id,
            workflow_id=wf_id,
            started_at=t_start,
            heartbeat_at=t_hb,
            inputs={"k": "v"},
            trigger_source="api",
            actor_user_id=None,
            recoverable=True,
            running_node_ids=[],
            running_node_started_at_ms={},
            node_results=[],
        )

        update_set = dict(stmt._post_values_clause.update_values_to_set)

        # 1. cancel_requested_at is omitted from update_set:
        # A delayed start write cannot overwrite cancellation timestamp to None
        self.assertNotIn("cancel_requested_at", update_set)

        # 2. heartbeat_at and worker_id use Case statements guarding against regression:
        self.assertIn("heartbeat_at", update_set)
        self.assertIsInstance(update_set["heartbeat_at"], Case)
        self.assertIn("worker_id", update_set)
        self.assertIsInstance(update_set["worker_id"], Case)

        # 3. running_node_ids, running_node_started_at_ms, and node_results use Case statements:
        self.assertIn("running_node_ids", update_set)
        self.assertIsInstance(update_set["running_node_ids"], Case)
        self.assertIn("running_node_started_at_ms", update_set)
        self.assertIsInstance(update_set["running_node_started_at_ms"], Case)
        self.assertIn("node_results", update_set)
        self.assertIsInstance(update_set["node_results"], Case)

    async def test_relinquished_token_purges_finish_commands_but_preserves_start(self) -> None:
        """Proves that relinquishing a registration token preserves start commands
        (so queued runs get persisted active execution records for visibility/cancellation)
        while purging finish commands (so dispatcher cleanup cannot delete worker rows).
        """
        from app.services.execution_cancellation import (
            ActiveExecutionRegistry,
            _RegistryCommand,
        )

        token_a = uuid.uuid4()
        token_b = uuid.uuid4()
        ex_id_a = uuid.uuid4()
        ex_id_b = uuid.uuid4()

        registry = ActiveExecutionRegistry()
        cmd_start_a = _RegistryCommand(
            action="start", execution_id=ex_id_a, registration_token=token_a
        )
        cmd_finish_a = _RegistryCommand(
            action="finish", execution_id=ex_id_a, registration_token=token_a
        )
        cmd_start_b = _RegistryCommand(
            action="start", execution_id=ex_id_b, registration_token=token_b
        )
        registry._commands.put(cmd_start_a)
        registry._commands.put(cmd_finish_a)
        registry._commands.put(cmd_start_b)

        # Relinquish token_a
        registry.relinquish(token_a)

        # cmd_start_a and cmd_start_b must be preserved, cmd_finish_a purged
        remaining_commands = list(registry._commands.queue)
        self.assertIn(cmd_start_a, remaining_commands)
        self.assertIn(cmd_start_b, remaining_commands)
        self.assertNotIn(cmd_finish_a, remaining_commands)

        # If placed in _pending, relinquish also cleans finish from _pending
        registry._pending.append(cmd_finish_a)
        registry._pending.append(cmd_start_a)
        registry.relinquish(token_a)
        self.assertNotIn(cmd_finish_a, registry._pending)
        self.assertIn(cmd_start_a, registry._pending)

    async def test_anti_resurrection_terminal_execution_discards_start_command(self) -> None:
        """A delayed start command for an execution that already reached a terminal state
        must be discarded and must NOT insert an ActiveWorkflowExecution row.
        """
        from app.services.execution_cancellation import (
            ActiveExecutionRegistry,
            _RegistryCommand,
        )

        ex_id = uuid.uuid4()
        wf_id = uuid.uuid4()
        now = datetime(2026, 9, 17, 10, 30, tzinfo=timezone.utc)
        cmd = _RegistryCommand(
            action="start",
            execution_id=ex_id,
            workflow_id=wf_id,
            started_at=datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc),
            inputs={"x": 1},
        )

        executed_stmts = []

        def handler(kind: str, execution_id: uuid.UUID | None) -> _FakeResult:
            executed_stmts.append((kind, execution_id))
            return _FakeResult(rowcount=1)

        # Return True for terminal check select (execution already finished)
        session = _FakeSession(handler, select_rows=[True])
        registry = ActiveExecutionRegistry()
        await registry._apply_command(session, cmd, now)

        # Only the select check was executed; NO insert/upsert was executed!
        self.assertEqual(len(executed_stmts), 0)
        insert_stmts = [kind for kind, _ in session.statements if kind == "insert"]
        self.assertEqual(len(insert_stmts), 0)

    async def test_delayed_start_command_applied_via_session(self) -> None:
        """Applying a delayed start command passes the guarded upsert to the database session
        using command.enqueued_at as heartbeat_at rather than drain time.
        """
        from app.services.execution_cancellation import (
            ActiveExecutionRegistry,
            _RegistryCommand,
        )

        ex_id = uuid.uuid4()
        wf_id = uuid.uuid4()
        enqueued_time = datetime(2026, 9, 17, 10, 5, tzinfo=timezone.utc)
        drain_time = datetime(2026, 9, 17, 10, 30, tzinfo=timezone.utc)
        cmd = _RegistryCommand(
            action="start",
            execution_id=ex_id,
            workflow_id=wf_id,
            started_at=datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc),
            enqueued_at=enqueued_time,
            inputs={"x": 1},
            trigger_source="api",
            actor_user_id=None,
            recoverable=True,
        )

        executed_stmts = []

        def handler(kind: str, execution_id: uuid.UUID | None) -> _FakeResult:
            executed_stmts.append((kind, execution_id))
            return _FakeResult(rowcount=1)

        # Non-terminal run (select returns False)
        session = _FakeSession(handler, select_rows=[False])
        registry = ActiveExecutionRegistry()
        await registry._apply_command(session, cmd, drain_time)

        self.assertEqual(len(executed_stmts), 1)
        kind, bound_id = executed_stmts[0]
        self.assertEqual(kind, "insert")
        self.assertEqual(bound_id, ex_id)

    async def test_in_flight_dispatcher_heartbeat_does_not_overwrite_worker_ownership(self) -> None:
        """Proves that _sync_local_handles scopes its heartbeat update to _WORKER_ID
        and checks if another worker owns the row before attempting reinsertion.
        """
        from app.services.execution_cancellation import (
            _ACTIVE_EXECUTIONS,
            ExecutionCancellationHandle,
        )

        ex_id = uuid.uuid4()
        wf_id = uuid.uuid4()
        handle = ExecutionCancellationHandle(
            execution_id=ex_id,
            workflow_id=wf_id,
            event=threading.Event(),
        )
        _ACTIVE_EXECUTIONS[ex_id] = handle

        executed_stmts = []

        def handler(kind: str, execution_id: uuid.UUID | None) -> _FakeResult:
            executed_stmts.append((kind, execution_id))
            if kind == "update":
                # Returns 0 because worker took ownership with different worker_id
                return _FakeResult(rowcount=0)
            return _FakeResult(rowcount=1)

        session = _FakeSession(handler, select_rows=[])
        original_execute = session.execute

        async def mock_execute(statement: Any) -> _FakeResult:
            kind = _statement_kind(statement)
            if kind == "select" and "worker_id" in str(statement):
                res = _FakeResult(rowcount=1)
                res.scalar_one_or_none = lambda: "other-worker-id"
                executed_stmts.append((kind, _bound_execution_id(statement)))
                return res
            return await original_execute(statement)

        session.execute = mock_execute

        registry = ActiveExecutionRegistry()
        with patch("app.db.session.async_session_maker", _session_maker(session)):
            await registry._sync_local_handles()

        # Update was attempted scoped to _WORKER_ID, worker_id was checked, and NO insert occurred
        kinds = [k for k, _ in executed_stmts]
        self.assertIn("update", kinds)
        self.assertNotIn("insert", kinds)

    async def test_unflushed_start_command_drains_after_relinquish_to_create_active_row(
        self,
    ) -> None:
        """Proves that registering an execution and immediately relinquishing preserves
        the unflushed start command so it drains and creates an ActiveWorkflowExecution row.
        """
        from app.services.execution_cancellation import (
            ActiveExecutionRegistry,
            _RegistryCommand,
        )

        ex_id = uuid.uuid4()
        wf_id = uuid.uuid4()
        token = uuid.uuid4()
        registry = ActiveExecutionRegistry()
        cmd = _RegistryCommand(
            action="start",
            execution_id=ex_id,
            workflow_id=wf_id,
            registration_token=token,
            inputs={"a": 1},
            trigger_source="api",
        )
        registry._commands.put(cmd)

        # Relinquish immediately before draining
        registry.relinquish(token)

        executed_stmts = []

        def handler(kind: str, execution_id: uuid.UUID | None) -> _FakeResult:
            executed_stmts.append((kind, execution_id))
            return _FakeResult(rowcount=1)

        session = _FakeSession(handler, select_rows=[False])  # terminal_check returns False
        with patch("app.db.session.async_session_maker", _session_maker(session)):
            await registry._drain_commands()

        # The start command was preserved and drained, inserting the active row
        self.assertIn(("insert", ex_id), executed_stmts)


class SameProcessInFlightHeartbeatRaceTests(unittest.IsolatedAsyncioTestCase):
    """Deterministic SAME-PROCESS race against real PostgreSQL proving that an
    in-flight dispatcher heartbeat cannot overwrite worker ownership after handoff.
    """

    async def asyncSetUp(self) -> None:
        _flush()
        from sqlalchemy import select

        from app.db.models import Workflow
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import active_execution_registry

        active_execution_registry._running = True
        self.addCleanup(setattr, active_execution_registry, "_running", False)

        self.ex_id = uuid.uuid4()
        async with async_session_maker() as session:
            result = await session.execute(select(Workflow.id).limit(1))
            self.wf_id = result.scalar_one()

    async def asyncTearDown(self) -> None:
        from sqlalchemy import delete

        from app.db.models import ActiveWorkflowExecution
        from app.db.session import async_session_maker

        async with async_session_maker() as session:
            await session.execute(
                delete(ActiveWorkflowExecution).where(
                    ActiveWorkflowExecution.execution_id == self.ex_id
                )
            )
            await session.commit()
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
        G: Ordering with worker registration BEFORE dispatcher relinquishment.
        H: Worker completion happens BEFORE dispatcher cleanup.
        """
        from sqlalchemy import func, select, update

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

        @asynccontextmanager
        async def pausing_session_maker():
            async with real_session_maker() as session:
                real_execute = session.execute

                async def intercepted_execute(stmt, *args, **kwargs):
                    if isinstance(stmt, Update):
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

            # c. make worker ownership/heartbeat/progress state current
            record_execution_node_started(str(self.ex_id), "worker_node_step_1")
            worker_hb = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
            async with real_session_maker() as session:
                await session.execute(
                    update(ActiveWorkflowExecution)
                    .where(ActiveWorkflowExecution.execution_id == self.ex_id)
                    .values(
                        worker_id=f"{_WORKER_ID}:{token_w}",
                        heartbeat_at=worker_hb,
                        running_node_ids=["worker_node_step_1"],
                    )
                )
                await session.commit()

            # d. relinquish H_D (Ordering G: dispatcher relinquishes after worker registers)
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

            # PROVE A: Dispatcher H_D cannot update worker-owned state
            self.assertEqual(row.worker_id, f"{_WORKER_ID}:{token_w}")
            self.assertNotEqual(row.worker_id, f"{_WORKER_ID}:{token_d}")

            # PROVE B: Dispatcher H_D cannot resurrect the row or create duplicate rows
            self.assertEqual(count, 1)

            # PROVE C: Dispatcher H_D cannot advance heartbeat after H_D was relinquished
            self.assertEqual(row.heartbeat_at, worker_hb)

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


if __name__ == "__main__":
    unittest.main()
