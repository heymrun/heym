"""The rollup's SQL and the read path against a real database (skips without PostgreSQL)."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.models import ExecutionHistory, NodeAnalyticsSnapshot, User, Workflow
from app.services.analytics_metrics import normalize_bucket_start
from app.services.node_analytics_metrics import compute_node_type_analytics
from app.services.node_analytics_rollup import roll_up_node_analytics_batch


class NodeAnalyticsPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL database is not reachable")
        self.hour = normalize_bucket_start(datetime.now(timezone.utc) - timedelta(hours=2))
        self.user = User(email=f"nodes-{uuid.uuid4()}@example.com", hashed_password="x", name="N")
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add(self.user)
            await db.flush()
            self.workflow = Workflow(name="Nodes", owner_id=self.user.id, nodes=[], edges=[])
            db.add(self.workflow)
            await db.flush()
            self.finished = ExecutionHistory(
                workflow_id=self.workflow.id,
                status="error",
                execution_time_ms=200.0,
                started_at=self.hour + timedelta(minutes=10),
                node_results=[
                    {"node_type": "agent", "status": "success", "execution_time_ms": 120.0},
                    {"node_type": "agent", "status": "error", "execution_time_ms": 30},
                    {"node_type": "set", "status": "skipped", "execution_time_ms": 0},
                    "not a node",
                    {"status": "success"},
                ],
            )
            self.paused = ExecutionHistory(
                workflow_id=self.workflow.id,
                status="pending",
                execution_time_ms=5.0,
                started_at=self.hour + timedelta(minutes=11),
                node_results=[{"node_type": "agent", "status": "success", "execution_time_ms": 5}],
            )
            self.legacy = ExecutionHistory(
                workflow_id=self.workflow.id,
                status="success",
                execution_time_ms=5.0,
                started_at=self.hour + timedelta(minutes=12),
                node_results=[{"node_type": "code", "status": "success", "execution_time_ms": 5}],
                node_analytics_pending=False,
            )
            self.not_a_list = ExecutionHistory(
                workflow_id=self.workflow.id,
                status="success",
                execution_time_ms=5.0,
                started_at=self.hour + timedelta(minutes=13),
                node_results={"unexpected": "shape"},
            )
            db.add_all([self.finished, self.paused, self.legacy, self.not_a_list])
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            await db.execute(
                delete(NodeAnalyticsSnapshot).where(
                    NodeAnalyticsSnapshot.workflow_id == self.workflow.id
                )
            )
            await db.execute(
                delete(ExecutionHistory).where(ExecutionHistory.workflow_id == self.workflow.id)
            )
            await db.execute(delete(Workflow).where(Workflow.id == self.workflow.id))
            await db.execute(delete(User).where(User.id == self.user.id))
            await db.commit()
        await self.engine.dispose()

    async def _snapshots(self) -> dict[str, NodeAnalyticsSnapshot]:
        async with AsyncSession(self.engine) as db:
            rows = (
                await db.execute(
                    select(NodeAnalyticsSnapshot).where(
                        NodeAnalyticsSnapshot.workflow_id == self.workflow.id
                    )
                )
            ).scalars()
            return {row.node_type: row for row in rows}

    async def _pending(self, history: ExecutionHistory) -> bool:
        async with AsyncSession(self.engine) as db:
            return (
                await db.execute(
                    select(ExecutionHistory.node_analytics_pending).where(
                        ExecutionHistory.id == history.id
                    )
                )
            ).scalar_one()

    async def test_a_batch_counts_finished_runs_once_and_leaves_paused_ones(self) -> None:
        async with AsyncSession(self.engine) as db:
            await roll_up_node_analytics_batch(db, batch_size=10_000)

        snapshots = await self._snapshots()
        self.assertEqual(set(snapshots), {"agent"})
        self.assertEqual(snapshots["agent"].call_count, 2)
        self.assertEqual(snapshots["agent"].error_count, 1)
        self.assertAlmostEqual(snapshots["agent"].total_duration_ms, 150.0)
        self.assertEqual(snapshots["agent"].bucket_start, self.hour)
        self.assertFalse(await self._pending(self.finished))
        self.assertFalse(await self._pending(self.not_a_list))
        self.assertTrue(await self._pending(self.paused))

        async with AsyncSession(self.engine) as db:
            await roll_up_node_analytics_batch(db, batch_size=10_000)
        self.assertEqual((await self._snapshots())["agent"].call_count, 2)

    async def test_the_read_path_sees_the_rollup(self) -> None:
        async with AsyncSession(self.engine) as db:
            await roll_up_node_analytics_batch(db, batch_size=10_000)
            result = await compute_node_type_analytics(
                db,
                accessible_workflow_ids=[self.workflow.id],
                workflow_id=None,
                since=self.hour,
                until=self.hour + timedelta(hours=2),
                bucket_delta=timedelta(hours=1),
            )

        self.assertEqual(result.most_calls[0].node_type, "agent")
        self.assertEqual(result.most_calls[0].total, 2.0)
        self.assertEqual(result.most_duration[0].average, 75.0)
        self.assertEqual(result.most_errors[0].total, 1.0)
