import asyncio
import contextlib
import unittest
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from types import TracebackType
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.chats import (
    clear_conversations,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    stream_conversation,
    update_conversation,
)
from app.db.models import CredentialType, DashboardConversation, DashboardMessage
from app.models.chat_schemas import ConversationCreate, ConversationUpdate


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
    conv.last_credential_id = None
    conv.last_model = None
    conv.created_at = datetime.now(timezone.utc)
    conv.updated_at = datetime.now(timezone.utc)
    conv.messages = []
    return conv


def _make_db(scalars_result: list | None = None, scalar_one: object = None) -> AsyncMock:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    if scalars_result is not None:
        mock_result.scalars.return_value.all.return_value = scalars_result
    mock_result.scalar_one_or_none.return_value = scalar_one
    mock_db.execute.return_value = mock_result
    return mock_db


def _close_created_task(coro: object) -> MagicMock:
    if hasattr(coro, "close"):
        coro.close()
    return MagicMock()


class _QueueContext:
    def __init__(self, queue: asyncio.Queue[object | None] | None) -> None:
        self.queue = queue

    async def __aenter__(self) -> asyncio.Queue[object | None] | None:
        return self.queue

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class TestListConversations(unittest.IsolatedAsyncioTestCase):
    async def test_returns_empty_list_when_no_conversations(self) -> None:
        user = _make_user()
        mock_db = _make_db(scalars_result=[])

        result = await list_conversations(current_user=user, db=mock_db)

        self.assertEqual(result.conversations, [])

    async def test_returns_conversations_for_user(self) -> None:
        user = _make_user()
        conv = _make_conversation(user.id, title="My Chat")
        mock_db = _make_db(scalars_result=[conv])

        result = await list_conversations(current_user=user, db=mock_db)

        self.assertEqual(len(result.conversations), 1)
        self.assertEqual(result.conversations[0].title, "My Chat")

    async def test_pinned_conversations_appear_first(self) -> None:
        user = _make_user()
        pinned = _make_conversation(user.id, title="Pinned", is_pinned=True)
        unpinned = _make_conversation(user.id, title="Unpinned", is_pinned=False)
        mock_db = _make_db(scalars_result=[pinned, unpinned])

        result = await list_conversations(current_user=user, db=mock_db)

        self.assertTrue(result.conversations[0].is_pinned)
        self.assertFalse(result.conversations[1].is_pinned)


class TestCreateConversation(unittest.IsolatedAsyncioTestCase):
    async def test_creates_with_given_title(self) -> None:
        user = _make_user()
        mock_db = AsyncMock()

        added: list[DashboardConversation] = []
        mock_db.add = MagicMock(side_effect=lambda obj: added.append(obj))

        async def fake_refresh(obj: DashboardConversation) -> None:
            obj.id = uuid.uuid4()
            obj.is_pinned = False
            obj.is_running = False
            obj.has_unread = False
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)

        mock_db.refresh.side_effect = fake_refresh

        result = await create_conversation(
            body=ConversationCreate(title="Hello"),
            current_user=user,
            db=mock_db,
        )

        self.assertEqual(result.title, "Hello")
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    async def test_defaults_title_to_new_chat(self) -> None:
        user = _make_user()
        mock_db = AsyncMock()

        added: list[DashboardConversation] = []
        mock_db.add = MagicMock(side_effect=lambda obj: added.append(obj))

        async def fake_refresh(obj: DashboardConversation) -> None:
            obj.id = uuid.uuid4()
            obj.is_pinned = False
            obj.is_running = False
            obj.has_unread = False
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)

        mock_db.refresh.side_effect = fake_refresh

        await create_conversation(
            body=ConversationCreate(),
            current_user=user,
            db=mock_db,
        )

        self.assertEqual(added[0].title, "New Chat")


