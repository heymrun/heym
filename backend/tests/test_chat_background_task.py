import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.chats import mark_conversation_read, send_message
from app.db.models import CredentialType, DashboardChatQueueItem, DashboardConversation
from app.models.chat_schemas import MessageCreate


def _make_user(user_id: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    return user


def _make_conversation(
    user_id: uuid.UUID,
    title: str = "Test Chat",
    is_pinned: bool = False,
) -> DashboardConversation:
    conv = DashboardConversation()
    conv.id = uuid.uuid4()
    conv.user_id = user_id
    conv.title = title
    conv.is_pinned = is_pinned
    conv.is_running = False
    conv.has_unread = False
    conv.created_at = datetime.now(timezone.utc)
    conv.updated_at = datetime.now(timezone.utc)
    conv.messages = []
    return conv


def _make_credential(cred_type: CredentialType = CredentialType.openai) -> MagicMock:
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.type = cred_type
    cred.encrypted_config = {}
    return cred


def _close_created_task(coro: object) -> MagicMock:
    if hasattr(coro, "close"):
        coro.close()
    return MagicMock()


class TestSendMessage(unittest.IsolatedAsyncioTestCase):
    async def test_returns_202_and_queues_task(self) -> None:
        user = _make_user()
        conv = _make_conversation(user.id)
        cred = _make_credential()
        cred_id = str(cred.id)

        mock_db = AsyncMock()
        mock_result_conv = MagicMock()
        mock_result_conv.scalar_one_or_none.return_value = conv
        mock_result_msgs = MagicMock()
        mock_result_msgs.scalars.return_value.all.return_value = []
        mock_db.execute.side_effect = [mock_result_conv, mock_result_msgs]
        mock_db.add = MagicMock()

        http_request = MagicMock()
        http_request.url = MagicMock()

        body = MessageCreate(
            content="Hello",
            credential_id=cred_id,
            model="gpt-4o",
        )

        with (
            patch(
                "app.api.chats.get_accessible_credential", new_callable=AsyncMock, return_value=cred
            ),
            patch(
                "app.api.chats._build_user_message",
                return_value={"role": "user", "content": "Hello"},
            ),
            patch("app.api.chats.build_public_base_url", return_value="http://localhost"),
            patch(
                "app.api.chats.registry.create_task",
                new_callable=AsyncMock,
            ),
            patch("asyncio.create_task", side_effect=_close_created_task) as mock_create_task,
        ):
            result = await send_message(
                http_request=http_request,
                conversation_id=conv.id,
                body=body,
                current_user=user,
                db=mock_db,
            )

        self.assertEqual(result.conversation_id, conv.id)
        self.assertEqual(result.status, "started")
        self.assertIsNotNone(result.user_message)
        mock_create_task.assert_called_once()
        mock_db.commit.assert_awaited()

    async def test_running_conversation_persists_queued_message_without_starting_task(self) -> None:
        user = _make_user()
        conv = _make_conversation(user.id)
        conv.is_running = True
        cred = _make_credential()

        mock_db = AsyncMock()
        mock_result_conv = MagicMock()
        mock_result_conv.scalar_one_or_none.return_value = conv
        mock_result_msgs = MagicMock()
        mock_result_msgs.scalars.return_value.all.return_value = [
            MagicMock(role="user", content="First")
        ]
        mock_db.execute.side_effect = [mock_result_conv, mock_result_msgs]
        added: list[object] = []
        mock_db.add = MagicMock(side_effect=lambda obj: added.append(obj))

        body = MessageCreate(
            content="Second",
            credential_id=str(cred.id),
            model="gpt-4o",
        )

        with (
            patch(
                "app.api.chats.get_accessible_credential", new_callable=AsyncMock, return_value=cred
            ),
            patch("app.api.chats.registry.publish", new_callable=AsyncMock) as publish,
            patch("app.api.chats.registry.create_task", new_callable=AsyncMock) as create_task,
            patch("asyncio.create_task", side_effect=_close_created_task) as mock_create_task,
        ):
            result = await send_message(
                http_request=MagicMock(),
                conversation_id=conv.id,
                body=body,
                current_user=user,
                db=mock_db,
            )

        self.assertEqual(result.status, "queued")
        self.assertIsNotNone(result.queued_message)
        self.assertEqual(result.queued_message.content, "Second")
        self.assertEqual(result.queued_message.credential_id, cred.id)
        self.assertTrue(any(isinstance(obj, DashboardChatQueueItem) for obj in added))
        create_task.assert_not_awaited()
        mock_create_task.assert_not_called()
        publish.assert_awaited_once()

    async def test_raises_404_when_credential_not_found(self) -> None:
        user = _make_user()
        conv = _make_conversation(user.id)

        mock_db = AsyncMock()
        mock_result_conv = MagicMock()
        mock_result_conv.scalar_one_or_none.return_value = conv
        mock_result_msgs = MagicMock()
        mock_result_msgs.scalars.return_value.all.return_value = []
        mock_db.execute.side_effect = [mock_result_conv, mock_result_msgs]

        http_request = MagicMock()
        body = MessageCreate(content="Hi", credential_id=str(uuid.uuid4()), model="gpt-4o")

        with patch(
            "app.api.chats.get_accessible_credential", new_callable=AsyncMock, return_value=None
        ):
            with self.assertRaises(HTTPException) as ctx:
                await send_message(
                    http_request=http_request,
                    conversation_id=conv.id,
                    body=body,
                    current_user=user,
                    db=mock_db,
                )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_raises_400_for_non_llm_credential(self) -> None:
        user = _make_user()
        conv = _make_conversation(user.id)
        cred = _make_credential(cred_type=CredentialType.bearer)

        mock_db = AsyncMock()
        mock_result_conv = MagicMock()
        mock_result_conv.scalar_one_or_none.return_value = conv
        mock_result_msgs = MagicMock()
        mock_result_msgs.scalars.return_value.all.return_value = []
        mock_db.execute.side_effect = [mock_result_conv, mock_result_msgs]

        http_request = MagicMock()
        body = MessageCreate(content="Hi", credential_id=str(cred.id), model="gpt-4o")

        with patch(
            "app.api.chats.get_accessible_credential", new_callable=AsyncMock, return_value=cred
        ):
            with self.assertRaises(HTTPException) as ctx:
                await send_message(
                    http_request=http_request,
                    conversation_id=conv.id,
                    body=body,
                    current_user=user,
                    db=mock_db,
                )
        self.assertEqual(ctx.exception.status_code, 400)


class TestMarkConversationRead(unittest.IsolatedAsyncioTestCase):
    async def test_clears_has_unread(self) -> None:
        user = _make_user()
        conv = _make_conversation(user.id)
        conv.has_unread = True

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = conv
        mock_db.execute.return_value = mock_result

        await mark_conversation_read(
            conversation_id=conv.id,
            current_user=user,
            db=mock_db,
        )

        self.assertFalse(conv.has_unread)
        mock_db.commit.assert_awaited_once()

    async def test_raises_404_when_conversation_not_found(self) -> None:
        user = _make_user()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with self.assertRaises(HTTPException) as ctx:
            await mark_conversation_read(
                conversation_id=uuid.uuid4(),
                current_user=user,
                db=mock_db,
            )
        self.assertEqual(ctx.exception.status_code, 404)


# The chat task registry is now backed by Postgres LISTEN/NOTIFY plus a
# chat_stream_events table; its behavior is exercised end-to-end through the
# chat endpoints rather than via white-box tests against the old in-memory dict.
