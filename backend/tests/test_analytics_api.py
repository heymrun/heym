import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.analytics import (
    _default_bucket_delta_for_window,
    _resolve_time_window,
    get_analytics_metrics,
    get_analytics_stats,
)


class _ScalarSequenceResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _ExecuteResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarSequenceResult:
        return _ScalarSequenceResult(self._rows)


class AnalyticsTimeWindowTests(unittest.TestCase):
    def test_resolve_time_window_normalizes_explicit_bounds_to_utc(self) -> None:
        start_at = datetime(2026, 4, 13, 12, 0, tzinfo=timezone(timedelta(hours=2)))
        end_at = datetime(2026, 4, 13, 18, 0, tzinfo=timezone(timedelta(hours=2)))

        resolved_start, resolved_end = _resolve_time_window(
            "7d",
            start_at=start_at,
            end_at=end_at,
        )

        self.assertEqual(
            resolved_start,
            datetime(2026, 4, 13, 10, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            resolved_end,
            datetime(2026, 4, 13, 16, 0, tzinfo=timezone.utc),
        )

    def test_resolve_time_window_requires_both_bounds(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_time_window(
                "7d",
                start_at=datetime(2026, 4, 13, 10, 0, tzinfo=timezone.utc),
                end_at=None,
            )

    def test_default_bucket_delta_scales_with_window_size(self) -> None:
        base = datetime(2026, 4, 13, 10, 0, tzinfo=timezone.utc)

        self.assertEqual(
            _default_bucket_delta_for_window(base, base + timedelta(hours=12)),
            timedelta(hours=1),
        )
        self.assertEqual(
            _default_bucket_delta_for_window(base, base + timedelta(days=7)),
            timedelta(hours=6),
        )
        self.assertEqual(
            _default_bucket_delta_for_window(base, base + timedelta(days=30)),
            timedelta(days=1),
        )


class AnalyticsMetricsApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = MagicMock()
        self.user.id = uuid.uuid4()
        self.db = AsyncMock()

    async def test_metrics_supports_half_open_custom_selection_window(self) -> None:
        start_at = datetime(2026, 4, 10, 0, 0, tzinfo=timezone.utc)
        end_at = start_at + timedelta(hours=6)
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult([]),
                _ExecuteResult([]),
            ]
        )

        with patch(
            "app.api.analytics.get_accessible_workflow_ids",
            AsyncMock(return_value=[uuid.uuid4()]),
        ):
            response = await get_analytics_metrics(
                workflow_id=None,
                time_range="7d",
                bucket_size="1h",
                start_at=start_at,
                end_at=end_at,
                current_user=self.user,
                db=self.db,
            )

        self.assertEqual(len(response.time_buckets), 6)
        self.assertEqual(response.time_buckets[0], start_at.isoformat())
        self.assertEqual(response.time_buckets[-1], (start_at + timedelta(hours=5)).isoformat())

        snapshot_stmt = self.db.execute.call_args_list[0].args[0]
        snapshot_sql = str(snapshot_stmt.compile(dialect=postgresql.dialect())).lower()
        self.assertIn("workflow_analytics_snapshots.bucket_start >=", snapshot_sql)
        self.assertIn("workflow_analytics_snapshots.bucket_start <", snapshot_sql)

    async def test_stats_endpoint_rejects_partial_custom_range(self) -> None:
        with patch(
            "app.api.analytics.get_accessible_workflow_ids",
            AsyncMock(return_value=[uuid.uuid4()]),
        ):
            with self.assertRaises(HTTPException) as context:
                await get_analytics_stats(
                    workflow_id=None,
                    time_range="7d",
                    start_at=datetime(2026, 4, 10, 0, 0, tzinfo=timezone.utc),
                    end_at=None,
                    current_user=self.user,
                    db=self.db,
                )

        self.assertEqual(context.exception.status_code, 422)
        self.assertEqual(
            context.exception.detail,
            "Both start_at and end_at must be provided together",
        )
