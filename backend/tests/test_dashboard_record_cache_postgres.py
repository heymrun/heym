"""The per-record widget cache upserts and keeps the newest records, on a real PostgreSQL."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.models import (
    Dashboard,
    DashboardWidget,
    DashboardWidgetRecordCache,
    User,
    Workflow,
)
from app.services.dashboard_data import RECORD_CACHE_LIMIT, store_record_cache


class DashboardRecordCachePostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL database is not reachable")
        self.owner = User(
            email=f"owner-{uuid.uuid4()}@example.com", hashed_password="x", name="Owner"
        )
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add(self.owner)
            await db.flush()
            self.dashboard = Dashboard(owner_id=self.owner.id, name="Customer")
            self.workflow = Workflow(
                name="Notes", owner_id=self.owner.id, kind="dashboard_widget", nodes=[], edges=[]
            )
            db.add_all([self.dashboard, self.workflow])
            await db.flush()
            self.widget = DashboardWidget(
                dashboard_id=self.dashboard.id, workflow_id=self.workflow.id, title="Notes"
            )
            db.add(self.widget)
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            await db.execute(delete(Dashboard).where(Dashboard.id == self.dashboard.id))
            await db.execute(delete(Workflow).where(Workflow.id == self.workflow.id))
            await db.execute(delete(User).where(User.id == self.owner.id))
            await db.commit()
        await self.engine.dispose()

    async def _records(self) -> dict[str, dict | None]:
        async with AsyncSession(self.engine) as db:
            rows = await db.execute(
                select(DashboardWidgetRecordCache).where(
                    DashboardWidgetRecordCache.widget_id == self.widget.id
                )
            )
            return {row.record: row.payload for row in rows.scalars().all()}

    async def test_a_second_write_for_a_record_replaces_the_first(self) -> None:
        now = datetime.now(timezone.utc)
        async with AsyncSession(self.engine) as db:
            await store_record_cache(db, self.widget.id, "ACME-1", {"v": 1}, now, "v1")
            await store_record_cache(db, self.widget.id, "ACME-1", {"v": 2}, now, "v1")
            await store_record_cache(db, self.widget.id, "ACME-2", {"v": 3}, now, "v1")
            await db.commit()

        self.assertEqual(await self._records(), {"ACME-1": {"v": 2}, "ACME-2": {"v": 3}})

    async def test_only_the_newest_records_are_kept(self) -> None:
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        async with AsyncSession(self.engine) as db:
            for index in range(RECORD_CACHE_LIMIT + 1):
                await store_record_cache(
                    db,
                    self.widget.id,
                    f"R-{index}",
                    {"v": index},
                    start + timedelta(seconds=index),
                    "v1",
                )
            await db.commit()

        records = await self._records()
        self.assertEqual(len(records), RECORD_CACHE_LIMIT)
        self.assertNotIn("R-0", records)
        self.assertIn(f"R-{RECORD_CACHE_LIMIT}", records)

    async def test_deleting_the_widget_drops_its_records(self) -> None:
        async with AsyncSession(self.engine) as db:
            await store_record_cache(
                db, self.widget.id, "ACME-1", {"v": 1}, datetime.now(timezone.utc), "v1"
            )
            await db.execute(delete(DashboardWidget).where(DashboardWidget.id == self.widget.id))
            await db.commit()

        self.assertEqual(await self._records(), {})


if __name__ == "__main__":
    unittest.main()
