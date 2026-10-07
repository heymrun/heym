"""analytics_metrics returns what the Analytics endpoints return, against a real database."""

import unittest
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import analytics as analytics_api
from app.config import settings
from app.db.models import ExecutionHistory, User, Workflow, WorkflowAnalyticsSnapshot
from app.services import analytics_metrics


class AnalyticsMetricsPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL database is not reachable")
        now = datetime.now(timezone.utc)
        hour = analytics_metrics.normalize_bucket_start(now - timedelta(hours=2))
        self.user = User(
            email=f"analytics-{uuid.uuid4()}@example.com", hashed_password="x", name="A"
        )
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add(self.user)
            await db.flush()
            self.workflow = Workflow(
                name="Invoices", owner_id=self.user.id, nodes=[], edges=[], minutes_saved_per_run=2
            )
            db.add(self.workflow)
            await db.flush()
            db.add_all(
                [
                    ExecutionHistory(
                        workflow_id=self.workflow.id,
                        status=status,
                        execution_time_ms=ms,
                        started_at=hour + timedelta(minutes=minute),
                    )
                    for status, ms, minute in [
                        ("success", 100.0, 1),
                        ("success", 200.0, 2),
                        ("error", 300.0, 3),
                        ("success", 400.0, 4),
                    ]
                ]
            )
            db.add(
                WorkflowAnalyticsSnapshot(
                    workflow_id=self.workflow.id,
                    owner_id=self.user.id,
                    workflow_name_snapshot="Invoices",
                    bucket_start=hour,
                    total_executions=4,
                    success_count=3,
                    error_count=1,
                    latency_sample_count=4,
                    total_latency_ms=1000.0,
                    max_latency_ms=400.0,
                    last_run_at=hour + timedelta(minutes=4),
                )
            )
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            await db.execute(
                delete(WorkflowAnalyticsSnapshot).where(
                    WorkflowAnalyticsSnapshot.workflow_id == self.workflow.id
                )
            )
            await db.execute(
                delete(ExecutionHistory).where(ExecutionHistory.workflow_id == self.workflow.id)
            )
            await db.execute(delete(Workflow).where(Workflow.id == self.workflow.id))
            await db.execute(delete(User).where(User.id == self.user.id))
            await db.commit()
        await self.engine.dispose()

    async def _user(self, db: AsyncSession) -> User:
        return (await db.execute(select(User).where(User.id == self.user.id))).scalar_one()

    async def test_stats_match_the_endpoint_and_the_seeded_runs(self) -> None:
        async with AsyncSession(self.engine) as db:
            stats = await analytics_metrics.compute_analytics_stats(
                db,
                user_id=self.user.id,
                accessible_workflow_ids=[self.workflow.id],
                workflow_id=None,
                time_range="24h",
            )
            endpoint = await analytics_api.get_analytics_stats(
                workflow_id=None,
                time_range="24h",
                start_at=None,
                end_at=None,
                current_user=await self._user(db),
                db=db,
            )
        self.assertEqual(asdict(stats), endpoint.model_dump())
        self.assertEqual(
            (stats.total_executions, stats.success_count, stats.error_count), (4, 3, 1)
        )
        self.assertEqual(stats.success_rate, 75.0)
        self.assertEqual(stats.avg_latency_ms, 250.0)
        self.assertEqual(stats.p95_latency_ms, 400.0)
        self.assertEqual(stats.time_saved_minutes, 6.0)

    async def test_series_and_breakdown_match_the_endpoints(self) -> None:
        async with AsyncSession(self.engine) as db:
            user = await self._user(db)
            since, until = analytics_metrics.resolve_time_window("24h")
            series = await analytics_metrics.compute_metrics_series(
                db,
                user_id=self.user.id,
                accessible_workflow_ids=[self.workflow.id],
                workflow_id=None,
                since=since,
                until=until,
                bucket_delta=timedelta(hours=1),
            )
            breakdown = await analytics_metrics.compute_workflow_breakdown(
                db,
                user_id=self.user.id,
                accessible_workflow_ids=[self.workflow.id],
                since=since,
                until=until,
                limit=10,
            )
            endpoint_breakdown = await analytics_api.get_workflow_breakdown(
                time_range="24h", start_at=None, end_at=None, limit=10, current_user=user, db=db
            )
        self.assertEqual(sum(series.executions), 4)
        self.assertEqual(sum(series.errors), 1)
        self.assertEqual([row.workflow_id for row in breakdown], [self.workflow.id])
        self.assertEqual(breakdown[0].time_saved_minutes, 6.0)
        self.assertEqual(
            [asdict(row) for row in breakdown],
            [item.model_dump() for item in endpoint_breakdown.items],
        )
