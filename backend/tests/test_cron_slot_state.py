import asyncio
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import delete, select

from app.db.models import CronCleanupClaim
from app.db.session import async_session_maker, engine
from app.services.cron_slot_state import (
    claim_cleanup_slot,
    claim_cron_slot,
    cleanup_cron_slot_claims,
    cleanup_old_cleanup_slot_claims,
)


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

    async def test_claim_returns_none_on_database_error(self) -> None:
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.__aexit__.return_value = False
        session.execute.side_effect = RuntimeError("connection is closed")

        with patch("app.services.cron_slot_state.async_session_maker", return_value=session):
            claimed = await claim_cron_slot(
                workflow_id=uuid.uuid4(), node_id="n1", slot_at=self.SLOT
            )

        self.assertIsNone(claimed)


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


class ClaimCleanupSlotTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_wins_when_the_row_is_inserted(self) -> None:
        session = _session_returning((uuid.uuid4(),))

        with patch("app.services.cron_slot_state.async_session_maker", return_value=session):
            claimed = await claim_cleanup_slot(
                job_name="scheduled_deletion_cleanup", slot_date="20990101", worker_id="worker-1"
            )

        self.assertTrue(claimed)
        session.commit.assert_awaited_once()

    async def test_claim_loses_when_another_worker_already_claimed_the_date(self) -> None:
        session = _session_returning(None)

        with patch("app.services.cron_slot_state.async_session_maker", return_value=session):
            claimed = await claim_cleanup_slot(
                job_name="scheduled_deletion_cleanup", slot_date="20990101"
            )

        self.assertFalse(claimed)

    async def test_claim_fails_closed_on_database_error(self) -> None:
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.__aexit__.return_value = False
        session.execute.side_effect = RuntimeError("connection is closed")

        with patch("app.services.cron_slot_state.async_session_maker", return_value=session):
            claimed = await claim_cleanup_slot(
                job_name="scheduled_deletion_cleanup", slot_date="20990101"
            )

        self.assertFalse(claimed)


class CleanupOldCleanupSlotClaimsTests(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_claims_older_than_the_retention_window(self) -> None:
        db = AsyncMock()
        db.execute.return_value = MagicMock(rowcount=2)

        deleted = await cleanup_old_cleanup_slot_claims(db, retention_days=7)

        self.assertEqual(deleted, 2)
        statement = db.execute.await_args.args[0]
        cutoff = statement.whereclause.right.value
        self.assertAlmostEqual(
            cutoff.timestamp(),
            (datetime.now(timezone.utc) - timedelta(days=7)).timestamp(),
            delta=5,
        )


class ClaimCleanupSlotRealPostgresTests(unittest.IsolatedAsyncioTestCase):
    """Proves the once-per-day guarantee holds across separate instances/connections,
    without relying on anything being held open on a pooled connection."""

    async def asyncSetUp(self) -> None:
        self.job_name = f"test_cleanup_job_{uuid.uuid4().hex[:8]}"
        self.slot_date = "20990101"

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                delete(CronCleanupClaim).where(CronCleanupClaim.job_name == self.job_name)
            )
            await db.commit()
        await engine.dispose()

    async def test_second_instance_cannot_claim_the_same_days_cleanup_twice(self) -> None:
        first = await claim_cleanup_slot(
            job_name=self.job_name, slot_date=self.slot_date, worker_id="instance-a"
        )
        second = await claim_cleanup_slot(
            job_name=self.job_name, slot_date=self.slot_date, worker_id="instance-b"
        )

        self.assertTrue(first)
        self.assertFalse(second)

    async def test_concurrent_claims_for_the_same_slot_only_one_wins(self) -> None:
        results = await asyncio.gather(
            *[
                claim_cleanup_slot(
                    job_name=self.job_name, slot_date=self.slot_date, worker_id=f"instance-{i}"
                )
                for i in range(10)
            ]
        )

        self.assertEqual(sum(1 for claimed in results if claimed), 1)

    async def test_claim_persists_after_the_claiming_connection_is_closed(self) -> None:
        # Closing a session only returns its connection to the pool, which is the
        # exact behavior that caused the original leak: a later caller can still get
        # that same physical connection back. Disposing the engine between the two
        # claims forces the second one onto a genuinely new connection, so this test
        # proves persistence survives the connection being gone, not merely the
        # session object - which is what a real leader handoff looks like.
        first = await claim_cleanup_slot(
            job_name=self.job_name, slot_date=self.slot_date, worker_id="instance-a"
        )
        self.assertTrue(first)

        async with async_session_maker() as db:
            result = await db.execute(
                select(CronCleanupClaim).where(CronCleanupClaim.job_name == self.job_name)
            )
            row = result.scalar_one()
            self.assertEqual(row.slot_date, self.slot_date)
            self.assertEqual(row.claimed_by, "instance-a")

        await engine.dispose()

        second = await claim_cleanup_slot(
            job_name=self.job_name, slot_date=self.slot_date, worker_id="instance-b"
        )
        self.assertFalse(second)
