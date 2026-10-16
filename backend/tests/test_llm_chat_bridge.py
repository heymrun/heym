"""Chat and the AI assistant on the API OpenCode serves a model on."""

import asyncio
import json
import unittest
import uuid
from collections.abc import Callable
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.api import ai_assistant
from app.db.models import CredentialType
from app.services import llm_chat_bridge
from app.services.assistant_yolo import YoloToolOutcome, stream_yolo_assistant_turn
from app.services.llm_chat_bridge import (
    GEMINI_SKIP_SIGNATURE,
    build_history,
    completion_caller,
    forget_remembered_turns,
    gateway_protocol,
)
from app.services.llm_trace import LLMTraceContext
from app.services.llm_transport import (
    ModelProtocolError,
    ResponsesTransport,
    ResponsesTransportError,
    ToolCall,
    TurnResult,
)
from app.services.llm_transport_gemini import GeminiTransport
from app.services.llm_transport_messages import AnthropicMessagesTransport
from app.services.openai_client import create_openai_client

GATEWAY = "https://opencode.ai/inference/go/v1"
GATEWAY_CONFIG = {"api_key": "test-key", "base_url": "https://opencode.ai/inference/go"}
TOOL = {
    "type": "function",
    "function": {
        "name": "list_workflows",
        "description": "List workflows",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
}
Handler = Callable[[httpx.Request], httpx.Response]


def _gateway_client(handler: Handler, session_id: str = "conversation-1") -> Any:
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return create_openai_client(
        api_key="test-key", base_url=GATEWAY, session_id=session_id, http_client=http_client
    )


def _claude_payload(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": content,
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 11, "output_tokens": 6},
    }


def _gemini_payload(parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 4},
    }


class TestGatewayProtocol(unittest.TestCase):
    def test_only_models_served_off_chat_completions_are_routed(self) -> None:
        client = SimpleNamespace(base_url=GATEWAY)
        self.assertEqual(gateway_protocol(client, "gpt-6-luna"), "responses")
        self.assertEqual(gateway_protocol(client, "grok-4.7"), "responses")
        self.assertEqual(gateway_protocol(client, "claude-haiku-5-5"), "messages")
        self.assertEqual(gateway_protocol(client, "minimax-m2.7"), "messages")
        self.assertEqual(gateway_protocol(client, "gemini-4-argon-contributor"), "google")
        for model in ("glm-5.3-flash", "kimi-k3", "deepseek-v4-pro", "minimax-m3", "qwen3.8-max"):
            self.assertIsNone(gateway_protocol(client, model))

    def test_other_gateways_are_never_switched_by_model_name(self) -> None:
        for base_url in ("https://api.openai.com/v1", "https://openrouter.ai/api/v1", "", None):
            client = SimpleNamespace(base_url=base_url)
            self.assertIsNone(gateway_protocol(client, "claude-haiku-5-5"))

    def test_a_lookalike_host_is_not_the_gateway(self) -> None:
        client = SimpleNamespace(base_url="https://opencode.ai.evil.example/v1")
        self.assertIsNone(gateway_protocol(client, "claude-haiku-5-5"))

    def test_a_mock_client_and_a_client_without_a_base_url_keep_the_old_path(self) -> None:
        self.assertIsNone(gateway_protocol(MagicMock(), "claude-haiku-5-5"))
        self.assertIsNone(gateway_protocol(SimpleNamespace(), "claude-haiku-5-5"))

    def test_models_on_chat_completions_get_the_client_method_itself(self) -> None:
        client = MagicMock()
        client.base_url = GATEWAY
        self.assertIs(completion_caller(client, "glm-5.3-flash"), client.chat.completions.create)
        plain = MagicMock()
        self.assertIs(completion_caller(plain, "claude-haiku-5-5"), plain.chat.completions.create)


