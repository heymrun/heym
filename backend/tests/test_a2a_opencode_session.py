"""A2A turns use the context id as their OpenCode session: stable per context, new per context."""

import unittest
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import chats
from app.services.a2a.executor import A2AExecutor
from app.services.a2a.models import Message, Part, Role, SendMessageRequest
from app.services.a2a.task_store import TaskScope
from app.services.heym_agent.errors import AgentError
from app.services.heym_agent.settings import AgentSettings
from app.services.heym_agent.turn import AgentTurnResult
from tests.a2a_fixtures import MemoryTaskStore

SETTINGS = AgentSettings(enabled=True, credential_id=None, model=None, a2a_enabled=True)


def _message(**kwargs: Any) -> SendMessageRequest:
    return SendMessageRequest(
        message=Message(
            message_id=str(uuid.uuid4()), role=Role.USER, parts=[Part(text="hi")], **kwargs
        )
    )


class A2AOpenCodeSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.user_id = uuid.uuid4()
        self.store = MemoryTaskStore()
        self.turn_conversations: list[uuid.UUID] = []

        async def create_conversation(user_id: uuid.UUID) -> uuid.UUID:
            conversation_id = uuid.uuid4()
            self.store.conversations[conversation_id] = user_id
            return conversation_id

        async def run_turn(request: Any, on_progress: Any) -> AgentTurnResult:
            self.turn_conversations.append(request.conversation_id)
            return AgentTurnResult(request.conversation_id, "ok", [])

        self.executor = A2AExecutor(
            scope=TaskScope(self.user_id, None),
            settings=SETTINGS,
            public_base_url="https://heym.test",
            store=self.store,
            run_turn=run_turn,
            create_conversation=create_conversation,
        )

    async def test_follow_ups_reuse_the_context_and_new_tasks_get_a_new_one(self) -> None:
        first = await self.executor.send_message(_message())
        follow_up = await self.executor.send_message(_message(context_id=first.context_id))
        fresh = await self.executor.send_message(_message())

        self.assertEqual(follow_up.context_id, first.context_id)
        self.assertNotEqual(fresh.context_id, first.context_id)
        self.assertEqual(
            [str(c) for c in self.turn_conversations],
            [first.context_id, first.context_id, fresh.context_id],
        )
        self.assertTrue(all(str(c) for c in self.turn_conversations))

    async def test_the_turn_runs_under_the_conversation_id(self) -> None:
        conversation = MagicMock(id=uuid.uuid4(), is_running=False, title="New Chat")
        seen: dict[str, str] = {}

        async def run_chat_turn(conv_id: str, user_id: uuid.UUID, turn: Any, base: str) -> Any:
            seen["conv_id"] = conv_id
            return chats.ChatTurnResult(False, uuid.uuid4())

        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=db)
        session.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(chats, "async_session_maker", MagicMock(return_value=session)),
            patch.object(
                chats,
                "_get_or_create_agent_conversation",
                AsyncMock(return_value=(conversation, False)),
            ),
            patch.object(chats, "_run_chat_turn", run_chat_turn),
            patch.object(chats, "_finish_worker_state", AsyncMock()),
            patch.object(chats, "registry", MagicMock(create_task=AsyncMock(), finish=AsyncMock())),
        ):
            with self.assertRaises(AgentError):
                # The fake session returns no assistant message, so the turn ends with AgentError.
                await chats.run_agent_chat_turn(
                    user_id=self.user_id,
                    message="hi",
                    conversation_id=conversation.id,
                    credential_id=uuid.uuid4(),
                    model="m",
                    public_base_url="https://heym.test",
                    source=chats.A2A_CONVERSATION_SOURCE,
                )

        # `_run_chat_turn` passes conv_id to resolve_model_binding(session_id=...) and to
        # ChatBuildSession(llm_session_id=...), so the OpenCode session is the context id.
        self.assertEqual(seen["conv_id"], str(conversation.id))
