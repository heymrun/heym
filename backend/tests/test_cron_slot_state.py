import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.cron_slot_state import claim_cron_slot, cleanup_cron_slot_claims


def _session_returning(first_row: object | None) -> AsyncMock:
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False
    session.execute.return_value = SimpleNamespace(first=lambda: first_row)
    return session


class ClaimCronSlotTests(unittest.IsolatedAsyncioTestCase):
    SLOT = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)

    async def test_claim_wins_when_the_row_is_inserted(self) -> None:
        session = _session_returning((uuid.uuid4(),))

        with patch("app.services.cron_slot_state.async_session_maker", return_value=session):
            claimed = await claim_cron_slot(
                workflow_id=uuid.uuid4(),
                node_id="n1",
                slot_at=self.SLOT,
                worker_id="worker-38",
            )

        self.assertTrue(claimed)
        session.commit.assert_awaited_once()

    async def test_claim_loses_when_another_worker_already_owns_the_slot(self) -> None:
        """on_conflict_do_nothing returns no row: the slot is someone else's."""
        session = _session_returning(None)

        with patch("app.services.cron_slot_state.async_session_maker", return_value=session):
            claimed = await claim_cron_slot(
                workflow_id=uuid.uuid4(), node_id="n1", slot_at=self.SLOT
            )

        self.assertFalse(claimed)

    async def test_claim_fails_closed_on_database_error(self) -> None:
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.__aexit__.return_value = False
        session.execute.side_effect = RuntimeError("connection is closed")

        with patch("app.services.cron_slot_state.async_session_maker", return_value=session):
            claimed = await claim_cron_slot(
                workflow_id=uuid.uuid4(), node_id="n1", slot_at=self.SLOT
            )

        self.assertFalse(claimed)


class CleanupCronSlotClaimsTests(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_claims_older_than_the_retention_window(self) -> None:
        db = AsyncMock()
        db.execute.return_value = MagicMock(rowcount=3)

        deleted = await cleanup_cron_slot_claims(db, retention_days=7)

        self.assertEqual(deleted, 3)
        statement = db.execute.await_args.args[0]
        cutoff = statement.whereclause.right.value
        self.assertAlmostEqual(
            cutoff.timestamp(),
            (datetime.now(timezone.utc) - timedelta(days=7)).timestamp(),
            delta=5,
        )
