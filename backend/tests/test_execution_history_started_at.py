"""History rows record when a run started, not when the row was written."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import (
    ActiveWorkflowExecution,
    ExecutionHistory,
    WorkflowRunQueue,
    execution_started_at,
    recorded_run_start,
    stamp_execution_history_start,
)
from app.db.session import async_session_maker
from tests.workflow_concurrency_fixtures import ConcurrencyPostgresCase

REQUESTED = datetime(2026, 10, 25, 13, 16, 44, tzinfo=timezone.utc)
FIRST_SPAN = datetime(2026, 10, 25, 13, 17, 4, 799000, tzinfo=timezone.utc)


def _span(started: datetime) -> dict:
    started_ms = started.timestamp() * 1000
    return {"metadata": {"started_at_ms": started_ms, "ended_at_ms": started_ms + 500}}


def _connection(found: datetime | None) -> MagicMock:
    connection = MagicMock()
    connection.execute.return_value.scalar.return_value = found
    return connection


class RecordedRunStartTests(unittest.TestCase):
    def test_the_first_span_is_the_start(self) -> None:
        later = FIRST_SPAN + timedelta(seconds=3)

        self.assertEqual(
            recorded_run_start([_span(later), _span(FIRST_SPAN)], 10_000.0), FIRST_SPAN
        )

    def test_without_spans_the_duration_is_taken_off_the_finish(self) -> None:
        before = datetime.now(timezone.utc)

        started = recorded_run_start([{"metadata": {"started_at_ms": 12.5}}], 10_000.0)

        self.assertLessEqual(started, before - timedelta(seconds=9.9))
        self.assertGreaterEqual(started, before - timedelta(seconds=11))


class StampExecutionHistoryStartTests(unittest.TestCase):
    def test_an_explicit_start_is_kept(self) -> None:
        row = ExecutionHistory(id=uuid.uuid4(), status="success", started_at=REQUESTED)
        connection = _connection(FIRST_SPAN)

        stamp_execution_history_start(None, connection, row)

        self.assertEqual(row.started_at, REQUESTED)
        connection.execute.assert_not_called()

    def test_a_requested_or_registered_start_wins_over_the_spans(self) -> None:
        row = ExecutionHistory(id=uuid.uuid4(), status="success", node_results=[_span(FIRST_SPAN)])

        stamp_execution_history_start(None, _connection(REQUESTED), row)

        self.assertEqual(row.started_at, REQUESTED)

    def test_without_either_the_first_span_is_used(self) -> None:
        row = ExecutionHistory(id=uuid.uuid4(), status="success", node_results=[_span(FIRST_SPAN)])

        stamp_execution_history_start(None, _connection(None), row)

        self.assertEqual(row.started_at, FIRST_SPAN)

    def test_a_row_without_an_id_skips_the_lookup(self) -> None:
        row = ExecutionHistory(status="success", node_results=[_span(FIRST_SPAN)])
        connection = _connection(REQUESTED)

        stamp_execution_history_start(None, connection, row)

        self.assertEqual(row.started_at, FIRST_SPAN)
        connection.execute.assert_not_called()


class ExecutionHistoryStartedAtPostgresTests(ConcurrencyPostgresCase):
    """Real inserts, through the ORM hook and through Core, as the run paths write them."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.addAsyncCleanup(self._remove_active_rows)

    async def _remove_active_rows(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                delete(ActiveWorkflowExecution).where(
                    ActiveWorkflowExecution.workflow_id == self.workflow_id
                )
            )
            await db.commit()

    async def _queue(self, execution_id: uuid.UUID) -> None:
        async with async_session_maker() as db:
            db.add(
                WorkflowRunQueue(
                    workflow_id=self.workflow_id,
                    execution_id=execution_id,
                    placement="anywhere",
                    status="done",
                    inputs={},
                    enqueued_at=REQUESTED,
                    not_after=REQUESTED + timedelta(minutes=5),
                )
            )
            await db.commit()

    async def _register(self, execution_id: uuid.UUID, started_at: datetime) -> None:
        async with async_session_maker() as db:
            db.add(
                ActiveWorkflowExecution(
                    execution_id=execution_id,
                    workflow_id=self.workflow_id,
                    worker_id="test-worker",
                    started_at=started_at,
                    heartbeat_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

    async def _orm_insert(self, execution_id: uuid.UUID, node_results: list) -> datetime:
        async with async_session_maker() as db:
            db.add(
                ExecutionHistory(
                    id=execution_id,
                    workflow_id=self.workflow_id,
                    status="success",
                    node_results=node_results,
                    execution_time_ms=10_000.0,
                )
            )
            await db.commit()
        return await self._stored_start(execution_id)

    async def _stored_start(self, execution_id: uuid.UUID) -> datetime:
        async with async_session_maker() as db:
            stored = await db.get(ExecutionHistory, execution_id)
            assert stored is not None
            return stored.started_at

    async def test_a_queued_run_starts_when_it_was_requested(self) -> None:
        execution_id = uuid.uuid4()
        await self._queue(execution_id)
        # A queued run registers when it is claimed, after it waited.
        await self._register(execution_id, FIRST_SPAN)

        started = await self._orm_insert(execution_id, [_span(FIRST_SPAN)])

        self.assertEqual(started, REQUESTED)

    async def test_a_recovered_run_keeps_its_first_attempt(self) -> None:
        execution_id = uuid.uuid4()
        first_attempt = FIRST_SPAN - timedelta(minutes=10)
        await self._register(execution_id, first_attempt)

        # The rerun after a restart records spans of its own, later than the first attempt.
        started = await self._orm_insert(execution_id, [_span(FIRST_SPAN)])

        self.assertEqual(started, first_attempt)

    async def test_an_unregistered_run_starts_at_its_first_span(self) -> None:
        started = await self._orm_insert(uuid.uuid4(), [_span(FIRST_SPAN)])

        self.assertEqual(started, FIRST_SPAN)

    async def test_a_core_insert_of_a_queued_run_uses_the_request_time(self) -> None:
        execution_id = uuid.uuid4()
        await self._queue(execution_id)
        async with async_session_maker() as db:
            await db.execute(
                pg_insert(ExecutionHistory).values(
                    id=execution_id,
                    workflow_id=self.workflow_id,
                    status="success",
                    node_results=[_span(FIRST_SPAN)],
                    execution_time_ms=10_000.0,
                    started_at=execution_started_at(execution_id, [_span(FIRST_SPAN)], 10_000.0),
                )
            )
            await db.commit()

        self.assertEqual(await self._stored_start(execution_id), REQUESTED)


if __name__ == "__main__":
    unittest.main()
