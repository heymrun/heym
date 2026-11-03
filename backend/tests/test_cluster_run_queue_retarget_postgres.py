"""Queued runs leave an instance that can no longer take work, on real PostgreSQL.

Requires a migrated PostgreSQL test database, like the other ``*_postgres`` suites.
Each test owns and removes only its random fixture rows and restores the
dispatch counters it touched.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from asyncpg import CannotConnectNowError, PostgresConnectionError
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from app.db.models import ClusterDispatchState, User, Workflow, WorkflowRunQueue
from app.db.session import async_session_maker, engine
from app.services.cluster import run_queue
from app.services.cluster.registry import InstanceView


def _instance(instance_id: str, role: str, weight: int, *, age_seconds: float = 0) -> InstanceView:
    return InstanceView(
        id=instance_id,
        name=instance_id,
        role=role,
        enabled=True,
        weight=weight,
        weight_configured=True,
        version="1.0.0",
        schema_revision="rev",
        keys_fingerprint="keys",
        docker_ok=True,
        db_latency_ms=1.0,
        heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
    )


class RetargetPostgresTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        try:
            async with asyncio.timeout(10):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except (OSError, TimeoutError, PostgresConnectionError, CannotConnectNowError) as exc:
            await engine.dispose()
            self.skipTest(f"PostgreSQL is unavailable ({type(exc).__name__})")
        except DBAPIError as exc:
            if not exc.connection_invalidated:
                raise
            await engine.dispose()
            self.skipTest("PostgreSQL connection is unavailable")
        suffix = uuid.uuid4().hex[:10]
        self.main = f"main-{suffix}"
        self.live = f"live-{suffix}"
        self.gone = f"gone-{suffix}"
        self.user_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        async with async_session_maker() as db:
            state = await db.get(ClusterDispatchState, "singleton")
            self.saved_counters = dict(state.counters or {})
            db.add(
                User(
                    id=self.user_id,
                    email=f"retarget-{self.user_id.hex}@example.com",
                    hashed_password="test-only",
                    name="Retarget fixture",
                )
            )
            db.add(
                Workflow(
                    id=self.workflow_id,
                    owner_id=self.user_id,
                    name="Retarget fixture",
                    nodes=[],
                    edges=[],
                )
            )
            await db.commit()
        self.addAsyncCleanup(self._cleanup)
        instances = [
            _instance(self.main, "main", 0),
            _instance(self.live, "worker", 100),
            _instance(self.gone, "worker", 100, age_seconds=120),
        ]
        listing = patch.object(
            run_queue.registry, "list_instances", AsyncMock(return_value=instances)
        )
        listing.start()
        self.addCleanup(listing.stop)

    async def _cleanup(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                delete(WorkflowRunQueue).where(WorkflowRunQueue.workflow_id == self.workflow_id)
            )
            await db.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            await db.execute(delete(User).where(User.id == self.user_id))
            await db.execute(
                update(ClusterDispatchState)
                .where(ClusterDispatchState.id == "singleton")
                .values(counters=self.saved_counters)
            )
            await db.commit()
        await engine.dispose()

    async def _row(
        self, *, target: str, placement: str = "anywhere", status: str = "queued"
    ) -> uuid.UUID:
        execution_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        async with async_session_maker() as db:
            db.add(
                WorkflowRunQueue(
                    workflow_id=self.workflow_id,
                    execution_id=execution_id,
                    placement=placement,
                    target_instance_id=target,
                    status=status,
                    inputs={},
                    test_run=False,
                    return_on_chart_output=False,
                    enqueued_at=now,
                    not_after=now + timedelta(minutes=10),
                    claimed_at=now if status == "claimed" else None,
                )
            )
            await db.commit()
        return execution_id

    async def _target(self, execution_id: uuid.UUID) -> tuple[str | None, str]:
        async with async_session_maker() as db:
            row = (
                await db.execute(
                    select(WorkflowRunQueue.target_instance_id, WorkflowRunQueue.status).where(
                        WorkflowRunQueue.execution_id == execution_id
                    )
                )
            ).one()
        return row[0], row[1]

    async def test_only_queued_anywhere_rows_of_the_offline_worker_move(self) -> None:
        orphan = await self._row(target=self.gone)
        main_only = await self._row(target=self.gone, placement="main_only")
        claimed = await self._row(target=self.gone, status="claimed")
        healthy = await self._row(target=self.live)

        self.assertEqual(await run_queue.retarget_unclaimable_rows(), 1)

        self.assertEqual(await self._target(orphan), (self.live, "queued"))
        self.assertEqual(await self._target(main_only), (self.gone, "queued"))
        self.assertEqual(await self._target(claimed), (self.gone, "claimed"))
        self.assertEqual(await self._target(healthy), (self.live, "queued"))

    async def test_a_row_claimed_while_moving_stays_with_its_claimer(self) -> None:
        orphan = await self._row(target=self.gone)
        choose = run_queue.choose_target

        async def claim_then_choose(placement: str) -> str | None:
            async with async_session_maker() as db:
                await db.execute(
                    update(WorkflowRunQueue)
                    .where(WorkflowRunQueue.execution_id == orphan)
                    .values(status="claimed", claimed_at=datetime.now(timezone.utc))
                )
                await db.commit()
            return await choose(placement)

        with patch.object(run_queue, "choose_target", side_effect=claim_then_choose):
            self.assertEqual(await run_queue.retarget_unclaimable_rows(), 0)
        self.assertEqual(await self._target(orphan), (self.gone, "claimed"))

    async def test_nothing_moves_when_no_instance_can_take_work(self) -> None:
        orphan = await self._row(target=self.gone)
        alone = [
            _instance(self.main, "main", 0),
            _instance(self.gone, "worker", 100, age_seconds=120),
        ]
        with patch.object(run_queue.registry, "list_instances", AsyncMock(return_value=alone)):
            self.assertEqual(await run_queue.retarget_unclaimable_rows(), 0)
        self.assertEqual(await self._target(orphan), (self.gone, "queued"))
