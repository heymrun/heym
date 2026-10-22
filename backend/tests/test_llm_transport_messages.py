"""Anthropic Messages transport: the endpoint OpenCode serves Claude Haiku and MiniMax M2.7 on."""

import json
import unittest
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from app.models.schemas import CredentialType
from app.services.llm_service import LLMService
from app.services.llm_trace import LLMTraceContext
from app.services.llm_transport import (
    ModelProtocolError,
    RequestOpts,
    ToolResult,
    TurnResult,
)
from app.services.llm_transport_messages import (
    DEFAULT_MAX_TOKENS,
    AnthropicMessagesTransport,
    MessagesHistory,
)

TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Weather for a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
    },
}


def _payload(content: list[dict[str, Any]], **usage: int) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": content,
        "stop_reason": "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn",
        "usage": {"input_tokens": 11, "output_tokens": 6, **usage},
    }


def _client(payload: dict[str, Any]) -> MagicMock:
    client = MagicMock()
    client.post.return_value.json.return_value = payload
    return client


class TestStart(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = AnthropicMessagesTransport()

    def test_system_prompt_is_kept_out_of_the_message_list(self) -> None:
        history = self.transport.start(
            system_instruction="be brief",
            conversation_history=[{"role": "assistant", "content": "earlier"}],
            user_message="now",
            image_input=None,
        )
        self.assertEqual(history.system, "be brief")
        self.assertEqual(
            history.messages,
            [
                {"role": "assistant", "content": "earlier"},
                {"role": "user", "content": "now"},
            ],
        )

    def test_remote_image_becomes_a_url_source(self) -> None:
        history = self.transport.start(
            system_instruction=None,
            conversation_history=None,
            user_message="what is this",
            image_input="https://example.com/a.png",
        )
        self.assertEqual(
            history.messages[-1]["content"],
            [
                {"type": "text", "text": "what is this"},
                {"type": "image", "source": {"type": "url", "url": "https://example.com/a.png"}},
            ],
        )

    def test_data_uri_image_becomes_a_base64_source(self) -> None:
        history = self.transport.start(
            system_instruction=None,
            conversation_history=None,
            user_message="what is this",
            image_input="data:image/png;base64,AAAA",
        )
        self.assertEqual(
            history.messages[-1]["content"][1],
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
            },
        )


