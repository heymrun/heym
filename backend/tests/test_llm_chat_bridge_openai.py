"""Chat and agents on OpenAI's own API move to Responses only for the requests OpenAI refuses."""

import json
import unittest
import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai

from app.api import ai_assistant
from app.db.models import CredentialType
from app.services import llm_chat_bridge
from app.services.llm_chat_bridge import (
    OpenAIChatTransport,
    completion_caller,
    forget_openai_responses_routes,
    forget_remembered_turns,
    gateway_protocol,
    is_native_openai,
    needs_responses_api,
)
from app.services.llm_service import LLMService
from app.services.llm_trace import LLMTraceContext
from app.services.llm_transport import RequestOpts
from app.services.openai_client import create_openai_client

OPENAI = "https://api.openai.com/v1"
CHAT_PATH = "/v1/chat/completions"
RESPONSES_PATH = "/v1/responses"
# Verbatim from OpenAI (2026-10-22).
TOOLS_REFUSAL = (
    "Function tools with reasoning_effort are not supported for gpt-6.1-sol in "
    "/v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort "
    "to 'none'."
)
RESPONSES_ONLY = (
    "This model is not supported in the v1/chat/completions endpoint. "
    "Use the v1/responses endpoint instead."
)
DEPRECATED = (
    "The model `gpt-5-codex` has been deprecated, learn more here: "
    "https://platform.openai.com/docs/deprecations"
)
NONE_REFUSAL = (
    "Unsupported value: 'reasoning_effort' does not support 'none' with this model. "
    "Supported values are: 'low', 'medium', 'high'."
)
TOOL = {
    "type": "function",
    "function": {
        "name": "list_workflows",
        "description": "List workflows",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
}
MESSAGES = [{"role": "user", "content": "Show recent runs"}]
Handler = Callable[[httpx.Request], httpx.Response]


def _error(status: int, message: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"message": message, "type": "invalid_request_error", "code": None}},
    )


def _chat_payload(text: str | None = "ok", tool_call: bool = False) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_call:
        message["tool_calls"] = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "list_workflows", "arguments": '{"limit": 5}'},
            }
        ]
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-5.5",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }


REASONING = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "enc-1"}
FUNCTION_CALL = {
    "type": "function_call",
    "id": "fc_1",
    "call_id": "call_1",
    "name": "list_workflows",
    "arguments": '{"limit": 5}',
    "status": "completed",
}