class TestBuildHistory(unittest.TestCase):
    def setUp(self) -> None:
        forget_remembered_turns()
        self.addCleanup(forget_remembered_turns)

    @staticmethod
    def _round(call_id: str = "call-1") -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "Show recent runs"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": "list_workflows", "arguments": '{"limit": 5}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": call_id, "content": '{"workflows": []}'},
        ]

    def test_messages_replays_the_remembered_thinking_block(self) -> None:
        thinking = {"type": "thinking", "thinking": "hm", "signature": "sig-1"}
        use = {"type": "tool_use", "id": "call-1", "name": "list_workflows", "input": {"limit": 5}}
        llm_chat_bridge._remember(
            "messages",
            TurnResult(
                text="",
                tool_calls=[ToolCall("call-1", "list_workflows", "{}")],
                raw_items=[thinking, use],
            ),
        )

        history = build_history(AnthropicMessagesTransport(), "messages", self._round())

        self.assertEqual(history.system, "be brief")
        self.assertEqual(
            history.messages,
            [
                {"role": "user", "content": "Show recent runs"},
                {"role": "assistant", "content": [thinking, use]},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-1",
                            "content": '{"workflows": []}',
                        }
                    ],
                },
            ],
        )

    def test_messages_without_a_remembered_turn_rebuilds_the_tool_use(self) -> None:
        history = build_history(AnthropicMessagesTransport(), "messages", self._round("call-9"))

        self.assertEqual(
            history.messages[1],
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-9",
                        "name": "list_workflows",
                        "input": {"limit": 5},
                    }
                ],
            },
        )

    def test_parallel_results_share_one_user_message(self) -> None:
        messages = self._round()
        messages[2]["tool_calls"].append(
            {
                "id": "call-2",
                "type": "function",
                "function": {"name": "list_workflows", "arguments": "{}"},
            }
        )
        messages.append({"role": "tool", "tool_call_id": "call-2", "content": "second"})

        history = build_history(AnthropicMessagesTransport(), "messages", messages)

        self.assertEqual(len(history.messages), 3)
        self.assertEqual(
            [b["tool_use_id"] for b in history.messages[2]["content"]], ["call-1", "call-2"]
        )

    def test_a_remembered_turn_for_other_calls_is_not_replayed(self) -> None:
        llm_chat_bridge._remember(
            "messages",
            TurnResult(
                text="",
                tool_calls=[ToolCall("call-1", "other", "{}"), ToolCall("call-2", "other", "{}")],
                raw_items=[{"type": "text", "text": "stale"}],
            ),
        )

        history = build_history(AnthropicMessagesTransport(), "messages", self._round())

        self.assertEqual(history.messages[1]["content"][0]["type"], "tool_use")

    def test_google_replays_the_thought_signature(self) -> None:
        call = {"id": "call-1", "name": "list_workflows", "args": {"limit": 5}}
        part = {"functionCall": call, "thoughtSignature": "sig-g"}
        llm_chat_bridge._remember(
            "google",
            TurnResult(
                text="", tool_calls=[ToolCall("call-1", "list_workflows", "{}")], raw_items=[part]
            ),
        )

        history = build_history(GeminiTransport(), "google", self._round())

        self.assertEqual(history.system, "be brief")
        self.assertEqual(history.contents[1], {"role": "model", "parts": [part]})
        self.assertEqual(
            history.contents[2]["parts"][0]["functionResponse"],
            {"id": "call-1", "name": "list_workflows", "response": {"workflows": []}},
        )

    def test_google_without_a_remembered_turn_skips_signature_validation(self) -> None:
        history = build_history(GeminiTransport(), "google", self._round())

        part = history.contents[1]["parts"][0]
        self.assertEqual(part["thoughtSignature"], GEMINI_SKIP_SIGNATURE)
        self.assertEqual(part["functionCall"]["name"], "list_workflows")

    def test_responses_replays_reasoning_items_and_pairs_outputs(self) -> None:
        reasoning = {"type": "reasoning", "id": "rs_1", "encrypted_content": "blob", "summary": []}
        call = {
            "type": "function_call",
            "call_id": "call-1",
            "name": "list_workflows",
            "arguments": '{"limit": 5}',
        }
        llm_chat_bridge._remember(
            "responses",
            TurnResult(
                text="",
                tool_calls=[ToolCall("call-1", "list_workflows", "{}")],
                raw_items=[reasoning, call],
            ),
        )

        history = build_history(ResponsesTransport(), "responses", self._round())

        self.assertEqual(
            history.items,
            [
                {"type": "message", "role": "system", "content": "be brief"},
                {"type": "message", "role": "user", "content": "Show recent runs"},
                reasoning,
                call,
                {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": '{"workflows": []}',
                },
            ],
        )

    def test_prior_assistant_text_and_an_image_survive_the_translation(self) -> None:
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                    {"type": "text", "text": "Date: today"},
                ],
            },
        ]

        history = build_history(AnthropicMessagesTransport(), "messages", messages)

        self.assertEqual(history.messages[0], {"role": "user", "content": "hi"})
        self.assertEqual(history.messages[1], {"role": "assistant", "content": "hello"})
        self.assertEqual(
            history.messages[2]["content"],
            [
                {"type": "text", "text": "what is this\n\nDate: today"},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
                },
            ],
        )

    def test_empty_messages_are_left_out(self) -> None:
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": ""},
        ]

        history = build_history(AnthropicMessagesTransport(), "messages", messages)

        self.assertEqual(history.messages, [{"role": "user", "content": "hi"}])


