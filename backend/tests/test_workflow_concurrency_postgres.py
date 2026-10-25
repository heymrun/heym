"""Admission, release and FIFO promotion against a real database."""

import asyncio
import uuid
from unittest.mock import patch

# backend/tests is not a package; pytest's default "prepend" import mode puts the
# test directory on sys.path, so the shared fixture imports by its bare name.
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.services import workflow_concurrency
from app.services.cluster import run_queue


class AdmitTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_the_first_run_is_admitted_and_holds_a_slot(self) -> None:
        admission = await workflow_concurrency.admit(self.held_run())
        self.assertEqual(admission.kind, "admitted")
        self.assertEqual(await self.slot_count(), 1)

    async def test_later_runs_queue_with_increasing_positions(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        second = await workflow_concurrency.admit(self.held_run())
        third = await workflow_concurrency.admit(self.held_run())
        self.assertEqual(second.kind, "queued")
        self.assertEqual((second.queue.position, second.queue.size), (1, 1))
        self.assertEqual(
            (third.queue.position, third.queue.size, third.queue.running, third.queue.limit),
            (2, 2, 1, 1),
        )
        row = await self.queue_row(third.execution_id)
        self.assertEqual(row.status, run_queue.STATUS_HELD)
        self.assertIsNotNone(row.concurrency_seq)

    async def test_re_admitting_a_slot_holder_is_idempotent(self) -> None:
        run = self.held_run()
        await workflow_concurrency.admit(run)
        again = await workflow_concurrency.admit(run)
        self.assertEqual(again.kind, "admitted")
        self.assertEqual(await self.slot_count(), 1)

    async def test_a_token_is_minted_only_when_asked(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        plain = await workflow_concurrency.admit(self.held_run())
        anonymous = await workflow_concurrency.admit(self.held_run(mint_status_token=True))
        self.assertIsNone(plain.status_token)
        self.assertTrue(anonymous.status_token)
        row = await self.queue_row(anonymous.execution_id)
        self.assertNotEqual(row.status_token_hash, anonymous.status_token)


class UnlimitedTests(ConcurrencyPostgresCase):
    limit = None

    async def test_no_limit_takes_no_slot(self) -> None:
        admission = await workflow_concurrency.admit(self.held_run())
        self.assertEqual(admission.kind, "unlimited")
        self.assertEqual(await self.slot_count(), 0)


class QueueFullTests(ConcurrencyPostgresCase):
    limit = 1
    max_queue = 1

    async def test_the_queue_rejects_past_max_queue(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        await workflow_concurrency.admit(self.held_run())
        rejected = await workflow_concurrency.admit(self.held_run())
        self.assertEqual(rejected.kind, "queue_full")
        self.assertIsNone(await self.queue_row(rejected.execution_id))


class ReleaseTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_release_promotes_the_head_in_fifo_order(self) -> None:
        first = await workflow_concurrency.admit(self.held_run())
        second = await workflow_concurrency.admit(self.held_run())
        third = await workflow_concurrency.admit(self.held_run())
        with patch.object(workflow_concurrency.settings, "cluster_enabled", False):
            await workflow_concurrency.release(first.execution_id)
        promoted = await self.queue_row(second.execution_id)
        waiting = await self.queue_row(third.execution_id)
        self.assertEqual(promoted.status, run_queue.STATUS_QUEUED)
        self.assertIsNotNone(promoted.target_instance_id)
        self.assertEqual(waiting.status, run_queue.STATUS_HELD)
        self.assertEqual(await self.slot_count(), 1)

    async def test_release_without_a_slot_is_a_no_op(self) -> None:
        await workflow_concurrency.release(uuid.uuid4())
        self.assertEqual(await self.slot_count(), 0)

    async def test_raising_the_limit_promotes_several(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = [await workflow_concurrency.admit(self.held_run()) for _ in range(3)]
        await self.set_limit(3)
        with patch.object(workflow_concurrency.settings, "cluster_enabled", False):
            promoted = await workflow_concurrency.promote(self.workflow_id)
        self.assertEqual(promoted, 2)
        statuses = [(await self.queue_row(a.execution_id)).status for a in held]
        self.assertEqual(statuses, ["queued", "queued", "held"])

    async def test_turning_the_limit_off_drains_the_queue_without_slots(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = [await workflow_concurrency.admit(self.held_run()) for _ in range(2)]
        await self.set_limit(None)
        with patch.object(workflow_concurrency.settings, "cluster_enabled", False):
            await workflow_concurrency.promote(self.workflow_id)
        statuses = [(await self.queue_row(a.execution_id)).status for a in held]
        self.assertEqual(statuses, ["queued", "queued"])
        self.assertEqual(await self.slot_count(), 1)


class RaceTests(ConcurrencyPostgresCase):
    limit = 3

    async def test_concurrent_admissions_never_exceed_the_limit(self) -> None:
        admissions = await asyncio.gather(
            *(workflow_concurrency.admit(self.held_run()) for _ in range(8))
        )
        kinds = sorted(a.kind for a in admissions)
        self.assertEqual(kinds.count("admitted"), 3)
        self.assertEqual(kinds.count("queued"), 5)
        positions = sorted(a.queue.position for a in admissions if a.kind == "queued")
        self.assertEqual(positions, [1, 2, 3, 4, 5])
        self.assertEqual(await self.slot_count(), 3)
