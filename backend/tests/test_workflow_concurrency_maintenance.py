"""Retiring held runs, reclaiming dead slots, and reading one run's status."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import select, update
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.db.models import ExecutionHistory, WorkflowConcurrencySlot, WorkflowRunQueue
from app.db.session import async_session_maker
from app.services import workflow_concurrency
from app.services.cluster import run_queue


async def _history_status(execution_id: uuid.UUID) -> str | None:
    async with async_session_maker() as db:
        return (
            await db.execute(
                select(ExecutionHistory.status).where(ExecutionHistory.id == execution_id)
            )
        ).scalar_one_or_none()


class CancelHeldTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_a_held_run_is_cancelled_with_a_history_row(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run())
        self.assertTrue(await workflow_concurrency.cancel_held(self.workflow_id, held.execution_id))
        row = await self.queue_row(held.execution_id)
        self.assertEqual(row.status, run_queue.STATUS_CANCELLED)
        self.assertEqual(await _history_status(held.execution_id), "cancelled")

    async def test_a_running_run_is_not_a_held_run(self) -> None:
        running = await workflow_concurrency.admit(self.held_run())
        self.assertFalse(
            await workflow_concurrency.cancel_held(self.workflow_id, running.execution_id)
        )


class QueueFullHistoryTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_a_rejected_run_gets_a_queue_full_history_row(self) -> None:
        execution_id = uuid.uuid4()
        await workflow_concurrency.record_queue_full(
            workflow_id=self.workflow_id,
            execution_id=execution_id,
            inputs={},
            trigger_source="API",
        )
        self.assertEqual(await _history_status(execution_id), "queue_full")


class ExpiryTests(ConcurrencyPostgresCase):
    limit = 1
    max_wait_seconds = 60

    async def test_maintain_expires_overdue_held_runs(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run())
        async with async_session_maker() as db:
            await db.execute(
                update(WorkflowRunQueue)
                .where(WorkflowRunQueue.execution_id == held.execution_id)
                .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
            )
            await db.commit()
        await workflow_concurrency.maintain()
        row = await self.queue_row(held.execution_id)
        self.assertEqual(row.status, run_queue.STATUS_EXPIRED)
        self.assertEqual(await _history_status(held.execution_id), "expired")


class StaleSlotTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_a_slot_nobody_is_running_is_reclaimed_and_the_head_promoted(self) -> None:
        dead = await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run())
        async with async_session_maker() as db:
            await db.execute(
                update(WorkflowConcurrencySlot)
                .where(WorkflowConcurrencySlot.execution_id == dead.execution_id)
                .values(acquired_at=datetime.now(timezone.utc) - timedelta(minutes=10))
            )
            await db.commit()
        with patch.object(workflow_concurrency.settings, "cluster_enabled", False):
            await workflow_concurrency.maintain()
        row = await self.queue_row(held.execution_id)
        self.assertEqual(row.status, run_queue.STATUS_QUEUED)

    async def test_a_young_slot_is_left_alone(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run())
        await workflow_concurrency.maintain()
        row = await self.queue_row(held.execution_id)
        self.assertEqual(row.status, run_queue.STATUS_HELD)


class StatusBodyTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_a_held_run_reports_its_queue_position(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run())
        body = await workflow_concurrency.build_status_body(self.workflow_id, held.execution_id)
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["queue"], {"position": 1, "size": 1, "running": 1, "limit": 1})

    async def test_an_unknown_execution_is_none(self) -> None:
        self.assertIsNone(
            await workflow_concurrency.build_status_body(self.workflow_id, uuid.uuid4())
        )

    async def test_history_answers_when_there_is_no_queue_row(self) -> None:
        execution_id = uuid.uuid4()
        async with async_session_maker() as db:
            db.add(
                ExecutionHistory(
                    id=execution_id,
                    workflow_id=self.workflow_id,
                    inputs={},
                    outputs={"answer": 42},
                    node_results=[],
                    status="success",
                    execution_time_ms=5.0,
                    trigger_source="API",
                )
            )
            await db.commit()
        body = await workflow_concurrency.build_status_body(self.workflow_id, execution_id)
        self.assertEqual((body["status"], body["outputs"]), ("success", {"answer": 42}))

    async def test_the_token_digest_is_readable_for_the_endpoint(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        held = await workflow_concurrency.admit(self.held_run(mint_status_token=True))
        digest = await workflow_concurrency.status_token_hash_for(
            self.workflow_id, held.execution_id
        )
        self.assertTrue(workflow_concurrency.status_token_matches(digest, held.status_token))


class HeldListingTests(ConcurrencyPostgresCase):
    limit = 1

    async def test_the_owner_sees_held_runs_with_positions(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        first = await workflow_concurrency.admit(self.held_run())
        second = await workflow_concurrency.admit(self.held_run())
        async with async_session_maker() as db:
            records = await workflow_concurrency.list_held_runs_for_user(db, self.user_id)
        mine = [r for r in records if r.workflow_id == self.workflow_id]
        self.assertEqual(
            [(r.execution_id, r.position, r.size) for r in mine],
            [(first.execution_id, 1, 2), (second.execution_id, 2, 2)],
        )

    async def test_a_stranger_sees_nothing(self) -> None:
        await workflow_concurrency.admit(self.held_run())
        await workflow_concurrency.admit(self.held_run())
        async with async_session_maker() as db:
            records = await workflow_concurrency.list_held_runs_for_user(db, uuid.uuid4())
        self.assertFalse([r for r in records if r.workflow_id == self.workflow_id])
