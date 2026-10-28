"""The node analytics rollup: what counts, how a batch is claimed, and how a tick paces itself."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.node_analytics_rollup import aggregate_node_rows

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
