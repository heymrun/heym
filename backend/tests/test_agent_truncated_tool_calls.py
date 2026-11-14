"""Tool calls from a turn cut at the output token limit, or with unparseable arguments, never run.

A turn that stops at the output token limit can end inside a tool call's arguments. Chat
Completions reports it as ``length``; Anthropic Messages, Gemini and the Responses API report
``max_tokens``, ``MAX_TOKENS`` and ``incomplete``, and their arguments still arrive as valid
JSON. Either way the calls must come back to the model as errors instead of running with
whatever was parsed (or with ``{}``).
"""

from __future__ import annotations

import copy
import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import ai_assistant
from app.db.models import CredentialType
from app.services import chat_round_stream
from app.services.llm_service import HumanReviewPause, LLMService
from app.services.llm_trace import LLMTraceContext
from app.services.llm_transport import ResponsesTransport
from app.services.llm_transport_gemini import GeminiTransport
from app.services.llm_transport_messages import AnthropicMessagesTransport

CUT_ARGUMENTS = '{"customer_id": "C-77", "older_than_d'
TOOLS = [
    {"name": "close_tickets", "parameters": {"type": "object"}},
    {"name": "review", "parameters": {"type": "object"}, "_source": "hitl"},
]


def _call(call_id: str, arguments: str, name: str = "close_tickets") -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _completion(
    *, content: str | None = None, calls: list[SimpleNamespace], finish_reason: str
) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=calls or None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


