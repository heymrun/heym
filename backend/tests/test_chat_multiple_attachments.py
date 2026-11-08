"""Several files attached to one chat message: storage, access checks, queue and runs."""

import json
import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api import chats
from app.api.ai_assistant import DashboardChatRequest, FileAttachment, _build_user_message
from app.db.models import CredentialType, DashboardChatQueueItem, DashboardConversation
from app.models.chat_schemas import ChatFileAttachment, MessageCreate
from app.services.chat_attachments import (
    MAX_CHAT_ATTACHMENTS,
    run_attachment,
    stored_attachments,
)
from app.services.chat_message_edit import attachment_blocks

REPORT_ID = uuid.UUID("0b8c2a8e-7d55-4e8e-9f3c-2b1d6f3a9c10")
NOTES_ID = uuid.UUID("5f0e7c1a-3b2d-4c6e-8a9f-1d2e3f4a5b6c")


def _drive(name: str, file_id: uuid.UUID, mime: str | None = None) -> FileAttachment:
    return FileAttachment(name=name, kind="file", file_id=file_id, size=10, mime=mime)


def _body(**fields: Any) -> MessageCreate:
    return MessageCreate(content="Compare", credential_id=str(uuid.uuid4()), model="m", **fields)


def _row(file_id: uuid.UUID, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=file_id, filename=name, size_bytes=65, mime_type=None)


class StoredAttachmentsTests(unittest.TestCase):
    def test_a_list_is_kept_in_order(self) -> None:
        stored = [{"name": "a.csv"}, {"name": "b.csv"}]
        self.assertEqual(stored_attachments(stored), stored)

    def test_a_row_queued_before_several_files_holds_one_dict(self) -> None:
        self.assertEqual(stored_attachments({"name": "a.csv"}), [{"name": "a.csv"}])

    def test_nothing_attached(self) -> None:
        self.assertEqual(stored_attachments(None), [])
        self.assertEqual(stored_attachments(["not a dict"]), [])


class RunAttachmentTests(unittest.TestCase):
    def test_a_single_attachment_is_always_the_one(self) -> None:
        only = FileAttachment(name="a.py", kind="text", content="x")
        self.assertIs(run_attachment([only], {}), only)

    def test_no_attachment(self) -> None:
        self.assertIsNone(run_attachment([], {"text": "x"}))

    def test_the_drive_id_in_the_inputs_picks_the_file(self) -> None:
        report, notes = _drive("report.pdf", REPORT_ID), _drive("burak.akgun", NOTES_ID)
        self.assertIs(run_attachment([report, notes], {"file_id": str(NOTES_ID)}), notes)

    def test_the_file_name_in_the_inputs_picks_the_file(self) -> None:
        first = FileAttachment(name="first.py", kind="text", content="a")
        second = FileAttachment(name="second.py", kind="text", content="b")
        self.assertIs(run_attachment([first, second], {"text": "Use second.py"}), second)

    def test_unnamed_runs_get_the_first_drive_file(self) -> None:
        code = FileAttachment(name="a.py", kind="text", content="a")
        report = _drive("report.pdf", REPORT_ID)
        self.assertIs(run_attachment([code, report], {}), report)

    def test_unnamed_inline_files_are_not_injected(self) -> None:
        first = FileAttachment(name="a.py", kind="text", content="a")
        second = FileAttachment(name="b.py", kind="text", content="b")
        self.assertIsNone(run_attachment([first, second], {"text": "something else"}))


class BuildUserMessageTests(unittest.TestCase):
    def test_every_attachment_adds_its_block_in_order(self) -> None:
        message = _build_user_message(
            "Compare these",
            [
                _drive("report.pdf", REPORT_ID, "application/pdf"),
                FileAttachment(name="notes.py", kind="text", content="print('hi')"),
                _drive("burak.akgun", NOTES_ID),
            ],
        )
        content = message["content"]
        self.assertTrue(content.startswith("Compare these\n\n[ATTACHED DRIVE FILE: report.pdf"))
        blocks = attachment_blocks(content)
        self.assertEqual(len(blocks), 3)
        self.assertIn(str(REPORT_ID), blocks[0])
        self.assertEqual(blocks[1], "\n\n[ATTACHED FILE: notes.py]\nprint('hi')")
        self.assertIn(f"burak.akgun · id {NOTES_ID}", blocks[2])

    def test_dashboard_chat_takes_the_single_field_first(self) -> None:
        request = DashboardChatRequest(
            credential_id=uuid.uuid4(),
            model="m",
            message="hi",
            attachment=FileAttachment(name="a.txt", kind="text", content="a"),
            attachments=[FileAttachment(name="b.txt", kind="text", content="b")],
        )
        names = [item.name for item in request.requested_attachments()]
        self.assertEqual(names, ["a.txt", "b.txt"])


class AttachmentsDataTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_drive_file_is_checked_and_described_in_order(self) -> None:
        rows = {REPORT_ID: _row(REPORT_ID, "report.pdf"), NOTES_ID: _row(NOTES_ID, "burak.akgun")}

        async def reachable(_db: object, file_id: uuid.UUID, _user_id: uuid.UUID) -> object:
            return SimpleNamespace(file=rows[file_id])

        body = _body(
            attachment=ChatFileAttachment(name="spoofed", kind="file", file_id=REPORT_ID),
            attachments=[
                ChatFileAttachment(name="code.py", kind="text", content="x = 1"),
                ChatFileAttachment(name="spoofed too", kind="file", file_id=NOTES_ID),
            ],
        )
        with patch.object(chats, "get_accessible_file", AsyncMock(side_effect=reachable)):
            data = await chats._attachments_data(MagicMock(), uuid.uuid4(), body)

        self.assertEqual([item["name"] for item in data], ["report.pdf", "code.py", "burak.akgun"])
        self.assertEqual(data[2]["file_id"], str(NOTES_ID))

    async def test_one_unreachable_file_refuses_the_whole_message(self) -> None:
        async def only_report(_db: object, file_id: uuid.UUID, _user_id: uuid.UUID) -> object:
            return (
                SimpleNamespace(file=_row(REPORT_ID, "report.pdf"))
                if file_id == REPORT_ID
                else None
            )

        body = _body(
            attachments=[
                ChatFileAttachment(name="report.pdf", kind="file", file_id=REPORT_ID),
                ChatFileAttachment(name="foreign.pdf", kind="file", file_id=uuid.uuid4()),
            ]
        )
        with patch.object(chats, "get_accessible_file", AsyncMock(side_effect=only_report)):
            with self.assertRaises(HTTPException) as caught:
                await chats._attachments_data(MagicMock(), uuid.uuid4(), body)
        self.assertEqual(caught.exception.status_code, 404)

    async def test_more_files_than_the_limit_are_refused(self) -> None:
        files = [
            ChatFileAttachment(name=f"{index}.txt", kind="text", content="x")
            for index in range(MAX_CHAT_ATTACHMENTS)
        ]
        body = _body(attachment=files[0], attachments=files)
        with self.assertRaises(HTTPException) as caught:
            await chats._attachments_data(MagicMock(), uuid.uuid4(), body)
        self.assertEqual(caught.exception.status_code, 400)

    def test_the_schema_caps_the_list(self) -> None:
        files = [
            ChatFileAttachment(name=f"{index}.txt", kind="text", content="x")
            for index in range(MAX_CHAT_ATTACHMENTS + 1)
        ]
        with self.assertRaises(ValidationError):
            _body(attachments=files)


def _queue_item(attachment: object) -> DashboardChatQueueItem:
    now = datetime.now(timezone.utc)
    return DashboardChatQueueItem(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        content="Compare",
        credential_id=uuid.uuid4(),
        model="m",
        attachment=attachment,
        allow_build=False,
        allow_skill_write=False,
        created_at=now,
        updated_at=now,
    )