class TestGetConversation(unittest.IsolatedAsyncioTestCase):
    async def test_returns_conversation_with_messages(self) -> None:
        user = _make_user()
        conv = _make_conversation(user.id)
        credential_id = uuid.uuid4()
        conv.last_credential_id = credential_id
        conv.last_model = "gpt-4o"
        msg = DashboardMessage()
        msg.id = uuid.uuid4()
        msg.conversation_id = conv.id
        msg.role = "user"
        msg.content = "Hello"
        msg.created_at = datetime.now(timezone.utc)
        conv.messages = [msg]

        mock_db = _make_db(scalar_one=conv)

        result = await get_conversation(
            conversation_id=conv.id,
            current_user=user,
            db=mock_db,
        )

        self.assertEqual(result.id, conv.id)
        self.assertEqual(result.last_credential_id, credential_id)
        self.assertEqual(result.last_model, "gpt-4o")
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0].content, "Hello")

    async def test_raises_404_for_wrong_user(self) -> None:
        user = _make_user()
        mock_db = _make_db(scalar_one=None)

        with self.assertRaises(HTTPException) as ctx:
            await get_conversation(
                conversation_id=uuid.uuid4(),
                current_user=user,
                db=mock_db,
            )

        self.assertEqual(ctx.exception.status_code, 404)


class TestUpdateConversation(unittest.IsolatedAsyncioTestCase):
    async def test_renames_conversation(self) -> None:
        user = _make_user()
        conv = _make_conversation(user.id, title="Old Title")
        mock_db = _make_db(scalar_one=conv)
        mock_db.refresh.side_effect = AsyncMock()

        result = await update_conversation(
            conversation_id=conv.id,
            body=ConversationUpdate(title="New Title"),
            current_user=user,
            db=mock_db,
        )

        self.assertEqual(conv.title, "New Title")
        self.assertEqual(result.title, "New Title")

    async def test_pins_conversation(self) -> None:
        user = _make_user()
        conv = _make_conversation(user.id, is_pinned=False)
        mock_db = _make_db(scalar_one=conv)
        mock_db.refresh.side_effect = AsyncMock()

        await update_conversation(
            conversation_id=conv.id,
            body=ConversationUpdate(is_pinned=True),
            current_user=user,
            db=mock_db,
        )

        self.assertTrue(conv.is_pinned)

    async def test_raises_404_for_wrong_user(self) -> None:
        user = _make_user()
        mock_db = _make_db(scalar_one=None)

        with self.assertRaises(HTTPException) as ctx:
            await update_conversation(
                conversation_id=uuid.uuid4(),
                body=ConversationUpdate(title="x"),
                current_user=user,
                db=mock_db,
            )

        self.assertEqual(ctx.exception.status_code, 404)