class ChatCompletionsAgentLoopTests(IsolatedAsyncioTestCase):
    async def _run(
        self,
        responses: list[SimpleNamespace],
        trace_context: LLMTraceContext | None = None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[tuple[Any, ...]], list[dict[str, Any]]]:
        sent: list[dict[str, Any]] = []

        def create(**request: Any) -> SimpleNamespace:
            sent.append(copy.deepcopy(request))
            return responses.pop(0)

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        executed: list[tuple[Any, ...]] = []

        def executor(*args: Any) -> dict[str, Any]:
            executed.append(args)
            return {"closed": args[2]}

        service = LLMService(CredentialType.openai, "test-key", trace_context=trace_context)
        with patch.object(service, "_get_client", return_value=(client, "Test")):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="close tickets for C-77",
                tools=TOOLS,
                tool_executor=executor,
                **kwargs,
            )
        return result, executed, sent

    @staticmethod
    def _tool_messages(request: dict[str, Any]) -> list[dict[str, Any]]:
        return [m for m in request["messages"] if m.get("role") == "tool"]

    async def test_length_cut_turn_does_not_run_its_tool_call(self) -> None:
        result, executed, sent = await self._run(
            [
                _completion(calls=[_call("call-1", CUT_ARGUMENTS)], finish_reason="length"),
                _completion(content="Could not finish.", calls=[], finish_reason="stop"),
            ]
        )

        self.assertEqual(executed, [])
        self.assertEqual(result["text"], "Could not finish.")
        entry = result["tool_calls"][0]
        self.assertEqual(entry["status"], "error")
        self.assertIn("output token limit", entry["result"]["error"])
        tool_messages = self._tool_messages(sent[1])
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["call-1"])
        self.assertIn("output token limit", tool_messages[0]["content"])

    async def test_parallel_cut_turn_fails_every_call_including_the_complete_one(self) -> None:
        result, executed, sent = await self._run(
            [
                _completion(
                    calls=[
                        _call("call-1", '{"customer_id": "C-12"}'),
                        _call("call-2", CUT_ARGUMENTS),
                    ],
                    finish_reason="length",
                ),
                _completion(content="Stopped.", calls=[], finish_reason="stop"),
            ]
        )

        self.assertEqual(executed, [])
        self.assertEqual([e["status"] for e in result["tool_calls"]], ["error", "error"])
        tool_messages = self._tool_messages(sent[1])
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["call-1", "call-2"])
        for message in tool_messages:
            self.assertIn("output token limit", message["content"])

    async def test_cut_turn_is_refused_before_the_hitl_branch(self) -> None:
        result, executed, _sent = await self._run(
            [
                _completion(
                    calls=[_call("call-1", '{"review_markdown": "ok"}', name="review")],
                    finish_reason="length",
                ),
                _completion(content="Stopped.", calls=[], finish_reason="stop"),
            ]
        )

        self.assertEqual(executed, [])
        self.assertNotIn("_hitl_pending", result)
        self.assertEqual(result["tool_calls"][0]["status"], "error")

    async def test_two_cut_turns_in_a_row_stop_with_a_max_tokens_error(self) -> None:
        responses = [
            _completion(calls=[_call("call-1", CUT_ARGUMENTS)], finish_reason="length"),
            _completion(calls=[_call("call-2", CUT_ARGUMENTS)], finish_reason="length"),
            _completion(content="never requested", calls=[], finish_reason="stop"),
        ]
        result, executed, sent = await self._run(responses, max_tokens=64)

        self.assertEqual(executed, [])
        self.assertEqual(len(sent), 2)
        self.assertIn("maxTokens", result["error"])
        self.assertIn("64", result["error"])
        self.assertEqual([e["status"] for e in result["tool_calls"]], ["error", "error"])

    async def test_a_complete_turn_after_a_cut_one_runs_and_resets_the_count(self) -> None:
        result, executed, _sent = await self._run(
            [
                _completion(calls=[_call("call-1", CUT_ARGUMENTS)], finish_reason="length"),
                _completion(
                    calls=[_call("call-2", '{"customer_id": "C-77"}')],
                    finish_reason="tool_calls",
                ),
                _completion(calls=[_call("call-3", CUT_ARGUMENTS)], finish_reason="length"),
                _completion(content="Closed C-77.", calls=[], finish_reason="stop"),
            ]
        )

        self.assertNotIn("error", result)
        self.assertEqual(result["text"], "Closed C-77.")
        self.assertEqual([args[2] for args in executed], [{"customer_id": "C-77"}])

    async def test_malformed_json_without_a_cut_is_returned_to_the_model(self) -> None:
        result, executed, sent = await self._run(
            [
                _completion(
                    calls=[_call("call-1", "{'customer_id': 'C-77'}")],
                    finish_reason="tool_calls",
                ),
                _completion(content="Retrying.", calls=[], finish_reason="stop"),
            ]
        )

        self.assertEqual(executed, [])
        self.assertEqual(result["tool_calls"][0]["status"], "error")
        tool_messages = self._tool_messages(sent[1])
        self.assertIn("not valid JSON", tool_messages[0]["content"])

    async def test_malformed_json_on_a_hitl_call_is_returned_to_the_model(self) -> None:
        result, executed, sent = await self._run(
            [
                _completion(
                    calls=[_call("call-1", "{'review_markdown': 'ok'}", name="review")],
                    finish_reason="tool_calls",
                ),
                _completion(content="Retrying.", calls=[], finish_reason="stop"),
            ]
        )

        self.assertEqual(executed, [])
        self.assertNotIn("_hitl_pending", result)
        tool_messages = self._tool_messages(sent[1])
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["call-1"])
        self.assertIn("not valid JSON", tool_messages[0]["content"])

    async def test_raw_cut_arguments_are_redacted_before_the_trace(self) -> None:
        secret = "sk-live-0123456789abcdef"
        cut = '{"api_key": "' + secret + '", "customer_id": "C-'
        trace_context = LLMTraceContext(
            user_id=uuid.uuid4(), credential_id=uuid.uuid4(), node_label="Agent"
        )
        with patch("app.services.llm_service.record_llm_trace") as record_trace:
            result, executed, _sent = await self._run(
                [
                    _completion(calls=[_call("call-1", cut)], finish_reason="length"),
                    _completion(content="Stopped.", calls=[], finish_reason="stop"),
                ],
                trace_context=trace_context,
            )

        self.assertEqual(executed, [])
        self.assertEqual(
            result["tool_calls"][0]["arguments"], {"unparsed_arguments_chars": len(cut)}
        )
        self.assertNotIn(secret, json.dumps(result["tool_calls"]))
        record_trace.assert_called()
        for call in record_trace.call_args_list:
            self.assertNotIn(secret, json.dumps(call.kwargs.get("response"), default=str))


class PersistedTraces:
    """Trace rows as `record_llm_trace` writes them, after its own sanitizer."""

    def __init__(self) -> None:
        self.rows: list[Any] = []
        session = MagicMock()
        session.add.side_effect = self.rows.append
        factory = MagicMock()
        factory.return_value.__enter__.return_value = session
        self.patcher = patch("app.services.llm_trace.SessionLocal", factory)

    def dump(self) -> str:
        return json.dumps(
            [{"request": row.request, "response": row.response} for row in self.rows],
            default=str,
        )


