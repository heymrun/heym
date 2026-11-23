"""The Heym node's chat service against real PostgreSQL: conversations, cleanup, fire and forget."""

import asyncio
import unittest
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import DashboardConversation, DashboardMessage
from app.services import heym_chat_node
from app.services.app_loop import chat_turn_depth
from app.services.heym_agent.settings import ResolvedAgentLLM
from app.services.heym_agent.turn import AgentOutcome, AgentTurnResult
from tests.board_pg_support import cleanup, connect_or_skip, make_user


class HeymChatServiceTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = await connect_or_skip(self)
        self.user = await make_user(self.engine, "chat-node-user")
        self.other = await make_user(self.engine, "chat-node-other")
        self.addAsyncCleanup(cleanup, self.engine, [self.user, self.other])

        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.credential = MagicMock(id=uuid.uuid4())
        self.turns: list[dict] = []
        self.turn_result = AgentOutcome.COMPLETED
        self.turn_gate: asyncio.Event | None = None
        self.turn_error: BaseException | None = None

        async def fake_turn(**kwargs) -> AgentTurnResult:
            self.turns.append({**kwargs, "depth": chat_turn_depth()})
            if self.turn_gate is not None:
                await self.turn_gate.wait()
            if self.turn_error is not None:
                raise self.turn_error
            return AgentTurnResult(
                conversation_id=kwargs["conversation_id"],
                text="Reply",
                tool_names=[],
                outcome=self.turn_result,
            )

        async def fake_llm(_db, _user_id) -> ResolvedAgentLLM:
            return ResolvedAgentLLM(credential=self.credential, model="model-x")

        for target, value in (
            ("app.services.heym_chat_node.async_session_maker", self.sessions),
            ("app.services.heym_chat_node.resolve_chat_default_llm", fake_llm),
            ("app.api.chats.run_agent_chat_turn", fake_turn),
            ("app.services.file_sandbox.chat_workspaces.delete_chat_workspace", MagicMock()),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _request(self, **overrides) -> heym_chat_node.ChatNodeRequest:
        values = {
            "user_id": self.user.id,
            "message": "Summarize my day",
            "conversation_id": None,
            "temporary": False,
            "depth": 1,
            "public_base_url": "https://heym.example.com",
        }
        values.update(overrides)
        return heym_chat_node.ChatNodeRequest(**values)

    async def _conversations(self, user_id: uuid.UUID) -> list[DashboardConversation]:
        async with self.sessions() as db:
            result = await db.execute(
                select(DashboardConversation).where(DashboardConversation.user_id == user_id)
            )
            return list(result.scalars().all())

    async def _make_conversation(
        self, user_id: uuid.UUID, *, running: bool = False
    ) -> DashboardConversation:
        async with self.sessions() as db:
            conversation = DashboardConversation(
                user_id=user_id, title="Earlier", source="chat", is_running=running
            )
            db.add(conversation)
            await db.commit()
            return conversation


class NewConversationTests(HeymChatServiceTestBase):
    async def test_a_new_conversation_is_saved_as_a_workflow_chat(self) -> None:
        output = await heym_chat_node.send_and_wait(self._request())
        [conversation] = await self._conversations(self.user.id)
        self.assertEqual(conversation.source, "workflow")
        self.assertEqual(conversation.title, "New Chat")
        self.assertEqual(output["conversation_id"], str(conversation.id))
        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["reply"], "Reply")
        [turn] = self.turns
        self.assertEqual(turn["conversation_id"], conversation.id)
        self.assertEqual(turn["credential_id"], self.credential.id)
        self.assertEqual(turn["model"], "model-x")
        self.assertEqual(turn["user_id"], self.user.id)

    async def test_the_turn_runs_at_the_requested_chat_depth(self) -> None:
        await heym_chat_node.send_and_wait(self._request(depth=3))
        self.assertEqual(self.turns[0]["depth"], 3)
        self.assertEqual(chat_turn_depth(), 0)


class ContinueConversationTests(HeymChatServiceTestBase):
    async def test_continue_writes_into_the_given_conversation(self) -> None:
        conversation = await self._make_conversation(self.user.id)
        output = await heym_chat_node.send_and_wait(self._request(conversation_id=conversation.id))
        self.assertEqual(self.turns[0]["conversation_id"], conversation.id)
        self.assertEqual(output["conversation_id"], str(conversation.id))
        self.assertEqual(len(await self._conversations(self.user.id)), 1)

    async def test_a_deleted_conversation_fails_and_never_starts_a_new_one(self) -> None:
        missing = uuid.uuid4()
        with self.assertRaisesRegex(
            ValueError, f"Conversation not found or not accessible: {missing}"
        ):
            await heym_chat_node.send_and_wait(self._request(conversation_id=missing))
        self.assertEqual(self.turns, [])
        self.assertEqual(await self._conversations(self.user.id), [])

    async def test_a_running_conversation_is_refused(self) -> None:
        conversation = await self._make_conversation(self.user.id, running=True)
        with self.assertRaisesRegex(ValueError, "already running"):
            await heym_chat_node.send_and_wait(self._request(conversation_id=conversation.id))
        self.assertEqual(self.turns, [])

    async def test_fire_and_forget_checks_the_conversation_before_returning(self) -> None:
        with self.assertRaisesRegex(ValueError, "Conversation not found or not accessible"):
            await heym_chat_node.send_in_background(self._request(conversation_id=uuid.uuid4()))
        self.assertEqual(self.turns, [])