class TestDeleteConversation(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_conversation(self) -> None:
        user = _make_user()
        conv = _make_conversation(user.id)
        mock_db = _make_db(scalar_one=conv)

        await delete_conversation(
            conversation_id=conv.id,
            current_user=user,
            db=mock_db,
        )

        mock_db.delete.assert_awaited_once_with(conv)
        mock_db.commit.assert_awaited()

    async def test_raises_404_for_wrong_user(self) -> None:
        user = _make_user()
        mock_db = _make_db(scalar_one=None)

        with self.assertRaises(HTTPException) as ctx:
            await delete_conversation(
                conversation_id=uuid.uuid4(),
                current_user=user,
                db=mock_db,
            )

        self.assertEqual(ctx.exception.status_code, 404)


class TestClearConversations(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_all_conversations_for_user(self) -> None:
        user = _make_user()
        mock_db = AsyncMock()

        await clear_conversations(current_user=user, db=mock_db)

        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()


class TestStreamConversation(unittest.IsolatedAsyncioTestCase):
    async def test_emits_heartbeat_while_waiting_for_chat_events(self) -> None:
        user = _make_user()
        conv = _make_conversation(user.id)
        queue: asyncio.Queue[object | None] = asyncio.Queue()
        mock_db = AsyncMock()

        @contextlib.asynccontextmanager
        async def _fake_session() -> AsyncGenerator[AsyncMock, None]:
            yield mock_db

        with (
            patch(
                "app.api.chats._get_conversation_or_404",
                new_callable=AsyncMock,
                return_value=conv,
            ),
            patch("app.api.chats.async_session_maker", _fake_session),
            patch("app.api.chats.registry.subscribe", return_value=_QueueContext(queue)),
            patch("app.api.chats.CHAT_STREAM_HEARTBEAT_SECONDS", 0.001),
        ):
            response = await stream_conversation(
                conversation_id=conv.id,
                user_id=user.id,
            )

            stream = response.body_iterator
            self.assertEqual(await stream.__anext__(), ": ping\n\n")

            await queue.put({"type": "content", "text": "hello"})
            self.assertEqual(
                await stream.__anext__(),
                'data: {"type": "content", "text": "hello"}\n\n',
            )

            await queue.put(None)
            self.assertEqual(await stream.__anext__(), 'data: {"type": "done"}\n\n')


class TestSendMessageAuth(unittest.IsolatedAsyncioTestCase):
    async def test_raises_404_when_conversation_not_found(self) -> None:
        from app.api.chats import send_message
        from app.models.chat_schemas import MessageCreate

        user = _make_user()
        mock_db = _make_db(scalar_one=None)

        with self.assertRaises(HTTPException) as ctx:
            await send_message(
                http_request=MagicMock(),
                conversation_id=uuid.uuid4(),
                body=MessageCreate(
                    content="hello", credential_id=str(uuid.uuid4()), model="gpt-4o"
                ),
                current_user=user,
                db=mock_db,
            )

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_uses_accessible_credential_and_returns_202(self) -> None:
        from app.api.chats import send_message
        from app.models.chat_schemas import MessageCreate

        user = _make_user()
        conv = _make_conversation(user.id)
        credential_id = uuid.uuid4()
        credential = MagicMock()
        credential.id = credential_id
        credential.type = CredentialType.openai
        credential.encrypted_config = "encrypted-config"

        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conv
        messages_result = MagicMock()
        messages_result.scalars.return_value.all.return_value = []
        mock_db = AsyncMock()
        mock_db.execute.side_effect = [conv_result, messages_result]
        mock_db.add = MagicMock()

        with (
            patch(
                "app.api.chats.get_accessible_credential",
                AsyncMock(return_value=credential),
            ) as get_accessible,
            patch(
                "app.api.chats._build_user_message",
                return_value={"role": "user", "content": "hello"},
            ),
            patch("app.api.chats.build_public_base_url", return_value="http://testserver"),
            patch("app.api.chats.registry.create_task", new_callable=AsyncMock),
            patch("asyncio.create_task", side_effect=_close_created_task),
        ):
            result = await send_message(
                http_request=MagicMock(),
                conversation_id=conv.id,
                body=MessageCreate(
                    content="hello",
                    credential_id=str(credential_id),
                    model="gpt-4o",
                ),
                current_user=user,
                db=mock_db,
            )

        self.assertEqual(result.conversation_id, conv.id)
        get_accessible.assert_awaited_once_with(mock_db, credential_id, user.id)
        mock_db.commit.assert_awaited()

    async def test_send_message_saves_credential_and_model_to_conversation(self) -> None:
        from app.api.chats import send_message
        from app.models.chat_schemas import MessageCreate

        user = _make_user()
        conv = _make_conversation(user.id)
        credential_id = uuid.uuid4()
        credential = MagicMock()
        credential.id = credential_id
        credential.type = CredentialType.openai
        credential.encrypted_config = "encrypted-config"

        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conv
        messages_result = MagicMock()
        messages_result.scalars.return_value.all.return_value = []
        mock_db = AsyncMock()
        mock_db.execute.side_effect = [conv_result, messages_result]
        mock_db.add = MagicMock()

        with (
            patch(
                "app.api.chats.get_accessible_credential",
                AsyncMock(return_value=credential),
            ),
            patch(
                "app.api.chats._build_user_message",
                return_value={"role": "user", "content": "hello"},
            ),
            patch("app.api.chats.build_public_base_url", return_value="http://testserver"),
            patch("app.api.chats.registry.create_task", new_callable=AsyncMock),
            patch("asyncio.create_task", side_effect=_close_created_task),
        ):
            await send_message(
                http_request=MagicMock(),
                conversation_id=conv.id,
                body=MessageCreate(
                    content="hello",
                    credential_id=str(credential_id),
                    model="gpt-4o",
                ),
                current_user=user,
                db=mock_db,
            )

        self.assertEqual(conv.last_credential_id, credential_id)
        self.assertEqual(conv.last_model, "gpt-4o")


class TestGenerateConversationTitle(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_uses_first_word(self) -> None:
        from app.api.chats import _fallback_title_from_content

        self.assertEqual(
            _fallback_title_from_content("Please explain dashboard automation history"),
            "Please explain dashboard automation history...",
        )

    async def test_fallback_uses_first_space_after_50_characters(self) -> None:
        from app.api.chats import _fallback_title_from_content

        self.assertEqual(
            _fallback_title_from_content(
                "Please explain dashboard automation history for account owners today"
            ),
            "Please explain dashboard automation history for account...",
        )

    async def test_fallback_ignores_attachment_metadata(self) -> None:
        from app.api.chats import _fallback_title_from_content

        self.assertEqual(
            _fallback_title_from_content("Summarize this\n\n[ATTACHED FILE: report.pdf]\nText"),
            "Summarize this...",
        )

    async def test_endpoint_stores_fallback_title_for_new_chat(self) -> None:
        from app.api.chats import generate_conversation_title
        from app.models.chat_schemas import ConversationTitleGenerate

        user = _make_user()
        conv = _make_conversation(user.id, title="New Chat")
        user_msg = DashboardMessage()
        user_msg.role = "user"
        user_msg.content = "Why do I get a 500?"
        assistant_msg = DashboardMessage()
        assistant_msg.role = "assistant"
        assistant_msg.content = "The credential field is wrong."

        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conv
        messages_result = MagicMock()
        messages_result.scalars.return_value.all.return_value = [user_msg, assistant_msg]

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [conv_result, messages_result]

        result = await generate_conversation_title(
            conversation_id=conv.id,
            body=ConversationTitleGenerate(
                credential_id=str(uuid.UUID(int=1)),
                model="gpt-4o",
            ),
            current_user=user,
            db=mock_db,
        )

        self.assertEqual(result.title, "Why do I get a 500...")
        self.assertEqual(conv.title, "Why do I get a 500...")
        mock_db.commit.assert_awaited_once()
        mock_db.refresh.assert_awaited_once_with(conv)

    async def test_endpoint_does_not_overwrite_manual_title(self) -> None:
        from app.api.chats import generate_conversation_title
        from app.models.chat_schemas import ConversationTitleGenerate

        conv = _make_conversation(uuid.uuid4(), title="Manual Title")
        user = _make_user(conv.user_id)
        mock_db = _make_db(scalar_one=conv)

        result = await generate_conversation_title(
            conversation_id=conv.id,
            body=ConversationTitleGenerate(
                credential_id=str(uuid.UUID(int=1)),
                model="gpt-4o",
            ),
            current_user=user,
            db=mock_db,
        )

        self.assertEqual(result.title, "Manual Title")
        self.assertEqual(conv.title, "Manual Title")
        mock_db.commit.assert_not_awaited()


class IngestToolEventTests(unittest.TestCase):
    def test_tool_start_appends_running_entry(self) -> None:
        from app.api.chats import _ingest_tool_event

        bucket: list[dict] = []
        _ingest_tool_event(
            bucket,
            {
                "type": "tool_start",
                "id": "tc_1",
                "name": "list_workflows",
                "label": "Listing workflows...",
                "args": {"k": "v"},
            },
        )
        self.assertEqual(len(bucket), 1)
        self.assertEqual(bucket[0]["id"], "tc_1")
        self.assertEqual(bucket[0]["status"], "running")
        self.assertEqual(bucket[0]["args"], {"k": "v"})

    def test_tool_end_updates_matching_entry(self) -> None:
        from app.api.chats import _ingest_tool_event

        bucket: list[dict] = [
            {
                "id": "tc_1",
                "name": "list_workflows",
                "label": "Listing...",
                "args": {},
                "status": "running",
            }
        ]
        _ingest_tool_event(
            bucket,
            {
                "type": "tool_end",
                "id": "tc_1",
                "response_summary": "3 workflows",
                "elapsed_ms": 42.0,
                "status": "success",
            },
        )
        self.assertEqual(bucket[0]["status"], "success")
        self.assertEqual(bucket[0]["response_summary"], "3 workflows")
        self.assertEqual(bucket[0]["elapsed_ms"], 42.0)

    def test_compressed_appends_compression_entry(self) -> None:
        from app.api.chats import _ingest_tool_event

        bucket: list[dict] = []
        _ingest_tool_event(
            bucket,
            {
                "type": "compressed",
                "messages_compressed": 18,
                "tokens_before": 98_000,
                "tokens_after": 12_000,
                "elapsed_ms": 412.0,
            },
        )
        self.assertEqual(len(bucket), 1)
        self.assertEqual(bucket[0]["name"], "_context_compression")
        self.assertEqual(bucket[0]["status"], "compressed")
        self.assertEqual(bucket[0]["args"], {"messages_compressed": 18})
        self.assertEqual(bucket[0]["response_summary"], "~98k → ~12k tokens")