class RefusedCallRedactionTests(IsolatedAsyncioTestCase):
    """A refused call's arguments keep the key-based redaction that a call that runs gets."""

    _run = ChatCompletionsAgentLoopTests._run

    async def _run_traced(
        self, responses: list[SimpleNamespace]
    ) -> tuple[dict[str, Any], list[tuple[Any, ...]], PersistedTraces]:
        traces = PersistedTraces()
        trace_context = LLMTraceContext(
            user_id=uuid.uuid4(), credential_id=uuid.uuid4(), node_label="Agent"
        )
        with traces.patcher:
            result, executed, _sent = await self._run(responses, trace_context=trace_context)
        self.assertTrue(traces.rows)
        return result, executed, traces

    async def test_complete_call_in_a_cut_turn_keeps_key_based_redaction(self) -> None:
        arguments = json.dumps(
            {"token": "opaque-credential", "service_token": "svc-cred-4711", "customer_id": "C-12"}
        )
        result, executed, traces = await self._run_traced(
            [
                _completion(
                    calls=[_call("call-1", arguments), _call("call-2", CUT_ARGUMENTS)],
                    finish_reason="length",
                ),
                _completion(content="Stopped.", calls=[], finish_reason="stop"),
            ]
        )

        self.assertEqual(executed, [])
        persisted = json.dumps(result["tool_calls"])
        # Still structured, so the reader sees which call it was.
        self.assertEqual(result["tool_calls"][0]["arguments"]["customer_id"], "C-12")
        for value in ("opaque-credential", "svc-cred-4711"):
            self.assertNotIn(value, persisted)
            self.assertNotIn(value, traces.dump())

    async def test_unparseable_cut_arguments_never_reach_the_record(self) -> None:
        # Text-mode redaction has no pattern for `token` or `service_token`, so the raw
        # string of a cut call must not be stored at all.
        cut = '{"token": "opaque-credential", "service_token": "svc-cred-4711", "customer_id": "C-'
        result, executed, traces = await self._run_traced(
            [
                _completion(calls=[_call("call-1", cut)], finish_reason="length"),
                _completion(content="Stopped.", calls=[], finish_reason="stop"),
            ]
        )

        self.assertEqual(executed, [])
        persisted = json.dumps(result["tool_calls"])
        response_traces = json.dumps([row.response for row in traces.rows], default=str)
        for value in ("opaque-credential", "svc-cred-4711"):
            self.assertNotIn(value, persisted)
            self.assertNotIn(value, response_traces)


PYTHON_TOOLS = [
    {"name": "run_python", "parameters": {"type": "object"}, "_source": "python"},
    {"name": "review", "parameters": {"type": "object"}, "_source": "hitl"},
]


class MalformedReviewCallTests(IsolatedAsyncioTestCase):
    """A review request that does not parse approves nothing, so its siblings must wait."""

    async def _run(
        self, responses: list[SimpleNamespace], review_result: Any
    ) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
        sent: list[dict[str, Any]] = []

        def create(**request: Any) -> SimpleNamespace:
            sent.append(copy.deepcopy(request))
            return responses.pop(0)

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        executed: list[str] = []

        def executor(tool_def: dict[str, Any], name: str, args: dict[str, Any], _t: float) -> Any:
            executed.append(name)
            if name == "review":
                return review_result(args)
            return {"ran": args}

        service = LLMService(CredentialType.openai, "test-key")
        with patch.object(service, "_get_client", return_value=(client, "Test")):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="delete customer 77",
                tools=PYTHON_TOOLS,
                tool_executor=executor,
            )
        return result, executed, sent

    async def test_malformed_review_call_defers_its_sibling_until_review_is_fixed(self) -> None:
        result, executed, sent = await self._run(
            [
                _completion(
                    calls=[
                        _call("call-1", "{'review_markdown': 'delete C-77'}", name="review"),
                        _call("call-2", '{"code": "delete_customer(77)"}', name="run_python"),
                    ],
                    finish_reason="tool_calls",
                ),
                _completion(
                    calls=[_call("call-3", '{"review_markdown": "delete C-77"}', name="review")],
                    finish_reason="tool_calls",
                ),
            ],
            lambda args: HumanReviewPause(review_markdown=args["review_markdown"]),
        )

        self.assertNotIn("run_python", executed)
        # The repaired review request pauses the run; nothing got past approval.
        self.assertIn("_hitl_pending", result)
        self.assertEqual(executed, ["review"])
        tool_messages = [m for m in sent[1]["messages"] if m.get("role") == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["call-1", "call-2"])
        self.assertIn("not valid JSON", tool_messages[0]["content"])
        self.assertIn("nothing has been approved", tool_messages[1]["content"])
        statuses = {
            e["tool_call_id"]: e["status"]
            for e in result["_hitl_pending"]["agent_state"]["tool_calls"]
        }
        self.assertEqual(statuses["call-1"], "error")
        self.assertEqual(statuses["call-2"], "error")

    async def test_review_not_required_still_lets_its_sibling_run(self) -> None:
        not_required = {"status": "not_required", "message": "Continue without pausing."}
        result, executed, sent = await self._run(
            [
                _completion(
                    calls=[
                        _call("call-1", '{"review_markdown": "delete C-77"}', name="review"),
                        _call("call-2", '{"code": "delete_customer(77)"}', name="run_python"),
                    ],
                    finish_reason="tool_calls",
                ),
                _completion(content="Deleted.", calls=[], finish_reason="stop"),
            ],
            lambda _args: not_required,
        )

        self.assertEqual(executed, ["review", "run_python"])
        self.assertEqual(result["text"], "Deleted.")
        tool_messages = [m for m in sent[1]["messages"] if m.get("role") == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["call-1", "call-2"])
        self.assertEqual(json.loads(tool_messages[0]["content"]), not_required)


