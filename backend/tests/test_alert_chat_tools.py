import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api.ai_assistant import (
    DASHBOARD_CHAT_SYSTEM_PROMPT,
    DASHBOARD_CHAT_TOOLS,
    handle_get_alert_detail,
    handle_get_alert_events,
    handle_list_alerts,
)


def _tool_names():
    return {t["function"]["name"] for t in DASHBOARD_CHAT_TOOLS}


def _user():
    return SimpleNamespace(id=uuid.uuid4())


class TestAlertToolsRegistered(unittest.TestCase):
    def test_all_three_tools_are_declared(self):
        for name in ("list_alerts", "get_alert_detail", "get_alert_events"):
            self.assertIn(name, _tool_names())

    def test_get_alert_events_accepts_a_time_range(self):
        tool = next(t for t in DASHBOARD_CHAT_TOOLS if t["function"]["name"] == "get_alert_events")
        props = tool["function"]["parameters"]["properties"]
        self.assertIn("time_range", props)
        self.assertEqual(props["time_range"]["enum"], ["24h", "7d", "30d", "all"])

    def test_system_prompt_instructs_the_model_to_cite_the_window(self):
        self.assertIn("get_alert_events", DASHBOARD_CHAT_SYSTEM_PROMPT)
        self.assertIn("observed value", DASHBOARD_CHAT_SYSTEM_PROMPT)


class TestListAlertsHandler(unittest.IsolatedAsyncioTestCase):
    async def test_returns_condition_summary_and_state(self):
        row = SimpleNamespace(
            id=uuid.uuid4(),
            name="Invoice failures",
            alert_type="error_threshold",
            scope="workflow",
            workflow_id=uuid.uuid4(),
            config={"window_minutes": 10, "threshold_count": 5},
            enabled=True,
            state="triggered",
            last_triggered_at=None,
            last_observed_value=12.0,
            created_at=None,
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        payload = await handle_list_alerts(db, _user(), {})

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["alerts"][0]["condition"], "5+ errors in 10m")
        self.assertEqual(payload["alerts"][0]["state"], "triggered")
        self.assertEqual(payload["alerts"][0]["last_observed_value"], 12.0)

    async def test_empty_result_is_reported_as_zero(self):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        payload = await handle_list_alerts(db, _user(), {})
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["alerts"], [])


class TestGetAlertDetailHandler(unittest.IsolatedAsyncioTestCase):
    async def test_missing_alert_id_is_an_error(self):
        payload = await handle_get_alert_detail(MagicMock(), _user(), {})
        self.assertIn("error", payload)

    async def test_inaccessible_alert_is_an_error(self):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        payload = await handle_get_alert_detail(db, _user(), {"alert_id": str(uuid.uuid4())})
        self.assertIn("error", payload)

    async def test_returns_config_and_seven_day_firing_count(self):
        alert = SimpleNamespace(
            id=uuid.uuid4(),
            name="Cost guard",
            description=None,
            alert_type="token_cost",
            scope="system",
            workflow_id=None,
            config={"window_minutes": 60, "metric": "usd", "threshold": 25},
            enabled=True,
            state="ok",
            renotify_mode="on_recovery",
            cooldown_minutes=None,
            notify_workflow_id=None,
            last_triggered_at=None,
            last_observed_value=3.5,
        )
        alert_result = MagicMock()
        alert_result.scalar_one_or_none.return_value = alert
        count_result = MagicMock()
        count_result.scalar.return_value = 4
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[alert_result, count_result])

        payload = await handle_get_alert_detail(db, _user(), {"alert_id": str(alert.id)})

        self.assertEqual(payload["condition"], "25 USD spent in 60m")
        self.assertEqual(payload["firings_last_7_days"], 4)
        self.assertEqual(payload["config"]["metric"], "usd")


class TestGetAlertEventsHandler(unittest.IsolatedAsyncioTestCase):
    def _event(self):
        now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        return SimpleNamespace(
            id=uuid.uuid4(),
            alert_id=uuid.uuid4(),
            triggered_at=now,
            observed_value=12.0,
            threshold_value=5.0,
            window_start=now,
            window_end=now,
            context={"error_count": 12},
            notify_status="skipped",
        )

    async def test_returns_observed_versus_threshold_and_context(self):
        event = self._event()
        result = MagicMock()
        result.all.return_value = [(event, "Invoice failures", "error_threshold")]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        payload = await handle_get_alert_events(db, _user(), {})

        self.assertEqual(payload["count"], 1)
        entry = payload["events"][0]
        self.assertEqual(entry["observed_value"], 12.0)
        self.assertEqual(entry["threshold_value"], 5.0)
        self.assertEqual(entry["context"]["error_count"], 12)
        self.assertEqual(entry["alert_name"], "Invoice failures")

    async def test_limit_is_capped_at_fifty(self):
        captured = {}

        async def _capture(statement):
            captured["statement"] = statement
            result = MagicMock()
            result.all.return_value = []
            return result

        db = MagicMock()
        db.execute = _capture
        await handle_get_alert_events(db, _user(), {"limit": 5000})
        self.assertEqual(captured["statement"]._limit, 50)

    async def test_default_time_range_is_seven_days(self):
        result = MagicMock()
        result.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        payload = await handle_get_alert_events(db, _user(), {})
        self.assertEqual(payload["time_range"], "7d")
