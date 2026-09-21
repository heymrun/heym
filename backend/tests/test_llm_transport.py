import unittest

from app.services.llm_transport import RequestOpts, ToolCall, ToolResult, TurnResult


class TestTransportTypes(unittest.TestCase):
    def test_tool_call_identity_not_value_equality(self) -> None:
        """The agent loop filters with `tc not in sub_agent_tcs`, so two identical
        tool calls must stay distinguishable."""
        a = ToolCall(id="call_1", name="search", arguments="{}")
        b = ToolCall(id="call_1", name="search", arguments="{}")
        self.assertIsNot(a, b)
        self.assertNotEqual(a, b)
        self.assertNotIn(b, [a])

    def test_turn_result_defaults(self) -> None:
        turn = TurnResult(text="hi", tool_calls=[])
        self.assertEqual(turn.prompt_tokens, 0)
        self.assertEqual(turn.completion_tokens, 0)
        self.assertEqual(turn.total_tokens, 0)
        self.assertIsNone(turn.finish_reason)
        self.assertEqual(turn.raw_items, [])

    def test_request_opts_defaults(self) -> None:
        opts = RequestOpts()
        self.assertIsNone(opts.temperature)
        self.assertIsNone(opts.reasoning_effort)
        self.assertIsNone(opts.max_tokens)
        self.assertIsNone(opts.response_format)
        self.assertIsNone(opts.extra_body)

    def test_tool_result_shape(self) -> None:
        result = ToolResult(call_id="call_1", output="42")
        self.assertEqual(result.call_id, "call_1")
        self.assertEqual(result.output, "42")


from unittest.mock import MagicMock  # noqa: E402

from app.services.llm_transport import ChatCompletionsTransport  # noqa: E402


def _fake_chat_response(content: str, tool_calls: list | None = None):
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"
    choice.model_dump.return_value = {"message": {"content": content}}
    response = MagicMock()
    response.choices = [choice]
    response.usage.prompt_tokens = 11
    response.usage.completion_tokens = 7
    response.usage.total_tokens = 18
    return response


def _fake_sdk_tool_call(call_id: str, name: str, arguments: str):
    tc = MagicMock()
    tc.id = call_id
    tc.type = "function"
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