class TestBuildKwargs(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = AnthropicMessagesTransport()
        self.history = self.transport.start(
            system_instruction="sys", conversation_history=None, user_message="hi", image_input=None
        )

    def _build(
        self, tools: Any = None, model: str = "claude-haiku-5-5", **opts: Any
    ) -> dict[str, Any]:
        return self.transport.build_kwargs(
            model=model, history=self.history, tools=tools, opts=RequestOpts(**opts)
        )

    def test_max_tokens_is_always_sent_because_the_api_requires_it(self) -> None:
        self.assertEqual(self._build()["max_tokens"], DEFAULT_MAX_TOKENS)
        self.assertEqual(self._build(max_tokens=77)["max_tokens"], 77)

    def test_tools_use_input_schema(self) -> None:
        kwargs = self._build(tools=[TOOL])
        self.assertEqual(
            kwargs["tools"],
            [
                {
                    "name": "get_weather",
                    "description": "Weather for a city",
                    "input_schema": TOOL["function"]["parameters"],
                }
            ],
        )
        self.assertEqual(kwargs["tool_choice"], {"type": "auto"})

    def test_tool_choice_vocabulary_is_translated(self) -> None:
        self.assertEqual(self._build([TOOL], tool_choice="none")["tool_choice"], {"type": "none"})
        self.assertEqual(
            self._build([TOOL], tool_choice="required")["tool_choice"], {"type": "any"}
        )

    def test_no_tools_means_no_tool_keys(self) -> None:
        kwargs = self._build()
        self.assertNotIn("tools", kwargs)
        self.assertNotIn("tool_choice", kwargs)

    def test_temperature_is_clamped_to_the_range_anthropic_accepts(self) -> None:
        self.assertEqual(self._build(model="minimax-m2.7", temperature=1.6)["temperature"], 1.0)
        self.assertEqual(self._build(model="minimax-m2.7", temperature=0.2)["temperature"], 0.2)
        self.assertNotIn("temperature", self._build(model="minimax-m2.7"))

    def test_claude_models_never_get_a_temperature(self) -> None:
        """Claude 5 answers 400 "temperature is deprecated" for anything but the default."""
        self.assertNotIn("temperature", self._build(temperature=0.7))
        self.assertNotIn("temperature", self._build(model="claude-opus-5-5", temperature=0.0))

    def test_reasoning_effort_is_not_forwarded(self) -> None:
        self.assertNotIn("reasoning_effort", self._build(reasoning_effort="high"))
        self.assertNotIn("reasoning", self._build(reasoning_effort="high"))

    def test_json_modes_become_a_system_instruction(self) -> None:
        schema = {"type": "json_schema", "json_schema": {"name": "x", "schema": {"type": "object"}}}
        self.assertIn("JSON", self._build(response_format={"type": "json_object"})["system"])
        with_schema = self._build(response_format=schema)["system"]
        self.assertTrue(with_schema.startswith("sys"))
        self.assertIn('"type": "object"', with_schema)
        self.assertNotIn("response_format", self._build(response_format=schema))

    def test_json_instruction_forbids_fences_and_echoing_the_schema(self) -> None:
        schema = {"type": "json_schema", "json_schema": {"name": "x", "schema": {"type": "object"}}}
        for response_format in ({"type": "json_object"}, schema):
            system = self._build(response_format=response_format)["system"]
            self.assertIn("code fences", system)
        self.assertIn("never the schema", self._build(response_format=schema)["system"])

    def test_extra_body_is_merged_into_the_request(self) -> None:
        self.assertEqual(self._build(extra_body={"top_k": 5})["top_k"], 5)

    def test_history_is_not_mutated(self) -> None:
        self._build(response_format={"type": "json_object"})
        self.assertEqual(self.history.system, "sys")


class TestCreate(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = AnthropicMessagesTransport()
        self.history = self.transport.start(
            system_instruction=None, conversation_history=None, user_message="hi", image_input=None
        )

    def _create(self, client: Any, tools: Any = None) -> TurnResult:
        return self.transport.create(
            client=client,
            model="claude-haiku-5-5",
            history=self.history,
            tools=tools,
            opts=RequestOpts(),
        )

    def test_posts_to_messages_with_the_version_header(self) -> None:
        client = _client(_payload([{"type": "text", "text": "Pong!"}]))
        self._create(client)
        args, kwargs = client.post.call_args
        self.assertEqual(args[0], "/messages")
        self.assertEqual(kwargs["options"]["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(kwargs["body"]["model"], "claude-haiku-5-5")

    def test_text_and_usage_are_parsed(self) -> None:
        client = _client(
            _payload(
                [{"type": "text", "text": "Pong!"}],
                cache_read_input_tokens=4,
                cache_creation_input_tokens=2,
            )
        )
        turn = self._create(client)
        self.assertEqual(turn.text, "Pong!")
        self.assertEqual(turn.tool_calls, [])
        self.assertEqual(turn.prompt_tokens, 17)
        self.assertEqual(turn.completion_tokens, 6)
        self.assertEqual(turn.total_tokens, 23)
        self.assertEqual(turn.finish_reason, "end_turn")

    def test_tool_use_becomes_a_tool_call_with_json_arguments(self) -> None:
        client = _client(
            _payload(
                [
                    {"type": "text", "text": "Checking."},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "get_weather",
                        "input": {"city": "Berlin"},
                    },
                ]
            )
        )
        turn = self._create(client, tools=[TOOL])
        self.assertEqual(turn.text, "Checking.")
        self.assertEqual(len(turn.tool_calls), 1)
        call = turn.tool_calls[0]
        self.assertEqual((call.id, call.name), ("tu_1", "get_weather"))
        self.assertEqual(call.arguments, '{"city": "Berlin"}')

    def test_json_mode_strips_a_single_wrapping_code_fence(self) -> None:
        fenced = '```json\n{"a": 1}\n```'
        client = _client(_payload([{"type": "text", "text": fenced}]))
        turn = self.transport.create(
            client=client,
            model="claude-haiku-5-5",
            history=self.history,
            tools=None,
            opts=RequestOpts(response_format={"type": "json_object"}),
        )
        self.assertEqual(turn.text, '{"a": 1}')

    def test_ambiguous_two_block_answers_are_left_for_the_parser_to_reject(self) -> None:
        two_blocks = '```json\n{"type": "object"}\n```\n\n```json\n{"a": 1}\n```'
        client = _client(_payload([{"type": "text", "text": two_blocks}]))
        turn = self.transport.create(
            client=client,
            model="claude-haiku-5-5",
            history=self.history,
            tools=None,
            opts=RequestOpts(response_format={"type": "json_object"}),
        )
        self.assertEqual(turn.text, two_blocks)

    def test_fences_are_left_alone_outside_json_mode(self) -> None:
        fenced = "```python\nprint(1)\n```"
        client = _client(_payload([{"type": "text", "text": fenced}]))
        self.assertEqual(self._create(client).text, fenced)

    def test_protocol_unsupported_names_the_way_out(self) -> None:
        error = Exception('Error code: 400 - {"error":{"type":"ModelProtocolUnsupported"}}')
        error.status_code = 400
        client = MagicMock()
        client.post.side_effect = error
        with self.assertRaises(ModelProtocolError) as ctx:
            self._create(client)
        self.assertIn("Messages", str(ctx.exception))

    def test_other_errors_pass_through_untouched(self) -> None:
        error = Exception("rate limited")
        error.status_code = 429
        client = MagicMock()
        client.post.side_effect = error
        with self.assertRaises(Exception) as ctx:
            self._create(client)
        self.assertIs(ctx.exception, error)


class TestHistory(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = AnthropicMessagesTransport()
        self.history = self.transport.start(
            system_instruction="sys", conversation_history=None, user_message="hi", image_input=None
        )
        self.blocks = [
            {"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "tu_1", "name": "a", "input": {}},
            {"type": "tool_use", "id": "tu_2", "name": "b", "input": {}},
        ]

    def test_assistant_turn_is_replayed_verbatim(self) -> None:
        self.transport.append_turn(
            self.history, TurnResult(text="", tool_calls=[], raw_items=self.blocks)
        )
        self.assertEqual(self.history.messages[-1], {"role": "assistant", "content": self.blocks})

    def test_tool_results_for_one_turn_share_one_user_message(self) -> None:
        self.transport.append_turn(
            self.history, TurnResult(text="", tool_calls=[], raw_items=self.blocks)
        )
        self.transport.append_tool_results(self.history, [ToolResult(call_id="tu_1", output="one")])
        self.transport.append_tool_results(self.history, [ToolResult(call_id="tu_2", output="two")])
        last = self.history.messages[-1]
        self.assertEqual(last["role"], "user")
        self.assertEqual(
            last["content"],
            [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "one"},
                {"type": "tool_result", "tool_use_id": "tu_2", "content": "two"},
            ],
        )
        self.assertEqual(len(self.history.messages), 3)
        self.assertTrue(self.transport.last_item_is_tool_result(self.history))

    def test_a_plain_user_message_is_not_a_tool_result(self) -> None:
        self.assertFalse(self.transport.last_item_is_tool_result(self.history))
        self.transport.append_user(self.history, "again")
        self.assertEqual(self.history.messages[-1], {"role": "user", "content": "again"})

    def test_dump_and_load_round_trip_with_a_refreshed_system_prompt(self) -> None:
        dumped = self.transport.dump(self.history)
        loaded = self.transport.load(dumped, "new system")
        self.assertEqual(loaded.system, "new system")
        self.assertEqual(loaded.messages, self.history.messages)
        self.assertIsNot(loaded.messages, self.history.messages)

    def test_trace_request_carries_system_messages_and_tools(self) -> None:
        trace = self.transport.trace_request(self.history, [TOOL])
        self.assertEqual(trace["system"], "sys")
        self.assertEqual(trace["messages"], self.history.messages)
        self.assertEqual(trace["tools"][0]["name"], "get_weather")

    def test_final_text_is_the_turn_text(self) -> None:
        self.assertEqual(self.transport.final_text(TurnResult(text="done", tool_calls=[])), "done")


class TestCompress(unittest.IsolatedAsyncioTestCase):
    async def test_history_is_left_alone(self) -> None:
        transport = AnthropicMessagesTransport()
        history = MessagesHistory(system="s", messages=[{"role": "user", "content": "x"}])
        out, info = await transport.compress(
            history, model="claude-haiku-5-5", client=MagicMock(), context_limit_tokens=1
        )
        self.assertIs(out, history)
        self.assertIsNone(info)


class TestTransportChoice(unittest.TestCase):
    GATEWAY = "https://opencode.ai/inference/go/v1"

    def _service(self, base_url: str, *, toggle: bool = False) -> LLMService:
        return LLMService(CredentialType.custom, "key", base_url, use_responses_api=toggle)

    def test_messages_only_models_use_the_messages_transport(self) -> None:
        for model in ("claude-haiku-5-5", "minimax-m2.7"):
            self.assertEqual(self._service(self.GATEWAY)._get_transport(model).name, "messages")

    def test_the_responses_toggle_cannot_send_a_messages_only_model_to_responses(self) -> None:
        service = self._service(self.GATEWAY, toggle=True)
        self.assertEqual(service._get_transport("claude-haiku-5-5").name, "messages")

    def test_other_gateways_are_never_switched_by_model_name(self) -> None:
        service = self._service("https://openrouter.ai/api/v1")
        self.assertEqual(service._get_transport("claude-haiku-5-5").name, "chat.completions")


class TestOpenCodeSessionHeader(unittest.IsolatedAsyncioTestCase):
    """The Messages call is a new LLM path, so it must carry the conversation id like the others."""

    async def test_tool_roundtrip_and_followups_keep_the_conversation_id(self) -> None:
        seen: list[tuple[str, str, str]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(
                (
                    request.url.path,
                    request.headers["x-opencode-session"],
                    request.headers.get("anthropic-version", ""),
                )
            )
            content: list[dict[str, Any]] = [{"type": "text", "text": "done"}]
            if len(seen) == 1:
                content = [{"type": "tool_use", "id": "tu_1", "name": "inspect", "input": {}}]
            return httpx.Response(200, json=_payload(content))

        def transport(**_kwargs: Any) -> httpx.Client:
            client = httpx.Client(transport=httpx.MockTransport(respond))
            self.addCleanup(client.close)
            return client

        def service(session_id: str) -> LLMService:
            return LLMService(
                CredentialType.custom,
                "test-key",
                "https://opencode.ai/inference/go/v1",
                trace_context=LLMTraceContext(
                    user_id=uuid.uuid4(), credential_id=uuid.uuid4(), session_id=session_id
                ),
            )

        with (
            patch("app.services.openai_client.guard_http_url"),
            patch("app.services.openai_client.build_guarded_http_client", side_effect=transport),
            patch("app.services.llm_service.record_llm_trace"),
        ):
            tool_executor = MagicMock(return_value={"result": "inspected"})
            result = await service("conversation-1").execute_with_tools(
                "claude-haiku-5-5",
                None,
                "inspect this",
                [{"name": "inspect", "parameters": {"type": "object", "properties": {}}}],
                tool_executor,
            )
            tool_executor.assert_called_once()
            self.assertEqual(result["text"], "done")
            await service("conversation-1").execute("claude-haiku-5-5", None, "follow up")
            await service("conversation-2").execute("claude-haiku-5-5", None, "new conversation")

        self.assertEqual([path for path, _, _ in seen], ["/inference/go/v1/messages"] * 4)
        self.assertEqual(
            [session for _, session, _ in seen], ["conversation-1"] * 3 + ["conversation-2"]
        )
        self.assertTrue(all(version == "2023-06-01" for _, _, version in seen))


class TestApiKeyHeader(unittest.IsolatedAsyncioTestCase):
    """OpenCode Go's /messages reads the key from x-api-key and answers 401 to Bearer alone."""

    async def test_the_key_rides_in_x_api_key_as_well_as_the_bearer(self) -> None:
        seen: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=_payload([{"type": "text", "text": "done"}]))

        def transport(**_kwargs: Any) -> httpx.Client:
            client = httpx.Client(transport=httpx.MockTransport(respond))
            self.addCleanup(client.close)
            return client

        with (
            patch("app.services.openai_client.guard_http_url"),
            patch("app.services.openai_client.build_guarded_http_client", side_effect=transport),
            patch("app.services.llm_service.record_llm_trace"),
        ):
            service = LLMService(CredentialType.custom, "go-key", "https://opencode.ai/zen/go/v1")
            await service.execute("claude-haiku-5-5", None, "hi")

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].headers["x-api-key"], "go-key")
        self.assertEqual(seen[0].headers["authorization"], "Bearer go-key")


_BINDING_ERROR = (
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': "
    "'Upstream request failed: [invalid_request_error] messages.1.content.2: Invalid `signature` "
    "in `thinking` block. The block is bound to a different conversation. Remove the block. The "
    "`system` prompt differs from the one this block was created with.'}}"
)


def _thinking_history() -> MessagesHistory:
    return MessagesHistory(
        system="s",
        messages=[
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "tool_use", "id": "tu_1", "name": "a", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "x"}],
            },
        ],
    )