def _text_item(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _responses_payload(output: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "gpt-6.1-sol",
        "output": output,
        "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
    }


class _Recorder:
    """A fake api.openai.com that answers Chat Completions and Responses separately."""

    def __init__(self, chat: list[httpx.Response], responses: list[httpx.Response]) -> None:
        self.chat = chat
        self.responses = responses
        self.paths: list[str] = []
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        self.bodies.append(json.loads(request.content))
        queue = self.chat if request.url.path.endswith("/chat/completions") else self.responses
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def client(self, base_url: str = OPENAI) -> Any:
        http_client = httpx.Client(transport=httpx.MockTransport(self))
        return create_openai_client(api_key="test-key", base_url=base_url, http_client=http_client)


class _ProviderError(Exception):
    def __init__(self, status_code: int | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class _CleanRoutes:
    def setUp(self) -> None:
        forget_openai_responses_routes()
        forget_remembered_turns()
        self.addCleanup(forget_openai_responses_routes)
        self.addCleanup(forget_remembered_turns)


class TestNativeOpenAIDetection(unittest.TestCase):
    def test_only_openais_own_host_counts(self) -> None:
        for base_url in (OPENAI, "https://api.openai.com./v1"):
            self.assertTrue(is_native_openai(SimpleNamespace(base_url=base_url)), base_url)
        for base_url in (
            "https://api.openai.com.evil.example/v1",
            "https://openrouter.ai/api/v1",
            "https://opencode.ai/inference/go/v1",
            "",
            None,
        ):
            self.assertFalse(is_native_openai(SimpleNamespace(base_url=base_url)), base_url)
        self.assertFalse(is_native_openai(MagicMock()))
        self.assertFalse(is_native_openai(SimpleNamespace()))

    def test_other_clients_keep_the_client_method_itself(self) -> None:
        for base_url in ("https://openrouter.ai/api/v1", "http://localhost:11434/v1"):
            client = MagicMock()
            client.base_url = base_url
            self.assertIs(completion_caller(client, "gpt-6.1-sol"), client.chat.completions.create)

    def test_openai_never_has_a_gateway_protocol_so_chat_keeps_compressing(self) -> None:
        client = SimpleNamespace(base_url=OPENAI)
        for model in ("gpt-6.1-sol", "gpt-5.3-codex", "gpt-5.5"):
            self.assertIsNone(gateway_protocol(client, model))

    def test_only_refusals_that_point_at_responses_count(self) -> None:
        self.assertTrue(needs_responses_api(_ProviderError(400, TOOLS_REFUSAL)))
        self.assertTrue(needs_responses_api(_ProviderError(404, RESPONSES_ONLY)))
        self.assertFalse(needs_responses_api(_ProviderError(404, DEPRECATED)))
        self.assertFalse(needs_responses_api(_ProviderError(400, NONE_REFUSAL)))
        self.assertFalse(needs_responses_api(_ProviderError(500, TOOLS_REFUSAL)))
        self.assertFalse(needs_responses_api(_ProviderError(None, TOOLS_REFUSAL)))
        self.assertFalse(needs_responses_api(ValueError(TOOLS_REFUSAL)))


class TestOpenAIChatCompletionsFallback(_CleanRoutes, unittest.TestCase):
    def test_a_model_chat_completions_serves_gets_one_request_there(self) -> None:
        recorder = _Recorder([httpx.Response(200, json=_chat_payload("hi"))], [])

        response = completion_caller(recorder.client(), "gpt-5.5")(
            model="gpt-5.5", messages=MESSAGES, tools=[TOOL], stream=False
        )

        self.assertEqual(recorder.paths, [CHAT_PATH])
        self.assertIsInstance(response, openai.types.chat.ChatCompletion)
        self.assertEqual(response.choices[0].message.content, "hi")
        self.assertEqual(llm_chat_bridge._openai_responses_routes, set())

    def test_refused_tools_move_to_responses_and_stay_there(self) -> None:
        recorder = _Recorder(
            [_error(400, TOOLS_REFUSAL)],
            [httpx.Response(200, json=_responses_payload([REASONING, FUNCTION_CALL]))],
        )
        client = recorder.client()

        first = completion_caller(client, "gpt-6.1-sol")(
            model="gpt-6.1-sol", messages=MESSAGES, tools=[TOOL], stream=False
        )
        second = completion_caller(client, "gpt-6.1-sol")(
            model="gpt-6.1-sol", messages=MESSAGES, tools=[TOOL], stream=False
        )

        self.assertEqual(recorder.paths, [CHAT_PATH, RESPONSES_PATH, RESPONSES_PATH])
        for response in (first, second):
            call = response.choices[0].message.tool_calls[0]
            self.assertEqual((call.id, call.function.name), ("call_1", "list_workflows"))
            self.assertEqual(json.loads(call.function.arguments), {"limit": 5})
        sent = recorder.bodies[1]
        self.assertEqual([tool["name"] for tool in sent["tools"]], ["list_workflows"])
        self.assertIs(sent["store"], False)
        self.assertEqual(sent["include"], ["reasoning.encrypted_content"])
        # Chat never picks an effort, so the model keeps its own default there too.
        self.assertNotIn("reasoning", sent)

    def test_the_same_model_without_tools_stays_on_chat_completions(self) -> None:
        recorder = _Recorder(
            [_error(400, TOOLS_REFUSAL), httpx.Response(200, json=_chat_payload("summary"))],
            [httpx.Response(200, json=_responses_payload([_text_item("ok")]))],
        )
        caller = completion_caller(recorder.client(), "gpt-6.1-sol")

        caller(model="gpt-6.1-sol", messages=MESSAGES, tools=[TOOL])
        response = caller(model="gpt-6.1-sol", messages=MESSAGES)

        self.assertEqual(recorder.paths, [CHAT_PATH, RESPONSES_PATH, CHAT_PATH])
        self.assertEqual(response.choices[0].message.content, "summary")

    def test_a_responses_only_model_streams_its_answer_as_one_chunk(self) -> None:
        recorder = _Recorder(
            [_error(404, RESPONSES_ONLY)],
            [httpx.Response(200, json=_responses_payload([_text_item("hello")]))],
        )

        chunks = list(
            completion_caller(recorder.client(), "gpt-5.3-codex")(
                model="gpt-5.3-codex",
                messages=MESSAGES,
                stream=True,
                stream_options={"include_usage": True},
            )
        )

        self.assertEqual(recorder.paths, [CHAT_PATH, RESPONSES_PATH])
        self.assertEqual(chunks[0].choices[0].delta.content, "hello")
        self.assertEqual(chunks[-1].usage.total_tokens, 7)

    def test_other_refusals_reach_the_caller_untouched(self) -> None:
        for status, message, error in (
            (400, NONE_REFUSAL, openai.BadRequestError),
            (404, DEPRECATED, openai.NotFoundError),
        ):
            with self.subTest(message=message):
                recorder = _Recorder([_error(status, message)], [])
                with self.assertRaises(error):
                    completion_caller(recorder.client(), "gpt-6.1-sol")(
                        model="gpt-6.1-sol", messages=MESSAGES, tools=[TOOL]
                    )
                self.assertEqual(recorder.paths, [CHAT_PATH])
                self.assertEqual(llm_chat_bridge._openai_responses_routes, set())


async def _drain_chat(client: Any, model: str, compressor: AsyncMock) -> list[dict[str, Any]]:
    user_id = uuid.uuid4()
    trace_context = LLMTraceContext(
        user_id=user_id, credential_id=uuid.uuid4(), source="dashboard_chat"
    )
    events: list[dict[str, Any]] = []
    with (
        patch.object(ai_assistant, "record_llm_trace"),
        patch.object(ai_assistant, "record_run_history"),
        patch.object(
            ai_assistant, "get_workflows_for_user_with_inputs", AsyncMock(return_value=[])
        ),
        patch("app.services.context_compressor.get_context_limit", return_value=200_000),
        patch("app.services.context_compressor.maybe_compress_messages", compressor),
    ):
        async for line in ai_assistant.stream_dashboard_chat(
            client,
            model,
            "system",
            list(MESSAGES),
            AsyncMock(),
            SimpleNamespace(id=user_id),
            "OpenAI",
            "http://localhost",
            trace_context,
            None,
        ):
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


def _passthrough_compressor() -> AsyncMock:
    return AsyncMock(side_effect=lambda messages, **_kwargs: (messages, None))


class TestDashboardChatOnOpenAI(_CleanRoutes, unittest.IsolatedAsyncioTestCase):
    async def test_a_tool_round_on_responses_keeps_its_reasoning_and_compression(self) -> None:
        recorder = _Recorder(
            [_error(400, TOOLS_REFUSAL)],
            [
                httpx.Response(200, json=_responses_payload([REASONING, FUNCTION_CALL])),
                httpx.Response(200, json=_responses_payload([_text_item("Here are your runs.")])),
            ],
        )
        compressor = _passthrough_compressor()

        events = await _drain_chat(recorder.client(), "gpt-6.1-sol", compressor)

        self.assertEqual(recorder.paths, [CHAT_PATH, RESPONSES_PATH, RESPONSES_PATH])
        replay = recorder.bodies[2]["input"]
        reasoning = [item for item in replay if item.get("type") == "reasoning"]
        self.assertEqual([item["encrypted_content"] for item in reasoning], ["enc-1"])
        outputs = [item for item in replay if item.get("type") == "function_call_output"]
        self.assertEqual([item["call_id"] for item in outputs], ["call_1"])
        self.assertIn({"type": "content", "text": "Here are your runs."}, events)
        self.assertEqual(events[-1], {"type": "done"})
        self.assertFalse([e for e in events if e.get("type") == "error"])
        self.assertEqual(compressor.await_count, 2)

    async def test_a_model_chat_completions_serves_keeps_one_request_per_round(self) -> None:
        recorder = _Recorder(
            [
                httpx.Response(200, json=_chat_payload(None, tool_call=True)),
                httpx.Response(200, json=_chat_payload("Here are your runs.")),
            ],
            [],
        )
        compressor = _passthrough_compressor()

        events = await _drain_chat(recorder.client(), "gpt-5.5", compressor)

        self.assertEqual(recorder.paths, [CHAT_PATH, CHAT_PATH])
        self.assertIn("tools", recorder.bodies[0])
        self.assertNotIn("reasoning_effort", recorder.bodies[0])
        self.assertIn({"type": "content", "text": "Here are your runs."}, events)
        self.assertEqual(compressor.await_count, 2)
        self.assertEqual(llm_chat_bridge._openai_responses_routes, set())


AGENT_TOOL = {
    "name": "list_workflows",
    "description": "List workflows",
    "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
}
PAUSED_HISTORY = [
    {"role": "system", "content": "be brief"},
    {"role": "user", "content": "Show recent runs"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "list_workflows", "arguments": '{"limit": 5}'},
            }
        ],
    },
    {"role": "tool", "tool_call_id": "call_1", "content": '{"workflows": []}'},
]


