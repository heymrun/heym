"""Editing an earlier user message: the conversation rewinds and the edit is sent again."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy.sql.dml import Delete

from app.api.chats import send_message
from app.db.models import CredentialType, DashboardConversation, DashboardMessage
from app.models.chat_schemas import MessageCreate
from app.services.chat_message_edit import (
    carried_attachment,
    messages_from_edit,
    split_attachment_block,
)

FILE_ID = uuid.UUID("0b8c2a8e-7d55-4e8e-9f3c-2b1d6f3a9c10")
DRIVE_BLOCK = (
    f"\n\n[ATTACHED DRIVE FILE: report.pdf · id {FILE_ID} · 2048 bytes · application/pdf]\n"
    "The file is in Heym Drive; its content is not in this message. Open it with "
    "inspect_file and run_python."
)


def _message(role: str, content: str, offset: int) -> DashboardMessage:
    message = DashboardMessage()
    message.id = uuid.uuid4()
    message.role = role
    message.content = content
    message.created_at = datetime(2026, 11, 8, tzinfo=timezone.utc) + timedelta(seconds=offset)
    return message


def _conversation(user_id: uuid.UUID, *, running: bool = False) -> DashboardConversation:
    conversation = DashboardConversation()
    conversation.id = uuid.uuid4()
    conversation.user_id = user_id
    conversation.title = "Quarterly numbers"
    conversation.is_running = running
    conversation.has_unread = False
    conversation.queue_paused_by_message_id = None
    return conversation


def _credential() -> MagicMock:
    credential = MagicMock()
    credential.id = uuid.uuid4()
    credential.type = CredentialType.openai
    return credential


def _db(conversation: DashboardConversation, messages: list[DashboardMessage]) -> AsyncMock:
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conversation
    messages_result = MagicMock()
    messages_result.scalars.return_value.all.return_value = messages
    db = AsyncMock()
    db.execute.side_effect = [conv_result, messages_result, MagicMock()]
    db.add = MagicMock()
    return db


def _close(coro: object) -> MagicMock:
    if hasattr(coro, "close"):
        coro.close()
    return MagicMock()


def _deleted_ids(db: AsyncMock) -> set[uuid.UUID]:
    for call in db.execute.call_args_list:
        statement = call.args[0]
        if isinstance(statement, Delete):
            compiled = statement.compile()
            ids: set[uuid.UUID] = set()
            for value in compiled.params.values():
                if isinstance(value, list):
                    ids.update(value)
            return ids
    raise AssertionError("no delete statement was executed")


class TestEditHelpers(unittest.TestCase):
    def test_split_attachment_block_finds_the_first_server_marker(self) -> None:
        text, block = split_attachment_block("Summarise this" + DRIVE_BLOCK)
        self.assertEqual(text, "Summarise this")
        self.assertEqual(block, DRIVE_BLOCK)

    def test_split_attachment_block_without_an_attachment(self) -> None:
        self.assertEqual(split_attachment_block("Just text"), ("Just text", ""))

    def test_carried_attachment_rebuilds_a_drive_file_from_its_id(self) -> None:
        carried = carried_attachment("Summarise this" + DRIVE_BLOCK)
        self.assertEqual(carried.drive_file_id, FILE_ID)
        self.assertEqual(carried.text_tail, "")

    def test_carried_attachment_keeps_inline_file_text(self) -> None:
        block = "\n\n[ATTACHED FILE: notes.txt]\nline one\nline two"
        carried = carried_attachment("Read the notes" + block)
        self.assertIsNone(carried.drive_file_id)
        self.assertEqual(carried.text_tail, block)

    def test_carried_attachment_without_an_attachment(self) -> None:
        carried = carried_attachment("Nothing attached")
        self.assertIsNone(carried.drive_file_id)
        self.assertEqual(carried.text_tail, "")

    def test_messages_from_edit_returns_the_message_and_everything_after(self) -> None:
        first = _message("user", "one", 0)
        reply = _message("assistant", "two", 1)
        second = _message("user", "three", 2)
        last = _message("assistant", "four", 3)
        dropped = messages_from_edit([first, reply, second, last], second.id)
        self.assertEqual(dropped, [second, last])

    def test_messages_from_edit_refuses_an_assistant_message(self) -> None:
        reply = _message("assistant", "two", 1)
        self.assertIsNone(messages_from_edit([_message("user", "one", 0), reply], reply.id))

    def test_messages_from_edit_refuses_an_unknown_id(self) -> None:
        self.assertIsNone(messages_from_edit([_message("user", "one", 0)], uuid.uuid4()))


class TestSendEditedMessage(unittest.IsolatedAsyncioTestCase):
    async def _send(
        self,
        conversation: DashboardConversation,
        messages: list[DashboardMessage],
        body: MessageCreate,
        *,
        file_access: object | None = None,
    ) -> tuple[object, AsyncMock, MagicMock, MagicMock]:
        user = MagicMock()
        user.id = conversation.user_id
        db = _db(conversation, messages)
        process_chat = MagicMock()
        with (
            patch(
                "app.api.chats.get_accessible_credential",
                new_callable=AsyncMock,
                return_value=self.credential,
            ),
            patch(
                "app.api.chats.get_accessible_file",
                new_callable=AsyncMock,
                return_value=file_access,
            ),
            patch("app.api.chats.build_public_base_url", return_value="http://localhost"),
            patch("app.api.chats.registry.create_task", new_callable=AsyncMock),
            patch("app.api.chats._process_chat", process_chat),
            patch(
                "app.api.chats._build_user_message",
                side_effect=lambda text, attachment: {"role": "user", "content": text},
            ) as build_user_message,
            patch("asyncio.create_task", side_effect=_close),
        ):
            result = await send_message(
                http_request=MagicMock(),
                conversation_id=conversation.id,
                body=body,
                current_user=user,
                db=db,
            )
        return result, db, process_chat, build_user_message

    def setUp(self) -> None:
        self.credential = _credential()
        self.user_id = uuid.uuid4()

    def _body(self, content: str, edit_message_id: uuid.UUID) -> MessageCreate:
        return MessageCreate(
            content=content,
            credential_id=str(self.credential.id),
            model="gpt-4o",
            edit_message_id=edit_message_id,
        )

    async def test_edit_removes_the_message_and_everything_after_it(self) -> None:
        conversation = _conversation(self.user_id)
        first = _message("user", "First question", 0)
        reply = _message("assistant", "First answer", 1)
        edited = _message("user", "Second question", 2)
        later_reply = _message("assistant", "Second answer", 3)
        later = _message("user", "Third question", 4)
        messages = [first, reply, edited, later_reply, later]

        result, db, process_chat, _ = await self._send(
            conversation, messages, self._body("Second question, rephrased", edited.id)
        )

        self.assertEqual(result.status, "started")
        self.assertEqual(_deleted_ids(db), {edited.id, later_reply.id, later.id})
        added = db.add.call_args.args[0]
        self.assertIsInstance(added, DashboardMessage)
        self.assertEqual(added.content, "Second question, rephrased")
        self.assertNotIn(added.id, {edited.id, later_reply.id, later.id})
        kwargs = process_chat.call_args.kwargs
        self.assertEqual(kwargs["content"], "Second question, rephrased")
        self.assertEqual(kwargs["model"], "gpt-4o")
        self.assertEqual(kwargs["credential_id"], self.credential.id)
        self.assertFalse(kwargs["should_generate_title"])
        self.assertEqual(conversation.last_model, "gpt-4o")

    async def test_editing_the_first_message_of_a_new_chat_titles_it_again(self) -> None:
        conversation = _conversation(self.user_id)
        conversation.title = "New Chat"
        first = _message("user", "Hello", 0)
        reply = _message("assistant", "Hi", 1)

        _, db, process_chat, _ = await self._send(
            conversation, [first, reply], self._body("Hello there", first.id)
        )

        self.assertEqual(_deleted_ids(db), {first.id, reply.id})
        self.assertTrue(process_chat.call_args.kwargs["should_generate_title"])

    async def test_edit_keeps_the_original_drive_attachment(self) -> None:
        conversation = _conversation(self.user_id)
        edited = _message("user", "Summarise this" + DRIVE_BLOCK, 0)
        reply = _message("assistant", "Summary", 1)
        row = SimpleNamespace(
            id=FILE_ID, filename="report.pdf", size_bytes=2048, mime_type="application/pdf"
        )

        _, _, process_chat, build_user_message = await self._send(
            conversation,
            [edited, reply],
            self._body("Summarise this in three bullets", edited.id),
            file_access=SimpleNamespace(file=row),
        )

        text, attachment = build_user_message.call_args.args
        self.assertEqual(text, "Summarise this in three bullets")
        self.assertEqual(attachment.kind, "file")
        self.assertEqual(attachment.file_id, FILE_ID)
        self.assertEqual(process_chat.call_args.kwargs["attachment_data"]["file_id"], str(FILE_ID))

    async def test_edit_keeps_a_drive_reference_the_user_can_no_longer_open_as_text(self) -> None:
        conversation = _conversation(self.user_id)
        edited = _message("user", "Summarise this" + DRIVE_BLOCK, 0)

        _, _, process_chat, build_user_message = await self._send(
            conversation, [edited], self._body("Summarise it", edited.id), file_access=None
        )

        text, attachment = build_user_message.call_args.args
        self.assertEqual(text, "Summarise it" + DRIVE_BLOCK)
        self.assertIsNone(attachment)
        self.assertIsNone(process_chat.call_args.kwargs["attachment_data"])

    async def test_edit_keeps_inline_file_text(self) -> None:
        conversation = _conversation(self.user_id)
        block = "\n\n[ATTACHED FILE: notes.txt]\nline one"
        edited = _message("user", "Read the notes" + block, 0)

        _, _, process_chat, _ = await self._send(
            conversation, [edited], self._body("Read the notes twice", edited.id)
        )

        self.assertEqual(process_chat.call_args.kwargs["content"], "Read the notes twice" + block)

    async def test_edit_is_refused_while_a_reply_is_running(self) -> None:
        conversation = _conversation(self.user_id, running=True)
        edited = _message("user", "Question", 0)

        with self.assertRaises(HTTPException) as caught:
            await self._send(conversation, [edited], self._body("Changed", edited.id))

        self.assertEqual(caught.exception.status_code, 409)

    async def test_edit_of_an_assistant_message_is_refused(self) -> None:
        conversation = _conversation(self.user_id)
        question = _message("user", "Question", 0)
        reply = _message("assistant", "Answer", 1)

        with self.assertRaises(HTTPException) as caught:
            await self._send(conversation, [question, reply], self._body("Changed", reply.id))

        self.assertEqual(caught.exception.status_code, 404)

    async def test_edit_of_a_message_from_another_conversation_is_refused(self) -> None:
        conversation = _conversation(self.user_id)
        question = _message("user", "Question", 0)

        with self.assertRaises(HTTPException) as caught:
            await self._send(conversation, [question], self._body("Changed", uuid.uuid4()))

        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
