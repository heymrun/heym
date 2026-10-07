"""Chat API plumbing for build mode: request checks, queued turns and the turn runner."""

import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import chats
from app.db.models import DashboardChatQueueItem
from app.models.chat_schemas import MessageCreate
from app.services.chat_build_mode import BuildRequest


def _body(**fields: Any) -> MessageCreate:
    return MessageCreate(
        content="Build it", credential_id=str(uuid.uuid4()), model="gpt-5.5", **fields
    )


def _fake_session_maker(db: Any) -> Any:
    @asynccontextmanager
    async def maker() -> Any:
        yield db

    return maker


class ResolveBuildRequestTests(unittest.IsolatedAsyncioTestCase):
    async def _resolve(
        self, body: MessageCreate, workflow: Any = None, writable: bool = True
    ) -> Any:
        with (
            patch.object(chats, "get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch.object(chats, "user_can_write_workflow", AsyncMock(return_value=writable)),
        ):
            return await chats._resolve_build_request(AsyncMock(), uuid.uuid4(), body)

    async def test_classic_chat_has_no_build_request(self) -> None:
        self.assertIsNone(await self._resolve(_body()))

    async def test_build_without_a_target_builds_new_workflows(self) -> None:
        self.assertEqual(await self._resolve(_body(allow_build=True)), BuildRequest())

    async def test_a_target_needs_allow_build(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            await self._resolve(_body(target_workflow_id=uuid.uuid4()))
        self.assertEqual(caught.exception.status_code, 400)

    async def test_a_target_must_exist_and_be_writable(self) -> None:
        target = uuid.uuid4()
        with self.assertRaises(HTTPException) as missing:
            await self._resolve(_body(allow_build=True, target_workflow_id=target))
        with self.assertRaises(HTTPException) as read_only:
            await self._resolve(
                _body(allow_build=True, target_workflow_id=target),
                workflow=object(),
                writable=False,
            )

        self.assertEqual(missing.exception.status_code, 404)
        self.assertEqual(read_only.exception.status_code, 403)
        self.assertEqual(
            await self._resolve(
                _body(allow_build=True, target_workflow_id=target), workflow=object()
            ),
            BuildRequest(target_workflow_id=target),
        )


class SendMessageBuildTests(unittest.IsolatedAsyncioTestCase):
    def _db(self, conversation: Any) -> AsyncMock:
        db = AsyncMock()
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        msgs_result = MagicMock()
        msgs_result.scalars.return_value.all.return_value = []
        db.execute.side_effect = [conv_result, msgs_result, conv_result]
        db.add = MagicMock()
        return db

    async def _send(self, conversation: Any, body: MessageCreate, db: AsyncMock) -> MagicMock:
        process_chat = MagicMock(return_value=None)
        credential = SimpleNamespace(id=uuid.UUID(body.credential_id), type="openai")
        user = SimpleNamespace(id=conversation.user_id)
        build = BuildRequest(target_workflow_id=body.target_workflow_id)

        def close_task(coro: Any) -> MagicMock:
            return MagicMock()

        with (
            patch.object(chats, "get_accessible_credential", AsyncMock(return_value=credential)),
            patch.object(chats, "_resolve_build_request", AsyncMock(return_value=build)),
            patch.object(
                chats, "_build_user_message", return_value={"role": "user", "content": "x"}
            ),
            patch.object(chats, "build_public_base_url", return_value="http://localhost"),
            patch.object(chats.registry, "create_task", AsyncMock()),
            patch.object(chats.registry, "publish", AsyncMock()),
            patch.object(chats, "_process_chat", process_chat),
            patch.object(chats, "_process_chat_queue", MagicMock(return_value=None)),
            patch("asyncio.create_task", side_effect=close_task),
        ):
            await chats.send_message(
                http_request=MagicMock(),
                conversation_id=conversation.id,
                body=body,
                current_user=user,
                db=db,
            )
        return process_chat

    def _conversation(self, running: bool) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            is_running=running,
            title="New Chat",
            has_unread=False,
            queue_paused_by_message_id=None,
            last_credential_id=None,
            last_model=None,
        )

    async def test_a_started_turn_carries_the_build_request(self) -> None:
        target = uuid.uuid4()
        conversation = self._conversation(running=False)

        process_chat = await self._send(
            conversation, _body(allow_build=True, target_workflow_id=target), self._db(conversation)
        )

        self.assertEqual(
            process_chat.call_args.kwargs["build"], BuildRequest(target_workflow_id=target)
        )

    async def test_a_queued_turn_stores_build_mode_and_target(self) -> None:
        target = uuid.uuid4()
        conversation = self._conversation(running=True)
        db = self._db(conversation)
        db.refresh = AsyncMock(side_effect=self._stamp)

        await self._send(conversation, _body(allow_build=True, target_workflow_id=target), db)

        item = next(
            c.args[0]
            for c in db.add.call_args_list
            if isinstance(c.args[0], DashboardChatQueueItem)
        )
        self.assertTrue(item.allow_build)
        self.assertEqual(item.build_target_workflow_id, target)

    @staticmethod
    async def _stamp(obj: Any, *_args: Any, **_kwargs: Any) -> None:
        if isinstance(obj, DashboardChatQueueItem):
            obj.id = obj.id or uuid.uuid4()


class QueuedBuildTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_dequeued_item_restores_the_build_request(self) -> None:
        target = uuid.uuid4()
        conv_id = uuid.uuid4()
        conversation = SimpleNamespace(id=conv_id, queue_paused_by_message_id=None, is_running=True)
        item = DashboardChatQueueItem(
            id=uuid.uuid4(),
            conversation_id=conv_id,
            content="Fix the lead workflow",
            credential_id=uuid.uuid4(),
            model="gpt-5.5",
            attachment=None,
            allow_build=True,
            build_target_workflow_id=target,
            created_at=datetime.now(timezone.utc),
        )
        db = AsyncMock()
        db.add = MagicMock()
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = conversation
        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = item
        db.execute.side_effect = [conv_result, item_result]

        with (
            patch.object(chats, "async_session_maker", _fake_session_maker(db)),
            patch.object(chats.registry, "publish", AsyncMock()),
        ):
            turn = await chats._dequeue_next_turn(str(conv_id))

        self.assertEqual(turn.build, BuildRequest(target_workflow_id=target))


class RunChatTurnBuildTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_build_turn_adds_the_session_and_its_prompt(self) -> None:
        conv_id = str(uuid.uuid4())
        user = SimpleNamespace(id=uuid.uuid4(), user_rules=None)
        credential = SimpleNamespace(id=uuid.uuid4(), encrypted_config="x")
        db = AsyncMock()
        db.add = MagicMock()
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user
        msgs_result = MagicMock()
        msgs_result.scalars.return_value.all.return_value = []
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [user_result, msgs_result, conv_result]
        sessions: list[dict[str, Any]] = []

        class FakeSession:
            def __init__(self, **kwargs: Any) -> None:
                sessions.append(kwargs)

            async def prompt(self) -> str:
                return "\n## Build mode\n"

        stream_kwargs: dict[str, Any] = {}

        async def fake_stream(*args: Any, **kwargs: Any) -> Any:
            stream_kwargs.update(kwargs, system_prompt=args[2])
            yield 'data: {"type": "done"}\n\n'

        parts = chats.SystemPromptParts(
            full_system_prompt="base",
            base_system_prompt="base",
            agents_md="",
            workflows_block="",
            user_rules="",
        )
        turn = chats.ChatTurn(
            content="Build it",
            credential_id=credential.id,
            model="gpt-5.5",
            attachment_data=None,
            should_generate_title=False,
            build=BuildRequest(),
        )
        with (
            patch.object(chats, "async_session_maker", _fake_session_maker(db)),
            patch.object(chats, "get_accessible_credential", AsyncMock(return_value=credential)),
            patch.object(chats, "decrypt_config", return_value={}),
            patch.object(chats, "_assemble_system_prompt_parts", AsyncMock(return_value=parts)),
            patch.object(
                chats,
                "resolve_model_binding",
                side_effect=lambda *a, **k: (MagicMock(), "OpenAI", "gpt-5.5", k["trace_context"]),
            ),
            patch.object(chats, "stream_dashboard_chat", fake_stream),
            patch.object(chats, "ChatBuildSession", FakeSession),
            patch.object(chats.registry, "publish", AsyncMock()),
        ):
            await chats._run_chat_turn(conv_id, user.id, turn, "http://localhost")

        self.assertEqual(sessions[0]["llm_session_id"], conv_id)
        self.assertEqual(sessions[0]["request"], BuildRequest())
        self.assertIsInstance(stream_kwargs["build"], FakeSession)
        self.assertTrue(stream_kwargs["system_prompt"].endswith("## Build mode\n"))
        self.assertEqual(stream_kwargs["system_prompt_parts"].build_block, "\n## Build mode\n")


if __name__ == "__main__":
    unittest.main()