class TestThinkingBlockBinding(unittest.TestCase):
    """A thinking block is signed for one system prompt; a changed prompt makes Claude refuse it."""

    def _create(self, client: MagicMock, history: MessagesHistory) -> TurnResult:
        return AnthropicMessagesTransport().create(
            client=client, model="claude-haiku-5-5", history=history, tools=None, opts=RequestOpts()
        )

    def _client(self, *outcomes: Any) -> MagicMock:
        client = MagicMock()
        replies = []
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                replies.append(outcome)
            else:
                reply = MagicMock()
                reply.json.return_value = outcome
                replies.append(reply)
        client.post.side_effect = replies
        return client

    def test_the_request_is_retried_once_without_thinking_blocks(self) -> None:
        history = _thinking_history()
        error = _status(_BINDING_ERROR, 400)
        client = self._client(error, _payload([{"type": "text", "text": "ok"}]))
        turn = self._create(client, history)

        self.assertEqual(turn.text, "ok")
        self.assertEqual(client.post.call_count, 2)
        sent = client.post.call_args_list[1].kwargs["body"]["messages"]
        self.assertEqual([b["type"] for b in sent[1]["content"]], ["tool_use"])

    def test_the_history_loses_them_too_so_later_turns_do_not_fail_again(self) -> None:
        history = _thinking_history()
        client = self._client(
            _status(_BINDING_ERROR, 400), _payload([{"type": "text", "text": "ok"}])
        )
        self._create(client, history)
        self.assertEqual([b["type"] for b in history.messages[1]["content"]], ["tool_use"])

    def test_a_second_binding_error_is_not_retried_again(self) -> None:
        history = _thinking_history()
        client = self._client(_status(_BINDING_ERROR, 400), _status(_BINDING_ERROR, 400))
        with self.assertRaises(Exception):
            self._create(client, history)
        self.assertEqual(client.post.call_count, 2)

    def test_other_400s_are_not_retried(self) -> None:
        error = _status("Error code: 400 - temperature is deprecated", 400)
        client = self._client(error)
        with self.assertRaises(Exception) as ctx:
            self._create(client, _thinking_history())
        self.assertIs(ctx.exception, error)
        self.assertEqual(client.post.call_count, 1)

    def test_nothing_to_strip_means_the_error_surfaces(self) -> None:
        history = MessagesHistory(system="s", messages=[{"role": "user", "content": "hi"}])
        error = _status(_BINDING_ERROR, 400)
        client = self._client(error)
        with self.assertRaises(Exception) as ctx:
            self._create(client, history)
        self.assertIs(ctx.exception, error)
        self.assertEqual(client.post.call_count, 1)


