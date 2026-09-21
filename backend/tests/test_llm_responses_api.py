import unittest
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.llm_service import LLMService


def _chat_response(content: str):
    message = MagicMock()
    message.content = content
    message.tool_calls = []
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"
    choice.model_dump.return_value = {"message": {"content": content}}
    response = MagicMock()
    response.choices = [choice]
    response.usage.prompt_tokens = 3
    response.usage.completion_tokens = 4
    response.usage.total_tokens = 7
    return response


class TestExecuteStillUsesChatCompletions(unittest.IsolatedAsyncioTestCase):
    async def test_default_path_sends_todays_kwargs(self) -> None:
        client = MagicMock()
        client.base_url = "https://api.openai.com/v1"
        client.chat.completions.create.return_value = _chat_response("hello")
        service = LLMService(CredentialType.openai, "sk-test")
        with patch.object(service, "_get_client", return_value=(client, "OpenAI")):
            result = await service.execute(
                model="gpt-4o",
                system_instruction="be brief",
                user_message="hi",
                temperature=0.2,
                max_tokens=64,
            )
        client.responses.create.assert_not_called()
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-4o")
        self.assertEqual(
            kwargs["messages"],
            [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hi"},
            ],
        )
        self.assertEqual(kwargs["temperature"], 0.2)
        self.assertEqual(kwargs["max_tokens"], 64)
        self.assertNotIn("tools", kwargs)
        self.assertEqual(result["text"], "hello")
        self.assertEqual(result["usage"]["total_tokens"], 7)


def _responses_response(text: str = "", items: list | None = None):
    response = MagicMock()
    if items is None:
        items = (
            [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            ]
            if text
            else []
        )
    response.output = items
    response.usage.input_tokens = 3
    response.usage.output_tokens = 4
    response.usage.total_tokens = 7
    return response


class TestFlagSelectsTransport(unittest.IsolatedAsyncioTestCase):
    async def test_flag_on_calls_responses(self) -> None:
        client = MagicMock()
        client.base_url = "https://api.openai.com/v1"
        client.responses.create.return_value = _responses_response("hello")

        service = LLMService(CredentialType.openai, "sk-test", use_responses_api=True)
        with patch.object(service, "_get_client", return_value=(client, "OpenAI")):
            result = await service.execute(
                model="gpt-5", system_instruction=None, user_message="hi"
            )
        client.chat.completions.create.assert_not_called()
        client.responses.create.assert_called_once()
        self.assertEqual(result["text"], "hello")

    async def test_trace_records_responses_request_type(self) -> None:
        client = MagicMock()
        client.base_url = "https://api.openai.com/v1"
        client.responses.create.return_value = _responses_response()

        service = LLMService(CredentialType.openai, "sk-test", use_responses_api=True)
        recorded: list[str] = []
        with (
            patch.object(service, "_get_client", return_value=(client, "OpenAI")),
            patch.object(
                service,
                "_record_trace",
                side_effect=lambda **kw: recorded.append(kw["request_type"]),
            ),
        ):
            await service.execute(model="gpt-5", system_instruction=None, user_message="hi")
        self.assertEqual(recorded, ["responses"])

    def test_opencode_session_header_travels_on_every_endpoint(self) -> None:
        """AGENTS.md: every OpenCode model request needs a non-empty session header.
        The header is stamped on the client, so it covers /responses too."""
        from app.services.openai_client import create_openai_client

        client = create_openai_client(
            api_key="sk-test", base_url="https://opencode.ai/v1", session_id="session-1"
        )
        headers = {k.lower(): v for k, v in client.default_headers.items()}
        self.assertEqual(headers.get("x-opencode-session"), "session-1")

    def test_opencode_session_header_never_empty(self) -> None:
        from app.services.openai_client import create_openai_client

        client = create_openai_client(
            api_key="sk-test", base_url="https://opencode.ai/v1", session_id=""
        )
        headers = {k.lower(): v for k, v in client.default_headers.items()}
        self.assertTrue(headers.get("x-opencode-session"))


from app.services.llm_transport import ResponsesTransport, ToolResult, TurnResult  # noqa: E402


class TestToolLoopOnResponses(unittest.IsolatedAsyncioTestCase):
    async def test_two_iteration_tool_loop_feeds_results_back(self) -> None:
        client = MagicMock()
        client.base_url = "https://api.openai.com/v1"

        first = _responses_response(
            items=[
                {"type": "reasoning", "id": "rs_1", "encrypted_content": "blob"},
                {
                    "type": "function_call",
                    "call_id": "fc_1",
                    "name": "add",
                    "arguments": '{"a":1}',
                },
            ]
        )
        first.usage.input_tokens = 10
        first.usage.output_tokens = 2
        second = _responses_response("the answer is 43")
        second.usage.input_tokens = 14
        second.usage.output_tokens = 6
        client.responses.create.side_effect = [first, second]

        def tool_executor(tool_def, name, args, timeout):
            del tool_def, name, args, timeout
            return "43"

        service = LLMService(CredentialType.openai, "sk-test", use_responses_api=True)
        with (
            patch.object(service, "_get_client", return_value=(client, "OpenAI")),
            patch("app.services.context_compressor.get_context_limit", return_value=100000),
        ):
            result = await service.execute_with_tools(
                model="gpt-5",
                system_instruction="be brief",
                user_message="what is 1 + 42",
                tools=[{"name": "add", "description": "adds", "parameters": {}}],
                tool_executor=tool_executor,
            )

        self.assertEqual(result["text"], "the answer is 43")
        self.assertEqual(result["usage"]["prompt_tokens"], 24)
        second_input = client.responses.create.call_args_list[1].kwargs["input"]
        self.assertIn(
            {"type": "reasoning", "id": "rs_1", "encrypted_content": "blob"}, second_input
        )
        self.assertEqual(second_input[-1]["type"], "function_call_output")
        self.assertEqual(second_input[-1]["call_id"], "fc_1")
        self.assertIn("43", second_input[-1]["output"])

    async def test_hitl_dump_load_round_trip_preserves_reasoning(self) -> None:
        transport = ResponsesTransport()
        history = transport.start(
            system_instruction="old",
            conversation_history=None,
            user_message="go",
            image_input=None,
        )
        reasoning = {"type": "reasoning", "id": "rs_1", "encrypted_content": "blob"}
        transport.append_turn(history, TurnResult(text="", tool_calls=[], raw_items=[reasoning]))
        transport.append_tool_results(history, [ToolResult(call_id="fc_1", output="42")])
        dumped = transport.dump(history)
        restored = transport.load(dumped, "new")
        self.assertIn(reasoning, restored.items)
        self.assertEqual(restored.items[0]["content"], "new")


