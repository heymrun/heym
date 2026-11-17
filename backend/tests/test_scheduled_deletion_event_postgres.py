"""Scheduled deletion publishes workflow.deleted, like the delete endpoint."""

import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, text

from app.db.models import HeymEvent, User, Workflow
from app.db.session import async_session_maker, engine
from app.services.cron_scheduler import CronScheduler


class ScheduledDeletionEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        try:
            async with async_session_maker() as db:
                await db.execute(text("SELECT 1"))
        except Exception:
            self.skipTest("PostgreSQL database is not reachable")
        self.user_id = uuid.uuid4()
        self.workflow_ids: list[uuid.UUID] = []
        async with async_session_maker() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"trash-{self.user_id.hex}@example.com",
                    hashed_password="x",
                    name="Trash",
                )
            )
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as db:
            await db.execute(delete(HeymEvent).where(HeymEvent.workflow_id.in_(self.workflow_ids)))
            await db.execute(delete(Workflow).where(Workflow.id.in_(self.workflow_ids)))
            await db.execute(delete(User).where(User.id == self.user_id))
            await db.commit()
        await engine.dispose()

    async def _scheduled(self, name: str, kind: str = "workflow") -> uuid.UUID:
        workflow_id = uuid.uuid4()
        self.workflow_ids.append(workflow_id)
        async with async_session_maker() as db:
            db.add(
                Workflow(
                    id=workflow_id,
                    name=name,
                    kind=kind,
                    owner_id=self.user_id,
                    nodes=[],
                    edges=[],
                    scheduled_for_deletion=datetime.now(timezone.utc),
                )
            )
            await db.commit()
        return workflow_id

    async def _deleted_events(self, workflow_id: uuid.UUID) -> list[HeymEvent]:
        async with async_session_maker() as db:
            result = await db.execute(
                select(HeymEvent).where(
                    HeymEvent.workflow_id == workflow_id, HeymEvent.name == "workflow.deleted"
                )
            )
            return list(result.scalars().all())

    async def test_a_scheduled_deletion_publishes_workflow_deleted(self) -> None:
        workflow_id = await self._scheduled("Old reports")

        await CronScheduler()._cleanup_scheduled_workflows()

        async with async_session_maker() as db:
            self.assertIsNone(await db.get(Workflow, workflow_id))
        events = await self._deleted_events(workflow_id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].owner_id, self.user_id)
        self.assertEqual(events[0].payload["name"], "Old reports")

    async def test_a_dashboard_widget_workflow_publishes_nothing(self) -> None:
        widget_id = await self._scheduled("Revenue widget", kind="dashboard_widget")

        await CronScheduler()._cleanup_scheduled_workflows()

        self.assertEqual(await self._deleted_events(widget_id), [])


if __name__ == "__main__":
    unittest.main()
