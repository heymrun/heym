"""The Heym node's Send Chat Message operation: handler, routing, depth, cancellation."""

import concurrent.futures
import threading
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import app_loop
from app.services.heym_agent.turn import AgentOutcome, AgentTurnResult
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import heym_node
from app.services.workflow_executor import WorkflowCancelledError, WorkflowExecutor


def _chat_ctx(
    node_data: dict,
    *,
    actor_user_id: uuid.UUID | None = None,
    sub_workflow_depth: int = 0,
    chat_depth: int = 0,
) -> NodeExecutionContext:
    executor = MagicMock()
    executor.workflow_id = str(uuid.uuid4())
    executor.actor_user_id = actor_user_id or uuid.uuid4()
    executor._sub_workflow_invocation_depth = sub_workflow_depth
    executor.chat_turn_depth = chat_depth
    executor.evaluate_message_template.side_effect = lambda v, *_a, **_kw: str(v) if v else ""
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


def _done(value: dict) -> concurrent.futures.Future:
    future: concurrent.futures.Future = concurrent.futures.Future()
    future.set_result(value)
    return future


def _wait_output(status: str, conversation_id: str | None = "c1") -> dict:
    return {
        "conversation_id": conversation_id,
        "status": status,
        "reply": "hi",
        "tool_names": [],
        "verified": False,
        "workflow_links": [],
        "eval_suite_links": [],
        "credential_form_urls": [],
    }


class ChatHandlerTestBase(unittest.TestCase):
    """Patches the DB session and the app-loop submit; records what the handler sent."""

    def setUp(self) -> None:
        session_cm = MagicMock()
        session_cm.__enter__.return_value = MagicMock()
        session_cm.__exit__.return_value = False
        patcher = patch("app.db.session.SessionLocal", MagicMock(return_value=session_cm))
        patcher.start()
        self.addCleanup(patcher.stop)

        self.requests: list = []
        self.next_output: dict = _wait_output("completed")

        async def fake_wait(request):  # pragma: no cover - never awaited
            return None

        def record(name: str):
            def factory(request):
                self.requests.append((name, request))
                return fake_wait(request)

            return factory

        for name in ("send_and_wait", "send_in_background"):
            # A plain mock: an AsyncMock would only run the side effect when awaited.
            p = patch(
                f"app.services.heym_chat_node.{name}", new=MagicMock(side_effect=record(name))
            )
            p.start()
            self.addCleanup(p.stop)

        def submit(coro):
            coro.close()
            return _done(self.next_output)

        self.submit = patch.object(app_loop, "submit", side_effect=submit)
        self.submit_mock = self.submit.start()
        self.addCleanup(self.submit.stop)


class ChatFieldValidationTests(ChatHandlerTestBase):
    def test_empty_message_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a chat message"):
            heym_node.execute(_chat_ctx({"heymChatMessage": "  "}))
        self.submit_mock.assert_not_called()

    def test_oversized_message_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "too long"):
            heym_node.execute(_chat_ctx({"heymChatMessage": "x" * 20001}))

    def test_no_history_and_continue_together_are_refused(self) -> None:
        ctx = _chat_ctx(
            {
                "heymChatMessage": "hello",
                "heymChatNoHistory": True,
                "heymChatContinue": True,
                "heymChatConversationId": str(uuid.uuid4()),
            }
        )
        with self.assertRaisesRegex(ValueError, "Don't save chat history"):
            heym_node.execute(ctx)
        self.submit_mock.assert_not_called()

    def test_continue_with_a_malformed_or_empty_id_fails_like_a_missing_one(self) -> None:
        for raw in ("not-a-uuid", ""):
            ctx = _chat_ctx(
                {"heymChatMessage": "hi", "heymChatContinue": True, "heymChatConversationId": raw}
            )
            with self.assertRaisesRegex(ValueError, "Conversation not found or not accessible"):
                heym_node.execute(ctx)
        self.submit_mock.assert_not_called()

    def test_conversation_id_is_ignored_unless_continue_is_on(self) -> None:
        ctx = _chat_ctx({"heymChatMessage": "hi", "heymChatConversationId": "garbage"})
        heym_node.execute(ctx)
        self.assertIsNone(self.requests[0][1].conversation_id)


