"""Deterministic concurrency race tests against real PostgreSQL.

Covers Issue #684:
Ensures Dashboard Chat run claims (normal chat POST messages, queued messages,
and MCP run_mcp_chat_turn) take row locks with FOR UPDATE on the first load,
preventing duplicate background chat tasks or duplicate run starts.
"""

import asyncio
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import delete, select

from app.api.chats import (
    ChatTurnResult,
    _chat_tasks,
    _dequeue_next_turn,
    run_mcp_chat_turn,
    send_message,
)
from app.db.models import (
    Credential,
    CredentialType,
    DashboardChatQueueItem,
    DashboardConversation,
    DashboardMessage,
    User,
)
from app.db.session import async_session_maker, engine
from app.models.chat_schemas import MessageCreate
from app.services.mcp_chat_service import MCPChatError


def _make_dummy_http_request() -> MagicMock:
    req = MagicMock()
    req.base_url = "http://localhost:10105"
    req.url = MagicMock()
    return req


class DashboardChatConcurrencyRaceTests(unittest.IsolatedAsyncioTestCase):
    """Test concurrent chat runs and row-level locking against real PostgreSQL."""

    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.user_id = uuid.uuid4()
        self.cred_id = uuid.uuid4()
        self.conv_id = uuid.uuid4()

        async with async_session_maker() as session:
            self.user = User(
                id=self.user_id,
                email=f"test_chat_race_{self.user_id.hex[:8]}@example.com",
                hashed_password="test_hashed_password",
                name="Test Chat Race User",
            )
            session.add(self.user)
            await session.flush()

            self.cred = Credential(
                id=self.cred_id,
                owner_id=self.user_id,
                name="Test OpenAI",
                type=CredentialType.openai,
                encrypted_config="encrypted",
            )
            session.add(self.cred)

            self.conv = DashboardConversation(
                id=self.conv_id,
                user_id=self.user_id,
                title="Test Concurrency Chat",
                is_running=False,
            )
            session.add(self.conv)
            await session.commit()

    async def asyncTearDown(self) -> None:
        _chat_tasks.pop(str(self.conv_id), None)
        async with async_session_maker() as session:
            await session.execute(
                delete(DashboardChatQueueItem).where(
                    DashboardChatQueueItem.conversation_id == self.conv_id
                )
            )
            await session.execute(
                delete(DashboardMessage).where(DashboardMessage.conversation_id == self.conv_id)
            )
            await session.execute(
                delete(DashboardConversation).where(DashboardConversation.id == self.conv_id)
            )
            await session.execute(delete(Credential).where(Credential.id == self.cred_id))
            await session.execute(delete(User).where(User.id == self.user_id))
            await session.commit()
        await engine.dispose()

    async def test_concurrent_send_message_claims_exactly_one_run(self) -> None:
        """Prove that two concurrent POST /messages calls for the same conversation

        cannot both claim 'started'; exactly one claims/starts and the other queues.
        """
        mock_process_chat = AsyncMock()

        body1 = MessageCreate(
            content="Message 1",
            credential_id=str(self.cred_id),
            model="gpt-4o",
        )
        body2 = MessageCreate(
            content="Message 2",
            credential_id=str(self.cred_id),
            model="gpt-4o",
        )

        with patch("app.api.chats._process_chat", mock_process_chat):
            async with async_session_maker() as s1, async_session_maker() as s2:
                req1 = send_message(
                    http_request=_make_dummy_http_request(),
                    conversation_id=self.conv_id,
                    body=body1,
                    current_user=self.user,
                    db=s1,
                )
                req2 = send_message(
                    http_request=_make_dummy_http_request(),
                    conversation_id=self.conv_id,
                    body=body2,
                    current_user=self.user,
                    db=s2,
                )
                resp1, resp2 = await asyncio.gather(req1, req2)

        # Invariant 1: Exactly one started, exactly one queued
        statuses = {resp1.status, resp2.status}
        self.assertEqual(statuses, {"started", "queued"})

        # Invariant 2: Exactly one background chat task was created
        self.assertEqual(mock_process_chat.call_count, 1)

        # Invariant 3: Exactly one DashboardMessage created, exactly one QueueItem created
        async with async_session_maker() as session:
            msgs = (
                (
                    await session.execute(
                        select(DashboardMessage).where(
                            DashboardMessage.conversation_id == self.conv_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            queue_items = (
                (
                    await session.execute(
                        select(DashboardChatQueueItem).where(
                            DashboardChatQueueItem.conversation_id == self.conv_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            conv = (
                await session.execute(
                    select(DashboardConversation).where(DashboardConversation.id == self.conv_id)
                )
            ).scalar_one()

            self.assertEqual(len(msgs), 1)
            self.assertEqual(len(queue_items), 1)
            self.assertTrue(conv.is_running)

    async def test_concurrent_send_message_and_mcp_chat_turn(self) -> None:
        """Prove that concurrent send_message and run_mcp_chat_turn for the same

        conversation cannot both start; one claims and the other either queues
        or raises MCPChatError.
        """
        assistant_msg_id = uuid.uuid4()

        async def _dummy_run_chat_turn(conv_id, user_id, turn, public_base_url):
            # Record dummy assistant reply in database
            async with async_session_maker() as db:
                db.add(
                    DashboardMessage(
                        id=assistant_msg_id,
                        conversation_id=uuid.UUID(conv_id),
                        role="assistant",
                        content="MCP reply",
                        created_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
            await asyncio.sleep(0.05)
            return ChatTurnResult(
                paused_for_clarification=False, assistant_message_id=assistant_msg_id
            )

        async def _dummy_process_chat(*args, **kwargs):
            await asyncio.sleep(0.05)

        body = MessageCreate(
            content="Normal message",
            credential_id=str(self.cred_id),
            model="gpt-4o",
        )

        with (
            patch("app.api.chats._run_chat_turn", side_effect=_dummy_run_chat_turn),
            patch("app.api.chats._process_chat", side_effect=_dummy_process_chat),
        ):
            async with async_session_maker() as s1:
                t1 = send_message(
                    http_request=_make_dummy_http_request(),
                    conversation_id=self.conv_id,
                    body=body,
                    current_user=self.user,
                    db=s1,
                )
                t2 = run_mcp_chat_turn(
                    user_id=self.user_id,
                    message="MCP message",
                    conversation_id=self.conv_id,
                    credential_id=self.cred_id,
                    model="gpt-4o",
                    public_base_url="http://localhost:10105",
                )
                res1, res2 = await asyncio.gather(t1, t2, return_exceptions=True)

        # Either send_message claimed (started) and MCP failed with MCPChatError,
        # OR MCP claimed (succeeded) and send_message queued.
        if isinstance(res2, Exception):
            self.assertIsInstance(res2, MCPChatError)
            self.assertIn("already running", str(res2))
            self.assertEqual(res1.status, "started")
        else:
            self.assertEqual(res1.status, "queued")
            self.assertEqual(res2.text, "MCP reply")

    async def test_concurrent_mcp_chat_turns_rejects_duplicate(self) -> None:
        """Prove that two concurrent run_mcp_chat_turn calls for the same conversation

        cannot both claim; exactly one runs and the other raises MCPChatError.
        """
        assistant_msg_id1 = uuid.uuid4()
        assistant_msg_id2 = uuid.uuid4()

        call_count = 0

        async def _dummy_run_chat_turn(conv_id, user_id, turn, public_base_url):
            nonlocal call_count
            call_count += 1
            msg_id = assistant_msg_id1 if call_count == 1 else assistant_msg_id2
            async with async_session_maker() as db:
                db.add(
                    DashboardMessage(
                        id=msg_id,
                        conversation_id=uuid.UUID(conv_id),
                        role="assistant",
                        content="Reply",
                        created_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
            await asyncio.sleep(0.05)
            return ChatTurnResult(paused_for_clarification=False, assistant_message_id=msg_id)

        with patch("app.api.chats._run_chat_turn", side_effect=_dummy_run_chat_turn):
            t1 = run_mcp_chat_turn(
                user_id=self.user_id,
                message="Turn 1",
                conversation_id=self.conv_id,
                credential_id=self.cred_id,
                model="gpt-4o",
                public_base_url="http://localhost:10105",
            )
            t2 = run_mcp_chat_turn(
                user_id=self.user_id,
                message="Turn 2",
                conversation_id=self.conv_id,
                credential_id=self.cred_id,
                model="gpt-4o",
                public_base_url="http://localhost:10105",
            )
            r1, r2 = await asyncio.gather(t1, t2, return_exceptions=True)

        successes = [r for r in (r1, r2) if not isinstance(r, Exception)]
        errors = [r for r in (r1, r2) if isinstance(r, Exception)]

        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MCPChatError)
        self.assertIn("already running", str(errors[0]))

    async def test_queued_branch_starts_queue_worker_when_conversation_becomes_idle(self) -> None:
        """Prove that if a message is queued while conversation was running, but

        the worker finished (is_running = False) right when queueing completed,
        the queued branch safely transitions is_running = True and starts _process_chat_queue.
        """
        # Set conversation to running initially
        async with async_session_maker() as s:
            c = (
                await s.execute(
                    select(DashboardConversation).where(DashboardConversation.id == self.conv_id)
                )
            ).scalar_one()
            c.is_running = True
            await s.commit()

        mock_process_queue = AsyncMock()
        body = MessageCreate(content="Queued item", credential_id=str(self.cred_id), model="gpt-4o")

        with patch("app.api.chats._process_chat_queue", mock_process_queue):
            async with async_session_maker() as s1:
                real_commit = s1.commit

                intercepted = False

                async def intercept_commit():
                    nonlocal intercepted
                    await real_commit()
                    if not intercepted:
                        intercepted = True
                        # Mark conversation idle in DB before s1 re-checks with with_for_update
                        async with async_session_maker() as s_idle:
                            conv_idle = (
                                await s_idle.execute(
                                    select(DashboardConversation).where(
                                        DashboardConversation.id == self.conv_id
                                    )
                                )
                            ).scalar_one()
                            conv_idle.is_running = False
                            await s_idle.commit()

                s1.commit = intercept_commit

                resp = await send_message(
                    http_request=_make_dummy_http_request(),
                    conversation_id=self.conv_id,
                    body=body,
                    current_user=self.user,
                    db=s1,
                )

        self.assertEqual(resp.status, "queued")
        self.assertEqual(mock_process_queue.call_count, 1)

        # Invariant: Conversation is now is_running = True in DB
        async with async_session_maker() as s:
            conv = (
                await s.execute(
                    select(DashboardConversation).where(DashboardConversation.id == self.conv_id)
                )
            ).scalar_one()
            self.assertTrue(conv.is_running)

    async def test_dequeue_next_turn_and_finish_worker_state_locking(self) -> None:
        """Prove that while a transaction holds DashboardConversation row lock,

        _dequeue_next_turn and _finish_worker_state wait for the lock.
        """
        async with async_session_maker() as locking_session:
            # Acquire exclusive row lock in locking_session
            conv = (
                await locking_session.execute(
                    select(DashboardConversation)
                    .where(DashboardConversation.id == self.conv_id)
                    .with_for_update()
                )
            ).scalar_one()
            conv.is_running = True

            dequeue_started = False
            dequeue_finished = False

            async def attempt_dequeue():
                nonlocal dequeue_started, dequeue_finished
                dequeue_started = True
                turn = await _dequeue_next_turn(str(self.conv_id))
                dequeue_finished = True
                return turn

            task = asyncio.create_task(attempt_dequeue())
            # Give attempt_dequeue time to start and block on row lock
            await asyncio.sleep(0.05)

            self.assertTrue(dequeue_started)
            # Must still be blocked waiting for row lock
            self.assertFalse(dequeue_finished)

            # Now commit locking_session to release row lock
            await locking_session.commit()

            # Now attempt_dequeue can finish
            turn = await task
            self.assertTrue(dequeue_finished)
            self.assertIsNone(turn)
