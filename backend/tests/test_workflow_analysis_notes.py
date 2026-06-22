import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException, status

from app.api.workflows import get_workflow_analysis_note, save_workflow_analysis_note
from app.models.schemas import AnalysisNoteSaveRequest


def _db_with_workflow_and_note(workflow, note):
    """db.execute returns workflow on first call, note on second."""
    db = AsyncMock()
    results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=note)),
    ]
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class GetAnalysisNoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_empty_default_when_no_note(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=user.id)
        db = _db_with_workflow_and_note(workflow, None)

        result = await get_workflow_analysis_note(workflow.id, current_user=user, db=db)

        self.assertEqual(result.content, "")
        self.assertEqual(result.revision, 0)
        self.assertIsNone(result.updated_by)

    async def test_404_when_no_access(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with self.assertRaises(HTTPException) as ctx:
            await get_workflow_analysis_note(uuid.uuid4(), current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)

    async def test_returns_existing_note(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=user.id)
        editor = SimpleNamespace(id=uuid.uuid4(), name="Burak")
        note = SimpleNamespace(content="hello", revision=2, updated_by=editor, updated_at=None)
        db = _db_with_workflow_and_note(workflow, note)

        result = await get_workflow_analysis_note(workflow.id, current_user=user, db=db)

        self.assertEqual(result.content, "hello")
        self.assertEqual(result.revision, 2)
        self.assertEqual(result.updated_by.name, "Burak")


class SaveAnalysisNoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_note_when_none_exists(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), name="Burak")
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=user.id)
        db = _db_with_workflow_and_note(workflow, None)

        body = AnalysisNoteSaveRequest(content="new doc", base_revision=0)
        result = await save_workflow_analysis_note(workflow.id, body, current_user=user, db=db)

        self.assertEqual(result.content, "new doc")
        self.assertEqual(result.revision, 1)
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    async def test_updates_existing_and_increments_revision(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), name="Burak")
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=user.id)
        note = SimpleNamespace(
            content="old", revision=3, updated_by=None, updated_at=None, updated_by_id=None
        )
        db = _db_with_workflow_and_note(workflow, note)

        body = AnalysisNoteSaveRequest(content="edited", base_revision=3)
        result = await save_workflow_analysis_note(workflow.id, body, current_user=user, db=db)

        self.assertEqual(result.content, "edited")
        self.assertEqual(result.revision, 4)
        self.assertEqual(note.updated_by_id, user.id)

    async def test_stale_base_revision_returns_409(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), name="Burak")
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=user.id)
        editor = SimpleNamespace(id=uuid.uuid4(), name="Ceren")
        note = SimpleNamespace(
            content="server version", revision=5, updated_by=editor, updated_at=None
        )
        db = _db_with_workflow_and_note(workflow, note)

        body = AnalysisNoteSaveRequest(content="mine", base_revision=2)
        with self.assertRaises(HTTPException) as ctx:
            await save_workflow_analysis_note(workflow.id, body, current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(ctx.exception.detail["revision"], 5)
        self.assertEqual(ctx.exception.detail["content"], "server version")

    async def test_404_when_no_access(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), name="Burak")
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        body = AnalysisNoteSaveRequest(content="x", base_revision=0)
        with self.assertRaises(HTTPException) as ctx:
            await save_workflow_analysis_note(uuid.uuid4(), body, current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)


class AnalyzeWorkflowEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_non_llm_credential(self) -> None:
        from app.api.ai_assistant import AnalyzeWorkflowRequest, analyze_workflow_stream
        from app.db.models import CredentialType

        user = SimpleNamespace(id=uuid.uuid4(), user_rules=None)
        credential = SimpleNamespace(
            id=uuid.uuid4(), type=CredentialType.slack, encrypted_config={}
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=credential))
        )

        body = AnalyzeWorkflowRequest(
            credential_id=credential.id,
            model="gpt-4o",
            current_workflow={"id": str(uuid.uuid4())},
        )
        with self.assertRaises(HTTPException) as ctx:
            await analyze_workflow_stream(body, current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, status.HTTP_400_BAD_REQUEST)

    async def test_404_when_credential_missing(self) -> None:
        from app.api.ai_assistant import AnalyzeWorkflowRequest, analyze_workflow_stream

        user = SimpleNamespace(id=uuid.uuid4(), user_rules=None)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        body = AnalyzeWorkflowRequest(
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            current_workflow={"id": str(uuid.uuid4())},
        )
        with self.assertRaises(HTTPException) as ctx:
            await analyze_workflow_stream(body, current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)