class TestAgentOnOpenAI(_CleanRoutes, unittest.IsolatedAsyncioTestCase):
    """The agent node keeps Chat Completions unless OpenAI refuses the request there."""

    async def _run_agent(
        self,
        client: Any,
        model: str,
        credential_type: CredentialType = CredentialType.openai,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[str], MagicMock]:
        service = LLMService(credential_type, "test-key")
        calls: list[str] = []

        def executor(_tool: dict, name: str, _args: dict, _timeout: float) -> object:
            calls.append(name)
            return {"workflows": []}

        with (
            patch.object(service, "_get_client", return_value=(client, "OpenAI")),
            patch.object(service, "_record_trace") as record_trace,
            patch("app.services.context_compressor.get_context_limit", return_value=200_000),
        ):
            result = await service.execute_with_tools(
                model=model,
                system_instruction="be brief",
                user_message="Show recent runs",
                tools=[AGENT_TOOL],
                tool_executor=executor,
                **kwargs,
            )
        return result, calls, record_trace

    def _two_responses_rounds(self) -> _Recorder:
        return _Recorder(
            [_error(400, TOOLS_REFUSAL)],
            [
                httpx.Response(200, json=_responses_payload([REASONING, FUNCTION_CALL])),
                httpx.Response(200, json=_responses_payload([_text_item("Here are your runs.")])),
            ],
        )

    def test_the_transport_is_still_chat_completions_by_name(self) -> None:
        for service in (
            LLMService(CredentialType.openai, "key"),
            LLMService(CredentialType.custom, "key", "https://openrouter.ai/api/v1"),
        ):
            transport = service._get_transport("gpt-5.6-sol")
            self.assertIsInstance(transport, OpenAIChatTransport)
            self.assertEqual(transport.name, "chat.completions")
        toggled = LLMService(CredentialType.openai, "key", use_responses_api=True)
        self.assertEqual(toggled._get_transport("gpt-5.6-sol").name, "responses")

    async def test_refused_tools_run_on_responses_with_their_reasoning(self) -> None:
        recorder = self._two_responses_rounds()

        result, calls, record_trace = await self._run_agent(recorder.client(), "gpt-5.6-sol")

        self.assertNotIn("error", result)
        self.assertEqual(result["text"], "Here are your runs.")
        self.assertEqual(calls, ["list_workflows"])
        self.assertEqual(recorder.paths, [CHAT_PATH, RESPONSES_PATH, RESPONSES_PATH])
        replay = recorder.bodies[2]["input"]
        self.assertEqual(
            [item["encrypted_content"] for item in replay if item.get("type") == "reasoning"],
            ["enc-1"],
        )
        self.assertEqual(
            [item["call_id"] for item in replay if item.get("type") == "function_call_output"],
            ["call_1"],
        )
        trace = record_trace.call_args.kwargs
        self.assertEqual(trace["request_type"], "chat.completions")
        self.assertEqual(trace["request"]["gateway_protocol"], "responses")
        self.assertEqual(trace["request"]["messages"][-2]["tool_calls"][0]["id"], "call_1")

    async def test_the_next_run_goes_to_responses_directly(self) -> None:
        await self._run_agent(self._two_responses_rounds().client(), "gpt-5.6-sol")
        recorder = self._two_responses_rounds()

        result, _calls, _trace = await self._run_agent(recorder.client(), "gpt-5.6-sol")

        self.assertEqual(result["text"], "Here are your runs.")
        self.assertEqual(recorder.paths, [RESPONSES_PATH, RESPONSES_PATH])

    async def test_a_route_learned_with_an_effort_leaves_requests_without_one_alone(self) -> None:
        agent = _Recorder(
            [_error(400, TOOLS_REFUSAL.replace("gpt-6.1-sol", "gpt-5.5"))],
            [
                httpx.Response(200, json=_responses_payload([REASONING, FUNCTION_CALL])),
                httpx.Response(200, json=_responses_payload([_text_item("Here are your runs.")])),
            ],
        )
        await self._run_agent(agent.client(), "gpt-5.5", reasoning_effort="medium")
        chat = _Recorder([httpx.Response(200, json=_chat_payload("hi"))], [])

        completion_caller(chat.client(), "gpt-5.5")(
            model="gpt-5.5", messages=MESSAGES, tools=[TOOL]
        )

        self.assertEqual(agent.paths, [CHAT_PATH, RESPONSES_PATH, RESPONSES_PATH])
        self.assertEqual(agent.bodies[1]["reasoning"], {"effort": "medium"})
        self.assertEqual(chat.paths, [CHAT_PATH])
        self.assertEqual(llm_chat_bridge._openai_responses_routes, {("gpt-5.5", True, True)})

    async def test_a_model_chat_completions_serves_keeps_todays_requests(self) -> None:
        recorder = _Recorder(
            [
                httpx.Response(200, json=_chat_payload(None, tool_call=True)),
                httpx.Response(200, json=_chat_payload("Here are your runs.")),
            ],
            [],
        )

        result, calls, record_trace = await self._run_agent(
            recorder.client(), "gpt-5.5", reasoning_effort="low"
        )

        self.assertEqual(result["text"], "Here are your runs.")
        self.assertEqual(calls, ["list_workflows"])
        self.assertEqual(recorder.paths, [CHAT_PATH, CHAT_PATH])
        self.assertEqual(recorder.bodies[0]["reasoning_effort"], "low")
        self.assertEqual(recorder.bodies[0]["tool_choice"], "auto")
        self.assertNotIn("gateway_protocol", record_trace.call_args.kwargs["request"])
        self.assertEqual(llm_chat_bridge._openai_responses_routes, set())

    async def test_other_hosts_get_the_refusal_untouched(self) -> None:
        recorder = _Recorder([_error(400, TOOLS_REFUSAL)], [])
        client = recorder.client("https://openrouter.ai/api/v1")

        with self.assertRaises(openai.BadRequestError):
            await self._run_agent(client, "openai/gpt-5.6-sol", CredentialType.custom)

        self.assertEqual(recorder.paths, ["/api/v1/chat/completions"])
        self.assertEqual(llm_chat_bridge._openai_responses_routes, set())

    async def test_a_resumed_agent_without_its_reasoning_items_still_runs(self) -> None:
        """A run paused for review can resume on another instance, where nothing was remembered."""
        recorder = _Recorder(
            [_error(400, TOOLS_REFUSAL)],
            [httpx.Response(200, json=_responses_payload([_text_item("Here are your runs.")]))],
        )

        result, _calls, _trace = await self._run_agent(
            recorder.client(), "gpt-5.6-sol", initial_messages=PAUSED_HISTORY
        )

        self.assertEqual(result["text"], "Here are your runs.")
        self.assertEqual(recorder.paths, [CHAT_PATH, RESPONSES_PATH])
        sent = recorder.bodies[1]["input"]
        self.assertFalse([item for item in sent if item.get("type") == "reasoning"])
        call = next(item for item in sent if item.get("type") == "function_call")
        self.assertEqual((call["call_id"], call["name"]), ("call_1", "list_workflows"))
        output = next(item for item in sent if item.get("type") == "function_call_output")
        self.assertEqual(output["call_id"], "call_1")

    def test_a_bridged_turn_joins_the_history_as_a_plain_message(self) -> None:
        recorder = _Recorder(
            [_error(400, TOOLS_REFUSAL)],
            [httpx.Response(200, json=_responses_payload([REASONING, FUNCTION_CALL]))],
        )
        transport = OpenAIChatTransport()
        history = transport.start(
            system_instruction="be brief",
            conversation_history=None,
            user_message="Show recent runs",
            image_input=None,
        )

        turn = transport.create(
            client=recorder.client(),
            model="gpt-5.6-sol",
            history=history,
            tools=[TOOL],
            opts=RequestOpts(),
        )
        transport.append_turn(history, turn)

        self.assertEqual(transport.dump(history), PAUSED_HISTORY[:3])
        self.assertTrue(all(isinstance(message, dict) for message in transport.dump(history)))


