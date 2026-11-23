"""Advisory: the Heym node's chat message reaches only the chat of the user the run belongs to.

The message goes to the person who ran the workflow (canvas, MCP, API, execution token,
Chat), and to the workflow owner only when nobody did (Cron and other triggers). A
conversation id is honoured only for its own user: someone else's conversation fails with
the same message as a deleted one, so ids cannot be probed.

These run the real handler in an executor thread, submitting to a real application loop,
against real PostgreSQL; only the model turn itself is stubbed.
"""

import asyncio
import unittest
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import DashboardConversation, Workflow
from app.services import app_loop
from app.services.heym_agent.settings import ResolvedAgentLLM
from app.services.heym_agent.turn import AgentTurnResult
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import heym_node
from tests.board_pg_support import cleanup, connect_or_skip, make_user


class HeymChatNodeScopeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = await connect_or_skip(self)
        self.owner = await make_user(self.engine, "chat-scope-owner")
        self.collaborator = await make_user(self.engine, "chat-scope-collaborator")
        self.addAsyncCleanup(cleanup, self.engine, [self.owner, self.collaborator])
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.workflow_id = uuid.uuid4()
        async with AsyncSession(self.engine) as db:
            db.add(
                Workflow(
                    id=self.workflow_id,
                    name="Daily chat",
                    owner_id=self.owner.id,
                    nodes=[],
                    edges=[],
                )
            )
            await db.commit()

        self.turn_users: list[uuid.UUID] = []

        async def fake_turn(**kwargs) -> AgentTurnResult:
            self.turn_users.append(kwargs["user_id"])
            return AgentTurnResult(
                conversation_id=kwargs["conversation_id"], text="ok", tool_names=[]
            )

        async def fake_llm(_db, user_id) -> ResolvedAgentLLM:
            return ResolvedAgentLLM(credential=MagicMock(id=uuid.uuid4()), model="model-x")

        for target, value in (
            ("app.services.heym_chat_node.async_session_maker", self.sessions),
            ("app.services.heym_chat_node.resolve_chat_default_llm", fake_llm),
            ("app.api.chats.run_agent_chat_turn", fake_turn),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        app_loop.set_app_loop(asyncio.get_running_loop())
        self.addCleanup(app_loop.set_app_loop, None)

    def _ctx(self, node_data: dict, actor_user_id: uuid.UUID | None) -> NodeExecutionContext:
        executor = MagicMock()
        executor.workflow_id = str(self.workflow_id)
        executor.actor_user_id = actor_user_id
        executor._sub_workflow_invocation_depth = 0
        executor.chat_turn_depth = 0
        executor.evaluate_message_template.side_effect = lambda v, *_a, **_kw: str(v)
        data = {"label": "chat", "heymOperation": "sendChatMessage", **node_data}
        return NodeExecutionContext(
            executor=executor,
            node_id="n1",
            inputs={},
            allow_branch_skip=False,
            start_time=0.0,
            node={"id": "n1", "type": "heym", "data": data},
            node_type="heym",
            node_data=data,
            node_label="chat",
        )

    async def _run(self, node_data: dict, actor_user_id: uuid.UUID | None) -> dict:
        ctx = self._ctx({"heymChatMessage": "hello", **node_data}, actor_user_id)
        return await asyncio.to_thread(heym_node.execute, ctx)

    async def _conversation_owners(self) -> list[uuid.UUID]:
        async with self.sessions() as db:
            result = await db.execute(
                select(DashboardConversation.user_id).where(
                    DashboardConversation.user_id.in_([self.owner.id, self.collaborator.id])
                )
            )
            return list(result.scalars().all())

    async def test_a_collaborators_run_writes_to_the_collaborators_chat(self) -> None:
        await self._run({}, actor_user_id=self.collaborator.id)
        self.assertEqual(self.turn_users, [self.collaborator.id])
        self.assertEqual(await self._conversation_owners(), [self.collaborator.id])

    async def test_a_run_nobody_started_writes_to_the_owners_chat(self) -> None:
        await self._run({}, actor_user_id=None)
        self.assertEqual(self.turn_users, [self.owner.id])
        self.assertEqual(await self._conversation_owners(), [self.owner.id])

    async def test_someone_elses_conversation_fails_like_a_deleted_one(self) -> None:
        async with self.sessions() as db:
            owners_chat = DashboardConversation(
                user_id=self.owner.id, title="Owner only", source="chat"
            )
            db.add(owners_chat)
            await db.commit()
        deleted = uuid.uuid4()

        messages = []
        for target in (owners_chat.id, deleted):
            for fire_and_forget in (False, True):
                with self.assertRaises(ValueError) as caught:
                    await self._run(
                        {
                            "heymChatContinue": True,
                            "heymChatConversationId": str(target),
                            "heymChatFireAndForget": fire_and_forget,
                        },
                        actor_user_id=self.collaborator.id,
                    )
                messages.append(str(caught.exception).replace(str(target), "<id>"))
        self.assertEqual(set(messages), {"Conversation not found or not accessible: <id>"})
        self.assertEqual(self.turn_users, [])

    async def test_the_owners_own_conversation_can_be_continued(self) -> None:
        async with self.sessions() as db:
            owners_chat = DashboardConversation(user_id=self.owner.id, title="Mine", source="chat")
            db.add(owners_chat)
            await db.commit()
        output = await self._run(
            {"heymChatContinue": True, "heymChatConversationId": str(owners_chat.id)},
            actor_user_id=self.owner.id,
        )
        self.assertEqual(output["conversation_id"], str(owners_chat.id))
        self.assertEqual(self.turn_users, [self.owner.id])


if __name__ == "__main__":
    unittest.main()
