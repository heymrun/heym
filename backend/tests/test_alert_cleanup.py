import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.services.alerts.cleanup import ALERT_EVENT_RETENTION_DAYS, cleanup_old_alert_events


class TestAlertEventCleanup(unittest.IsolatedAsyncioTestCase):
    def test_retention_is_ninety_days(self):
        self.assertEqual(ALERT_EVENT_RETENTION_DAYS, 90)

    async def test_deletes_and_reports_row_count(self):
        result = MagicMock()
        result.rowcount = 14
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        deleted = await cleanup_old_alert_events(db, now=datetime(2026, 8, 9, tzinfo=timezone.utc))

        self.assertEqual(deleted, 14)
        db.commit.assert_awaited_once()

    async def test_cutoff_is_now_minus_retention(self):
        captured: dict = {}

        async def _capture(statement):
            captured["statement"] = statement
            result = MagicMock()
            result.rowcount = 0
            return result

        db = MagicMock()
        db.execute = _capture
        db.commit = AsyncMock()

        now = datetime(2026, 8, 9, tzinfo=timezone.utc)
        await cleanup_old_alert_events(db, now=now)

        rendered = str(
            captured["statement"].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        expected_cutoff = (now - timedelta(days=ALERT_EVENT_RETENTION_DAYS)).strftime("%Y-%m-%d")
        self.assertIn("DELETE FROM alert_events", rendered)
        self.assertIn(expected_cutoff, rendered)

    async def test_zero_rowcount_is_handled(self):
        result = MagicMock()
        result.rowcount = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        deleted = await cleanup_old_alert_events(db)
        self.assertEqual(deleted, 0)
