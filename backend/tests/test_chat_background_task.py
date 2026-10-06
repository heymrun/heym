import asyncio
import unittest
import uuid
from datetime import datetime, timezone
from threading import Event
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.chats import (
    _cancel_events,
    _chat_tasks,
    _process_chat,
    _process_chat_queue,
    mark_conversation_read,
    send_message,
)
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
        mock_db.execute.side_effect = [mock_result_conv, mock_result_msgs, mock_result_conv]
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

    async def test_queued_message_starts_queue_worker_when_conversation_becomes_idle(self) -> None:
        user = _make_user()
        conv_initial = _make_conversation(user.id)
        conv_initial.is_running = True
        conv_idle = _make_conversation(user.id)
        conv_idle.id = conv_initial.id
        conv_idle.is_running = False
        cred = _make_credential()

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_result_conv1 = MagicMock()
        mock_result_conv1.scalar_one_or_none.return_value = conv_initial
        mock_result_msgs = MagicMock()
        mock_result_msgs.scalars.return_value.all.return_value = []
        mock_result_conv2 = MagicMock()
        mock_result_conv2.scalar_one_or_none.return_value = conv_idle
        mock_db.execute.side_effect = [mock_result_conv1, mock_result_msgs, mock_result_conv2]

        body = MessageCreate(
            content="Queued item",
            credential_id=str(cred.id),
            model="gpt-4o",
        )

        with (
            patch(
                "app.api.chats.get_accessible_credential", new_callable=AsyncMock, return_value=cred
            ),
            patch("app.api.chats.build_public_base_url", return_value="http://localhost"),
            patch("app.api.chats.registry.publish", new_callable=AsyncMock),
            patch("app.api.chats.registry.create_task", new_callable=AsyncMock) as create_task,
            patch("asyncio.create_task", side_effect=_close_created_task) as mock_create_task,
        ):
            result = await send_message(
                http_request=MagicMock(),
                conversation_id=conv_initial.id,
                body=body,
                current_user=user,
                db=mock_db,
            )

        self.assertEqual(result.status, "queued")
        self.assertTrue(conv_idle.is_running)
        create_task.assert_awaited_once()
        mock_create_task.assert_called_once()

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


