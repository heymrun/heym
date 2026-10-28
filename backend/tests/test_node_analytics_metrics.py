"""Node type rankings for the Analytics tab, read from node_analytics_snapshots."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.services.analytics_metrics import bucket_keys
from app.services.node_analytics_metrics import (
    NodeTypeAnalytics,
    compute_node_type_analytics,
    rank_node_types,
)

BASE = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)
HOURLY = timedelta(hours=1)


def _row(
    node_type: str,
    hour: int,
    *,
    calls: int = 0,
    errors: int = 0,
    duration: float = 0.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        node_type=node_type,
        bucket_start=BASE + timedelta(hours=hour),
        call_count=calls,
        error_count=errors,
        total_duration_ms=duration,
    )


def _rank(
    rows: list[SimpleNamespace],
    *,
    hours: int = 2,
    delta: timedelta = HOURLY,
    limit: int = 10,
) -> NodeTypeAnalytics:
    buckets = bucket_keys(BASE, BASE + timedelta(hours=hours), delta)
    return rank_node_types(rows, time_buckets=buckets, bucket_delta=delta, limit=limit)


class BucketKeysTests(unittest.TestCase):
    def test_lists_every_bucket_start_in_the_half_open_window(self) -> None:
        self.assertEqual(
            bucket_keys(BASE, BASE + timedelta(hours=12), timedelta(hours=6)),
            [BASE.isoformat(), (BASE + timedelta(hours=6)).isoformat()],
        )


class RankNodeTypesTests(unittest.TestCase):
    def test_hourly_rows_fold_into_wider_buckets(self) -> None:
        result = _rank(
            [_row("set", 1, calls=2), _row("set", 5, calls=1), _row("set", 7, calls=1)],
            hours=12,
            delta=timedelta(hours=6),
        )

        self.assertEqual(result.most_calls[0].values, [3.0, 1.0])
        self.assertEqual(result.most_calls[0].total, 4.0)

    def test_duration_ranks_by_total_and_plots_the_average_per_call(self) -> None:
        result = _rank(
            [
                _row("agent", 0, calls=10, duration=1000.0),
                _row("code", 0, calls=1, duration=600.0),
                _row("code", 1, calls=1, duration=300.0),
            ]
        )

        self.assertEqual([s.node_type for s in result.most_duration], ["agent", "code"])
        agent, code = result.most_duration
        self.assertEqual(agent.total, 1000.0)
        self.assertEqual(agent.average, 100.0)
        self.assertEqual(agent.values, [100.0, None])
        self.assertEqual(code.average, 450.0)
        self.assertEqual(code.values, [600.0, 300.0])

    def test_errors_list_only_types_that_failed(self) -> None:
        result = _rank([_row("agent", 0, calls=3, errors=0), _row("http", 0, calls=2, errors=2)])

        self.assertEqual([s.node_type for s in result.most_errors], ["http"])
        self.assertIsNone(result.most_errors[0].average)
        self.assertEqual(result.most_errors[0].values, [2.0, 0.0])

    def test_each_ranking_keeps_the_top_limit_with_a_name_tie_break(self) -> None:
        result = _rank(
            [_row("b", 0, calls=5), _row("a", 0, calls=5), _row("c", 0, calls=9)], limit=2
        )

        self.assertEqual([s.node_type for s in result.most_calls], ["c", "a"])

    def test_rows_outside_the_window_are_ignored(self) -> None:
        result = _rank([_row("set", 5, calls=4)])

        self.assertEqual(result.most_calls, [])

    def test_no_rows_still_returns_the_buckets(self) -> None:
        result = _rank([])

        self.assertEqual(len(result.time_buckets), 2)
        self.assertEqual(result.most_duration, [])
        self.assertEqual(result.most_errors, [])
        self.assertEqual(result.most_calls, [])


class ComputeNodeTypeAnalyticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_nothing_accessible_reads_nothing(self) -> None:
        db = AsyncMock()

        result = await compute_node_type_analytics(
            db,
            accessible_workflow_ids=[],
            workflow_id=None,
            since=BASE,
            until=BASE + timedelta(hours=2),
            bucket_delta=HOURLY,
        )

        db.execute.assert_not_awaited()
        self.assertEqual(len(result.time_buckets), 2)

    async def test_an_inaccessible_workflow_reads_nothing(self) -> None:
        db = AsyncMock()

        await compute_node_type_analytics(
            db,
            accessible_workflow_ids=[uuid.uuid4()],
            workflow_id=uuid.uuid4(),
            since=BASE,
            until=BASE + timedelta(hours=2),
            bucket_delta=HOURLY,
        )

        db.execute.assert_not_awaited()

    async def test_one_grouped_query_over_the_scope_and_window(self) -> None:
        rows = MagicMock()
        rows.all.return_value = [_row("set", 0, calls=1)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=rows)
        workflow_id = uuid.uuid4()

        result = await compute_node_type_analytics(
            db,
            accessible_workflow_ids=[workflow_id],
            workflow_id=workflow_id,
            since=BASE,
            until=BASE + timedelta(hours=2),
            bucket_delta=HOURLY,
        )

        sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn("node_analytics_snapshots.workflow_id = ", sql)
        self.assertIn("node_analytics_snapshots.bucket_start >= ", sql)
        self.assertIn("node_analytics_snapshots.bucket_start < ", sql)
        self.assertIn(
            "GROUP BY node_analytics_snapshots.node_type, node_analytics_snapshots.bucket_start",
            sql,
        )
        self.assertEqual(result.most_calls[0].node_type, "set")
