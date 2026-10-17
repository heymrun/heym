"""Snapshot store against real PostgreSQL: one poll per interval, one consumer per change.

Requires a reachable PostgreSQL with migrations applied (see AGENTS.md, PostgreSQL
Integration Tests).
"""

import asyncio
import unittest
import uuid

from sqlalchemy import delete, func, update

from app.services.google_triggers.events import ItemWrite
from app.services.google_triggers.state_store import TriggerStateStore


class TriggerStateStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from app.db.models import User, Workflow
        from app.db.session import async_session_maker, engine

        await engine.dispose()
        self.store = TriggerStateStore()
        self.user_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        # A node type of its own, so delete_except never touches rows of tests running in
        # parallel against the same database.
        self.node_type = f"testTrigger{self.workflow_id.hex[:8]}"
        async with async_session_maker() as session:
            session.add(
                User(
                    id=self.user_id,
                    email=f"trigger_state_{self.user_id.hex[:8]}@example.com",
                    hashed_password="test_hashed_password",
                    name="Trigger State",
                )
            )
            session.add(
                Workflow(
                    id=self.workflow_id,
                    name="Trigger state",
                    owner_id=self.user_id,
                    nodes=[],
                    edges=[],
                )
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        from app.db.models import User, Workflow
        from app.db.session import async_session_maker, engine

        async with async_session_maker() as session:
            await session.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            await session.execute(delete(User).where(User.id == self.user_id))
            await session.commit()
        await engine.dispose()

    async def _baseline(self, items: dict | None = None) -> bool:
        return await self.store.insert_baseline(
            workflow_id=self.workflow_id,
            node_id="n1",
            node_type=self.node_type,
            scope_fingerprint="scope",
            key_id="key",
            items={"a": {"r": 2, "c": ["x"]}} if items is None else items,
            poll_minutes=1,
        )

    async def _make_due(self) -> None:
        from app.db.models import TriggerPollState
        from app.db.session import async_session_maker

        async with async_session_maker() as session:
            await session.execute(
                update(TriggerPollState)
                .where(TriggerPollState.workflow_id == self.workflow_id)
                .values(next_poll_at=func.now() - func.make_interval(0, 0, 0, 0, 0, 1))
            )
            await session.commit()

    async def _claim(self):
        return await self.store.claim(self.workflow_id, "n1", 1)

    async def test_a_node_without_state_needs_a_baseline(self) -> None:
        claim = await self._claim()
        self.assertTrue(claim.due)
        self.assertIsNone(claim.poll)

    async def test_a_fresh_baseline_is_not_due_again_yet(self) -> None:
        self.assertTrue(await self._baseline())
        self.assertFalse((await self._claim()).due)

    async def test_concurrent_baselines_record_one(self) -> None:
        results = await asyncio.gather(self._baseline(), self._baseline())
        self.assertEqual(sorted(results), [False, True])

    async def test_concurrent_claims_poll_once(self) -> None:
        await self._baseline()
        await self._make_due()
        claims = await asyncio.gather(self._claim(), self._claim())
        polls = [claim.poll for claim in claims if claim.poll is not None]
        self.assertEqual(len(polls), 1)
        self.assertEqual(polls[0].items, {"a": {"r": 2, "c": ["x"]}})
        self.assertEqual(polls[0].version, 0)

    async def test_one_consumer_wins_a_change(self) -> None:
        await self._baseline()
        await self._make_due()
        poll = (await self._claim()).poll
        results = await asyncio.gather(
            self.store.consume(poll.state_id, poll.version, [ItemWrite("b", {"r": 3, "c": ["1"]})]),
            self.store.consume(poll.state_id, poll.version, [ItemWrite("b", {"r": 3, "c": ["2"]})]),
        )
        self.assertEqual(sorted(results), [False, True])
        await self._make_due()
        after = (await self._claim()).poll
        self.assertEqual(after.version, 1)
        self.assertIn("b", after.items)

    async def test_revert_restores_the_previous_item(self) -> None:
        await self._baseline()
        await self._make_due()
        poll = (await self._claim()).poll
        old = poll.items["a"]
        self.assertTrue(
            await self.store.consume(poll.state_id, 0, [ItemWrite("a", {"r": 2, "c": ["y"]})])
        )
        self.assertTrue(await self.store.consume(poll.state_id, 1, [ItemWrite("a", old)]))
        await self._make_due()
        after = (await self._claim()).poll
        self.assertEqual(after.items["a"], old)
        self.assertEqual(after.version, 2)

    async def test_a_delete_write_removes_the_item(self) -> None:
        await self._baseline()
        await self._make_due()
        poll = (await self._claim()).poll
        self.assertTrue(await self.store.consume(poll.state_id, 0, [ItemWrite("a", None)]))
        await self._make_due()
        self.assertEqual((await self._claim()).poll.items, {})

    async def test_reset_baseline_replaces_items_and_fingerprint(self) -> None:
        await self._baseline()
        await self._make_due()
        poll = (await self._claim()).poll
        self.assertFalse(
            await self.store.reset_baseline(
                poll.state_id, 7, scope_fingerprint="other", key_id="key", items={}
            )
        )
        self.assertTrue(
            await self.store.reset_baseline(
                poll.state_id,
                0,
                scope_fingerprint="other",
                key_id="key2",
                items={"z": {"r": 9, "c": []}},
            )
        )
        await self._make_due()
        after = (await self._claim()).poll
        self.assertEqual(after.scope_fingerprint, "other")
        self.assertEqual(after.key_id, "key2")
        self.assertEqual(after.items, {"z": {"r": 9, "c": []}})

    async def test_delete_except_drops_states_that_are_not_kept(self) -> None:
        await self._baseline()
        removed = await self.store.delete_except((self.node_type,), set())
        self.assertEqual(removed, 1)
        claim = await self._claim()
        self.assertTrue(claim.due)
        self.assertIsNone(claim.poll)

    async def test_delete_except_keeps_listed_states(self) -> None:
        await self._baseline()
        removed = await self.store.delete_except((self.node_type,), {(self.workflow_id, "n1")})
        self.assertEqual(removed, 0)


if __name__ == "__main__":
    unittest.main()