class TestLlmNodeOnOpenAI(_CleanRoutes, unittest.IsolatedAsyncioTestCase):
    async def _execute(self, client: Any, model: str) -> dict[str, Any]:
        service = LLMService(CredentialType.openai, "test-key")
        with (
            patch.object(service, "_get_client", return_value=(client, "OpenAI")),
            patch.object(service, "_record_trace"),
        ):
            return await service.execute(
                model=model, system_instruction="be brief", user_message="hi"
            )

    async def test_a_responses_only_model_answers(self) -> None:
        recorder = _Recorder(
            [_error(404, RESPONSES_ONLY)],
            [httpx.Response(200, json=_responses_payload([_text_item("hello")]))],
        )

        result = await self._execute(recorder.client(), "gpt-5.3-codex")

        self.assertEqual(result["text"], "hello")
        self.assertEqual(recorder.paths, [CHAT_PATH, RESPONSES_PATH])

    async def test_gpt_6_without_tools_stays_on_chat_completions(self) -> None:
        recorder = _Recorder([httpx.Response(200, json=_chat_payload("hello"))], [])

        result = await self._execute(recorder.client(), "gpt-6.1-sol")

        self.assertEqual(result["text"], "hello")
        self.assertEqual(recorder.paths, [CHAT_PATH])


if __name__ == "__main__":
    unittest.main()
