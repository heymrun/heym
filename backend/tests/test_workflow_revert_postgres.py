"""Reverting to an old version is a save: Edit History keeps the state it replaces."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import workflows as workflows_api
from app.config import settings
from app.db.models import User, Workflow, WorkflowVersion
from app.models.schemas import RevertVersionRequest, WorkflowUpdate


def _graph(label: str) -> list[dict]:
    return [
        {"id": "n1", "type": "textInput", "position": {"x": 0, "y": 0}, "data": {"label": label}}
    ]


class WorkflowRevertPostgresTests(unittest.IsolatedAsyncioTestCase):
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
            self.workflow = Workflow(
                name="Invoices", owner_id=self.owner.id, nodes=_graph("v1"), edges=[]
            )
            db.add(self.workflow)
            await db.commit()
        self.announce = AsyncMock()
        self.patches = [
            patch.object(workflows_api, "announce_workflow_saved", self.announce),
            patch.object(workflows_api, "audit"),
        ]
        for p in self.patches:
            p.start()
        self.user = SimpleNamespace(id=self.owner.id, email=self.owner.email)

    async def asyncTearDown(self) -> None:
        for p in self.patches:
            p.stop()
        async with AsyncSession(self.engine) as db:
            await db.execute(
                delete(WorkflowVersion).where(WorkflowVersion.workflow_id == self.workflow.id)
            )
            await db.execute(delete(Workflow).where(Workflow.id == self.workflow.id))
            await db.execute(delete(User).where(User.id == self.owner.id))
            await db.commit()
        await self.engine.dispose()

    async def _save(self, label: str) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            await workflows_api.update_workflow(
                self.workflow.id, WorkflowUpdate(nodes=_graph(label)), self.user, db
            )

    async def _versions(self) -> list[WorkflowVersion]:
        async with AsyncSession(self.engine) as db:
            result = await db.execute(
                select(WorkflowVersion)
                .where(WorkflowVersion.workflow_id == self.workflow.id)
                .order_by(WorkflowVersion.version_number)
            )
            return list(result.scalars().all())

    async def _revert(self, version: WorkflowVersion) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            await workflows_api.revert_workflow_to_version(
                self.workflow.id, version.id, RevertVersionRequest(confirm=True), self.user, db
            )

    async def _current_label(self) -> str:
        async with AsyncSession(self.engine) as db:
            workflow = await db.get(Workflow, self.workflow.id)
            return workflow.nodes[0]["data"]["label"]

    async def test_revert_keeps_the_replaced_state_and_can_be_undone(self) -> None:
        await self._save("v2")
        await self._save("v3")
        v1 = (await self._versions())[0]
        self.announce.reset_mock()

        await self._revert(v1)

        versions = await self._versions()
        self.assertEqual([v.nodes[0]["data"]["label"] for v in versions], ["v1", "v2", "v3"])
        self.assertEqual(await self._current_label(), "v1")
        self.announce.assert_awaited_once()

        await self._revert(versions[-1])

        self.assertEqual(await self._current_label(), "v3")

    async def test_revert_to_an_identical_state_adds_no_version(self) -> None:
        await self._save("v2")
        await self._save("v1")
        same_as_current = (await self._versions())[0]

        await self._revert(same_as_current)

        self.assertEqual(len(await self._versions()), 2)


if __name__ == "__main__":
    unittest.main()
