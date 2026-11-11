"""Queue interruption must preserve other messages and await the previous turn."""

import asyncio
import unittest
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import chats
from app.db.models import DashboardChatQueueItem


class SendQueuedMessageNowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.conv_id = uuid.uuid4()
        self.user = MagicMock(id=uuid.uuid4())
        self.conversation = MagicMock(is_running=False, queue_paused_by_message_id=uuid.uuid4())
        now = datetime.now(timezone.utc)
        self.item = DashboardChatQueueItem(
            id=uuid.uuid4(),
            conversation_id=self.conv_id,
            content="Use a different sender",
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            created_at=now,
            updated_at=now,
        )
        self.db = AsyncMock()
        for name, value in (
            ("_get_conversation_or_404", self.conversation),
            ("_get_queue_item_or_404", self.item),
        ):
            mock = AsyncMock(return_value=value)
            patcher = patch.object(chats, name, mock)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.registry = patch.object(chats.registry, "create_task", AsyncMock()).start()
        self.addCleanup(patch.stopall)

    async def asyncTearDown(self) -> None:
        task = chats._chat_tasks.pop(str(self.conv_id), None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        chats._cancel_events.pop(str(self.conv_id), None)

    async def test_idle_queue_starts_selected_item_and_resumes_planning_pause(self) -> None:
        worker = AsyncMock()
        with patch.object(chats, "_process_chat_queue", worker):
            response = await chats.send_queued_message_now(
                MagicMock(), self.conv_id, self.item.id, self.user, self.db
            )
            await chats._chat_tasks[str(self.conv_id)]

        self.assertEqual(response.status, "started")
        self.assertEqual(response.queued_message.id, self.item.id)
        self.assertTrue(self.conversation.is_running)
        self.assertIsNone(self.conversation.queue_paused_by_message_id)
        self.registry.assert_awaited_once_with(str(self.conv_id))
        self.db.commit.assert_awaited_once()
        self.assertEqual(worker.call_args.kwargs["first_item_id"], self.item.id)
        self.assertIsNone(worker.call_args.kwargs["interrupted_task"])
        chats._get_conversation_or_404.assert_awaited_once_with(
            self.conv_id, self.user.id, self.db, for_update=True
        )
        chats._get_queue_item_or_404.assert_awaited_once_with(
            self.conv_id, self.item.id, self.user.id, self.db
        )

    async def test_missing_conversation_or_item_never_interrupts_a_reply(self) -> None:
        for helper in (chats._get_conversation_or_404, chats._get_queue_item_or_404):
            with self.subTest(helper=helper), patch.object(chats, "request_chat_cancel") as cancel:
                helper.side_effect = HTTPException(status_code=404, detail="Not found")
                with self.assertRaises(HTTPException) as raised:
                    await chats.send_queued_message_now(
                        MagicMock(), self.conv_id, self.item.id, self.user, self.db
                    )
                self.assertEqual(raised.exception.status_code, 404)
                cancel.assert_not_called()
                helper.side_effect = None

    async def test_unreachable_worker_cannot_start_a_second_reply(self) -> None:
        self.conversation.is_running = True
        with self.assertRaises(HTTPException) as raised:
            await chats.send_queued_message_now(
                MagicMock(), self.conv_id, self.item.id, self.user, self.db
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.registry.assert_not_awaited()
        self.db.commit.assert_not_awaited()


class SupersededTurnCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_during_model_routing_still_records_a_cancelled_turn(self) -> None:
        await self._check_cancellation(superseded=True, during_routing=True)

    async def test_partial_reply_is_saved_without_clearing_successors_queue(self) -> None:
        await self._check_cancellation(superseded=True)

    async def test_normal_stop_still_saves_the_reply_and_clears_the_queue(self) -> None:
        await self._check_cancellation(superseded=False)

    async def _check_cancellation(self, *, superseded: bool, during_routing: bool = False) -> None:
        conv_id = str(uuid.uuid4())
        user_id = uuid.uuid4()
        conversation = MagicMock(is_running=True)
        credential = MagicMock(id=uuid.uuid4())
        db = AsyncMock()
        db.add = MagicMock()
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = MagicMock(id=user_id)
        history_result = MagicMock()
        history_result.scalars.return_value.all.return_value = []
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        db.execute.side_effect = [user_result, history_result, conv_result]
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=db)
        context.__aexit__ = AsyncMock(return_value=False)

        async def interrupted_stream(*_args: object, **_kwargs: object) -> AsyncGenerator[str]:
            yield 'data: {"type":"content","text":"Partial reply"}\n\n'
            yield 'data: {"type":"tool_start","id":"tool-1","name":"lookup","args":{}}\n\n'
            raise asyncio.CancelledError

        successor = asyncio.create_task(asyncio.sleep(60))
        if superseded:
            chats._chat_tasks[conv_id] = successor
        try:
            with (
                patch.object(chats, "async_session_maker", return_value=context),
                patch.object(
                    chats, "get_accessible_credential", AsyncMock(return_value=credential)
                ),
                patch.object(chats, "decrypt_config", return_value={}),
                patch.object(chats, "ChatFileTools") as files,
                patch.object(
                    chats,
                    "_assemble_system_prompt_parts",
                    AsyncMock(return_value=chats.SystemPromptParts("system", "system", "", "", "")),
                ),
                patch.object(
                    chats,
                    "resolve_model_binding",
                    return_value=(None, "openai", "gpt-4o", None),
                    side_effect=asyncio.CancelledError if during_routing else None,
                ),
                patch.object(chats, "stream_dashboard_chat", interrupted_stream),
                patch.object(chats, "record_llm_trace") as record_trace,
                patch.object(chats, "record_run_history") as record_history,
                patch.object(chats, "_clear_queue_items", AsyncMock()) as clear,
                patch.object(chats.registry, "publish", AsyncMock()) as publish,
            ):
                files.return_value.workspace_block.return_value = ""
                with self.assertRaises(asyncio.CancelledError):
                    await chats._run_chat_turn(
                        conv_id,
                        user_id,
                        chats.ChatTurn("First request", credential.id, "gpt-4o", [], False),
                        "http://localhost",
                    )
                if superseded:
                    clear.assert_not_awaited()
                    self.assertTrue(conversation.is_running)
                else:
                    clear.assert_awaited_once()
                    self.assertFalse(conversation.is_running)
                if during_routing:
                    record_trace.assert_called_once()
                    self.assertTrue(record_trace.call_args.kwargs["response"]["cancelled"])
                    self.assertEqual(
                        record_trace.call_args.kwargs["request"]["messages"][0]["content"],
                        "First request",
                    )
                    self.assertEqual(record_trace.call_args.kwargs["context"].session_id, conv_id)
                    record_history.assert_called_once()
                    self.assertEqual(record_history.call_args.kwargs["status"], "cancelled")
                    db.add.assert_not_called()
                else:
                    saved = db.add.call_args.args[0]
                    self.assertEqual(saved.content, "Partial reply")
                    self.assertEqual(saved.tool_calls[0]["status"], "cancelled")
                events = [call.args[1] for call in publish.await_args_list]
                self.assertEqual({"type": "queue_cleared"} in events, not superseded)
                self.assertTrue(events[-1]["cancelled"])
        finally:
            chats._chat_tasks.pop(conv_id, None)
            chats._cancel_events.pop(conv_id, None)
            successor.cancel()
            await asyncio.gather(successor, return_exceptions=True)
