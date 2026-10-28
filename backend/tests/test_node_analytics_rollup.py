"""The node analytics rollup: what counts, how a batch is claimed, and how a tick paces itself."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

from app.services import node_analytics_rollup
from app.services.node_analytics_rollup import (
    MAX_BATCHES_PER_TICK,
    ROLLUP_BATCH_SIZE,
    aggregate_node_rows,
    pending_on_first_write,
    roll_up_node_analytics,
    roll_up_node_analytics_batch,
)
from app.services.workflow_executor import ExecutionResult

HOUR = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)
WORKFLOW = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _row(
    node_type: str | None,
    status: str | None,
    duration: str | None = "10",
    *,
    workflow_id: uuid.UUID = WORKFLOW,
    started_at: datetime | None = HOUR + timedelta(minutes=5),
) -> SimpleNamespace:
    return SimpleNamespace(
        workflow_id=workflow_id,
        started_at=started_at,
        node_type=node_type,
        status=status,
        execution_time_ms=duration,
    )


class AggregateNodeRowsTests(unittest.TestCase):
    def test_counts_calls_errors_and_duration_per_type_and_hour(self) -> None:
        deltas = aggregate_node_rows(
            [
                _row("agent", "success", "120.5"),
                _row("agent", "error", "30"),
                _row("httpRequest", "success", "5"),
            ]
        )

        by_type = {delta.node_type: delta for delta in deltas}
        self.assertEqual(by_type["agent"].call_count, 2)
        self.assertEqual(by_type["agent"].error_count, 1)
        self.assertAlmostEqual(by_type["agent"].total_duration_ms, 150.5)
        self.assertEqual(by_type["agent"].bucket_start, HOUR)
        self.assertEqual(by_type["httpRequest"].call_count, 1)

    def test_skipped_pending_and_untyped_results_are_not_calls(self) -> None:
        deltas = aggregate_node_rows(
            [
                _row("agent", "skipped"),
                _row("agent", "pending"),
                _row("agent", None),
                _row(None, "success"),
                _row("  ", "success"),
                _row("agent", "success", started_at=None),
            ]
        )

        self.assertEqual(deltas, [])

    def test_timeout_counts_as_an_error_and_cancelled_as_a_call(self) -> None:
        deltas = aggregate_node_rows([_row("code", "timeout"), _row("code", "cancelled")])

        self.assertEqual(deltas[0].call_count, 2)
        self.assertEqual(deltas[0].error_count, 1)

    def test_durations_that_are_not_finite_non_negative_numbers_add_nothing(self) -> None:
        deltas = aggregate_node_rows(
            [
                _row("set", "success", None),
                _row("set", "success", "fast"),
                _row("set", "success", "-4"),
                _row("set", "success", "NaN"),
                _row("set", "success", "Infinity"),
                _row("set", "success", "true"),
                _row("set", "success", "7"),
            ]
        )

        self.assertEqual(deltas[0].call_count, 7)
        self.assertEqual(deltas[0].total_duration_ms, 7.0)

    def test_a_node_repeated_in_a_loop_counts_every_time(self) -> None:
        deltas = aggregate_node_rows([_row("set", "success") for _ in range(3)])

        self.assertEqual(deltas[0].call_count, 3)

    def test_runs_in_different_hours_and_workflows_stay_apart_in_a_stable_order(self) -> None:
        other = uuid.UUID("00000000-0000-0000-0000-000000000002")
        deltas = aggregate_node_rows(
            [
                _row("set", "success", workflow_id=other),
                _row("set", "success", started_at=HOUR + timedelta(hours=1, minutes=1)),
                _row("agent", "success"),
            ]
        )

        self.assertEqual(
            [(d.workflow_id, d.node_type, d.bucket_start) for d in deltas],
            [
                (WORKFLOW, "agent", HOUR),
                (WORKFLOW, "set", HOUR + timedelta(hours=1)),
                (other, "set", HOUR),
            ],
        )


class _Scalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(
        self, *, rows: list[object] | None = None, ids: list[object] | None = None
    ) -> None:
        self._rows = rows or []
        self._ids = ids or []

    def all(self) -> list[object]:
        return self._rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._ids)


def _sql(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


class RollUpBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_claims_only_finished_pending_runs_without_waiting_on_locks(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_Result(ids=[]))

        claimed = await roll_up_node_analytics_batch(db)

        self.assertEqual(claimed, 0)
        claim_sql = _sql(db.execute.await_args_list[0].args[0])
        self.assertIn("WHERE execution_history.node_analytics_pending AND", claim_sql)
        self.assertIn("execution_history.status NOT IN", claim_sql)
        self.assertIn("ORDER BY execution_history.started_at", claim_sql)
        self.assertIn("FOR UPDATE SKIP LOCKED", claim_sql)
        db.commit.assert_not_awaited()

    async def test_upserts_the_deltas_and_clears_the_marker_in_one_transaction(self) -> None:
        run_id = uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _Result(ids=[run_id]),
                _Result(rows=[_row("agent", "success", "12"), _row("agent", "error", "3")]),
                _Result(),
                _Result(),
            ]
        )

        claimed = await roll_up_node_analytics_batch(db)

        self.assertEqual(claimed, 1)
        statements = [_sql(call.args[0]) for call in db.execute.await_args_list]
        self.assertIn("json_array_elements", statements[1])
        self.assertIn("json_typeof(execution_history.node_results)", statements[1])
        self.assertIn("INSERT INTO node_analytics_snapshots", statements[2])
        self.assertIn(
            "ON CONFLICT ON CONSTRAINT uq_node_analytics_snapshot_scope DO UPDATE", statements[2]
        )
        self.assertIn("node_analytics_snapshots.call_count + excluded.call_count", statements[2])
        self.assertIn("UPDATE execution_history SET node_analytics_pending", statements[3])
        db.commit.assert_awaited_once()

    async def test_runs_without_countable_nodes_still_leave_the_queue(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_Result(ids=[uuid.uuid4()]), _Result(rows=[]), _Result()]
        )

        claimed = await roll_up_node_analytics_batch(db)

        self.assertEqual(claimed, 1)
        self.assertEqual(db.execute.await_count, 3)
        self.assertIn("UPDATE execution_history", _sql(db.execute.await_args_list[2].args[0]))
        db.commit.assert_awaited_once()


class RollUpTickTests(unittest.IsolatedAsyncioTestCase):
    def _factory(self) -> MagicMock:
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        return factory

    async def test_stops_after_a_short_batch(self) -> None:
        batch = AsyncMock(side_effect=[ROLLUP_BATCH_SIZE, 37])
        with (
            patch.object(node_analytics_rollup, "async_session_maker", self._factory()),
            patch.object(node_analytics_rollup, "roll_up_node_analytics_batch", batch),
        ):
            counted = await roll_up_node_analytics()

        self.assertEqual(counted, ROLLUP_BATCH_SIZE + 37)
        self.assertEqual(batch.await_count, 2)

    async def test_a_tick_never_runs_more_than_its_batch_budget(self) -> None:
        batch = AsyncMock(return_value=ROLLUP_BATCH_SIZE)
        with (
            patch.object(node_analytics_rollup, "async_session_maker", self._factory()),
            patch.object(node_analytics_rollup, "roll_up_node_analytics_batch", batch),
        ):
            await roll_up_node_analytics()

        self.assertEqual(batch.await_count, MAX_BATCHES_PER_TICK)


class PendingOnFirstWriteTests(unittest.TestCase):
    def test_a_run_with_downstream_work_waits_for_its_finalizer(self) -> None:
        result = ExecutionResult(
            workflow_id=uuid.uuid4(), status="success", outputs={}, execution_time_ms=1.0
        )
        result._allow_downstream_pending = [MagicMock()]

        self.assertFalse(pending_on_first_write(result))

    def test_any_other_run_is_pending_right_away(self) -> None:
        result = ExecutionResult(
            workflow_id=uuid.uuid4(), status="success", outputs={}, execution_time_ms=1.0
        )

        self.assertTrue(pending_on_first_write(result))
        self.assertTrue(pending_on_first_write(SimpleNamespace(status="success")))