class ChatRequestTests(ChatHandlerTestBase):
    def test_request_carries_the_run_user_message_and_toggles(self) -> None:
        actor = uuid.uuid4()
        conversation_id = uuid.uuid4()
        ctx = _chat_ctx(
            {
                "heymChatMessage": "Summarize today",
                "heymChatContinue": True,
                "heymChatConversationId": str(conversation_id),
            },
            actor_user_id=actor,
        )
        heym_node.execute(ctx)
        name, request = self.requests[0]
        self.assertEqual(name, "send_and_wait")
        self.assertEqual(request.user_id, actor)
        self.assertEqual(request.message, "Summarize today")
        self.assertEqual(request.conversation_id, conversation_id)
        self.assertFalse(request.temporary)
        self.assertEqual(request.depth, 1)

    def test_fire_and_forget_starts_in_the_background(self) -> None:
        self.next_output = {"conversation_id": "c1", "status": "started"}
        ctx = _chat_ctx({"heymChatMessage": "hi", "heymChatFireAndForget": True})
        output = heym_node.execute(ctx)
        self.assertEqual(self.requests[0][0], "send_in_background")
        self.assertEqual(output["status"], "started")
        self.assertEqual(output["_skip_source_handles"], ["question"])

    def test_no_history_sends_a_temporary_request(self) -> None:
        ctx = _chat_ctx({"heymChatMessage": "hi", "heymChatNoHistory": True})
        heym_node.execute(ctx)
        self.assertTrue(self.requests[0][1].temporary)

    def test_message_is_resolved_as_an_expression(self) -> None:
        ctx = _chat_ctx({"heymChatMessage": "$input.text"})
        ctx.executor.evaluate_message_template.side_effect = lambda v, *_a, **_kw: "resolved"
        heym_node.execute(ctx)
        self.assertEqual(self.requests[0][1].message, "resolved")

    def test_missing_app_loop_is_a_node_error(self) -> None:
        def no_loop(coro):
            coro.close()
            raise RuntimeError("The Heym application loop is not running.")

        self.submit_mock.side_effect = no_loop
        with self.assertRaisesRegex(ValueError, "Heym Chat is not available here"):
            heym_node.execute(_chat_ctx({"heymChatMessage": "hi"}))


class ChatHandleRoutingTests(ChatHandlerTestBase):
    def test_completed_and_canceled_turns_leave_through_output(self) -> None:
        for status in ("completed", "canceled"):
            self.next_output = _wait_output(status)
            output = heym_node.execute(_chat_ctx({"heymChatMessage": "hi"}))
            self.assertEqual(output["_skip_source_handles"], ["question"])
            self.assertEqual(output["status"], status)

    def test_questions_and_credential_forms_leave_through_question(self) -> None:
        for status in ("input_required", "auth_required"):
            self.next_output = _wait_output(status)
            output = heym_node.execute(_chat_ctx({"heymChatMessage": "hi"}))
            self.assertEqual(output["_skip_source_handles"], ["output"])

    def test_without_history_a_question_leaves_through_output(self) -> None:
        """A temporary conversation is gone afterwards, so the node has no QUESTION output."""
        for status in ("input_required", "auth_required"):
            self.next_output = _wait_output(status, conversation_id=None)
            ctx = _chat_ctx({"heymChatMessage": "hi", "heymChatNoHistory": True})
            output = heym_node.execute(ctx)
            self.assertEqual(output["_skip_source_handles"], ["question"])
            self.assertEqual(output["status"], status)


class ChatDepthTests(ChatHandlerTestBase):
    def test_chat_and_sub_workflow_hops_count_toward_one_limit(self) -> None:
        ctx = _chat_ctx({"heymChatMessage": "hi"}, sub_workflow_depth=2, chat_depth=3)
        with self.assertRaisesRegex(ValueError, "Max Heym Chat call depth exceeded"):
            heym_node.execute(ctx)
        self.submit_mock.assert_not_called()

    def test_turn_runs_one_hop_deeper_than_the_run(self) -> None:
        heym_node.execute(_chat_ctx({"heymChatMessage": "hi"}, sub_workflow_depth=1, chat_depth=2))
        self.assertEqual(self.requests[0][1].depth, 4)


class ChatCancellationTests(ChatHandlerTestBase):
    def test_stopping_the_run_cancels_the_waiting_turn(self) -> None:
        pending: concurrent.futures.Future = concurrent.futures.Future()

        def submit(coro):
            coro.close()
            return pending

        self.submit_mock.side_effect = submit
        ctx = _chat_ctx({"heymChatMessage": "hi"})
        ctx.executor.check_cancelled.side_effect = WorkflowCancelledError("stopped")
        with patch.object(heym_node, "_CHAT_CANCEL_POLL_SECONDS", 0.01):
            with self.assertRaises(WorkflowCancelledError):
                heym_node.execute(ctx)
        self.assertTrue(pending.cancelled())

    def test_a_turn_cancelled_elsewhere_is_a_node_error(self) -> None:
        cancelled: concurrent.futures.Future = concurrent.futures.Future()
        cancelled.cancel()

        def submit(coro):
            coro.close()
            return cancelled

        self.submit_mock.side_effect = submit
        with self.assertRaisesRegex(ValueError, "cancelled before it finished"):
            heym_node.execute(_chat_ctx({"heymChatMessage": "hi"}))