def _scripted(transport_cls: type, payloads: list[Any]) -> Any:
    """A real transport whose provider answers come from `payloads`, parsed by its own to_turn."""

    class Scripted(transport_cls):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__()
            self.sent: list[list[dict[str, Any]]] = []

        def create(self, *, client: Any, model: str, history: Any, tools: Any, opts: Any) -> Any:
            self.sent.append(copy.deepcopy(self.dump(history)))
            return self.to_turn(payloads.pop(0))

    return Scripted()


class OtherTransportStopReasonTests(IsolatedAsyncioTestCase):
    """Arguments on these APIs are always valid JSON; only the stop reason tells the cut."""

    async def _run(self, transport: Any) -> tuple[dict[str, Any], list[Any]]:
        executed: list[Any] = []

        def executor(*args: Any) -> dict[str, Any]:
            executed.append(args)
            return {"closed": args[2]}

        service = LLMService(CredentialType.openai, "test-key")
        with (
            patch.object(service, "_get_client", return_value=(SimpleNamespace(), "Test")),
            patch.object(service, "_get_transport", return_value=transport),
        ):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="close tickets for C-77",
                tools=TOOLS,
                tool_executor=executor,
            )
        return result, executed

    def _assert_refused(self, result: dict[str, Any], executed: list[Any], transport: Any) -> None:
        self.assertEqual(executed, [])
        self.assertEqual(result["text"], "done")
        self.assertEqual(result["tool_calls"][0]["status"], "error")
        self.assertIn("output token limit", json.dumps(transport.sent[1]))

    async def test_anthropic_messages_max_tokens(self) -> None:
        transport = _scripted(
            AnthropicMessagesTransport,
            [
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call-1",
                            "name": "close_tickets",
                            "input": {"customer_id": "C-77"},
                        }
                    ],
                    "stop_reason": "max_tokens",
                },
                {"content": [{"type": "text", "text": "done"}], "stop_reason": "end_turn"},
            ],
        )
        result, executed = await self._run(transport)
        self._assert_refused(result, executed, transport)

    async def test_gemini_max_tokens(self) -> None:
        transport = _scripted(
            GeminiTransport,
            [
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "functionCall": {
                                            "id": "call-1",
                                            "name": "close_tickets",
                                            "args": {"customer_id": "C-77"},
                                        }
                                    }
                                ]
                            },
                            "finishReason": "MAX_TOKENS",
                        }
                    ]
                },
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "done"}]}, "finishReason": "STOP"}
                    ]
                },
            ],
        )
        result, executed = await self._run(transport)
        self._assert_refused(result, executed, transport)

    async def test_responses_api_incomplete(self) -> None:
        transport = _scripted(
            ResponsesTransport,
            [
                SimpleNamespace(
                    output=[
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "close_tickets",
                            "arguments": '{"customer_id": "C-77"}',
                        }
                    ],
                    status="incomplete",
                    usage=None,
                ),
                SimpleNamespace(
                    output=[
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "done"}],
                        }
                    ],
                    status="completed",
                    usage=None,
                ),
            ],
        )
        result, executed = await self._run(transport)
        self._assert_refused(result, executed, transport)


def _chunk(
    text: str | None = None,
    calls: list[dict[str, Any]] | None = None,
    finish_reason: str | None = None,
) -> SimpleNamespace:
    tool_calls = [
        SimpleNamespace(
            index=call.get("index", 0),
            id=call.get("id"),
            function=SimpleNamespace(name=call.get("name"), arguments=call.get("arguments")),
        )
        for call in calls or []
    ]
    delta = SimpleNamespace(content=text, tool_calls=tool_calls or None)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)], usage=None
    )


