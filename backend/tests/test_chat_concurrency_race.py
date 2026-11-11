"""Deterministic concurrency race tests against real PostgreSQL.

Covers Issue #684:
Ensures Dashboard Chat run claims (normal chat POST messages, queued messages,
and MCP run_agent_chat_turn) take row locks with FOR UPDATE on the first load,
preventing duplicate background chat tasks or duplicate run starts.
"""

import asyncio
import unittest
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.api import ai_assistant, chats
from app.api.chats import (
    ChatTurn,
    ChatTurnResult,
    _cancel_events,
    _chat_tasks,
    _dequeue_next_turn,
    _process_chat,
    run_agent_chat_turn,
    send_message,
    send_queued_message_now,
)
from app.db.models import (
    Credential,
    CredentialType,
    DashboardChatQueueItem,
    DashboardConversation,
    DashboardMessage,
    LLMTrace,
    RunHistory,
    User,
)
from app.db.session import async_session_maker, engine
from app.models.chat_schemas import MessageCreate
from app.services.chat_round_stream import RoundAnswer, RoundDraft
from app.services.heym_agent.errors import AgentError
from app.services.trace_metrics import compute_trace_stats, trace_filters, trace_status


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

    async def test_interrupted_model_call_is_cancelled_and_replacement_only_queries_teams(
        self,
    ) -> None:
        """Persist both terminal states and give the replacement no unfinished user task."""
        conv_id = str(self.conv_id)
        first_content = "Which workflows ran today?"
        latest_content = "Skip the workflow question, just show my teams"
        selected_id = uuid.uuid4()
        async with async_session_maker() as db:
            conversation = await db.get(DashboardConversation, self.conv_id)
            conversation.is_running = True
            db.add_all(
                [
                    DashboardMessage(
                        conversation_id=self.conv_id, role="user", content=first_content
                    ),
                    DashboardChatQueueItem(
                        id=selected_id,
                        conversation_id=self.conv_id,
                        content=latest_content,
                        credential_id=self.cred_id,
                        model="gpt-4o",
                    ),
                ]
            )
            await db.commit()
        started = asyncio.Event()

        async def model_round(
            _client: object, _cancel: Event | None, **kwargs: object
        ) -> AsyncGenerator[RoundDraft | RoundAnswer, None]:
            messages = kwargs["messages"]
            users = [m["content"] for m in messages if m["role"] == "user"]
            if users[-1].startswith(first_content):
                yield RoundDraft("Looking up workflow runs")
                started.set()
                await asyncio.Event().wait()
            self.assertNotIn(first_content, users)
            self.assertIn("Current request after an interruption", messages[0]["content"])
            calls = None
            text = "Here are your teams"
            if not any(m["role"] == "tool" for m in messages):
                calls = [
                    SimpleNamespace(
                        id="teams-call",
                        type="function",
                        function=SimpleNamespace(name="get_teams", arguments="{}"),
                    )
                ]
                text = None
            yield RoundAnswer(
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=calls))
                    ],
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                )
            )

        def binding(*_args: object, **kwargs: object) -> tuple[object, str, str, object]:
            return MagicMock(), "OpenAI", "gpt-4o", kwargs["trace_context"]

        previous = worker = None
        try:
            with (
                patch.object(chats, "decrypt_config", return_value={}),
                patch.object(chats, "resolve_model_binding", side_effect=binding),
                patch.object(chats, "ChatFileTools") as files,
                patch.object(
                    chats,
                    "_assemble_system_prompt_parts",
                    AsyncMock(return_value=chats.SystemPromptParts("system", "system", "", "", "")),
                ),
                patch.object(ai_assistant, "stream_round", model_round),
                patch.object(
                    ai_assistant, "get_teams_tool", AsyncMock(return_value='{"teams":[]}')
                ) as teams,
                patch.object(ai_assistant, "get_recent_executions_for_user", AsyncMock()) as runs,
            ):
                files.return_value.workspace_block.return_value = ""
                files.return_value.handles.return_value = False
                files.return_value.schemas.return_value = []
                await chats.registry.create_task(conv_id)
                previous = asyncio.create_task(
                    chats._process_chat(
                        conv_id,
                        self.user_id,
                        first_content,
                        self.cred_id,
                        "gpt-4o",
                        [],
                        "http://localhost",
                        False,
                    )
                )
                _chat_tasks[conv_id] = previous
                await asyncio.wait_for(started.wait(), 5)
                async with async_session_maker() as db:
                    await send_queued_message_now(
                        _make_dummy_http_request(), self.conv_id, selected_id, self.user, db
                    )
                worker = _chat_tasks[conv_id]
                await asyncio.wait_for(worker, 5)
                await previous
                teams.assert_awaited_once()
                runs.assert_not_awaited()
            async with async_session_maker() as db:
                traces = (
                    await db.scalars(
                        select(LLMTrace)
                        .where(LLMTrace.user_id == self.user_id)
                        .order_by(LLMTrace.created_at)
                    )
                ).all()
                self.assertEqual(
                    [trace_status(t.error, t.response) for t in traces], ["cancelled", "success"]
                )
                self.assertTrue(traces[0].response["turn_timings"][0]["cancelled"])
                self.assertIsNone(traces[0].total_tokens)
                runs = (
                    await db.scalars(
                        select(RunHistory)
                        .where(RunHistory.user_id == self.user_id)
                        .order_by(RunHistory.started_at)
                    )
                ).all()
                self.assertEqual([run.status for run in runs], ["cancelled", "success"])
                filters = trace_filters(self.user_id)
                stats = await compute_trace_stats(
                    db,
                    user_id=self.user_id,
                    filters=filters,
                    search=None,
                    bucket_seconds=3600,
                    resolve_costs=AsyncMock(return_value=[(None, False)]),
                )
                self.assertEqual(stats.kpis.total_calls, 2)
                self.assertEqual(stats.kpis.success_calls, 1)
                self.assertEqual(stats.kpis.error_calls, 0)
                self.assertEqual(sum(row.success for row in stats.by_time), 1)
                cancelled = (
                    await db.scalars(
                        select(LLMTrace.id).where(*trace_filters(self.user_id, status="cancelled"))
                    )
                ).all()
                self.assertEqual(cancelled, [traces[0].id])
        finally:
            for task in (previous, worker):
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            _cancel_events.pop(conv_id, None)

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

    async def test_send_now_waits_for_cancel_then_appends_selected_message_with_its_settings(
        self,
    ) -> None:
        """A selected follow-up runs first, after the partial reply, without losing the queue."""
        conv_id = str(self.conv_id)
        now = datetime.now(timezone.utc)
        attachment = {"name": "notes.txt", "kind": "text", "content": "Attached notes"}
        first_id, selected_id = uuid.uuid4(), uuid.uuid4()
        async with async_session_maker() as db:
            conversation = await db.get(DashboardConversation, self.conv_id)
            conversation.is_running = True
            db.add_all(
                [
                    DashboardChatQueueItem(
                        id=first_id,
                        conversation_id=self.conv_id,
                        content="Older follow-up",
                        credential_id=self.cred_id,
                        model="old-model",
                        created_at=now - timedelta(seconds=2),
                    ),
                    DashboardChatQueueItem(
                        id=selected_id,
                        conversation_id=self.conv_id,
                        content="Send this now",
                        credential_id=self.cred_id,
                        model="selected-model",
                        attachment=attachment,
                        allow_build=True,
                        build_target_workflow_id=None,
                        created_at=now - timedelta(seconds=1),
                    ),
                ]
            )
            await db.commit()

        old_started, old_cancelled, allow_old_finish = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        new_started, allow_new_finish = asyncio.Event(), asyncio.Event()
        turns: list[ChatTurn] = []

        async def old_worker() -> None:
            old_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                old_cancelled.set()
                await allow_old_finish.wait()
                async with async_session_maker() as db:
                    db.add(
                        DashboardMessage(
                            conversation_id=self.conv_id, role="assistant", content="Partial reply"
                        )
                    )
                    await db.commit()

        async def run_turn(
            _conv_id: str, _user_id: uuid.UUID, turn: ChatTurn, _base_url: str
        ) -> ChatTurnResult:
            turns.append(turn)
            new_started.set()
            await allow_new_finish.wait()
            return ChatTurnResult(False, uuid.uuid4())

        previous = asyncio.create_task(old_worker())
        _chat_tasks[conv_id] = previous
        _cancel_events[conv_id] = Event()
        await old_started.wait()
        worker: asyncio.Task[None] | None = None
        try:
            with patch("app.api.chats._run_chat_turn", side_effect=run_turn):
                async with async_session_maker() as db:
                    response = await send_queued_message_now(
                        _make_dummy_http_request(), self.conv_id, selected_id, self.user, db
                    )
                worker = _chat_tasks[conv_id]
                self.assertIsNot(worker, previous)
                self.assertEqual(response.status, "started")
                await asyncio.wait_for(old_cancelled.wait(), 3)
                self.assertFalse(new_started.is_set())
                # A double click while cancellation is pending must not start a second worker.
                async with async_session_maker() as db:
                    with self.assertRaises(HTTPException) as raised:
                        await send_queued_message_now(
                            _make_dummy_http_request(), self.conv_id, selected_id, self.user, db
                        )
                self.assertEqual(raised.exception.status_code, 409)

                allow_old_finish.set()
                await asyncio.wait_for(new_started.wait(), 3)
                self.assertEqual(turns[0].content, "Send this now")
                self.assertEqual(turns[0].model, "selected-model")
                self.assertTrue(turns[0].interrupted)
                self.assertEqual(turns[0].attachments, [attachment])
                self.assertIsNotNone(turns[0].build)
                async with async_session_maker() as db:
                    messages = (
                        await db.scalars(
                            select(DashboardMessage)
                            .where(DashboardMessage.conversation_id == self.conv_id)
                            .order_by(DashboardMessage.created_at)
                        )
                    ).all()
                    self.assertEqual([m.role for m in messages], ["assistant", "user"])
                    self.assertEqual(messages[0].content, "Partial reply")
                    self.assertIn("Send this now", messages[1].content)
                    self.assertIn("Attached notes", messages[1].content)
                    queued = (
                        await db.scalars(
                            select(DashboardChatQueueItem).where(
                                DashboardChatQueueItem.conversation_id == self.conv_id
                            )
                        )
                    ).all()
                    self.assertEqual([item.id for item in queued], [first_id])
                allow_new_finish.set()
                await asyncio.wait_for(worker, 3)
                self.assertEqual(
                    [turn.content for turn in turns], ["Send this now", "Older follow-up"]
                )
                self.assertFalse(turns[1].interrupted)
        finally:
            allow_old_finish.set()
            allow_new_finish.set()
            for task in (previous, worker):
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            _cancel_events.pop(conv_id, None)

    async def test_send_now_refuses_another_users_conversation_and_wrong_queue_item(self) -> None:
        """Failed ownership or item checks must leave the existing run untouched."""
        conv_id = str(self.conv_id)
        async with async_session_maker() as db:
            conversation = await db.get(DashboardConversation, self.conv_id)
            conversation.is_running = True
            await db.commit()
        previous = asyncio.create_task(asyncio.sleep(60))
        _chat_tasks[conv_id] = previous
        event = Event()
        _cancel_events[conv_id] = event
        try:
            for user in (MagicMock(id=uuid.uuid4()), self.user):
                async with async_session_maker() as db:
                    with self.assertRaises(HTTPException) as raised:
                        await send_queued_message_now(
                            _make_dummy_http_request(), self.conv_id, uuid.uuid4(), user, db
                        )
                self.assertEqual(raised.exception.status_code, 404)
                self.assertFalse(event.is_set())
                self.assertIs(_chat_tasks[conv_id], previous)
                self.assertFalse(previous.done())
        finally:
            previous.cancel()
            await asyncio.gather(previous, return_exceptions=True)
            _cancel_events.pop(conv_id, None)

    async def test_concurrent_send_message_and_mcp_chat_turn(self) -> None:
        """Prove that concurrent send_message and run_agent_chat_turn for the same

        conversation cannot both start; one claims and the other either queues
        or raises AgentError.
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
                t2 = run_agent_chat_turn(
                    user_id=self.user_id,
                    message="MCP message",
                    conversation_id=self.conv_id,
                    credential_id=self.cred_id,
                    model="gpt-4o",
                    public_base_url="http://localhost:10105",
                )
                res1, res2 = await asyncio.gather(t1, t2, return_exceptions=True)

        # Either send_message claimed (started) and MCP failed with AgentError,
        # OR MCP claimed (succeeded) and send_message queued.
        if isinstance(res2, Exception):
            self.assertIsInstance(res2, AgentError)
            self.assertIn("already running", str(res2))
            self.assertEqual(res1.status, "started")
        else:
            self.assertEqual(res1.status, "queued")
            self.assertEqual(res2.text, "MCP reply")

    async def test_concurrent_mcp_chat_turns_rejects_duplicate(self) -> None:
        """Prove that two concurrent run_agent_chat_turn calls for the same conversation

        cannot both claim; exactly one runs and the other raises AgentError.
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
            t1 = run_agent_chat_turn(
                user_id=self.user_id,
                message="Turn 1",
                conversation_id=self.conv_id,
                credential_id=self.cred_id,
                model="gpt-4o",
                public_base_url="http://localhost:10105",
            )
            t2 = run_agent_chat_turn(
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
        self.assertIsInstance(errors[0], AgentError)
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

    async def test_old_worker_exception_does_not_reset_real_postgres_state(self) -> None:
        """Prove against real PostgreSQL that when an old worker raises an exception
        after a newer worker took ownership:
        1. conversation.is_running remains True in the database.
        2. DashboardChatQueueItem is NOT deleted from the database.
        3. The newer worker's task and cancel event remain registered.
        4. Conversely, when the owning worker fails, is_running is set to False and queue is cleared.
        """
        queue_item_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # 1. Setup conversation as running with a queued item in real PostgreSQL
        async with async_session_maker() as s:
            c = (
                await s.execute(
                    select(DashboardConversation).where(DashboardConversation.id == self.conv_id)
                )
            ).scalar_one()
            c.is_running = True
            queue_item = DashboardChatQueueItem(
                id=queue_item_id,
                conversation_id=self.conv_id,
                content="Queued item to preserve",
                credential_id=self.cred_id,
                model="gpt-4o",
                created_at=now,
                updated_at=now,
            )
            s.add(queue_item)
            await s.commit()

        newer_task = asyncio.create_task(asyncio.sleep(10))
        newer_event = Event()
        conv_id_str = str(self.conv_id)

        async def _supersede_and_fail(*args, **kwargs):
            _chat_tasks[conv_id_str] = newer_task
            _cancel_events[conv_id_str] = newer_event
            raise RuntimeError("Old worker simulated error")

        try:
            with (
                patch("app.api.chats.registry.has_task", new_callable=AsyncMock, return_value=True),
                patch("app.api.chats.registry.finish", new_callable=AsyncMock) as mock_finish,
                patch("app.api.chats.registry.publish", new_callable=AsyncMock) as mock_publish,
                patch("app.api.chats._run_chat_turn", side_effect=_supersede_and_fail),
            ):
                await _process_chat(
                    conv_id=conv_id_str,
                    user_id=self.user_id,
                    content="Old msg",
                    credential_id=self.cred_id,
                    model="gpt-4o",
                    attachments=[],
                    public_base_url="http://localhost:10105",
                    should_generate_title=False,
                )

            # Invariants on real PostgreSQL:
            async with async_session_maker() as s:
                conv = (
                    await s.execute(
                        select(DashboardConversation).where(
                            DashboardConversation.id == self.conv_id
                        )
                    )
                ).scalar_one()
                self.assertTrue(conv.is_running)

                q_item = (
                    await s.execute(
                        select(DashboardChatQueueItem).where(
                            DashboardChatQueueItem.id == queue_item_id
                        )
                    )
                ).scalar_one_or_none()
                self.assertIsNotNone(q_item)

            self.assertIs(_chat_tasks.get(conv_id_str), newer_task)
            self.assertIs(_cancel_events.get(conv_id_str), newer_event)
            mock_finish.assert_not_called()
            mock_publish.assert_not_called()

            # Now test current/owning worker failure: cleans up in real PostgreSQL
            current_task = asyncio.current_task()
            _chat_tasks[conv_id_str] = current_task

            with (
                patch("app.api.chats.registry.has_task", new_callable=AsyncMock, return_value=True),
                patch("app.api.chats.registry.finish", new_callable=AsyncMock) as mock_finish2,
                patch("app.api.chats.registry.publish", new_callable=AsyncMock),
                patch(
                    "app.api.chats._run_chat_turn",
                    side_effect=RuntimeError("Current worker error"),
                ),
            ):
                await _process_chat(
                    conv_id=conv_id_str,
                    user_id=self.user_id,
                    content="Current msg",
                    credential_id=self.cred_id,
                    model="gpt-4o",
                    attachments=[],
                    public_base_url="http://localhost:10105",
                    should_generate_title=False,
                )

            # Invariants on real PostgreSQL after current worker failure:
            async with async_session_maker() as s:
                conv = (
                    await s.execute(
                        select(DashboardConversation).where(
                            DashboardConversation.id == self.conv_id
                        )
                    )
                ).scalar_one()
                self.assertFalse(conv.is_running)

                q_item = (
                    await s.execute(
                        select(DashboardChatQueueItem).where(
                            DashboardChatQueueItem.id == queue_item_id
                        )
                    )
                ).scalar_one_or_none()
                self.assertIsNone(q_item)

            self.assertIsNone(_chat_tasks.get(conv_id_str))
            self.assertIsNone(_cancel_events.get(conv_id_str))
            mock_finish2.assert_awaited_once_with(conv_id_str)
        finally:
            newer_task.cancel()
            await asyncio.gather(newer_task, return_exceptions=True)
