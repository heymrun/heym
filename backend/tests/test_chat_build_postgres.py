"""Chat build mode saves keep Edit History and write access on a real PostgreSQL."""

import copy
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import chat_build
from app.config import settings
from app.db.models import User, Workflow, WorkflowShare, WorkflowVersion
from app.services.chat_build_mode import BuildRequest
from app.services.credential_catalog import CredentialPromptMode

DSL = {
    "name": "Lead intake",
    "description": "Saves website leads",
    "nodes": [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "done",
            "type": "output",
            "position": {"x": 300, "y": 0},
            "data": {"label": "result", "message": "$start.text"},
        },
    ],
    "edges": [{"id": "e1", "source": "start", "target": "done"}],
}


class ChatBuildPostgresTests(unittest.IsolatedAsyncioTestCase):
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
        self.reader = User(
            email=f"reader-{uuid.uuid4()}@example.com", hashed_password="x", name="Reader"
        )
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add_all([self.owner, self.reader])
            await db.flush()
            self.workflow = Workflow(
                name="Old intake", description="", owner_id=self.owner.id, nodes=[], edges=[]
            )
            db.add(self.workflow)
            await db.flush()
            db.add(
                WorkflowShare(
                    workflow_id=self.workflow.id, user_id=self.reader.id, permission="read"
                )
            )
            await db.commit()
        self.patches = [
            patch.object(chat_build, "announce_workflow_saved", AsyncMock()),
            patch.object(chat_build, "audit"),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self) -> None:
        for p in self.patches:
            p.stop()
        async with AsyncSession(self.engine) as db:
            await db.execute(
                delete(WorkflowVersion).where(WorkflowVersion.workflow_id == self.workflow.id)
            )
            await db.execute(
                delete(WorkflowShare).where(WorkflowShare.workflow_id == self.workflow.id)
            )
            await db.execute(delete(Workflow).where(Workflow.id == self.workflow.id))
            await db.execute(delete(User).where(User.id.in_([self.owner.id, self.reader.id])))
            await db.commit()
        await self.engine.dispose()

    def _session(self, db: AsyncSession, user: User) -> chat_build.ChatBuildSession:
        return chat_build.ChatBuildSession(
            db=db,
            user=user,
            request=BuildRequest(target_workflow_id=self.workflow.id),
            selected_credential=SimpleNamespace(id=uuid.uuid4(), owner_id=user.id, type="openai"),
            model="gpt-5.5",
            credential_mode=CredentialPromptMode.ASK_AND_CREATE,
            public_base_url="http://localhost",
            cancel_event=None,
            llm_session_id="conv-1",
        )

    async def _versions(self) -> list[WorkflowVersion]:
        async with AsyncSession(self.engine) as db:
            result = await db.execute(
                select(WorkflowVersion)
                .where(WorkflowVersion.workflow_id == self.workflow.id)
                .order_by(WorkflowVersion.version_number)
            )
            return list(result.scalars().all())

    async def test_each_changing_save_adds_a_version_of_what_it_replaced(self) -> None:
        changed = copy.deepcopy(DSL)
        changed["nodes"][1]["data"]["message"] = "Lead: $start.text"
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            session = self._session(db, self.owner)
            first = await session.call("save_workflow", {"workflow": DSL})
            second = await session.call("save_workflow", {"workflow": changed})
            same = await session.call("save_workflow", {"workflow": changed})

        versions = await self._versions()
        self.assertEqual([v.version_number for v in versions], [1, 2])
        self.assertEqual(versions[0].nodes, [])
        self.assertEqual(versions[1].nodes[1]["data"]["message"], "$start.text")
        self.assertIn("version 2", first.summary)
        self.assertIn("version 3", second.summary)
        self.assertIn("no changes", same.summary)

    async def test_a_reader_cannot_save_the_shared_workflow(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            outcome = await self._session(db, self.reader).call("save_workflow", {"workflow": DSL})

        self.assertIn("read-only", outcome.result)
        self.assertEqual(await self._versions(), [])
        async with AsyncSession(self.engine) as db:
            stored = await db.get(Workflow, self.workflow.id)
            self.assertEqual(stored.name, "Old intake")


if __name__ == "__main__":
    unittest.main()
