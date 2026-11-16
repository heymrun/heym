"""A File Upload run that pauses for review mints the review request, like other triggers."""

import time
import unittest
import uuid
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from fastapi import UploadFile
from openai.resources.chat.completions import Completions
from openai.types.chat import ChatCompletion
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.datastructures import Headers

from app.api.file_intake import upload_to_slot
from app.config import settings
from app.db.models import (
    Credential,
    CredentialType,
    ExecutionHistory,
    FileUploadAudit,
    FileUploadSlot,
    GeneratedFile,
    HITLRequest,
    LLMTrace,
    User,
    Workflow,
    WorkflowAnalyticsSnapshot,
)
from app.services.encryption import encrypt_config
from app.services.file_intake_service import mint_slot


def _review_requested(_self: object, **kwargs: object) -> ChatCompletion:
    """The model asks for human review before importing."""
    return ChatCompletion.model_validate(
        {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": kwargs.get("model"),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_review_1",
                                "type": "function",
                                "function": {
                                    "name": "request_human_review",
                                    "arguments": '{"summary": "Import 12 invoices", '
                                    '"review_markdown": "12 rows", "reason": "Import"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )


class FileIntakeReviewPostgresTests(unittest.IsolatedAsyncioTestCase):
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
            email=f"file-review-{uuid.uuid4()}@example.com", hashed_password="x", name="Owner"
        )
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add(self.owner)
            await db.flush()
            self.credential = Credential(
                owner_id=self.owner.id,
                name="openai",
                type=CredentialType.openai,
                encrypted_config=encrypt_config({"api_key": "sk-test-not-real"}),
            )
            db.add(self.credential)
            self.workflow = Workflow(
                name="Invoice import", owner_id=self.owner.id, nodes=[], edges=[]
            )
            db.add(self.workflow)
            await db.commit()

    async def asyncTearDown(self) -> None:
        workflow_id = self.workflow.id
        async with AsyncSession(self.engine) as db:
            await db.execute(delete(HITLRequest).where(HITLRequest.workflow_id == workflow_id))
            await db.execute(
                delete(FileUploadAudit).where(FileUploadAudit.workflow_id == workflow_id)
            )
            await db.execute(
                delete(FileUploadSlot).where(FileUploadSlot.workflow_id == workflow_id)
            )
            await db.execute(
                delete(ExecutionHistory).where(ExecutionHistory.workflow_id == workflow_id)
            )
            await db.execute(delete(LLMTrace).where(LLMTrace.user_id == self.owner.id))
            await db.execute(
                delete(WorkflowAnalyticsSnapshot).where(
                    WorkflowAnalyticsSnapshot.owner_id == self.owner.id
                )
            )
            await db.execute(delete(GeneratedFile).where(GeneratedFile.owner_id == self.owner.id))
            await db.execute(delete(Workflow).where(Workflow.id == workflow_id))
            await db.execute(delete(Credential).where(Credential.id == self.credential.id))
            await db.execute(delete(User).where(User.id == self.owner.id))
            await db.commit()

    async def test_a_paused_upload_mints_its_review_request(self) -> None:
        nodes = [
            {"id": "upload", "type": "fileUploadTrigger", "data": {"label": "upload"}},
            {
                "id": "agent",
                "type": "agent",
                "data": {
                    "label": "importer",
                    "credentialId": str(self.credential.id),
                    "model": "gpt-4o-mini",
                    "userMessage": "Import $upload.file.filename",
                    "hitlEnabled": True,
                },
            },
        ]
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            workflow = await db.get(Workflow, self.workflow.id)
            workflow.nodes = nodes
            workflow.edges = [{"id": "e1", "source": "upload", "target": "agent"}]
            slot, token = await mint_slot(
                db,
                workflow_id=workflow.id,
                node=nodes[0],
                created_by_user_id=self.owner.id,
                mint_source="http",
            )
            await db.commit()
        request = MagicMock()
        request.headers = {}
        request.base_url = "http://testserver/"
        request.client.host = "127.0.0.1"

        with patch.object(Completions, "create", _review_requested):
            async with AsyncSession(self.engine, expire_on_commit=False) as db:
                result = await upload_to_slot(
                    token=token,
                    request=request,
                    file=UploadFile(
                        BytesIO(b"invoice,amount\n1,40\n"),
                        filename="invoices.csv",
                        headers=Headers({"content-type": "text/csv"}),
                    ),
                    db=db,
                )

        self.assertEqual(result["status"], "pending")
        run_id = uuid.UUID(result["run_id"])
        async with AsyncSession(self.engine) as db:
            review = (
                await db.execute(
                    select(HITLRequest).where(HITLRequest.execution_history_id == run_id)
                )
            ).scalar_one_or_none()
            history = await db.get(ExecutionHistory, run_id)
            events = (
                (
                    await db.execute(
                        select(FileUploadAudit.event).where(FileUploadAudit.slot_id == slot.id)
                    )
                )
                .scalars()
                .all()
            )
        self.assertIsNotNone(review)
        self.assertEqual(review.status, "pending")
        self.assertEqual(history.status, "pending")
        self.assertEqual(history.inputs["file"]["name"], "invoices.csv")
        self.assertIn("upload_accepted", events)
        self.assertNotIn("run_failed", events)


if __name__ == "__main__":
    unittest.main()