class TestCompletion(unittest.TestCase):
    def setUp(self) -> None:
        forget_remembered_turns()
        self.addCleanup(forget_remembered_turns)

    def test_messages_answer_reads_like_a_chat_completion(self) -> None:
        bodies: list[dict[str, Any]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            self.assertEqual(request.url.path, "/inference/go/v1/messages")
            return httpx.Response(
                200,
                json=_claude_payload(
                    [
                        {"type": "text", "text": "Checking."},
                        {"type": "tool_use", "id": "tu_1", "name": "list_workflows", "input": {}},
                    ]
                ),
            )

        client = _gateway_client(respond)
        response = completion_caller(client, "claude-haiku-5-5")(
            model="claude-haiku-5-5",
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ],
            tools=[TOOL],
            temperature=0.1,
            stream=False,
            extra_body={"disable_reasoning": True},
        )

        message = response.choices[0].message
        self.assertEqual(message.content, "Checking.")
        self.assertEqual(message.tool_calls[0].id, "tu_1")
        self.assertEqual(message.tool_calls[0].function.name, "list_workflows")
        self.assertEqual(message.tool_calls[0].function.arguments, "{}")
        self.assertEqual(response.usage.prompt_tokens, 11)
        self.assertEqual(response.usage.total_tokens, 17)
        body = bodies[0]
        self.assertEqual(body["system"], "sys")
        self.assertNotIn("temperature", body)
        self.assertNotIn("disable_reasoning", body)
        self.assertNotIn("stream", body)
        self.assertEqual(body["tools"][0]["name"], "list_workflows")

    def test_a_plain_answer_has_no_tool_calls(self) -> None:
        client = _gateway_client(
            lambda _request: httpx.Response(
                200, json=_claude_payload([{"type": "text", "text": "done"}])
            )
        )

        response = completion_caller(client, "claude-haiku-5-5")(
            model="claude-haiku-5-5", messages=[{"role": "user", "content": "hi"}]
        )

        self.assertEqual(response.choices[0].message.content, "done")
        self.assertIsNone(response.choices[0].message.tool_calls)

    def test_streaming_callers_get_the_answer_as_one_chunk_then_usage(self) -> None:
        client = _gateway_client(
            lambda _request: httpx.Response(
                200, json=_claude_payload([{"type": "text", "text": "whole answer"}])
            )
        )

        chunks = list(
            completion_caller(client, "claude-haiku-5-5")(
                model="claude-haiku-5-5",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
                stream_options={"include_usage": True},
            )
        )

        self.assertEqual(chunks[0].choices[0].delta.content, "whole answer")
        self.assertIsNone(chunks[0].usage)
        self.assertEqual(chunks[-1].choices, [])
        self.assertEqual(chunks[-1].usage.completion_tokens, 6)

    def test_gemini_answer_reads_like_a_chat_completion(self) -> None:
        paths: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(
                200,
                json=_gemini_payload(
                    [{"functionCall": {"name": "list_workflows", "args": {"limit": 3}}}]
                ),
            )

        response = completion_caller(_gateway_client(respond), "gemini-4-argon-contributor")(
            model="gemini-4-argon-contributor",
            messages=[{"role": "user", "content": "hi"}],
            tools=[TOOL],
        )

        self.assertEqual(
            paths, ["/inference/go/google/v1beta/models/gemini-4-argon-contributor:generateContent"]
        )
        call = response.choices[0].message.tool_calls[0]
        self.assertEqual(call.function.name, "list_workflows")
        self.assertEqual(json.loads(call.function.arguments), {"limit": 3})

    def test_responses_answer_reads_like_a_chat_completion(self) -> None:
        create = MagicMock(
            return_value=SimpleNamespace(
                output=[{"type": "message", "content": [{"type": "output_text", "text": "hello"}]}],
                usage=SimpleNamespace(input_tokens=5, output_tokens=2, total_tokens=7),
                status="completed",
            )
        )
        client = SimpleNamespace(base_url=GATEWAY, responses=SimpleNamespace(create=create))

        response = completion_caller(client, "gpt-6-luna")(
            model="gpt-6-luna",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.1,
        )

        self.assertEqual(response.choices[0].message.content, "hello")
        self.assertEqual(response.usage.total_tokens, 7)
        sent = create.call_args.kwargs
        self.assertEqual(sent["model"], "gpt-6-luna")
        self.assertEqual(sent["input"], [{"type": "message", "role": "user", "content": "hi"}])
        self.assertEqual(sent["temperature"], 0.1)

    def test_a_responses_refusal_tells_chat_users_what_to_do_not_node_users(self) -> None:
        refusal = ValueError("Error code: 400 - ModelProtocolUnsupported")
        create = MagicMock(side_effect=refusal)
        client = SimpleNamespace(base_url=GATEWAY, responses=SimpleNamespace(create=create))

        with self.assertRaises(ModelProtocolError) as raised:
            completion_caller(client, "gpt-6-luna")(
                model="gpt-6-luna", messages=[{"role": "user", "content": "hi"}]
            )

        self.assertIsInstance(raised.exception, ModelProtocolError)
        self.assertIn("gpt-6-luna", str(raised.exception))
        self.assertIn("ModelProtocolUnsupported", str(raised.exception))
        self.assertNotIn("this node", str(raised.exception))
        self.assertIsInstance(raised.exception.__cause__, ResponsesTransportError)

    def test_the_remembered_turn_list_stays_bounded(self) -> None:
        for index in range(llm_chat_bridge._RAW_TURN_LIMIT + 50):
            llm_chat_bridge._remember(
                "messages",
                TurnResult(
                    text="",
                    tool_calls=[ToolCall(f"call-{index}", "x", "{}")],
                    raw_items=[{"type": "text", "text": "x"}],
                ),
            )

        self.assertEqual(len(llm_chat_bridge._raw_turns), llm_chat_bridge._RAW_TURN_LIMIT)
        self.assertNotIn("call-0", llm_chat_bridge._raw_turns)


