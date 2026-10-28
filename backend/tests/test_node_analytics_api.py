"""GET /api/analytics/nodes: access, range validation and the response shape."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.analytics import get_node_type_analytics
from app.models.schemas import NodeTypeAnalyticsResponse

START = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)


class NodeTypeAnalyticsApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = MagicMock()
        self.user.id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()

    async def _call(self, db: AsyncMock, **overrides: object) -> NodeTypeAnalyticsResponse:
        params: dict[str, object] = {
            "workflow_id": None,
            "time_range": "7d",
            "bucket_size": "1h",
            "start_at": START,
            "end_at": START + timedelta(hours=6),
            "limit": 10,
            "current_user": self.user,
            "db": db,
        }
        params.update(overrides)
        with patch(
            "app.api.analytics.get_accessible_workflow_ids",
            AsyncMock(return_value=[self.workflow_id]),
        ):
            return await get_node_type_analytics(**params)

    async def test_an_inaccessible_workflow_is_forbidden(self) -> None:
        with self.assertRaises(HTTPException) as context:
            await self._call(AsyncMock(), workflow_id=uuid.uuid4())

        self.assertEqual(context.exception.status_code, 403)

    async def test_a_partial_range_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as context:
            await self._call(AsyncMock(), end_at=None)

        self.assertEqual(context.exception.status_code, 422)

    async def test_returns_buckets_and_rankings(self) -> None:
        rows = MagicMock()
        rows.all.return_value = [
            SimpleNamespace(
                node_type="agent",
                bucket_start=START + timedelta(hours=1),
                call_count=4,
                error_count=1,
                total_duration_ms=400.0,
            )
        ]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=rows)

        response = await self._call(db)

        self.assertEqual(len(response.time_buckets), 6)
        self.assertEqual(response.most_duration[0].node_type, "agent")
        self.assertEqual(response.most_duration[0].average, 100.0)
        self.assertIsNone(response.most_duration[0].values[0])
        self.assertEqual(response.most_duration[0].values[1], 100.0)
        self.assertEqual(response.most_errors[0].total, 1.0)
        self.assertEqual(response.most_calls[0].total, 4.0)