def _status(message: str, status: int) -> Exception:
    error = Exception(message)
    error.status_code = status
    return error


class TestSystemPromptStaysTheSameAcrossTurns(unittest.IsolatedAsyncioTestCase):
    """A repair turn used to change the system prompt, which Claude rejects once a thinking block exists."""

    async def test_every_request_of_a_tool_loop_with_a_repair_has_the_same_system(self) -> None:
        bodies: list[dict[str, Any]] = []
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }

        def respond(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            if len(bodies) == 1:
                content: list[dict[str, Any]] = [
                    {"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "tool_use", "id": "tu_1", "name": "lookup", "input": {}},
                ]
            elif len(bodies) == 2:
                content = [{"type": "text", "text": "not json"}]
            else:
                content = [{"type": "text", "text": '{"name": "Anna"}'}]
            return httpx.Response(200, json=_payload(content))

        def transport(**_kwargs: Any) -> httpx.Client:
            client = httpx.Client(transport=httpx.MockTransport(respond))
            self.addCleanup(client.close)
            return client

        service = LLMService(
            CredentialType.custom, "test-key", "https://opencode.ai/inference/go/v1"
        )
        with (
            patch("app.services.openai_client.guard_http_url"),
            patch("app.services.openai_client.build_guarded_http_client", side_effect=transport),
            patch("app.services.llm_service.record_llm_trace"),
        ):
            result = await service.execute_with_tools(
                "claude-haiku-5-5",
                "extract",
                "Anna",
                [{"name": "lookup", "parameters": {"type": "object", "properties": {}}}],
                MagicMock(return_value={"ok": True}),
                response_format={"type": "json_schema", "json_schema": {"schema": schema}},
                repair_json_output=True,
            )

        self.assertEqual(result["text"], '{"name": "Anna"}')
        self.assertEqual(len(bodies), 3)
        self.assertEqual(len({body["system"] for body in bodies}), 1)
        self.assertIn("JSON", bodies[0]["system"])