def _tool_round(
    arguments: list[str], finish_reason: str, first_id: int = 1
) -> list[SimpleNamespace]:
    chunks = [
        _chunk(
            calls=[
                {
                    "index": index,
                    "id": f"call-{first_id + index}",
                    "name": "list_workflows",
                    "arguments": args,
                }
            ]
        )
        for index, args in enumerate(arguments)
    ]
    return [*chunks, _chunk(finish_reason=finish_reason)]


class DashboardChatLoopTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch.multiple(
            chat_round_stream, DRAFT_FLUSH_SECONDS=0, PROGRESS_REFRESH_SECONDS=0
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _run(self, rounds: list[list[SimpleNamespace]]) -> dict[str, Any]:
        client = MagicMock()
        client.base_url = "https://llm.example/v1"
        client.chat.completions.create.side_effect = [iter(chunks) for chunks in rounds]
        list_workflows = AsyncMock(return_value=[])
        events: list[dict[str, Any]] = []
        user_id = uuid.uuid4()
        trace_context = LLMTraceContext(
            user_id=user_id,
            credential_id=uuid.uuid4(),
            node_label="Dashboard Chat",
            source="dashboard_chat",
            session_id="conv-1",
        )
        with (
            patch.object(ai_assistant, "record_llm_trace") as record_trace,
            patch.object(ai_assistant, "record_run_history"),
            patch.object(ai_assistant, "get_workflows_for_user_with_inputs", list_workflows),
        ):
            async for chunk in ai_assistant.stream_dashboard_chat(
                client,
                "gpt-5.5",
                "system",
                [{"role": "user", "content": "List my workflows"}],
                AsyncMock(),
                SimpleNamespace(id=user_id),
                "OpenAI",
                "http://localhost",
                trace_context,
                None,
            ):
                if chunk.startswith("data: "):
                    events.append(json.loads(chunk[6:]))
        requests = [c.kwargs for c in client.chat.completions.create.call_args_list]
        return {
            "events": events,
            "list_workflows": list_workflows,
            "requests": requests,
            "trace": record_trace.call_args.kwargs,
        }

    @staticmethod
    def _tool_messages(request: dict[str, Any]) -> list[dict[str, Any]]:
        return [m for m in request["messages"] if m.get("role") == "tool"]

    async def test_length_cut_round_does_not_run_its_tool_call(self) -> None:
        run = await self._run([_tool_round(['{"limit": '], "length"), [_chunk("Sorry, cut off.")]])

        run["list_workflows"].assert_not_awaited()
        tool_messages = self._tool_messages(run["requests"][1])
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["call-1"])
        self.assertIn("output token limit", tool_messages[0]["content"])
        self.assertEqual(run["trace"]["response"]["tool_calls"][0]["status"], "error")
        self.assertEqual(run["events"][-1], {"type": "done"})

    async def test_parallel_cut_round_fails_every_call_including_the_complete_one(self) -> None:
        run = await self._run(
            [_tool_round(['{"limit": 5}', '{"limit": '], "length"), [_chunk("Stopped.")]]
        )

        run["list_workflows"].assert_not_awaited()
        tool_messages = self._tool_messages(run["requests"][1])
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["call-1", "call-2"])
        for message in tool_messages:
            self.assertIn("output token limit", message["content"])

    async def test_two_cut_rounds_in_a_row_stop_with_an_error(self) -> None:
        run = await self._run(
            [
                _tool_round(['{"limit": '], "length"),
                _tool_round(['{"limit": '], "length", first_id=2),
                [_chunk("never requested")],
            ]
        )

        run["list_workflows"].assert_not_awaited()
        self.assertEqual(len(run["requests"]), 2)
        self.assertEqual(run["events"][-1]["type"], "error")
        self.assertIn("output token limit", run["events"][-1]["message"])
        self.assertIn("output token limit", run["trace"]["error"])

    async def test_malformed_json_without_a_cut_is_returned_to_the_model(self) -> None:
        run = await self._run([_tool_round(["{'limit': 5}"], "tool_calls"), [_chunk("Retrying.")]])

        run["list_workflows"].assert_not_awaited()
        tool_messages = self._tool_messages(run["requests"][1])
        self.assertIn("not valid JSON", tool_messages[0]["content"])
        self.assertEqual(run["trace"]["response"]["tool_calls"][0]["status"], "error")

    async def test_complete_round_still_runs(self) -> None:
        run = await self._run([_tool_round(['{"limit": 5}'], "tool_calls"), [_chunk("Done.")]])

        run["list_workflows"].assert_awaited_once()
        self.assertEqual(run["events"][-1], {"type": "done"})
