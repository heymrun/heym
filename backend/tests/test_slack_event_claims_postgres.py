"""A Slack event is handled once per scope, whichever worker receives the retry."""

import asyncio
import unittest
import uuid

from sqlalchemy import delete, text

from app.db.models import CronCleanupClaim
from app.db.session import async_session_maker, engine
from app.services.slack_event_claims import claim_slack_event


class SlackEventClaimTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        try:
            async with asyncio.timeout(10):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            await engine.dispose()
            self.skipTest(f"PostgreSQL is unavailable ({type(exc).__name__})")
        self.event_id = "Ev" + uuid.uuid4().hex[:10]
        self.addAsyncCleanup(self._cleanup)

    async def _cleanup(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                delete(CronCleanupClaim).where(CronCleanupClaim.job_name.like("slack-event:%"))
            )
            await db.commit()
        await engine.dispose()

    async def test_a_retry_of_the_same_event_is_not_handled_again(self) -> None:
        self.assertTrue(await claim_slack_event(self.event_id, "credential:c1"))
        self.assertFalse(await claim_slack_event(self.event_id, "credential:c1"))

    async def test_concurrent_deliveries_are_handled_once(self) -> None:
        results = await asyncio.gather(
            *(claim_slack_event(self.event_id, "node:n1") for _ in range(8))
        )
        self.assertEqual(sorted(results), [False] * 7 + [True])

    async def test_scopes_and_events_without_an_id_are_independent(self) -> None:
        self.assertTrue(await claim_slack_event(self.event_id, "node:n1"))
        self.assertTrue(await claim_slack_event(self.event_id, "node:n2"))
        self.assertTrue(await claim_slack_event(None, "node:n1"))
        self.assertTrue(await claim_slack_event(None, "node:n1"))