class ChatRunUserTests(ChatHandlerTestBase):
    def test_a_run_without_an_actor_writes_to_the_owners_chat(self) -> None:
        owner_id = uuid.uuid4()
        ctx = _chat_ctx({"heymChatMessage": "hi"})
        ctx.executor.actor_user_id = None
        workflow = MagicMock()
        workflow.owner_id = owner_id
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = workflow
        session_cm = MagicMock()
        session_cm.__enter__.return_value = db
        session_cm.__exit__.return_value = False
        with patch("app.db.session.SessionLocal", MagicMock(return_value=session_cm)):
            heym_node.execute(ctx)
        self.assertEqual(self.requests[0][1].user_id, owner_id)
        # The session is closed before the turn is submitted, not held while it runs.
        session_cm.__exit__.assert_called_once()


class ChatOutputShapeTests(unittest.TestCase):
    def test_build_chat_output_maps_the_turn_result(self) -> None:
        from app.services.heym_agent.links import WorkflowLink
        from app.services.heym_chat_node import build_chat_output

        conversation_id = uuid.uuid4()
        result = AgentTurnResult(
            conversation_id=conversation_id,
            text="Done",
            tool_names=["save_workflow"],
            outcome=AgentOutcome.COMPLETED,
            verified=True,
            workflow_links=(WorkflowLink(name="Digest", url="https://h/workflows/1"),),
            credential_form_urls=("https://h/credentials/setup/1",),
        )
        output = build_chat_output(result, temporary=False)
        self.assertEqual(
            output,
            {
                "conversation_id": str(conversation_id),
                "status": "completed",
                "reply": "Done",
                "questions": [],
                "tool_names": ["save_workflow"],
                "verified": True,
                "workflow_links": [{"name": "Digest", "url": "https://h/workflows/1"}],
                "eval_suite_links": [],
                "credential_form_urls": ["https://h/credentials/setup/1"],
            },
        )
        self.assertIsNone(build_chat_output(result, temporary=True)["conversation_id"])


class ClarifyQuestionTests(unittest.TestCase):
    def test_questions_are_split_out_of_the_reply(self) -> None:
        from app.services.heym_chat_node import split_clarify_questions

        text = (
            "Which report do you want?\n\n```heym-clarify\n"
            '{"questions": [{"id": "q1", "type": "text", "question": "Which report?"}]}\n```'
        )
        reply, questions = split_clarify_questions(text)
        self.assertEqual(reply, "Which report do you want?")
        self.assertEqual(questions, [{"id": "q1", "type": "text", "question": "Which report?"}])

    def test_a_reply_without_questions_is_unchanged(self) -> None:
        from app.services.heym_chat_node import split_clarify_questions

        self.assertEqual(split_clarify_questions("All done.\n"), ("All done.\n", []))

    def test_a_block_that_does_not_parse_stays_in_the_reply(self) -> None:
        from app.services.heym_chat_node import split_clarify_questions

        text = "Hm\n```heym-clarify\n{not json\n```"
        self.assertEqual(split_clarify_questions(text), (text, []))

    def test_the_output_carries_the_questions(self) -> None:
        from app.services.heym_chat_node import build_chat_output

        result = AgentTurnResult(
            conversation_id=uuid.uuid4(),
            text='Pick one\n```heym-clarify\n{"questions": [{"id": "a", "question": "A?"}]}\n```',
            tool_names=[],
            outcome=AgentOutcome.INPUT_REQUIRED,
        )
        output = build_chat_output(result, temporary=False)
        self.assertEqual(output["reply"], "Pick one")
        self.assertEqual(output["questions"], [{"id": "a", "question": "A?"}])
        self.assertEqual(output["status"], "input_required")


class ClarifyQuestionDocsTests(unittest.TestCase):
    def test_the_documented_question_field_is_the_one_the_protocol_defines(self) -> None:
        # The docs and the DSL said `question`; the model writes `text`, so
        # `$chat.questions[0].question` was empty.
        from pathlib import Path

        from app.services.workflow_dsl_prompt import (
            CLARIFY_PROTOCOL_PROMPT,
            WORKFLOW_DSL_SYSTEM_PROMPT,
        )

        self.assertIn("Each question: `id` (short slug), `text`, `type`", CLARIFY_PROTOCOL_PROMPT)
        docs = Path(__file__).resolve().parents[2] / "frontend/src/docs/content/nodes/heym-node.md"
        for text, marker in (
            (docs.read_text(), "`$nodeLabel.questions`"),
            (WORKFLOW_DSL_SYSTEM_PROMPT, "`$<label>.questions`"),
        ):
            with self.subTest(marker=marker):
                line = next(row for row in text.splitlines() if marker in row)
                self.assertIn("`id`, `text`", line)
                self.assertNotIn("`question`", line)


class ChatDefaultModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_user_without_a_chat_default_model_is_told_to_pick_one(self) -> None:
        from app.services import heym_chat_node

        user = MagicMock(preferred_credential_id=None, preferred_model=None)
        with patch.object(heym_chat_node, "load_user", AsyncMock(return_value=user)):
            with self.assertRaisesRegex(ValueError, "Pick a model in the Chat tab"):
                await heym_chat_node.resolve_chat_default_llm(MagicMock(), uuid.uuid4())

    async def test_an_unreachable_default_credential_is_refused(self) -> None:
        from app.services import heym_chat_node

        user = MagicMock(preferred_credential_id=uuid.uuid4(), preferred_model="gpt")
        with (
            patch.object(heym_chat_node, "load_user", AsyncMock(return_value=user)),
            patch.object(heym_chat_node, "get_accessible_credential", AsyncMock(return_value=None)),
        ):
            with self.assertRaisesRegex(ValueError, "no longer available"):
                await heym_chat_node.resolve_chat_default_llm(MagicMock(), uuid.uuid4())

    async def test_the_chat_default_model_is_used(self) -> None:
        from app.services import heym_chat_node

        credential = MagicMock(type=next(iter(heym_chat_node.LLM_CREDENTIAL_TYPES)))
        user = MagicMock(preferred_credential_id=uuid.uuid4(), preferred_model="gpt")
        with (
            patch.object(heym_chat_node, "load_user", AsyncMock(return_value=user)),
            patch.object(
                heym_chat_node, "get_accessible_credential", AsyncMock(return_value=credential)
            ),
        ):
            resolved = await heym_chat_node.resolve_chat_default_llm(MagicMock(), uuid.uuid4())
        self.assertIs(resolved.credential, credential)
        self.assertEqual(resolved.model, "gpt")


class ExecutorChatDepthTests(unittest.TestCase):
    def test_executor_reads_the_depth_of_the_context_it_is_built_in(self) -> None:
        with app_loop.chat_turn_depth_scope(2):
            executor = WorkflowExecutor(nodes=[], edges=[])
        self.assertEqual(executor.chat_turn_depth, 2)
        self.assertEqual(WorkflowExecutor(nodes=[], edges=[]).chat_turn_depth, 0)

    def test_an_explicit_depth_wins_over_the_context(self) -> None:
        with app_loop.chat_turn_depth_scope(2):
            executor = WorkflowExecutor(nodes=[], edges=[], chat_turn_depth=4)
        self.assertEqual(executor.chat_turn_depth, 4)

    def test_depth_survives_an_executor_built_in_a_plain_thread(self) -> None:
        """A sub-executor built in a node thread gets the parent's depth handed down."""
        with app_loop.chat_turn_depth_scope(3):
            parent = WorkflowExecutor(nodes=[], edges=[])
        built: dict = {}

        def build() -> None:
            built["child"] = WorkflowExecutor(
                nodes=[], edges=[], chat_turn_depth=parent.chat_turn_depth
            )

        worker = threading.Thread(target=build)
        worker.start()
        worker.join()
        self.assertEqual(built["child"].chat_turn_depth, 3)


class OutputHandleSkipTests(unittest.TestCase):
    def _executor(self, node_type: str) -> WorkflowExecutor:
        return WorkflowExecutor(
            nodes=[
                {"id": "a", "type": node_type, "data": {"label": "a"}},
                {"id": "b", "type": "set", "data": {"label": "b"}},
            ],
            edges=[],
        )

    def test_skipping_output_skips_an_edge_saved_without_a_handle(self) -> None:
        executor = self._executor("heym")
        edge = {"source": "a", "target": "b", "sourceHandle": None}
        self.assertTrue(executor._source_handle_is_skipped(edge, {"output"}))
        named = {"source": "a", "target": "b", "sourceHandle": "output"}
        self.assertTrue(executor._source_handle_is_skipped(named, {"output"}))
        question = {"source": "a", "target": "b", "sourceHandle": "question"}
        self.assertFalse(executor._source_handle_is_skipped(question, {"output"}))

    def test_skipping_question_leaves_an_unnamed_output_edge_alone(self) -> None:
        executor = self._executor("heym")
        edge = {"source": "a", "target": "b", "sourceHandle": None}
        self.assertFalse(executor._source_handle_is_skipped(edge, {"question"}))

    def test_a_conditions_unnamed_handle_is_not_output(self) -> None:
        executor = self._executor("condition")
        edge = {"source": "a", "target": "b", "sourceHandle": None}
        self.assertFalse(executor._source_handle_is_skipped(edge, {"output"}))


if __name__ == "__main__":
    unittest.main()
