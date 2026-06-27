"""Unit tests for the file-intake multipart upload endpoint guards + happy path."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.file_intake import upload_to_slot
from app.services import file_intake_service


def _make_request(headers: dict[str, str] | None = None) -> MagicMock:
    req = MagicMock()
    req.headers = headers or {}
    req.base_url = "http://testserver/"
    req.client = SimpleNamespace(host="1.2.3.4")
    return req


def _make_upload(data: bytes, filename: str, content_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        read=AsyncMock(return_value=data),
        filename=filename,
        content_type=content_type,
    )


def _select_result(value: object) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


def _update_result(rowcount: int) -> MagicMock:
    res = MagicMock()
    res.rowcount = rowcount
    return res


def _make_slot(**overrides) -> MagicMock:
    slot = MagicMock()
    slot.id = uuid.uuid4()
    slot.workflow_id = uuid.uuid4()
    slot.status = "pending"
    slot.max_size_bytes = 10 * 1024 * 1024
    slot.allowed_mime = None
    slot.trigger_node_id = "n1"
    slot.trigger_node_label = "audio"
    slot.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    slot.uploaded_file_id = None
    slot.run_id = None
    for k, v in overrides.items():
        setattr(slot, k, v)
    return slot


def _added_events(db: MagicMock) -> list[str]:
    return [
        row.event
        for (args, _kw) in db.add.call_args_list
        for row in [args[0]]
        if hasattr(row, "event")
    ]


class UploadGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_token_rejected_and_audited(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        db.execute.return_value = _select_result(None)

        with self.assertRaises(HTTPException) as ctx:
            await upload_to_slot(
                token="nope",
                request=_make_request(),
                file=_make_upload(b"x", "a.mp3", "audio/mpeg"),
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("rejected_unknown_token", _added_events(db))

    async def test_already_consumed_rejected(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        slot = _make_slot(status="consumed")
        db.execute.return_value = _select_result(slot)

        with self.assertRaises(HTTPException) as ctx:
            await upload_to_slot(
                token="t",
                request=_make_request(),
                file=_make_upload(b"x", "a.mp3", "audio/mpeg"),
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("rejected_consumed", _added_events(db))

    async def test_expired_rejected(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        slot = _make_slot(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        db.execute.return_value = _select_result(slot)

        with self.assertRaises(HTTPException) as ctx:
            await upload_to_slot(
                token="t",
                request=_make_request(),
                file=_make_upload(b"x", "a.mp3", "audio/mpeg"),
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 410)
        self.assertIn("rejected_expired", _added_events(db))

    async def test_oversize_rejected_and_slot_not_consumed(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        slot = _make_slot(max_size_bytes=3)
        db.execute.return_value = _select_result(slot)

        # read_upload_file_limited reads max+1 bytes; returning >max triggers 413.
        big = _make_upload(b"abcd", "a.mp3", "audio/mpeg")
        with self.assertRaises(HTTPException) as ctx:
            await upload_to_slot(token="t", request=_make_request(), file=big, db=db)
        self.assertEqual(ctx.exception.status_code, 413)
        self.assertIn("rejected_oversize", _added_events(db))
        # only the slot SELECT happened; no consume UPDATE
        self.assertEqual(db.execute.call_count, 1)

    async def test_mime_not_allowed_rejected(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        slot = _make_slot(allowed_mime=["audio/*"])
        db.execute.return_value = _select_result(slot)

        with self.assertRaises(HTTPException) as ctx:
            await upload_to_slot(
                token="t",
                request=_make_request(),
                file=_make_upload(b"x", "clip.mp4", "video/mp4"),
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 415)
        self.assertIn("rejected_mime", _added_events(db))
        self.assertEqual(db.execute.call_count, 1)


class UploadHappyPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_upload_stores_runs_and_consumes(self) -> None:
        slot = _make_slot(allowed_mime=["audio/*"])
        workflow = SimpleNamespace(
            id=slot.workflow_id,
            owner_id=uuid.uuid4(),
            nodes=[{"id": "n1", "type": "fileUploadTrigger", "data": {"label": "audio"}}],
            edges=[],
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.execute.side_effect = [
            _select_result(slot),  # slot lookup
            _update_result(1),  # consume_slot atomic UPDATE wins
            _select_result(workflow),  # workflow lookup
        ]

        stored = SimpleNamespace(
            id=uuid.uuid4(), filename="rec.mp3", mime_type="audio/mpeg", size_bytes=3
        )
        exec_result = SimpleNamespace(
            outputs={"text": "hello"}, node_results=[], status="success", execution_time_ms=12.0
        )

        with (
            patch(
                "app.api.file_intake.file_storage.store_file",
                new=AsyncMock(return_value=stored),
            ),
            patch("app.api.file_intake.execute_workflow", return_value=exec_result),
            patch("app.api.mcp.get_credentials_context_for_user", new=AsyncMock(return_value={})),
            patch("app.api.workflows.collect_referenced_workflows", new=AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                new=AsyncMock(return_value={}),
            ),
        ):
            result = await upload_to_slot(
                token="t",
                request=_make_request(),
                file=_make_upload(b"abc", "rec.mp3", "audio/mpeg"),
                db=db,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["output"], {"text": "hello"})
        self.assertEqual(result["file"]["name"], "rec.mp3")
        self.assertEqual(result["file"]["id"], str(stored.id))
        self.assertEqual(slot.uploaded_file_id, stored.id)
        self.assertIn("upload_accepted", _added_events(db))
        db.commit.assert_awaited()

    async def test_concurrent_loser_rejected_when_consume_returns_zero(self) -> None:
        slot = _make_slot()
        db = AsyncMock()
        db.add = MagicMock()
        db.execute.side_effect = [
            _select_result(slot),  # slot lookup (still pending)
            _update_result(0),  # lost the atomic race
        ]
        with self.assertRaises(HTTPException) as ctx:
            await upload_to_slot(
                token="t",
                request=_make_request(),
                file=_make_upload(b"abc", "rec.mp3", "audio/mpeg"),
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("rejected_consumed", _added_events(db))


class SlotStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_slot_returns_no_run(self) -> None:
        from app.api.file_intake import get_slot_status

        owner_id = uuid.uuid4()
        slot = _make_slot(status="pending")
        workflow = SimpleNamespace(id=slot.workflow_id, owner_id=owner_id)
        db = AsyncMock()
        db.get.side_effect = [slot, workflow]
        user = SimpleNamespace(id=owner_id)

        result = await get_slot_status(slot_id=slot.id, current_user=user, db=db)
        self.assertEqual(result["status"], "pending")
        self.assertIsNone(result["run"])

    async def test_consumed_slot_returns_run_result(self) -> None:
        from app.api.file_intake import get_slot_status

        owner_id = uuid.uuid4()
        run_id = uuid.uuid4()
        slot = _make_slot(status="consumed", run_id=str(run_id))
        workflow = SimpleNamespace(id=slot.workflow_id, owner_id=owner_id)
        history = SimpleNamespace(
            id=run_id,
            status="success",
            outputs={"Result": {"result": "ok"}},
            node_results=[{"node_id": "n2", "status": "success"}],
            execution_time_ms=5.0,
        )
        db = AsyncMock()
        db.get.side_effect = [slot, workflow, history]
        user = SimpleNamespace(id=owner_id)

        result = await get_slot_status(slot_id=slot.id, current_user=user, db=db)
        self.assertEqual(result["status"], "consumed")
        self.assertIsNotNone(result["run"])
        self.assertEqual(result["run"]["status"], "success")
        self.assertEqual(result["run"]["execution_history_id"], str(run_id))

    async def test_other_users_slot_is_404(self) -> None:
        from app.api.file_intake import get_slot_status

        slot = _make_slot(status="pending")
        workflow = SimpleNamespace(id=slot.workflow_id, owner_id=uuid.uuid4())
        db = AsyncMock()
        db.get.side_effect = [slot, workflow]
        user = SimpleNamespace(id=uuid.uuid4())

        with self.assertRaises(HTTPException) as ctx:
            await get_slot_status(slot_id=slot.id, current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 404)


class TokenNeverStoredPlaintextTest(unittest.TestCase):
    def test_slot_stores_only_hash(self) -> None:
        token = file_intake_service.generate_token()
        self.assertNotEqual(file_intake_service.hash_token(token), token)
        self.assertEqual(len(file_intake_service.hash_token(token)), 64)
