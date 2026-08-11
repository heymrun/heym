import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.services.alerts import evaluator


class TestClaimDueAlerts(unittest.IsolatedAsyncioTestCase):
    async def test_claim_advances_next_check_at_and_commits(self):
        alert = SimpleNamespace(id=uuid.uuid4(), check_interval_seconds=60)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [alert]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        claimed = await evaluator.claim_due_alerts(db, now=datetime.now(timezone.utc))

        self.assertEqual(claimed, [alert])
        db.commit.assert_awaited_once()
        self.assertEqual(db.execute.await_count, 1)

    async def test_no_due_alerts_returns_empty(self):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        claimed = await evaluator.claim_due_alerts(db, now=datetime.now(timezone.utc))
        self.assertEqual(claimed, [])

    async def test_claim_statement_compiles_for_postgres_with_skip_locked(self):
        """The claim is the duplicate-fire defense; verify the SQL it actually emits."""
        captured: dict = {}

        async def _capture(statement):
            captured["statement"] = statement
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            return result

        db = MagicMock()
        db.execute = _capture
        db.commit = AsyncMock()

        await evaluator.claim_due_alerts(db, now=datetime.now(timezone.utc))

        sql = str(
            captured["statement"].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}
            )
        )
        self.assertIn("UPDATE alerts", sql)
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertIn("next_check_at", sql)
        self.assertIn("last_evaluated_at", sql)
        self.assertIn("RETURNING", sql)
        self.assertIn("LIMIT", sql)

    async def test_claim_only_selects_enabled_alerts(self):
        captured: dict = {}

        async def _capture(statement):
            captured["statement"] = statement
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            return result

        db = MagicMock()
        db.execute = _capture
        db.commit = AsyncMock()

        await evaluator.claim_due_alerts(db, now=datetime.now(timezone.utc))

        sql = str(
            captured["statement"].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn("enabled IS true", sql)

    async def test_batch_size_is_capped(self):
        self.assertEqual(evaluator.CLAIM_BATCH_SIZE, 50)