class TemporaryConversationTests(HeymChatServiceTestBase):
    async def test_a_chat_without_history_is_deleted_after_the_turn(self) -> None:
        output = await heym_chat_node.send_and_wait(self._request(temporary=True))
        self.assertIsNone(output["conversation_id"])
        self.assertEqual(output["reply"], "Reply")
        self.assertEqual(await self._conversations(self.user.id), [])
        self.assertEqual(self.turns[0]["source"], "workflow_temp")

    async def test_its_messages_go_with_it(self) -> None:
        marker = f"temporary message {uuid.uuid4()}"

        async def turn_with_message(**kwargs) -> AgentTurnResult:
            async with self.sessions() as db:
                db.add(
                    DashboardMessage(
                        conversation_id=kwargs["conversation_id"], role="user", content=marker
                    )
                )
                await db.commit()
            return AgentTurnResult(
                conversation_id=kwargs["conversation_id"], text="ok", tool_names=[]
            )

        with patch("app.api.chats.run_agent_chat_turn", turn_with_message):
            await heym_chat_node.send_and_wait(self._request(temporary=True))
        async with self.sessions() as db:
            remaining = await db.execute(
                select(DashboardMessage.id).where(DashboardMessage.content == marker)
            )
            self.assertEqual(remaining.all(), [])

    async def test_it_is_deleted_when_the_turn_fails(self) -> None:
        from app.services.heym_agent.errors import AgentError

        self.turn_error = AgentError("The assistant did not produce a reply. Try again.")
        with self.assertRaisesRegex(ValueError, "did not produce a reply"):
            await heym_chat_node.send_and_wait(self._request(temporary=True))
        self.assertEqual(await self._conversations(self.user.id), [])

    async def test_it_is_deleted_when_the_turn_is_cancelled(self) -> None:
        self.turn_gate = asyncio.Event()
        task = asyncio.create_task(heym_chat_node.send_and_wait(self._request(temporary=True)))
        while not self.turns:
            await asyncio.sleep(0.01)
        self.assertEqual(len(await self._conversations(self.user.id)), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(await self._conversations(self.user.id), [])

    async def test_a_temporary_chat_is_never_listed(self) -> None:
        from app.api.chats import list_conversations

        self.turn_gate = asyncio.Event()
        task = asyncio.create_task(heym_chat_node.send_and_wait(self._request(temporary=True)))
        while not self.turns:
            await asyncio.sleep(0.01)
        await self._make_conversation(self.user.id)
        async with AsyncSession(self.engine) as db:
            listed = await list_conversations(current_user=self.user, db=db)
        self.assertEqual([c.title for c in listed.conversations], ["Earlier"])
        self.turn_gate.set()
        await task


class FireAndForgetTests(HeymChatServiceTestBase):
    async def test_returns_before_the_turn_ends_and_the_turn_finishes_later(self) -> None:
        self.turn_gate = asyncio.Event()
        output = await heym_chat_node.send_in_background(self._request(depth=2))
        [conversation] = await self._conversations(self.user.id)
        self.assertEqual(output, {"conversation_id": str(conversation.id), "status": "started"})
        while not self.turns:
            await asyncio.sleep(0.01)
        self.assertEqual(self.turns[0]["depth"], 2)
        [task] = list(heym_chat_node._background_turns)
        self.turn_gate.set()
        await task
        self.assertEqual(heym_chat_node._background_turns, set())

    async def test_a_temporary_background_chat_is_deleted_when_it_ends(self) -> None:
        self.turn_gate = asyncio.Event()
        output = await heym_chat_node.send_in_background(self._request(temporary=True))
        self.assertEqual(output, {"conversation_id": None, "status": "started"})
        [task] = list(heym_chat_node._background_turns)
        self.turn_gate.set()
        await task
        self.assertEqual(await self._conversations(self.user.id), [])

    async def test_a_background_failure_is_logged_not_raised(self) -> None:
        from app.services.heym_agent.errors import AgentError

        self.turn_error = AgentError("boom")
        await heym_chat_node.send_in_background(self._request())
        [task] = list(heym_chat_node._background_turns)
        with self.assertLogs("app.services.heym_chat_node", level="ERROR"):
            await task


if __name__ == "__main__":
    unittest.main()
