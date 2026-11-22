"""The collaborator whose canvas run minted an upload slot can poll it; nobody else can."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.file_intake import get_slot_status
from app.config import settings
from app.db.models import ExecutionHistory, FileUploadSlot, User, Workflow, WorkflowShare
from app.services.file_intake_service import mint_slot

NODE = {"id": "upload", "type": "fileUploadTrigger", "data": {"label": "upload"}}


class SlotStatusAccessPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL database is not reachable")
        self.addAsyncCleanup(self.engine.dispose)
        self.owner, self.minter, self.other = (
            User(email=f"slot-{name}-{uuid.uuid4()}@example.com", hashed_password="x", name=name)
            for name in ("owner", "minter", "other")
        )
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add_all([self.owner, self.minter, self.other])
            await db.flush()
            self.workflow = Workflow(
                name="Invoice import", owner_id=self.owner.id, nodes=[NODE], edges=[]
            )
            db.add(self.workflow)
            await db.flush()
            for user in (self.minter, self.other):
                db.add(
                    WorkflowShare(workflow_id=self.workflow.id, user_id=user.id, permission="write")
                )
            await db.commit()

    async def asyncTearDown(self) -> None:
        workflow_id = self.workflow.id
        async with AsyncSession(self.engine) as db:
            await db.execute(
                delete(FileUploadSlot).where(FileUploadSlot.workflow_id == workflow_id)
            )
            await db.execute(
                delete(ExecutionHistory).where(ExecutionHistory.workflow_id == workflow_id)
            )
            await db.execute(delete(WorkflowShare).where(WorkflowShare.workflow_id == workflow_id))
            await db.execute(delete(Workflow).where(Workflow.id == workflow_id))
            await db.execute(
                delete(User).where(User.id.in_([self.owner.id, self.minter.id, self.other.id]))
            )
            await db.commit()

    async def _uploaded_slot(self, minter: User) -> uuid.UUID:
        """A slot in the state an upload leaves it: consumed, with its run's history row."""
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            slot, _token = await mint_slot(
                db,
                workflow_id=self.workflow.id,
                node=NODE,
                created_by_user_id=minter.id,
                mint_source="canvas",
            )
            run_id = uuid.uuid4()
            db.add(
                ExecutionHistory(
                    id=run_id,
                    workflow_id=self.workflow.id,
                    inputs={},
                    outputs={"done": "Imported"},
                    node_results=[],
                    status="success",
                    execution_time_ms=3.0,
                    trigger_source="file_upload",
                )
            )
            slot.status, slot.run_id = "consumed", str(run_id)
            await db.commit()
            return slot.id

    async def _poll(self, slot_id: uuid.UUID, user: User) -> dict:
        async with AsyncSession(self.engine) as db:
            return await get_slot_status(
                slot_id=slot_id, current_user=SimpleNamespace(id=user.id), db=db
            )

    async def test_the_minting_collaborator_sees_the_uploaded_run(self) -> None:
        slot_id = await self._uploaded_slot(self.minter)

        result = await self._poll(slot_id, self.minter)

        self.assertEqual(result["status"], "consumed")
        self.assertEqual(result["run"]["outputs"], {"done": "Imported"})

    async def test_the_owner_still_sees_every_slot(self) -> None:
        slot_id = await self._uploaded_slot(self.minter)

        self.assertEqual((await self._poll(slot_id, self.owner))["status"], "consumed")

    async def test_another_collaborator_gets_404(self) -> None:
        slot_id = await self._uploaded_slot(self.minter)

        with self.assertRaises(HTTPException) as caught:
            await self._poll(slot_id, self.other)
        self.assertEqual(caught.exception.status_code, 404)

    async def test_the_minter_without_access_any_more_gets_404(self) -> None:
        slot_id = await self._uploaded_slot(self.minter)
        async with AsyncSession(self.engine) as db:
            await db.execute(
                delete(WorkflowShare).where(
                    WorkflowShare.workflow_id == self.workflow.id,
                    WorkflowShare.user_id == self.minter.id,
                )
            )
            await db.commit()

        with self.assertRaises(HTTPException) as caught:
            await self._poll(slot_id, self.minter)
        self.assertEqual(caught.exception.status_code, 404)

    async def test_pending_unexpired_slot_returns_pending_and_expires_at(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            slot, _token = await mint_slot(
                db,
                workflow_id=self.workflow.id,
                node=NODE,
                created_by_user_id=self.minter.id,
                mint_source="canvas",
            )
            await db.commit()
            slot_id = slot.id

        result = await self._poll(slot_id, self.minter)
        self.assertEqual(result["status"], "pending")
        self.assertIsNone(result["run_id"])
        self.assertIsNone(result["run"])
        self.assertIsNotNone(result.get("expires_at"))

    async def test_pending_expired_slot_returns_derived_expired_status(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            slot, _token = await mint_slot(
                db,
                workflow_id=self.workflow.id,
                node=NODE,
                created_by_user_id=self.minter.id,
                mint_source="canvas",
            )
            slot.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            await db.commit()
            slot_id = slot.id

        result = await self._poll(slot_id, self.minter)
        self.assertEqual(result["status"], "expired")
        self.assertIsNone(result["run_id"])
        self.assertIsNone(result["run"])

    async def test_consumed_slot_executing_without_run_id_returns_consumed_and_no_run(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            slot, _token = await mint_slot(
                db,
                workflow_id=self.workflow.id,
                node=NODE,
                created_by_user_id=self.minter.id,
                mint_source="canvas",
            )
            slot.status = "consumed"
            slot.run_id = None
            await db.commit()
            slot_id = slot.id

        result = await self._poll(slot_id, self.minter)
        self.assertEqual(result["status"], "consumed")
        self.assertIsNone(result["run_id"])
        self.assertIsNone(result["run"])

    async def test_consumed_slot_past_original_expiry_remains_consumed_with_run(self) -> None:
        slot_id = await self._uploaded_slot(self.minter)
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            slot = await db.get(FileUploadSlot, slot_id)
            assert slot is not None
            slot.expires_at = datetime.now(timezone.utc) - timedelta(hours=2)
            await db.commit()

        result = await self._poll(slot_id, self.minter)
        self.assertEqual(result["status"], "consumed")
        self.assertIsNotNone(result["run"])
        self.assertEqual(result["run"]["outputs"], {"done": "Imported"})


if __name__ == "__main__":
    unittest.main()
