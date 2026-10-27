"""Agent turns: outcome mapping, progress hook, message tagging and cancellation."""

import asyncio
import unittest
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import chats
from app.services.heym_agent.turn import AgentOutcome, outcome_of


class OutcomeTests(unittest.TestCase):
    def test_outcome_precedence(self) -> None:
        cases = [
            (
                dict(cancelled=True, form_urls=("u",), paused_for_clarification=True),
                AgentOutcome.CANCELED,
            ),
            (
                dict(cancelled=False, form_urls=("u",), paused_for_clarification=True),
                AgentOutcome.AUTH_REQUIRED,
            ),
            (
                dict(cancelled=False, form_urls=(), paused_for_clarification=True),
                AgentOutcome.INPUT_REQUIRED,
            ),
            (
                dict(cancelled=False, form_urls=(), paused_for_clarification=False),
                AgentOutcome.COMPLETED,
            ),
        ]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                self.assertIs(outcome_of(**kwargs), expected)


def _sessions(assistant: SimpleNamespace | None) -> Any:
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=assistant))
    )

    @asynccontextmanager
    async def maker() -> Any:
        yield db

    return maker, db


class AgentChatTurnTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.conversation = SimpleNamespace(
            id=uuid.uuid4(),
            is_running=False,
            title="New Chat",
            has_unread=False,
            queue_paused_by_message_id=None,
            last_credential_id=None,
            last_model=None,
        )

    async def _run(self, run_chat_turn: Any, **kwargs: Any) -> Any:
        assistant = SimpleNamespace(content="Done.", tool_calls=[])
        maker, db = _sessions(assistant)
        with (
            patch.object(chats, "async_session_maker", maker),
            patch.object(
                chats,
                "_get_or_create_agent_conversation",
                AsyncMock(return_value=(self.conversation, False)),
            ),
            patch.object(chats, "_run_chat_turn", run_chat_turn),
            patch.object(chats, "_finish_worker_state", AsyncMock()),
            patch.object(chats, "registry", MagicMock(create_task=AsyncMock(), finish=AsyncMock())),
            patch.object(chats, "_saved_workflow_links", AsyncMock(return_value=())),
            patch.object(chats, "_saved_eval_suite_links", AsyncMock(return_value=())),
        ):
            result = await chats.run_agent_chat_turn(
                user_id=uuid.uuid4(),
                message="hi",
                conversation_id=self.conversation.id,
                credential_id=uuid.uuid4(),
                model="gpt-5",
                public_base_url="https://heym.test",
                **kwargs,
            )
        return result, db

    async def test_turn_carries_the_hook_and_task_id(self) -> None:
        task_id = uuid.uuid4()
        hook = AsyncMock()
        seen: dict[str, Any] = {}

        async def run_chat_turn(conv_id: str, user_id: uuid.UUID, turn: Any, base: str) -> Any:
            seen["turn"] = turn
            return chats.ChatTurnResult(False, uuid.uuid4())

        result, db = await self._run(
            run_chat_turn,
            source=chats.A2A_CONVERSATION_SOURCE,
            on_event=hook,
            a2a_task_id=task_id,
        )

        self.assertIs(seen["turn"].on_event, hook)
        self.assertEqual(seen["turn"].a2a_task_id, task_id)
        user_message = db.add.call_args_list[0].args[0]
        self.assertEqual(user_message.a2a_task_id, task_id)
        self.assertIs(result.outcome, AgentOutcome.COMPLETED)

    async def test_a_stop_request_cancels_the_turn_and_reports_it(self) -> None:
        started = asyncio.Event()

        async def run_chat_turn(conv_id: str, user_id: uuid.UUID, turn: Any, base: str) -> Any:
            started.set()
            await asyncio.sleep(30)

        async def stop_when_started() -> None:
            await started.wait()
            self.assertTrue(chats.request_chat_cancel(str(self.conversation.id)))

        stopper = asyncio.create_task(stop_when_started())
        result, _ = await self._run(run_chat_turn)
        await stopper

        self.assertIs(result.outcome, AgentOutcome.CANCELED)
        self.assertNotIn(str(self.conversation.id), chats._chat_tasks)
