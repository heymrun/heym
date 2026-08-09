"""Registry must survive a single unwritable row or a transient database error.

A corrupt page or a lock timeout on `active_workflow_executions` used to abort the
whole sync transaction, which stopped every heartbeat on the worker, dropped queued
start/finish commands, and logged a traceback twice a second.
"""

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


if __name__ == "__main__":
    unittest.main()