def _user_context() -> tuple[LLMTraceContext, SimpleNamespace]:
    user_id = uuid.uuid4()
    return (
        LLMTraceContext(user_id=user_id, credential_id=uuid.uuid4(), source="dashboard_chat"),
        SimpleNamespace(id=user_id),
    )


async def _drain_chat(client: Any, model: str, cancel_event: Event | None = None) -> list[dict]:
    trace_context, user = _user_context()
    events: list[dict] = []
    with (
        patch.object(ai_assistant, "record_llm_trace"),
        patch.object(ai_assistant, "record_run_history"),
        patch.object(
            ai_assistant, "get_workflows_for_user_with_inputs", AsyncMock(return_value=[])
        ),
    ):
        async for line in ai_assistant.stream_dashboard_chat(
            client,
            model,
            "system",
            [{"role": "user", "content": "Show recent runs"}],
            AsyncMock(),
            user,
            "Custom",
            "http://localhost",
            trace_context,
            cancel_event,
        ):
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


class TestDashboardChatOnOtherProtocols(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        forget_remembered_turns()
        self.addCleanup(forget_remembered_turns)

    async def test_claude_tool_round_keeps_its_thinking_block_and_session(self) -> None:
        seen: list[tuple[str, str, dict[str, Any]]] = []
        thinking = {"type": "thinking", "thinking": "plan", "signature": "sig-1"}
        use = {"type": "tool_use", "id": "tu_1", "name": "list_workflows", "input": {"limit": 5}}

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(
                (
                    request.url.path,
                    request.headers["x-opencode-session"],
                    json.loads(request.content),
                )
            )
            if len(seen) == 1:
                return httpx.Response(200, json=_claude_payload([thinking, use]))
            return httpx.Response(
                200, json=_claude_payload([{"type": "text", "text": "Here are your runs."}])
            )

        events = await _drain_chat(_gateway_client(respond), "claude-haiku-5-5")

        self.assertEqual([path for path, _, _ in seen], ["/inference/go/v1/messages"] * 2)
        self.assertEqual([session for _, session, _ in seen], ["conversation-1"] * 2)
        second = seen[1][2]
        self.assertEqual(second["messages"][1], {"role": "assistant", "content": [thinking, use]})
        self.assertEqual(second["messages"][2]["content"][0]["tool_use_id"], "tu_1")
        self.assertIn(
            {"type": "content", "text": "Here are your runs."},
            events,
        )
        self.assertEqual(events[-1], {"type": "done"})
        self.assertFalse([e for e in events if e.get("type") == "error"])

    async def test_gemini_tool_round_keeps_its_thought_signature(self) -> None:
        seen: list[dict[str, Any]] = []
        part = {
            "functionCall": {"name": "list_workflows", "args": {"limit": 5}},
            "thoughtSignature": "sig-g",
        }

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            if len(seen) == 1:
                return httpx.Response(200, json=_gemini_payload([part]))
            return httpx.Response(200, json=_gemini_payload([{"text": "Here are your runs."}]))

        events = await _drain_chat(_gateway_client(respond), "gemini-4-argon-contributor")

        model_part = seen[1]["contents"][1]["parts"][0]
        self.assertEqual(model_part["thoughtSignature"], "sig-g")
        response_part = seen[1]["contents"][2]["parts"][0]["functionResponse"]
        self.assertEqual(response_part["name"], "list_workflows")
        self.assertEqual(response_part["id"], model_part["functionCall"]["id"])
        self.assertIn({"type": "content", "text": "Here are your runs."}, events)

    async def test_the_summariser_never_runs_for_these_models(self) -> None:
        compressor = AsyncMock(side_effect=AssertionError("compressed over Chat Completions"))
        client = _gateway_client(
            lambda _request: httpx.Response(
                200, json=_claude_payload([{"type": "text", "text": "ok"}])
            )
        )

        with (
            patch("app.services.context_compressor.maybe_compress_messages", compressor),
            patch("app.services.context_compressor.hard_compress_messages", compressor),
            patch("app.services.context_compressor.get_context_limit", return_value=10),
        ):
            events = await _drain_chat(client, "claude-haiku-5-5")

        compressor.assert_not_called()
        self.assertEqual(events[-1], {"type": "done"})

    async def test_a_provider_error_reaches_the_user_as_an_error_event(self) -> None:
        client = _gateway_client(
            lambda _request: httpx.Response(
                400, json={"error": {"message": "ModelProtocolUnsupported"}}
            )
        )

        events = await _drain_chat(client, "claude-haiku-5-5")

        errors = [e for e in events if e.get("type") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("claude-haiku-5-5", errors[0]["message"])

    async def test_models_on_chat_completions_still_use_the_client_method(self) -> None:
        message = MagicMock(content="plain", tool_calls=None)
        response = MagicMock(
            choices=[MagicMock(message=message)],
            usage=MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )
        client = MagicMock()
        client.base_url = GATEWAY
        client.chat.completions.create.return_value = response

        events = await _drain_chat(client, "glm-5.3-flash")

        client.chat.completions.create.assert_called_once()
        self.assertEqual(client.chat.completions.create.call_args.kwargs["model"], "glm-5.3-flash")
        self.assertEqual(events[-1], {"type": "done"})


class TestChatEntryPoints(unittest.IsolatedAsyncioTestCase):
    """Chat with Heym and the MCP chat model reach the bridge through the shared chat engine."""

    def setUp(self) -> None:
        forget_remembered_turns()
        self.addCleanup(forget_remembered_turns)

    @staticmethod
    def _credential() -> MagicMock:
        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.type = CredentialType.custom
        credential.encrypted_config = "encrypted-config"
        return credential

    def _patch_gateway(self, handler: Handler) -> Any:
        def http_client(**_kwargs: Any) -> httpx.Client:
            client = httpx.Client(transport=httpx.MockTransport(handler))
            self.addCleanup(client.close)
            return client

        return (
            patch("app.api.ai_assistant.decrypt_config", return_value=GATEWAY_CONFIG),
            patch("app.services.openai_client.guard_http_url"),
            patch("app.services.openai_client.build_guarded_http_client", side_effect=http_client),
        )

    def test_the_binding_chat_and_mcp_share_lands_on_the_bridge(self) -> None:
        with (
            patch("app.services.openai_client.guard_http_url"),
            patch(
                "app.services.openai_client.build_guarded_http_client",
                side_effect=lambda **_kwargs: httpx.Client(),
            ),
        ):
            client, _provider, model, _trace = ai_assistant.resolve_model_binding(
                self._credential(), GATEWAY_CONFIG, "claude-haiku-5-5", session_id="conv-42"
            )

        self.assertEqual(model, "claude-haiku-5-5")
        self.assertEqual(gateway_protocol(client, model), "messages")
        self.assertEqual(client.default_headers["x-opencode-session"], "conv-42")
        for chat_only in ("glm-5.3-flash", "kimi-k3"):
            self.assertIsNone(gateway_protocol(client, chat_only))

    async def test_docs_chat_runs_a_claude_model_on_messages(self) -> None:
        seen: list[tuple[str, str, dict[str, Any]]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(
                (
                    request.url.path,
                    request.headers["x-opencode-session"],
                    json.loads(request.content),
                )
            )
            return httpx.Response(
                200, json=_claude_payload([{"type": "text", "text": "It explains the LLM node."}])
            )

        credential = self._credential()
        conversation_id = uuid.uuid4()
        request = ai_assistant.DashboardChatRequest(
            credential_id=credential.id,
            model="claude-haiku-5-5",
            message="What does this page explain?",
            conversation_id=conversation_id,
            conversation_history=[{"role": "assistant", "content": "Earlier answer"}],
            chat_surface="documentation",
            user_rules="The user is reading /docs/nodes/llm-node.",
            client_local_datetime="4/10/2026, 10:15:00 AM",
        )
        http_request = MagicMock()
        http_request.is_disconnected = AsyncMock(return_value=False)
        current_user = MagicMock()
        current_user.id = uuid.uuid4()
        decrypt, guard, build = self._patch_gateway(respond)

        with (
            decrypt,
            guard,
            build,
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=credential),
            ),
            patch(
                "app.api.ai_assistant.get_workflows_for_user_with_inputs",
                AsyncMock(return_value=[]),
            ),
            patch("app.api.ai_assistant._load_agents_md_content", return_value="AGENTS context"),
            patch("app.api.ai_assistant.build_public_base_url", return_value="http://localhost"),
            patch("app.api.ai_assistant.build_credentials_prompt", AsyncMock(return_value="")),
            patch("app.api.ai_assistant.load_credential_catalog", AsyncMock(return_value=[])),
            patch("app.api.ai_assistant.load_data_table_catalog", AsyncMock(return_value=[])),
            patch.object(ai_assistant, "record_llm_trace"),
            patch.object(ai_assistant, "record_run_history"),
        ):
            response = await ai_assistant.dashboard_chat_stream(
                http_request=http_request,
                request=request,
                current_user=current_user,
                db=AsyncMock(),
            )
            chunks = [
                chunk.decode() if isinstance(chunk, bytes) else chunk
                async for chunk in response.body_iterator
            ]

        events = [json.loads(c[len("data: ") :]) for c in chunks if c.startswith("data: ")]
        self.assertEqual(len(seen), 1)
        path, session, body = seen[0]
        self.assertEqual(path, "/inference/go/v1/messages")
        self.assertEqual(session, str(conversation_id))
        self.assertIn("/docs/nodes/llm-node", body["system"])
        self.assertEqual(body["messages"][0], {"role": "assistant", "content": "Earlier answer"})
        self.assertIn({"type": "content", "text": "It explains the LLM node."}, events)
        self.assertFalse([e for e in events if e.get("type") == "error"])


class TestAssistantOnOtherProtocols(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        forget_remembered_turns()
        self.addCleanup(forget_remembered_turns)

    async def test_workflow_assistant_stream_delivers_the_whole_answer(self) -> None:
        bodies: list[dict[str, Any]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(
                200, json=_claude_payload([{"type": "text", "text": "Add a Condition node."}])
            )

        events: list[dict[str, Any]] = []
        with patch.object(ai_assistant, "record_run_history"):
            async for line in ai_assistant.stream_llm_response(
                _gateway_client(respond),
                "claude-haiku-5-5",
                "system",
                [{"role": "user", "content": "how do I branch?"}],
                "Custom",
            ):
                events.append(json.loads(line[len("data: ") :]))

        self.assertEqual(
            events,
            [{"type": "content", "text": "Add a Condition node."}, {"type": "done"}],
        )
        self.assertNotIn("stream", bodies[0])
        self.assertNotIn("stream_options", bodies[0])

    async def test_builder_pass_reads_the_answer_through_the_same_helper(self) -> None:
        client = _gateway_client(
            lambda _request: httpx.Response(
                200, json=_claude_payload([{"type": "text", "text": '{"nodes": []}'}])
            )
        )

        response = await ai_assistant._await_chat_completions(
            client,
            None,
            model="claude-haiku-5-5",
            messages=[{"role": "user", "content": "build it"}],
            stream=False,
        )

        self.assertEqual(response.choices[0].message.content, '{"nodes": []}')

    async def test_a_cancelled_turn_returns_nothing(self) -> None:
        cancelled = Event()
        cancelled.set()
        client = _gateway_client(lambda _request: httpx.Response(500))

        response = await ai_assistant._await_chat_completions(
            client, cancelled, model="claude-haiku-5-5", messages=[]
        )

        self.assertIsNone(response)

    def test_yolo_rounds_use_the_matching_protocol(self) -> None:
        use = {"type": "tool_use", "id": "tu_1", "name": "execute_workflow", "input": {}}
        bodies: list[dict[str, Any]] = []
        sessions: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            sessions.append(request.headers["x-opencode-session"])
            if len(bodies) == 1:
                return httpx.Response(200, json=_claude_payload([use]))
            return httpx.Response(200, json=_claude_payload([{"type": "text", "text": "Ran it."}]))

        async def run() -> list[dict[str, Any]]:
            outcome = YoloToolOutcome(llm_content="{}", summary="ok", status="success")
            events: list[dict[str, Any]] = []
            async for line in stream_yolo_assistant_turn(
                client=_gateway_client(respond),
                model="claude-haiku-5-5",
                provider="Custom",
                system_prompt="system",
                messages=[{"role": "user", "content": "run it"}],
                run_workflow=AsyncMock(return_value=outcome),
                workflow_names={},
                editing_workflow_id=None,
                cancel_event=Event(),
            ):
                events.append(json.loads(line[len("data: ") :]))
            return events

        with (
            patch("app.services.assistant_yolo.record_llm_trace"),
            patch("app.services.assistant_yolo.record_run_history"),
        ):
            events = asyncio.run(run())

        self.assertEqual(len(bodies), 2)
        self.assertEqual(sessions, ["conversation-1"] * 2)
        self.assertEqual(bodies[1]["messages"][1]["content"][0]["id"], "tu_1")
        self.assertIn({"type": "content", "text": "Ran it."}, events)


if __name__ == "__main__":
    unittest.main()