class TestChatCompletionsTransport(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = ChatCompletionsTransport()

    def test_start_builds_message_list(self) -> None:
        history = self.transport.start(
            system_instruction="be brief",
            conversation_history=[{"role": "user", "content": "earlier"}],
            user_message="now",
            image_input=None,
        )
        self.assertEqual(
            history,
            [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "earlier"},
                {"role": "user", "content": "now"},
            ],
        )

    def test_start_with_image_uses_image_url_object(self) -> None:
        history = self.transport.start(
            system_instruction=None,
            conversation_history=None,
            user_message="what is this",
            image_input="https://example.com/a.png",
        )
        self.assertEqual(
            history[0]["content"],
            [
                {"type": "text", "text": "what is this"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            ],
        )

    def test_load_replaces_leading_system_message(self) -> None:
        history = self.transport.load(
            [{"role": "system", "content": "old"}, {"role": "user", "content": "hi"}],
            "new",
        )
        self.assertEqual(history[0], {"role": "system", "content": "new"})
        self.assertEqual(len(history), 2)

    def test_load_inserts_system_message_when_absent(self) -> None:
        history = self.transport.load([{"role": "user", "content": "hi"}], "new")
        self.assertEqual(history[0], {"role": "system", "content": "new"})
        self.assertEqual(len(history), 2)

    def test_create_translates_opts_and_returns_turn(self) -> None:
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_chat_response(
            "done", [_fake_sdk_tool_call("call_1", "search", '{"q":1}')]
        )
        turn = self.transport.create(
            client=client,
            model="gpt-4o",
            history=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "search"}}],
            opts=RequestOpts(temperature=0.3, max_tokens=256),
        )
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-4o")
        self.assertEqual(kwargs["messages"], [{"role": "user", "content": "hi"}])
        self.assertEqual(kwargs["temperature"], 0.3)
        self.assertEqual(kwargs["max_tokens"], 256)
        self.assertEqual(kwargs["tool_choice"], "auto")
        self.assertEqual(turn.text, "done")
        self.assertEqual(turn.prompt_tokens, 11)
        self.assertEqual(turn.completion_tokens, 7)
        self.assertEqual([tc.name for tc in turn.tool_calls], ["search"])
        self.assertEqual(turn.tool_calls[0].id, "call_1")
        self.assertEqual(turn.tool_calls[0].arguments, '{"q":1}')

    def test_create_uses_max_completion_tokens_for_reasoning_models(self) -> None:
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_chat_response("ok")
        self.transport.create(
            client=client,
            model="o3-mini",
            history=[],
            tools=None,
            opts=RequestOpts(max_tokens=99, reasoning_effort="high", temperature=0.5),
        )
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["max_completion_tokens"], 99)
        self.assertEqual(kwargs["reasoning_effort"], "high")
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("max_tokens", kwargs)

    def test_append_turn_writes_assistant_tool_call_message(self) -> None:
        history: list = []
        turn = TurnResult(
            text="thinking",
            tool_calls=[ToolCall(id="call_1", name="search", arguments='{"q":1}')],
        )
        self.transport.append_turn(history, turn)
        self.assertEqual(
            history,
            [
                {
                    "role": "assistant",
                    "content": "thinking",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"q":1}'},
                        }
                    ],
                }
            ],
        )

    def test_append_tool_results(self) -> None:
        history: list = []
        self.transport.append_tool_results(history, [ToolResult(call_id="call_1", output="42")])
        self.assertEqual(history, [{"role": "tool", "tool_call_id": "call_1", "content": "42"}])

    def test_dump_round_trips(self) -> None:
        history = [{"role": "user", "content": "hi"}]
        self.assertEqual(self.transport.dump(history), history)


from app.services.llm_transport import ResponsesTransport  # noqa: E402


def _fake_responses_response(items: list[dict]):
    response = MagicMock()
    response.output = items
    response.usage.input_tokens = 21
    response.usage.output_tokens = 5
    response.usage.total_tokens = 26
    response.model_dump.return_value = {"output": items}
    return response