class TestNodeFlagPlumbing(unittest.TestCase):
    def _run_llm_node(self, node_data: dict) -> dict:
        from app.services.node_execution.base import NodeExecutionContext
        from app.services.node_execution.nodes import llm_node

        captured: dict = {}

        class _Executor:
            def _visible_inputs(self, inputs):
                return inputs

            def _resolve_template(self, template, inputs, node_id):
                del inputs, node_id
                return template

            def resolve_expression(self, expr, inputs, node_id, preserve_type=False):
                del inputs, node_id, preserve_type
                return expr

            def _execute_llm_node(self, **kwargs):
                captured.update(kwargs)
                return {"text": "ok"}

            def _pop_internal_trace_id(self, output):
                del output
                return None

            def _restore_internal_trace_id(self, output, trace_id):
                del output, trace_id

        ctx = NodeExecutionContext(
            executor=_Executor(),
            node_id="n1",
            inputs={},
            allow_branch_skip=False,
            start_time=0.0,
            node={},
            node_type="llm",
            node_data={"credentialId": "c1", "model": "gpt-5", **node_data},
            node_label="LLM",
        )
        llm_node.execute(ctx)
        return captured

    def test_llm_node_forwards_responses_flag(self) -> None:
        captured = self._run_llm_node({"responsesApiEnabled": True})
        self.assertTrue(captured["use_responses_api"])

    def test_llm_node_defaults_to_chat_completions(self) -> None:
        captured = self._run_llm_node({})
        self.assertFalse(captured["use_responses_api"])

    def test_batch_mode_wins_over_responses(self) -> None:
        captured = self._run_llm_node({"responsesApiEnabled": True, "batchModeEnabled": True})
        self.assertFalse(captured["use_responses_api"])


class TestAgentFlagPlumbing(unittest.TestCase):
    """The agent path is too entangled to instantiate here, so assert on the source
    that the flag is read once and reaches both call sites in the `attempts` loop.
    `agent_use_responses_api` is unique to the agent path, so a module-wide count
    is exact."""

    def _executor_source(self) -> str:
        import inspect

        from app.services import workflow_executor

        return inspect.getsource(workflow_executor)

    def test_agent_reads_the_flag_once(self) -> None:
        source = self._executor_source()
        self.assertEqual(
            source.count(
                'agent_use_responses_api = bool(node_data.get("responsesApiEnabled", False))'
            ),
            1,
        )

    def test_both_agent_call_sites_forward_the_flag(self) -> None:
        source = self._executor_source()
        self.assertEqual(
            source.count("use_responses_api=agent_use_responses_api"),
            2,
            "execute_llm_with_tools and execute_llm must both forward the flag",
        )

    def test_llm_node_path_forwards_its_own_flag(self) -> None:
        source = self._executor_source()
        self.assertIn("use_responses_api=use_responses_api", source)


class TestTracePayloadIsSerializable(unittest.IsolatedAsyncioTestCase):
    """A trace row is written as JSON, so nothing in the payload may be a transport's
    own history object. Regression: `ResponsesHistory` leaked into the request and the
    llm_traces insert failed, leaving the run with no trace at all."""

    async def _capture_trace_requests(self, *, use_responses_api: bool) -> list[object]:
        import json

        client = MagicMock()
        client.base_url = "https://api.openai.com/v1"
        if use_responses_api:
            client.responses.create.return_value = _responses_response("done")
        else:
            client.chat.completions.create.return_value = _chat_response("done")

        service = LLMService(CredentialType.openai, "sk-test", use_responses_api=use_responses_api)
        captured: list[object] = []
        with (
            patch.object(service, "_get_client", return_value=(client, "OpenAI")),
            patch("app.services.context_compressor.get_context_limit", return_value=100000),
            patch.object(
                service, "_record_trace", side_effect=lambda **kw: captured.append(kw["request"])
            ),
        ):
            await service.execute_with_tools(
                model="gpt-5",
                system_instruction="be brief",
                user_message="hi",
                tools=[{"name": "noop", "description": "", "parameters": {}}],
                tool_executor=lambda *a, **k: "",
            )
        self.assertTrue(captured)
        for request in captured:
            json.dumps(request)  # raises TypeError if a history object leaked
        return captured

    async def test_responses_trace_request_is_json_serializable(self) -> None:
        captured = await self._capture_trace_requests(use_responses_api=True)
        self.assertIn("input", captured[0])
        self.assertNotIn("messages", captured[0])

    async def test_chat_trace_request_is_json_serializable(self) -> None:
        captured = await self._capture_trace_requests(use_responses_api=False)
        self.assertIn("messages", captured[0])
