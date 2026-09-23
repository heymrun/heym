import asyncio
import uuid
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import ai_assistant
from app.services.llm_trace import LLMTraceContext


def _usage(prompt: int, completion: int) -> MagicMock:
    return MagicMock(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )


def _tool_response(call_id: str = "call-1", prompt: int = 100, completion: int = 10) -> MagicMock:
    tool_call = MagicMock()
    tool_call.id = call_id
    tool_call.function.name = "list_workflows"
    tool_call.function.arguments = '{"limit": 5}'
    message = MagicMock(content=None, tool_calls=[tool_call])
    return MagicMock(choices=[MagicMock(message=message)], usage=_usage(prompt, completion))


def _final_response(text: str = "Here are your runs.") -> MagicMock:
    message = MagicMock(content=text, tool_calls=None)
    return MagicMock(choices=[MagicMock(message=message)], usage=_usage(200, 20))


def _trace_context(model_routing: dict[str, Any] | None = None) -> LLMTraceContext:
    return LLMTraceContext(
        user_id=uuid.uuid4(),
        credential_id=uuid.uuid4(),
        node_label="Dashboard Chat",
        source="dashboard_chat",
        model_routing=model_routing,
    )


class DashboardChatTurnTraceTests(IsolatedAsyncioTestCase):
    """One chat turn is one trace, laid out like an agent run."""

    async def _run(
        self,
        responses: list[Any],
        trace_context: LLMTraceContext,
        cancel_event: Event | None = None,
    ) -> MagicMock:
        client = MagicMock()
        client.chat.completions.create.side_effect = responses
        with (
            patch.object(ai_assistant, "record_llm_trace") as record_trace,
            patch.object(ai_assistant, "record_run_history"),
            patch.object(
                ai_assistant, "get_workflows_for_user_with_inputs", AsyncMock(return_value=[])
            ),
        ):
            try:
                async for _ in ai_assistant.stream_dashboard_chat(
                    client,
                    "qwen3.8-flash",
                    "system",
                    [{"role": "user", "content": "Show recent runs"}],
                    AsyncMock(),
                    SimpleNamespace(id=trace_context.user_id),
                    "OpenAI",
                    "http://localhost",
                    trace_context,
                    cancel_event,
                ):
                    pass
            except asyncio.CancelledError:
                pass
        return record_trace

    async def test_tool_round_and_answer_record_one_trace(self) -> None:
        record_trace = await self._run([_tool_response(), _final_response()], _trace_context())

        record_trace.assert_called_once()
        kwargs = record_trace.call_args.kwargs
        response = kwargs["response"]
        self.assertEqual(response["text"], "Here are your runs.")
        self.assertIsNone(kwargs["error"])
        # Tokens of every model call in the turn, so cost stays what it was per round.
        self.assertEqual(kwargs["prompt_tokens"], 300)
        self.assertEqual(kwargs["completion_tokens"], 30)
        self.assertEqual(kwargs["total_tokens"], 330)
        self.assertEqual(response["usage"]["total_tokens"], 330)

    async def test_request_holds_the_tool_call_and_its_result(self) -> None:
        record_trace = await self._run([_tool_response(), _final_response()], _trace_context())

        messages = record_trace.call_args.kwargs["request"]["messages"]
        roles = [message["role"] for message in messages]
        self.assertEqual(roles, ["system", "user", "assistant", "tool"])
        self.assertEqual(messages[2]["tool_calls"][0]["id"], "call-1")
        self.assertEqual(messages[3]["tool_call_id"], "call-1")

    async def test_each_model_call_is_a_turn_in_order(self) -> None:
        record_trace = await self._run([_tool_response(), _final_response()], _trace_context())

        turns = record_trace.call_args.kwargs["response"]["turn_timings"]
        self.assertEqual([turn["turn"] for turn in turns], [1, 2])
        self.assertEqual([turn["toolCalls"] for turn in turns], [1, 0])
        self.assertEqual(turns[0]["model"], "qwen3.8-flash")
        self.assertEqual(turns[0]["totalTokens"], 110)
        self.assertEqual(turns[1]["textChars"], len("Here are your runs."))
        self.assertLessEqual(turns[0]["startMs"], turns[1]["startMs"])

    async def test_tool_sits_between_the_calls_on_the_timeline(self) -> None:
        record_trace = await self._run([_tool_response(), _final_response()], _trace_context())

        response = record_trace.call_args.kwargs["response"]
        turns = response["turn_timings"]
        tool = response["tool_calls"][0]
        self.assertEqual(tool["tool_call_id"], "call-1")
        self.assertEqual(tool["name"], "list_workflows")
        self.assertEqual(tool["arguments"], {"limit": 5})
        self.assertEqual(tool["status"], "success")
        self.assertIsInstance(tool["elapsed_ms"], float)
        self.assertGreaterEqual(tool["start_ms"], turns[0]["startMs"])
        self.assertLessEqual(tool["start_ms"], turns[1]["startMs"])
        self.assertEqual(response["tool_metrics"]["count"], 1)

    async def test_routing_time_comes_first_on_the_timeline(self) -> None:
        routing = {
            "routerLabel": "model-router",
            "routerCredentialId": str(uuid.uuid4()),
            "decisionModel": "jev-latest",
            "decisionTotalMs": 402.64,
            "calls": [{"turn": 1, "model": "qwen3.8-flash", "decisionMs": 402.64}],
        }
        record_trace = await self._run(
            [_tool_response(), _final_response()], _trace_context(routing)
        )

        turns = record_trace.call_args.kwargs["response"]["turn_timings"]
        self.assertGreaterEqual(turns[0]["startMs"], 402.64)

    async def test_failed_first_call_is_one_error_trace_with_its_turn(self) -> None:
        record_trace = await self._run([RuntimeError("model failed")], _trace_context())

        record_trace.assert_called_once()
        kwargs = record_trace.call_args.kwargs
        self.assertEqual(kwargs["error"], "model failed")
        turns = kwargs["response"]["turn_timings"]
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["error"], "model failed")

    async def test_stop_after_a_tool_keeps_the_finished_call(self) -> None:
        cancel_event = Event()

        async def list_and_stop(*_args: Any, **_kwargs: Any) -> list[Any]:
            cancel_event.set()
            return []

        client = MagicMock()
        client.chat.completions.create.side_effect = [_tool_response(), _final_response()]
        trace_context = _trace_context()
        with (
            patch.object(ai_assistant, "record_llm_trace") as record_trace,
            patch.object(ai_assistant, "record_run_history"),
            patch.object(ai_assistant, "get_workflows_for_user_with_inputs", list_and_stop),
        ):
            async for _ in ai_assistant.stream_dashboard_chat(
                client,
                "qwen3.8-flash",
                "system",
                [{"role": "user", "content": "Show recent runs"}],
                AsyncMock(),
                SimpleNamespace(id=trace_context.user_id),
                "OpenAI",
                "http://localhost",
                trace_context,
                cancel_event,
            ):
                pass

        record_trace.assert_called_once()
        kwargs = record_trace.call_args.kwargs
        self.assertIsNone(kwargs["error"])
        self.assertTrue(kwargs["response"]["cancelled"])
        self.assertEqual(kwargs["total_tokens"], 110)

    async def test_task_cancelled_mid_call_still_records_finished_calls(self) -> None:
        record_trace = await self._run(
            [_tool_response(), asyncio.CancelledError()], _trace_context()
        )

        record_trace.assert_called_once()
        kwargs = record_trace.call_args.kwargs
        self.assertTrue(kwargs["response"]["cancelled"])
        self.assertEqual(len(kwargs["response"]["turn_timings"]), 1)
        self.assertEqual(kwargs["total_tokens"], 110)

    async def test_cancel_before_any_call_records_nothing(self) -> None:
        cancel_event = Event()
        cancel_event.set()

        record_trace = await self._run([_final_response()], _trace_context(), cancel_event)

        record_trace.assert_not_called()
