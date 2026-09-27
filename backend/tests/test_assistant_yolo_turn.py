"""One YOLO turn: tool rounds, the edited-workflow guard, cancellation and tracing."""

import asyncio
import json
import unittest
import uuid
from collections.abc import AsyncGenerator
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx

from app.services.assistant_yolo import (
    EDITED_WORKFLOW_MESSAGE,
    MAX_YOLO_TOOL_CALLS_PER_TURN,
    TOOL_BUDGET_MESSAGE,
    YOLO_EXECUTE_WORKFLOW_TOOL,
    YoloToolOutcome,
    stream_until_disconnect,
    stream_yolo_assistant_turn,
)
from app.services.llm_trace import LLMTraceContext
from app.services.openai_client import create_openai_client

OTHER_WORKFLOW_ID = "11111111-1111-1111-1111-111111111111"
EDITED_WORKFLOW_ID = "22222222-2222-2222-2222-222222222222"


class _FakeCompletions:
    """Returns queued responses (or raises queued errors) and copies every request."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _fake_client(responses: list[Any]) -> tuple[Any, _FakeCompletions]:
    completions = _FakeCompletions(responses)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def _answer(content: str | None = None, tool_calls: list[Any] | None = None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def _execute_call(
    call_id: str, workflow_id: str, inputs: dict[str, Any] | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(
            name="execute_workflow",
            arguments=json.dumps({"workflow_id": workflow_id, "inputs": inputs or {}}),
        ),
    )


def _outcome(summary: str = "Status: success", status: str = "success") -> YoloToolOutcome:
    return YoloToolOutcome(
        llm_content=json.dumps({"status": status, "outputs": {"answer": 42}}),
        summary=summary,
        status=status,
    )


async def _events(stream: Any) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    async for chunk in stream:
        if chunk.startswith("data: "):
            collected.append(json.loads(chunk[len("data: ") :]))
    return collected


def _turn(client: Any, runner: Any, cancel_event: Event | None = None, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "client": client,
        "model": "gpt-test",
        "provider": "OpenAI",
        "system_prompt": "SYSTEM",
        "messages": [{"role": "user", "content": "Build it"}],
        "run_workflow": runner,
        "workflow_names": {OTHER_WORKFLOW_ID: "Lookup"},
        "editing_workflow_id": EDITED_WORKFLOW_ID,
        "cancel_event": cancel_event or Event(),
    }
    kwargs.update(overrides)
    return stream_yolo_assistant_turn(**kwargs)


class YoloTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_without_tools_streams_content_then_done(self) -> None:
        client, completions = _fake_client([_answer("Here is the workflow")])
        runner = AsyncMock()

        events = await _events(_turn(client, runner))

        self.assertEqual(
            events,
            [{"type": "content", "text": "Here is the workflow"}, {"type": "done"}],
        )
        self.assertEqual(completions.calls[0]["tools"], [YOLO_EXECUTE_WORKFLOW_TOOL])
        self.assertEqual(
            completions.calls[0]["messages"][0], {"role": "system", "content": "SYSTEM"}
        )
        runner.assert_not_awaited()

    async def test_runs_another_workflow_and_feeds_the_result_back(self) -> None:
        client, completions = _fake_client(
            [
                _answer(tool_calls=[_execute_call("call-1", OTHER_WORKFLOW_ID, {"text": "hi"})]),
                _answer("Done checking"),
            ]
        )
        runner = AsyncMock(return_value=_outcome())

        events = await _events(_turn(client, runner))

        runner.assert_awaited_once_with(OTHER_WORKFLOW_ID, {"text": "hi"})
        self.assertEqual(
            [event["type"] for event in events], ["tool_start", "tool_end", "content", "done"]
        )
        self.assertEqual(events[0]["label"], 'Running workflow "Lookup"...')
        self.assertEqual(events[1]["status"], "success")
        self.assertEqual(events[1]["response_summary"], "Status: success")
        second_request = completions.calls[1]["messages"]
        self.assertEqual(second_request[-2]["tool_calls"][0]["id"], "call-1")
        self.assertEqual(
            second_request[-1],
            {"role": "tool", "tool_call_id": "call-1", "content": _outcome().llm_content},
        )

    async def test_refuses_the_workflow_being_edited(self) -> None:
        client, completions = _fake_client(
            [
                _answer(tool_calls=[_execute_call("call-1", EDITED_WORKFLOW_ID)]),
                _answer("I will test it with a run block"),
            ]
        )
        runner = AsyncMock()

        events = await _events(_turn(client, runner))

        runner.assert_not_awaited()
        self.assertEqual(events[1]["status"], "error")
        self.assertIn(EDITED_WORKFLOW_MESSAGE, completions.calls[1]["messages"][-1]["content"])

    async def test_caps_tool_calls_per_turn(self) -> None:
        rounds = [
            _answer(tool_calls=[_execute_call(f"call-{index}", OTHER_WORKFLOW_ID)])
            for index in range(MAX_YOLO_TOOL_CALLS_PER_TURN + 1)
        ]
        client, completions = _fake_client([*rounds, _answer("Answering now")])
        runner = AsyncMock(return_value=_outcome())

        events = await _events(_turn(client, runner))

        self.assertEqual(runner.await_count, MAX_YOLO_TOOL_CALLS_PER_TURN)
        tool_ends = [event for event in events if event["type"] == "tool_end"]
        self.assertEqual(tool_ends[-1]["status"], "error")
        self.assertIn(TOOL_BUDGET_MESSAGE, completions.calls[-1]["messages"][-1]["content"])
        self.assertEqual(events[-1], {"type": "done"})

    async def test_stops_when_cancelled_during_a_tool_run(self) -> None:
        cancel_event = Event()
        client, completions = _fake_client(
            [_answer(tool_calls=[_execute_call("call-1", OTHER_WORKFLOW_ID)])]
        )

        async def cancel_while_running(
            _workflow_id: str, _inputs: dict[str, Any]
        ) -> YoloToolOutcome:
            cancel_event.set()
            return _outcome("Execution cancelled", "cancelled")

        events = await _events(_turn(client, cancel_while_running, cancel_event))

        self.assertEqual([event["type"] for event in events], ["tool_start", "tool_end"])
        self.assertEqual(events[1]["status"], "cancelled")
        self.assertEqual(len(completions.calls), 1)

    async def test_model_error_becomes_an_error_event(self) -> None:
        client, _ = _fake_client([RuntimeError("model unavailable")])

        events = await _events(_turn(client, AsyncMock()))

        self.assertEqual(events, [{"type": "error", "message": "model unavailable"}])

    async def test_records_one_trace_with_the_tool_calls(self) -> None:
        client, _ = _fake_client(
            [
                _answer(tool_calls=[_execute_call("call-1", OTHER_WORKFLOW_ID)]),
                _answer("Done"),
            ]
        )
        trace_context = LLMTraceContext(
            user_id=uuid.uuid4(), credential_id=uuid.uuid4(), source="assistant"
        )

        with (
            patch("app.services.assistant_yolo.record_llm_trace") as record_trace,
            patch("app.services.assistant_yolo.record_run_history") as record_history,
        ):
            await _events(
                _turn(client, AsyncMock(return_value=_outcome()), trace_context=trace_context)
            )

        record_trace.assert_called_once()
        response = record_trace.call_args.kwargs["response"]
        self.assertEqual(response["text"], "Done")
        self.assertEqual(response["tool_calls"][0]["name"], "execute_workflow")
        self.assertEqual(response["tool_metrics"]["count"], 1)
        history = record_history.call_args.kwargs
        self.assertEqual(history["run_type"], "workflow_assistant")
        self.assertEqual(history["status"], "success")
        self.assertEqual(history["steps"][0]["label"], 'Running workflow "Lookup"...')


class YoloTurnOpenCodeSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_rounds_keep_the_conversation_session_header(self) -> None:
        sessions: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            sessions.append(request.headers["x-opencode-session"])
            message: dict[str, Any] = {"role": "assistant", "content": "done"}
            finish_reason = "stop"
            if len(sessions) == 1:
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "execute_workflow",
                                "arguments": json.dumps(
                                    {"workflow_id": OTHER_WORKFLOW_ID, "inputs": {}}
                                ),
                            },
                        }
                    ],
                }
                finish_reason = "tool_calls"
            return httpx.Response(
                200,
                json={
                    "id": "test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "test",
                    "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )

        http_client = httpx.Client(transport=httpx.MockTransport(respond))
        self.addCleanup(http_client.close)
        client = create_openai_client(
            api_key="test-key",
            base_url="https://opencode.ai/zen/go/v1",
            session_id="conversation-1",
            http_client=http_client,
        )

        events = await _events(_turn(client, AsyncMock(return_value=_outcome())))

        self.assertEqual(events[-1], {"type": "done"})
        self.assertEqual(sessions, ["conversation-1", "conversation-1"])


class StreamUntilDisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_forwards_chunks_until_the_source_ends(self) -> None:
        async def source() -> AsyncGenerator[str, None]:
            yield "data: one\n\n"
            yield "data: two\n\n"

        cancel_event = Event()
        chunks = [
            chunk
            async for chunk in stream_until_disconnect(
                source(),
                is_disconnected=AsyncMock(return_value=False),
                cancel_event=cancel_event,
                heartbeat_seconds=5,
            )
        ]

        self.assertEqual(chunks, ["data: one\n\n", "data: two\n\n"])
        self.assertTrue(cancel_event.is_set())

    async def test_sends_keepalives_while_the_source_is_quiet(self) -> None:
        release = asyncio.Event()

        async def source() -> AsyncGenerator[str, None]:
            await release.wait()
            yield "data: late\n\n"

        stream = stream_until_disconnect(
            source(),
            is_disconnected=AsyncMock(return_value=False),
            cancel_event=Event(),
            heartbeat_seconds=0.01,
        )

        self.assertEqual(await stream.__anext__(), ": ping\n\n")
        release.set()
        remaining = [chunk async for chunk in stream]
        self.assertIn("data: late\n\n", remaining)

    async def test_cancels_the_source_when_the_client_disconnects(self) -> None:
        cancel_event = Event()

        async def source() -> AsyncGenerator[str, None]:
            await asyncio.sleep(3600)
            yield "data: never\n\n"

        chunks = [
            chunk
            async for chunk in stream_until_disconnect(
                source(),
                is_disconnected=AsyncMock(return_value=True),
                cancel_event=cancel_event,
                heartbeat_seconds=0.01,
                poll_seconds=0.01,
            )
        ]

        self.assertTrue(cancel_event.is_set())
        self.assertNotIn("data: never\n\n", chunks)
