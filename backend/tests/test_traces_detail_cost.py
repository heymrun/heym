import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.traces import get_trace


def _trace(model: str | None) -> MagicMock:
    trace = MagicMock()
    trace.id = uuid.uuid4()
    trace.created_at = datetime(2026, 9, 25, tzinfo=timezone.utc)
    trace.source = "workflow"
    trace.request_type = "chat.completions"
    trace.provider = "zai"
    trace.model = model
    trace.credential_id = uuid.uuid4()
    trace.router_credential_id = None
    trace.router_label = None
    trace.workflow_id = uuid.uuid4()
    trace.node_id = "agent1"
    trace.node_label = "humanizeAgent"
    trace.error = None
    trace.elapsed_ms = 32823.42
    trace.prompt_tokens = 107
    trace.completion_tokens = 5534
    trace.total_tokens = 5641
    trace.request = {"messages": []}
    trace.response = {"text": "ok"}
    return trace


class TraceDetailCostTests(unittest.IsolatedAsyncioTestCase):
    async def _get(self, trace: MagicMock, resolved: tuple[Decimal | None, bool]):
        user = MagicMock()
        user.id = uuid.uuid4()
        row = MagicMock()
        row.first = MagicMock(return_value=(trace, "Z.ai", "Support flow"))
        db = AsyncMock()
        db.execute = AsyncMock(return_value=row)
        with patch("app.api.traces.resolve_costs_for_user", new_callable=AsyncMock) as resolve_mock:
            resolve_mock.return_value = [resolved]
            detail = await get_trace(trace_id=trace.id, current_user=user, db=db)
        return detail, resolve_mock, db, user

    async def test_detail_includes_cost_resolved_like_the_list(self):
        detail, resolve_mock, db, user = await self._get(
            _trace("glm-5.3-flash"), (Decimal("0.0042"), True)
        )

        resolve_mock.assert_awaited_once_with(db, user.id, [("glm-5.3-flash", 107, 5534)])
        self.assertEqual(detail.cost_usd, Decimal("0.0042"))
        self.assertTrue(detail.is_priced)

    async def test_detail_of_unpriced_model_has_no_cost(self):
        detail, resolve_mock, db, user = await self._get(_trace(None), (None, False))

        resolve_mock.assert_awaited_once_with(db, user.id, [("", 107, 5534)])
        self.assertIsNone(detail.cost_usd)
        self.assertFalse(detail.is_priced)