class TestWorkerOwnershipExceptionCleanup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.conv_id = str(uuid.uuid4())
        self.user_id = uuid.uuid4()
        self.cred_id = uuid.uuid4()
        _chat_tasks.pop(self.conv_id, None)
        _cancel_events.pop(self.conv_id, None)

    async def asyncTearDown(self) -> None:
        _chat_tasks.pop(self.conv_id, None)
        _cancel_events.pop(self.conv_id, None)

    async def test_process_chat_old_worker_superseded_in_flight_exception_does_not_clear_newer_worker_state(
        self,
    ) -> None:
        newer_task = asyncio.create_task(asyncio.sleep(10))
        newer_event = Event()

        mock_db = AsyncMock()
        mock_db_context = AsyncMock()
        mock_db_context.__aenter__.return_value = mock_db
        mock_db_maker = MagicMock(return_value=mock_db_context)

        mock_finish = AsyncMock()
        mock_publish = AsyncMock()
        mock_clear_queue = AsyncMock()

        async def _supersede_and_fail(*args, **kwargs):
            # Simulate a newer worker replacing ownership while the old worker was in-flight
            _chat_tasks[self.conv_id] = newer_task
            _cancel_events[self.conv_id] = newer_event
            raise RuntimeError("Old worker failure")

        try:
            with (
                patch("app.api.chats.registry.has_task", new_callable=AsyncMock, return_value=True),
                patch("app.api.chats.registry.finish", mock_finish),
                patch("app.api.chats.registry.publish", mock_publish),
                patch("app.api.chats._clear_queue_items", mock_clear_queue),
                patch("app.api.chats.async_session_maker", mock_db_maker),
                patch(
                    "app.api.chats._run_chat_turn",
                    new_callable=AsyncMock,
                    side_effect=_supersede_and_fail,
                ),
            ):
                await _process_chat(
                    conv_id=self.conv_id,
                    user_id=self.user_id,
                    content="Hello",
                    credential_id=self.cred_id,
                    model="gpt-4o",
                    attachment_data=None,
                    public_base_url="http://localhost",
                    should_generate_title=False,
                )

            # Invariant: Newer worker's state is completely preserved
            self.assertIs(_chat_tasks.get(self.conv_id), newer_task)
            self.assertIs(_cancel_events.get(self.conv_id), newer_event)
            mock_finish.assert_not_called()
            mock_publish.assert_not_called()
            mock_clear_queue.assert_not_called()
            mock_db_maker.assert_not_called()
        finally:
            newer_task.cancel()
            await asyncio.gather(newer_task, return_exceptions=True)

    async def test_process_chat_old_worker_already_superseded_before_start(self) -> None:
        newer_task = asyncio.create_task(asyncio.sleep(10))
        newer_event = Event()
        _chat_tasks[self.conv_id] = newer_task
        _cancel_events[self.conv_id] = newer_event

        mock_run_turn = AsyncMock()
        try:
            with (
                patch("app.api.chats.registry.has_task", new_callable=AsyncMock, return_value=True),
                patch("app.api.chats._run_chat_turn", mock_run_turn),
            ):
                await _process_chat(
                    conv_id=self.conv_id,
                    user_id=self.user_id,
                    content="Hello",
                    credential_id=self.cred_id,
                    model="gpt-4o",
                    attachment_data=None,
                    public_base_url="http://localhost",
                    should_generate_title=False,
                )

            # Invariant: Superseded worker aborts before starting; newer state untouched
            self.assertIs(_chat_tasks.get(self.conv_id), newer_task)
            self.assertIs(_cancel_events.get(self.conv_id), newer_event)
            mock_run_turn.assert_not_called()
        finally:
            newer_task.cancel()
            await asyncio.gather(newer_task, return_exceptions=True)

    async def test_process_chat_current_worker_exception_performs_failure_cleanup(self) -> None:
        current_task = asyncio.current_task()
        _chat_tasks[self.conv_id] = current_task

        mock_db = AsyncMock()
        mock_db_context = AsyncMock()
        mock_db_context.__aenter__.return_value = mock_db
        mock_db_maker = MagicMock(return_value=mock_db_context)

        mock_finish = AsyncMock()
        mock_publish = AsyncMock()
        mock_clear_queue = AsyncMock()

        with (
            patch("app.api.chats.registry.has_task", new_callable=AsyncMock, return_value=True),
            patch("app.api.chats.registry.finish", mock_finish),
            patch("app.api.chats.registry.publish", mock_publish),
            patch("app.api.chats._clear_queue_items", mock_clear_queue),
            patch("app.api.chats.async_session_maker", mock_db_maker),
            patch(
                "app.api.chats._run_chat_turn",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Current worker failure"),
            ),
        ):
            await _process_chat(
                conv_id=self.conv_id,
                user_id=self.user_id,
                content="Hello",
                credential_id=self.cred_id,
                model="gpt-4o",
                attachment_data=None,
                public_base_url="http://localhost",
                should_generate_title=False,
            )

        # Invariant: Current worker cleans up on failure
        self.assertIsNone(_chat_tasks.get(self.conv_id))
        self.assertIsNone(_cancel_events.get(self.conv_id))
        mock_finish.assert_awaited_once_with(self.conv_id)
        mock_clear_queue.assert_awaited_once()
        self.assertEqual(mock_publish.await_count, 2)
        mock_db.commit.assert_awaited_once()

    async def test_process_chat_queue_old_worker_superseded_in_flight_exception_does_not_clear_newer_worker_state(
        self,
    ) -> None:
        newer_task = asyncio.create_task(asyncio.sleep(10))
        newer_event = Event()

        mock_db = AsyncMock()
        mock_db_context = AsyncMock()
        mock_db_context.__aenter__.return_value = mock_db
        mock_db_maker = MagicMock(return_value=mock_db_context)

        mock_finish = AsyncMock()
        mock_publish = AsyncMock()
        mock_clear_queue = AsyncMock()

        async def _supersede_and_fail(*args, **kwargs):
            # Simulate a newer worker replacing ownership while the old queue worker was in-flight
            _chat_tasks[self.conv_id] = newer_task
            _cancel_events[self.conv_id] = newer_event
            raise RuntimeError("Old queue worker failure")

        try:
            with (
                patch("app.api.chats.registry.has_task", new_callable=AsyncMock, return_value=True),
                patch("app.api.chats.registry.finish", mock_finish),
                patch("app.api.chats.registry.publish", mock_publish),
                patch("app.api.chats._clear_queue_items", mock_clear_queue),
                patch("app.api.chats.async_session_maker", mock_db_maker),
                patch(
                    "app.api.chats._dequeue_next_turn",
                    new_callable=AsyncMock,
                    side_effect=_supersede_and_fail,
                ),
            ):
                await _process_chat_queue(
                    conv_id=self.conv_id,
                    user_id=self.user_id,
                    public_base_url="http://localhost",
                )

            # Invariant: Newer worker's state is completely preserved
            self.assertIs(_chat_tasks.get(self.conv_id), newer_task)
            self.assertIs(_cancel_events.get(self.conv_id), newer_event)
            mock_finish.assert_not_called()
            mock_publish.assert_not_called()
            mock_clear_queue.assert_not_called()
            mock_db_maker.assert_not_called()
        finally:
            newer_task.cancel()
            await asyncio.gather(newer_task, return_exceptions=True)

    async def test_process_chat_queue_old_worker_already_superseded_before_start(self) -> None:
        newer_task = asyncio.create_task(asyncio.sleep(10))
        newer_event = Event()
        _chat_tasks[self.conv_id] = newer_task
        _cancel_events[self.conv_id] = newer_event

        mock_dequeue = AsyncMock()
        try:
            with (
                patch("app.api.chats.registry.has_task", new_callable=AsyncMock, return_value=True),
                patch("app.api.chats._dequeue_next_turn", mock_dequeue),
            ):
                await _process_chat_queue(
                    conv_id=self.conv_id,
                    user_id=self.user_id,
                    public_base_url="http://localhost",
                )

            # Invariant: Superseded queue worker aborts before starting; newer state untouched
            self.assertIs(_chat_tasks.get(self.conv_id), newer_task)
            self.assertIs(_cancel_events.get(self.conv_id), newer_event)
            mock_dequeue.assert_not_called()
        finally:
            newer_task.cancel()
            await asyncio.gather(newer_task, return_exceptions=True)

    async def test_process_chat_queue_current_worker_exception_performs_failure_cleanup(
        self,
    ) -> None:
        current_task = asyncio.current_task()
        _chat_tasks[self.conv_id] = current_task

        mock_db = AsyncMock()
        mock_db_context = AsyncMock()
        mock_db_context.__aenter__.return_value = mock_db
        mock_db_maker = MagicMock(return_value=mock_db_context)

        mock_finish = AsyncMock()
        mock_publish = AsyncMock()
        mock_clear_queue = AsyncMock()

        with (
            patch("app.api.chats.registry.has_task", new_callable=AsyncMock, return_value=True),
            patch("app.api.chats.registry.finish", mock_finish),
            patch("app.api.chats.registry.publish", mock_publish),
            patch("app.api.chats._clear_queue_items", mock_clear_queue),
            patch("app.api.chats.async_session_maker", mock_db_maker),
            patch(
                "app.api.chats._dequeue_next_turn",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Current queue worker failure"),
            ),
        ):
            await _process_chat_queue(
                conv_id=self.conv_id,
                user_id=self.user_id,
                public_base_url="http://localhost",
            )

        # Invariant: Current worker cleans up on failure
        self.assertIsNone(_chat_tasks.get(self.conv_id))
        self.assertIsNone(_cancel_events.get(self.conv_id))
        mock_finish.assert_awaited_once_with(self.conv_id)
        mock_clear_queue.assert_awaited_once()
        self.assertEqual(mock_publish.await_count, 2)
        mock_db.commit.assert_awaited_once()