class TestResponsesTransportTranslation(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = ResponsesTransport()

    def test_name(self) -> None:
        self.assertEqual(self.transport.name, "responses")

    def test_start_builds_input_items(self) -> None:
        history = self.transport.start(
            system_instruction="be brief",
            conversation_history=None,
            user_message="hi",
            image_input=None,
        )
        self.assertEqual(
            history.items,
            [
                {"type": "message", "role": "system", "content": "be brief"},
                {"type": "message", "role": "user", "content": "hi"},
            ],
        )

    def test_start_with_image_uses_input_image_string_url(self) -> None:
        history = self.transport.start(
            system_instruction=None,
            conversation_history=None,
            user_message="what is this",
            image_input="https://example.com/a.png",
        )
        self.assertEqual(
            history.items[0]["content"],
            [
                {"type": "input_text", "text": "what is this"},
                {"type": "input_image", "image_url": "https://example.com/a.png"},
            ],
        )

    def test_always_stateless_with_encrypted_reasoning(self) -> None:
        client = MagicMock()
        client.responses.create.return_value = _fake_responses_response([])
        self.transport.create(
            client=client,
            model="gpt-5",
            history=self.transport.new_history(),
            tools=None,
            opts=RequestOpts(),
        )
        kwargs = client.responses.create.call_args.kwargs
        self.assertIs(kwargs["store"], False)
        self.assertEqual(kwargs["include"], ["reasoning.encrypted_content"])

    def test_opts_translation(self) -> None:
        client = MagicMock()
        client.responses.create.return_value = _fake_responses_response([])
        self.transport.create(
            client=client,
            model="gpt-5",
            history=self.transport.new_history(),
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "search",
                        "description": "find",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            opts=RequestOpts(
                max_tokens=128,
                reasoning_effort="high",
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "output", "schema": {"type": "object"}, "strict": True},
                },
            ),
        )
        kwargs = client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["max_output_tokens"], 128)
        self.assertEqual(kwargs["reasoning"], {"effort": "high"})
        self.assertEqual(
            kwargs["text"],
            {
                "format": {
                    "type": "json_schema",
                    "name": "output",
                    "schema": {"type": "object"},
                    "strict": True,
                }
            },
        )
        self.assertEqual(
            kwargs["tools"],
            [
                {
                    "type": "function",
                    "name": "search",
                    "description": "find",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
        )

    def test_json_object_format_translation(self) -> None:
        client = MagicMock()
        client.responses.create.return_value = _fake_responses_response([])
        self.transport.create(
            client=client,
            model="gpt-4o",
            history=self.transport.new_history(),
            tools=None,
            opts=RequestOpts(response_format={"type": "json_object"}),
        )
        kwargs = client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["text"], {"format": {"type": "json_object"}})

    def test_tool_choice_is_forwarded(self) -> None:
        client = MagicMock()
        client.responses.create.return_value = _fake_responses_response([])
        self.transport.create(
            client=client,
            model="gpt-4o",
            history=self.transport.new_history(),
            tools=[{"type": "function", "function": {"name": "s", "parameters": {}}}],
            opts=RequestOpts(tool_choice="none"),
        )
        self.assertEqual(client.responses.create.call_args.kwargs["tool_choice"], "none")

    def test_output_parsing_and_usage_normalisation(self) -> None:
        client = MagicMock()
        client.responses.create.return_value = _fake_responses_response(
            [
                {"type": "reasoning", "id": "rs_1", "encrypted_content": "blob"},
                {
                    "type": "function_call",
                    "call_id": "fc_1",
                    "name": "search",
                    "arguments": '{"q":1}',
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "partial"}],
                },
            ]
        )
        turn = self.transport.create(
            client=client,
            model="gpt-5",
            history=self.transport.new_history(),
            tools=None,
            opts=RequestOpts(),
        )
        self.assertEqual(turn.text, "partial")
        self.assertEqual([tc.id for tc in turn.tool_calls], ["fc_1"])
        self.assertEqual(turn.tool_calls[0].name, "search")
        self.assertEqual(turn.prompt_tokens, 21)
        self.assertEqual(turn.completion_tokens, 5)
        self.assertEqual(turn.total_tokens, 26)
        self.assertEqual(len(turn.raw_items), 3)

    def test_append_tool_results_uses_function_call_output(self) -> None:
        history = self.transport.new_history()
        self.transport.append_tool_results(history, [ToolResult(call_id="fc_1", output="42")])
        self.assertEqual(
            history.items,
            [{"type": "function_call_output", "call_id": "fc_1", "output": "42"}],
        )

    def test_last_item_is_tool_result(self) -> None:
        history = self.transport.new_history()
        self.assertFalse(self.transport.last_item_is_tool_result(history))
        self.transport.append_tool_results(history, [ToolResult(call_id="fc_1", output="42")])
        self.assertTrue(self.transport.last_item_is_tool_result(history))


from unittest.mock import patch  # noqa: E402

from app.services.llm_transport import ResponsesHistory, ResponsesTransportError  # noqa: E402