class QueueTests(unittest.IsolatedAsyncioTestCase):
    def test_a_queued_message_lists_every_file_name(self) -> None:
        item = _queue_item([{"name": "report.pdf"}, {"name": "burak.akgun"}])
        response = chats._queued_message_response(item)
        self.assertEqual(response.attachment_names, ["report.pdf", "burak.akgun"])
        self.assertEqual(response.attachment_name, "report.pdf")

    def test_a_row_queued_before_several_files_keeps_its_name(self) -> None:
        response = chats._queued_message_response(_queue_item({"name": "q3.xlsx"}))
        self.assertEqual(response.attachment_names, ["q3.xlsx"])

    async def test_a_message_sent_while_running_queues_every_file(self) -> None:
        user_id = uuid.uuid4()
        conversation = DashboardConversation()
        conversation.id = uuid.uuid4()
        conversation.user_id = user_id
        conversation.title = "Chat"
        conversation.is_running = True
        conversation.queue_paused_by_message_id = None
        credential = SimpleNamespace(id=uuid.uuid4(), type=CredentialType.openai)
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        messages_result = MagicMock()
        messages_result.scalars.return_value.all.return_value = []
        db = AsyncMock()
        db.add = MagicMock()
        db.execute.side_effect = [conv_result, messages_result, MagicMock()]
        body = _body(
            attachments=[
                ChatFileAttachment(name="a.py", kind="text", content="a = 1"),
                ChatFileAttachment(name="b.py", kind="text", content="b = 2"),
            ]
        )

        with (
            patch.object(chats, "get_accessible_credential", AsyncMock(return_value=credential)),
            patch.object(chats.registry, "publish", AsyncMock()),
        ):
            response = await chats.send_message(
                http_request=MagicMock(),
                conversation_id=conversation.id,
                body=body,
                current_user=SimpleNamespace(id=user_id),
                db=db,
            )

        self.assertEqual(response.status, "queued")
        queued = db.add.call_args.args[0]
        self.assertEqual([item["name"] for item in queued.attachment], ["a.py", "b.py"])
        self.assertEqual(response.queued_message.attachment_names, ["a.py", "b.py"])

    async def test_a_dequeued_legacy_row_still_carries_its_file(self) -> None:
        item = _queue_item(
            {"name": "notes.py", "kind": "text", "content": "print('hi')", "file_id": None}
        )
        conversation = SimpleNamespace(
            id=item.conversation_id, queue_paused_by_message_id=None, is_running=True
        )
        db = AsyncMock()
        db.add = MagicMock()
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = item

        @asynccontextmanager
        async def maker() -> Any:
            yield db

        db.execute.side_effect = [conv_result, item_result]
        with (
            patch.object(chats, "async_session_maker", maker),
            patch.object(chats.registry, "publish", AsyncMock()),
        ):
            turn = await chats._dequeue_next_turn(str(item.conversation_id))

        self.assertEqual([data["name"] for data in turn.attachments], ["notes.py"])
        message = db.add.call_args.args[0]
        self.assertIn("[ATTACHED FILE: notes.py]\nprint('hi')", message.content)


class BuildSessionAttachmentTests(unittest.TestCase):
    def _session(self, attachments: list[FileAttachment]) -> Any:
        from app.api.chat_build import ChatBuildSession
        from app.services.chat_build_mode import BuildRequest
        from app.services.credential_catalog import CredentialPromptMode

        return ChatBuildSession(
            db=AsyncMock(),
            user=SimpleNamespace(id=uuid.uuid4()),
            request=BuildRequest(),
            selected_credential=SimpleNamespace(id=uuid.uuid4(), type="openai"),
            model="m",
            credential_mode=CredentialPromptMode.ASK_AND_CREATE,
            public_base_url="http://localhost",
            cancel_event=None,
            llm_session_id="conv-1",
            attachments=attachments,
        )

    def test_a_test_run_gets_the_file_its_inputs_name(self) -> None:
        report, notes = _drive("report.pdf", REPORT_ID), _drive("burak.akgun", NOTES_ID)
        session = self._session([report, notes])
        args = {"inputs": {"file_id": str(NOTES_ID)}}
        self.assertIs(session._run_attachment(args), notes)
        self.assertIs(session._run_attachment({"inputs": {}}), report)

    def test_a_named_sample_file_picks_the_attachment(self) -> None:
        report, notes = _drive("report.pdf", REPORT_ID), _drive("burak.akgun", NOTES_ID)
        session = self._session([report, notes])
        self.assertIs(session._run_attachment({"sample_file": "burak.akgun"}), notes)

    def test_skills_are_read_from_every_attached_zip(self) -> None:
        first = SimpleNamespace(name="alpha")
        second = SimpleNamespace(name="beta")
        readings = {
            "a": SimpleNamespace(skills=[first]),
            "b": SimpleNamespace(skills=[second]),
        }
        session = self._session(
            [
                FileAttachment(name="a.zip", kind="zip", content="a"),
                FileAttachment(name="b.zip", kind="zip", content="b"),
            ]
        )
        with (
            patch("app.api.chat_build.decode_zip_payload", side_effect=lambda value: value),
            patch("app.api.chat_build.read_zip", side_effect=lambda raw: readings[raw]),
        ):
            self.assertIs(session._attached_bundle("beta"), second)
            outcome = session._attached_bundle(None)
        result = json.loads(outcome.result)
        self.assertEqual(result["status"], "needs_choice")
        self.assertEqual(result["skills"], ["alpha", "beta"])
        self.assertIn("The zips have several skills", result["message"])


if __name__ == "__main__":
    unittest.main()
