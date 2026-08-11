import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.services.cron_scheduler import CronScheduler

MODULE = "app.services.cron_scheduler"


class TestSchedulerAlertPasses(unittest.IsolatedAsyncioTestCase):
    async def test_check_alerts_delegates_to_the_evaluator(self):
        scheduler = CronScheduler()
        with patch(f"{MODULE}.evaluate_due_alerts", new=AsyncMock(return_value=2)) as evaluate:
            await scheduler._check_alerts()
        evaluate.assert_awaited_once()

    async def test_check_alerts_swallows_errors(self):
        """One bad alert pass must never stop the cron loop."""
        scheduler = CronScheduler()
        with patch(
            f"{MODULE}.evaluate_due_alerts", new=AsyncMock(side_effect=RuntimeError("db down"))
        ):
            await scheduler._check_alerts()  # must not raise

    async def test_event_cleanup_runs_once_per_day(self):
        scheduler = CronScheduler()
        scheduler._last_alert_event_cleanup_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with patch(f"{MODULE}.cleanup_old_alert_events", new=AsyncMock()) as cleanup:
            await scheduler._check_alert_event_cleanup()
        cleanup.assert_not_awaited()

    async def test_event_cleanup_runs_on_a_new_day(self):
        scheduler = CronScheduler()
        scheduler._last_alert_event_cleanup_date = "2000-01-01"
        with patch(f"{MODULE}.cleanup_old_alert_events", new=AsyncMock(return_value=0)) as cleanup:
            await scheduler._check_alert_event_cleanup()
        cleanup.assert_awaited_once()

    async def test_event_cleanup_swallows_errors(self):
        scheduler = CronScheduler()
        scheduler._last_alert_event_cleanup_date = "2000-01-01"
        with patch(
            f"{MODULE}.cleanup_old_alert_events", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            await scheduler._check_alert_event_cleanup()  # must not raise

    def test_scheduler_initialises_the_cleanup_marker(self):
        self.assertIsNone(CronScheduler()._last_alert_event_cleanup_date)