class TestResponsesReasoningAndCompression(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.transport = ResponsesTransport()

    def test_reasoning_item_returns_verbatim_on_next_turn(self) -> None:
        """The whole point of the feature: a reasoning item produced alongside a
        tool call must be present in the next request's input."""
        client = MagicMock()
        reasoning = {"type": "reasoning", "id": "rs_1", "encrypted_content": "blob"}
        call = {
            "type": "function_call",
            "call_id": "fc_1",
            "name": "search",
            "arguments": "{}",
        }
        client.responses.create.return_value = _fake_responses_response([reasoning, call])

        history = self.transport.start(
            system_instruction=None,
            conversation_history=None,
            user_message="find it",
            image_input=None,
        )
        turn = self.transport.create(
            client=client, model="gpt-5", history=history, tools=None, opts=RequestOpts()
        )
        self.transport.append_turn(history, turn)
        self.transport.append_tool_results(history, [ToolResult(call_id="fc_1", output="42")])

        client.responses.create.return_value = _fake_responses_response([])
        self.transport.create(
            client=client, model="gpt-5", history=history, tools=None, opts=RequestOpts()
        )
        sent = client.responses.create.call_args.kwargs["input"]
        self.assertIn(reasoning, sent)
        self.assertEqual(
            sent[-1], {"type": "function_call_output", "call_id": "fc_1", "output": "42"}
        )

    def test_create_does_not_mutate_history(self) -> None:
        client = MagicMock()
        client.responses.create.return_value = _fake_responses_response(
            [{"type": "reasoning", "id": "rs_1", "encrypted_content": "blob"}]
        )
        history = self.transport.new_history()
        self.transport.create(
            client=client, model="gpt-5", history=history, tools=None, opts=RequestOpts()
        )
        self.assertEqual(history.items, [])

    def test_hard_fail_wraps_404_with_actionable_message(self) -> None:
        client = MagicMock()
        error = Exception("Not Found")
        error.status_code = 404
        client.responses.create.side_effect = error
        with self.assertRaises(ResponsesTransportError) as ctx:
            self.transport.create(
                client=client,
                model="gpt-5",
                history=self.transport.new_history(),
                tools=None,
                opts=RequestOpts(),
            )
        self.assertIn("Use Responses API", str(ctx.exception))
        self.assertIn("404", str(ctx.exception))

    def test_unrelated_errors_are_not_wrapped(self) -> None:
        client = MagicMock()
        error = Exception("rate limited")
        error.status_code = 429
        client.responses.create.side_effect = error
        with self.assertRaises(Exception) as ctx:
            self.transport.create(
                client=client,
                model="gpt-5",
                history=self.transport.new_history(),
                tools=None,
                opts=RequestOpts(),
            )
        self.assertNotIsInstance(ctx.exception, ResponsesTransportError)

    async def test_compress_drops_reasoning_items_and_keeps_shape(self) -> None:
        history = ResponsesHistory(
            items=[
                {"type": "message", "role": "user", "content": "one"},
                {"type": "reasoning", "id": "rs_1", "encrypted_content": "blob"},
                {"type": "message", "role": "assistant", "content": "two"},
                {"type": "message", "role": "user", "content": "three"},
            ]
        )

        async def fake_compress(messages, **kwargs):
            del kwargs
            return (
                [messages[0], {"role": "assistant", "content": "summary"}, messages[-1]],
                {"messages_compressed": 1},
            )

        with patch("app.services.context_compressor.maybe_compress_messages", new=fake_compress):
            compressed, info = await self.transport.compress(
                history, model="gpt-5", client=MagicMock(), context_limit_tokens=1000
            )
        self.assertEqual(info, {"messages_compressed": 1})
        self.assertTrue(all(item["type"] == "message" for item in compressed.items))
        self.assertNotIn(
            {"type": "reasoning", "id": "rs_1", "encrypted_content": "blob"}, compressed.items
        )
        self.assertEqual(compressed.items[-1]["content"], "three")

    async def test_compress_returns_history_unchanged_when_compressor_declines(self) -> None:
        history = ResponsesHistory(
            items=[{"type": "reasoning", "id": "rs_1", "encrypted_content": "blob"}]
        )

        async def fake_compress(messages, **kwargs):
            del kwargs
            return messages, None

        with patch("app.services.context_compressor.maybe_compress_messages", new=fake_compress):
            compressed, info = await self.transport.compress(
                history, model="gpt-5", client=MagicMock(), context_limit_tokens=1000
            )
        self.assertIsNone(info)
        self.assertIs(compressed, history)
