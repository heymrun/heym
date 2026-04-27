import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api.schedules import _get_schedule_events, fetch_schedule_events_for_user
from app.models.schemas import ScheduleEvent


class _WorkflowQueryResult:
    """Minimal async execute() result: result.scalars().all()."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> "_WorkflowQueryResult":
        return self

    def all(self) -> list[object]:
        return self._rows


def _make_workflow(nodes: list[dict], name: str = "Test WF") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), name=name, nodes=nodes)


def _cron_node(expr: str, active: bool = True) -> dict:
    return {
        "type": "cron",
        "id": str(uuid.uuid4()),
        "data": {"cronExpression": expr, "active": active},
    }


class TestGetScheduleEvents(unittest.IsolatedAsyncioTestCase):
    async def test_active_cron_returns_occurrences(self) -> None:
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        workflows = [_make_workflow([_cron_node("0 * * * *")])]
        events = await _get_schedule_events(workflows, start, end)
        self.assertEqual(len(events), 24)  # hours 00:00..23:00 inclusive (start boundary included)
        self.assertIsInstance(events[0], ScheduleEvent)

    async def test_inactive_cron_filtered_out(self) -> None:
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        workflows = [_make_workflow([_cron_node("0 * * * *", active=False)])]
        events = await _get_schedule_events(workflows, start, end)
        self.assertEqual(len(events), 0)

    async def test_no_cron_node_filtered_out(self) -> None:
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        workflows = [_make_workflow([{"type": "llm", "id": "n1", "data": {}}])]
        events = await _get_schedule_events(workflows, start, end)
        self.assertEqual(len(events), 0)

    async def test_multiple_workflows_merged(self) -> None:
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        workflows = [
            _make_workflow([_cron_node("0 6 * * *")], name="Morning"),
            _make_workflow([_cron_node("0 18 * * *")], name="Evening"),
        ]
        events = await _get_schedule_events(workflows, start, end)
        names = {e.workflow_name for e in events}
        self.assertEqual(names, {"Morning", "Evening"})
        self.assertEqual(len(events), 2)

    async def test_hourly_cron_day_range_returns_correct_count(self) -> None:
        # start=00:00, end=23:59:59 → hits at 00:00 .. 23:00 = 24 hits (start boundary included)
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        workflows = [_make_workflow([_cron_node("0 * * * *")])]
        events = await _get_schedule_events(workflows, start, end)
        self.assertEqual(len(events), 24)

    async def test_weekly_cron_week_range(self) -> None:
        # "0 9 * * 1" = every Monday at 09:00
        # 2026-04-20 is a Monday
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)  # Friday
        end = datetime(2026, 4, 24, 0, 0, 0, tzinfo=timezone.utc)  # next Friday
        workflows = [_make_workflow([_cron_node("0 9 * * 1")])]
        events = await _get_schedule_events(workflows, start, end)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].scheduled_at.weekday(), 0)  # Monday


class TestFetchScheduleEventsForUser(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_end_before_start(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        start = datetime(2026, 4, 20, tzinfo=timezone.utc)
        end = datetime(2026, 4, 19, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            await fetch_schedule_events_for_user(db, user, start, end, True)

    async def test_rejects_span_over_62_days(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 4, 1, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            await fetch_schedule_events_for_user(db, user, start, end, True)

    async def test_returns_events_for_mock_workflow(self) -> None:
        wf = MagicMock()
        wf.id = uuid.uuid4()
        wf.name = "Cron WF"
        wf.description = None
        wf.nodes = [_cron_node("0 6 * * *")]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_WorkflowQueryResult(rows=[wf]))
        user = MagicMock()
        user.id = uuid.uuid4()
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        resp = await fetch_schedule_events_for_user(db, user, start, end, include_shared=False)
        self.assertEqual(resp.total, 1)
        self.assertEqual(len(resp.events), 1)
        self.assertEqual(resp.events[0].workflow_name, "Cron WF")

    async def test_execute_not_called_when_range_invalid(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        start = datetime(2026, 4, 20, tzinfo=timezone.utc)
        end = start - timedelta(seconds=1)
        with self.assertRaises(ValueError):
            await fetch_schedule_events_for_user(db, user, start, end, True)
        db.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
