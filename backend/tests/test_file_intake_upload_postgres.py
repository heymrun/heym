"""Upload history survives a workflow deleting its input file on another connection."""

import unittest
import uuid
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from fastapi import UploadFile
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.datastructures import Headers

from app.api.file_intake import get_slot_status, upload_to_slot
from app.config import settings
from app.db.models import (
    ExecutionHistory,
    FileUploadAudit,
    FileUploadSlot,
    GeneratedFile,
    User,
    Workflow,
)
from app.services.file_intake_service import mint_slot


class FileIntakeUploadPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL database is not reachable")
        self.addAsyncCleanup(self.engine.dispose)
        self.storage = TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        storage_patch = patch(
            "app.services.file_storage._storage_root", return_value=Path(self.storage.name)
        )
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.owner = User(
            email=f"file-intake-{uuid.uuid4()}@example.com", hashed_password="x", name="Owner"
        )
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add(self.owner)
            await db.flush()
            self.workflow = Workflow(
                name="Upload cleanup", owner_id=self.owner.id, nodes=[], edges=[]
            )
            db.add(self.workflow)
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            await db.execute(
                delete(FileUploadAudit).where(FileUploadAudit.workflow_id == self.workflow.id)
            )
            await db.execute(
                delete(ExecutionHistory).where(ExecutionHistory.workflow_id == self.workflow.id)
            )
            await db.execute(delete(Workflow).where(Workflow.id == self.workflow.id))
            await db.execute(delete(User).where(User.id == self.owner.id))
            await db.commit()

    async def _upload(self, *, cleanup: bool, fail: bool = False) -> dict:
        nodes = [
            {"id": "upload", "type": "fileUploadTrigger", "data": {"label": "upload"}},
            {
                "id": "read",
                "type": "drive",
                "data": {
                    "label": "read",
                    "driveOperation": "get",
                    "driveFileId": "$upload.file.id",
                    "driveIncludeBinary": True,
                },
            },
        ]
        if cleanup:
            nodes.append(
                {
                    "id": "cleanup",
                    "type": "drive",
                    "data": {
                        "label": "cleanup",
                        "driveOperation": "delete",
                        "driveFileId": "$upload.file.id",
                    },
                }
            )
        nodes.append(
            {
                "id": "done",
                "type": "throwError" if fail else "output",
                "data": {
                    "label": "done",
                    "message": "Imported",
                    "errorMessage": "Invalid upload contents",
                    "httpStatusCode": 422,
                },
            }
        )
        edges = [
            {"id": f"e{index}", "source": source["id"], "target": target["id"]}
            for index, (source, target) in enumerate(zip(nodes, nodes[1:]))
        ]
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            workflow = await db.get(Workflow, self.workflow.id)
            workflow.nodes, workflow.edges = nodes, edges
            slot, token = await mint_slot(
                db,
                workflow_id=workflow.id,
                node=nodes[0],
                created_by_user_id=self.owner.id,
                mint_source="http",
            )
            self.slot_id = slot.id
            await db.commit()

        request = MagicMock()
        request.headers = {}
        request.base_url = "http://testserver/"
        request.client.host = "127.0.0.1"
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            return await upload_to_slot(
                token=token,
                request=request,
                file=UploadFile(
                    BytesIO(b"upload contents"),
                    filename="input.xer",
                    headers=Headers({"content-type": "application/octet-stream"}),
                ),
                db=db,
            )

    async def _assert_persisted(self, result: dict, *, deleted: bool) -> None:
        async with AsyncSession(self.engine) as db:
            slot = await db.get(FileUploadSlot, self.slot_id)
            history = await db.get(ExecutionHistory, uuid.UUID(result["run_id"]))
            self.assertIsNotNone(history)
            self.assertEqual(history.status, result["status"])
            self.assertEqual(history.inputs["file"], result["file"])
            self.assertEqual(history.outputs, result["output"])
            self.assertEqual(slot.run_id, result["run_id"])
            self.assertEqual(slot.status, "consumed")
            file_id = uuid.UUID(result["file"]["id"])
            self.assertEqual(slot.uploaded_file_id, None if deleted else file_id)
            self.assertEqual(await db.get(GeneratedFile, file_id) is None, deleted)
            results = {row["node_id"]: row for row in history.node_results}
            self.assertEqual(results["read"]["status"], "success")
            if deleted:
                self.assertEqual(results["cleanup"]["status"], "success")
            events = (
                (
                    await db.execute(
                        select(FileUploadAudit.event).where(FileUploadAudit.slot_id == slot.id)
                    )
                )
                .scalars()
                .all()
            )
            self.assertIn("upload_accepted", events)
            self.assertEqual("run_failed" in events, result["status"] == "error")
            polled = await get_slot_status(slot_id=slot.id, current_user=self.owner, db=db)
            self.assertEqual(polled["run"]["execution_history_id"], result["run_id"])
            self.assertEqual(polled["run"]["status"], result["status"])

    async def test_cleanup_keeps_successful_run_history(self) -> None:
        result = await self._upload(cleanup=True)
        self.assertEqual(result["status"], "success")
        await self._assert_persisted(result, deleted=True)

    async def test_failure_after_cleanup_keeps_failed_run_history(self) -> None:
        result = await self._upload(cleanup=True, fail=True)
        self.assertEqual(result["status"], "error")
        await self._assert_persisted(result, deleted=True)

    async def test_retained_upload_stays_linked_to_the_slot(self) -> None:
        result = await self._upload(cleanup=False)
        self.assertEqual(result["status"], "success")
        await self._assert_persisted(result, deleted=False)
