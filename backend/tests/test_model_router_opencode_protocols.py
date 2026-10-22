"""A Model Router turn inherits the OpenCode protocol handling of the model it picks."""

import json
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.llm_chat_bridge import BridgedChatTransport, forget_remembered_turns
from app.services.llm_service import LLMService, TurnBinding
from app.services.llm_transport import ChatCompletionsTransport
from app.services.openai_client import create_openai_client

GATEWAY = "https://opencode.ai/inference/go/v1"
SESSION = "conversation-1"
INSPECT = {"name": "inspect", "parameters": {"type": "object", "properties": {}}}
SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
JSON_FORMAT = {"type": "json_schema", "json_schema": {"name": "answer", "schema": SCHEMA}}


def _gateway_client(handler: Any) -> Any:
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return create_openai_client(
        api_key="test-key", base_url=GATEWAY, session_id=SESSION, http_client=http_client
    )


def _binding(
    client: Any,
    model: str,
    *,
    credential_type: CredentialType = CredentialType.custom,
    base_url: str | None = GATEWAY,
) -> TurnBinding:
    return TurnBinding(
        client=client,
        provider="Custom",
        model=model,
        credential_id=uuid.uuid4(),
        router_credential_id=uuid.uuid4(),
        router_label="Auto Model",
        option_label=model,
        credential_type=credential_type,
        base_url=base_url,
    )


def _routed_service() -> LLMService:
    router = MagicMock()
    router.label = "Auto Model"
    router.credential_id = str(uuid.uuid4())
    return LLMService(CredentialType.model_router, "", router=router)


def _claude(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": content,
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 11, "output_tokens": 6},
    }


def _chat(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "kimi-k3",
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", **message}}
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


def _chat_tool_call() -> dict[str, Any]:
    return _chat(
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "inspect", "arguments": "{}"},
                }
            ],
        }
    )


class TestRoutedTransportChoice(unittest.TestCase):
    def setUp(self) -> None:
        self.service = _routed_service()
        self.default = ChatCompletionsTransport()

    def _transport(self, model: str, **kwargs: Any) -> Any:
        binding = _binding(MagicMock(), model, **kwargs)
        return self.service._transport_for(binding, self.default)

    def test_models_served_off_chat_completions_get_the_bridge_for_their_api(self) -> None:
        for model, protocol in (
            ("claude-haiku-5-5", "messages"),
            ("minimax-m2.7", "messages"),
            ("gpt-6-luna", "responses"),
            ("grok-4.7", "responses"),
            ("gemini-4-argon-contributor", "google"),
        ):
            transport = self._transport(model)
            self.assertIsInstance(transport, BridgedChatTransport, model)
            self.assertEqual(transport.protocol, protocol, model)

    def test_models_on_chat_completions_keep_the_runs_transport(self) -> None:
        for model in ("kimi-k3", "glm-5.3-flash", "deepseek-v4-pro", "minimax-m3"):
            self.assertIs(self._transport(model), self.default, model)

    def test_only_an_opencode_custom_credential_is_switched_by_model_name(self) -> None:
        other_gateway = self._transport("claude-haiku-5-5", base_url="https://openrouter.ai/api/v1")
        self.assertIs(other_gateway, self.default)
        openai = self._transport(
            "claude-haiku-5-5", credential_type=CredentialType.openai, base_url=None
        )
        self.assertIs(openai, self.default)

    def test_without_a_router_the_runs_transport_is_never_replaced(self) -> None:
        service = LLMService(CredentialType.custom, "key", GATEWAY)
        binding = _binding(MagicMock(), "claude-haiku-5-5")
        self.assertIs(service._transport_for(binding, self.default), self.default)

    def test_a_routed_run_always_starts_from_a_plain_message_list(self) -> None:
        self.assertEqual(self.service._get_transport("claude-haiku-5-5").name, "chat.completions")

    def test_the_bridge_keeps_the_natives_response_format_rule(self) -> None:
        self.assertFalse(BridgedChatTransport("messages").carries_response_format)
        self.assertFalse(BridgedChatTransport("google").carries_response_format)
        self.assertTrue(BridgedChatTransport("responses").carries_response_format)


class TestRoutedExecute(unittest.IsolatedAsyncioTestCase):
    """The failure that started this: Auto Model picked Haiku and the gateway refused Chat."""

    def setUp(self) -> None:
        forget_remembered_turns()
        self.addCleanup(forget_remembered_turns)

    async def test_a_routed_claude_turn_goes_to_messages_not_chat_completions(self) -> None:
        seen: list[tuple[str, str]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append((request.url.path, request.headers.get("x-opencode-session", "")))
            if request.url.path.endswith("/chat/completions"):
                return httpx.Response(
                    400, json={"error": {"message": "ModelProtocolUnsupported: use /messages"}}
                )
            return httpx.Response(200, json=_claude([{"type": "text", "text": "a plan"}]))

        service = _routed_service()
        binding = _binding(_gateway_client(respond), "claude-haiku-5-5")
        recorded: list[dict[str, Any]] = []
        with (
            patch.object(service, "_resolve_turn", return_value=binding),
            patch.object(service, "_record_trace", side_effect=lambda **kw: recorded.append(kw)),
        ):
            result = await service.execute("auto", "plan widgets", "A sales page")

        self.assertEqual(result["text"], "a plan")
        self.assertEqual(result["model"], "claude-haiku-5-5")
        self.assertEqual(seen, [("/inference/go/v1/messages", SESSION)])
        trace = recorded[-1]
        self.assertEqual(trace["request_type"], "chat.completions")
        self.assertEqual(trace["request"]["gateway_protocol"], "messages")
        self.assertIs(trace["binding"], binding)

    async def test_a_routed_chat_model_still_uses_chat_completions(self) -> None:
        paths: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, json=_chat({"content": "hello"}))

        service = _routed_service()
        binding = _binding(_gateway_client(respond), "kimi-k3")
        with (
            patch.object(service, "_resolve_turn", return_value=binding),
            patch.object(service, "_record_trace"),
        ):
            result = await service.execute("auto", None, "hi")

        self.assertEqual(result["text"], "hello")
        self.assertEqual(paths, ["/inference/go/v1/chat/completions"])


class TestRoutedToolLoop(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        forget_remembered_turns()
        self.addCleanup(forget_remembered_turns)
        patcher = patch("app.services.context_compressor.get_context_limit", return_value=128_000)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _run(
        self, service: LLMService, bindings: list[TurnBinding], **kwargs: Any
    ) -> tuple[dict[str, Any], MagicMock]:
        executor = MagicMock(return_value={"result": "inspected"})
        with (
            patch.object(service, "_resolve_turn", side_effect=bindings),
            patch.object(service, "_record_trace"),
        ):
            result = await service.execute_with_tools(
                "auto", "be brief", "inspect it", [INSPECT], executor, **kwargs
            )
        return result, executor

    async def test_the_loop_moves_from_claude_on_messages_to_gpt_on_responses(self) -> None:
        claude_bodies: list[dict[str, Any]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            claude_bodies.append(json.loads(request.content))
            return httpx.Response(
                200,
                json=_claude([{"type": "tool_use", "id": "tu_1", "name": "inspect", "input": {}}]),
            )

        responses_create = MagicMock(
            return_value=SimpleNamespace(
                output=[
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "all clear"}],
                    }
                ],
                usage=SimpleNamespace(input_tokens=5, output_tokens=2, total_tokens=7),
                status="completed",
            )
        )
        gpt_client = SimpleNamespace(
            base_url=GATEWAY, responses=SimpleNamespace(create=responses_create)
        )

        result, executor = await self._run(
            _routed_service(),
            [
                _binding(_gateway_client(respond), "claude-haiku-5-5"),
                _binding(gpt_client, "gpt-6-luna"),
            ],
        )

        executor.assert_called_once()
        self.assertEqual(result["text"], "all clear")
        self.assertEqual(len(claude_bodies), 1)
        self.assertEqual(claude_bodies[0]["system"], "be brief")
        items = responses_create.call_args.kwargs["input"]
        self.assertEqual(
            [item.get("type") for item in items],
            ["message", "message", "function_call", "function_call_output"],
        )
        self.assertEqual(items[2]["call_id"], "tu_1")
        self.assertEqual(items[3]["call_id"], "tu_1")
        self.assertIn("inspected", items[3]["output"])

    async def test_a_chat_model_after_claude_reads_the_same_history(self) -> None:
        chat_bodies: list[dict[str, Any]] = []

        def claude(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_claude([{"type": "tool_use", "id": "tu_1", "name": "inspect", "input": {}}]),
            )

        def kimi(request: httpx.Request) -> httpx.Response:
            chat_bodies.append(json.loads(request.content))
            return httpx.Response(200, json=_chat({"content": "fine"}))

        result, _ = await self._run(
            _routed_service(),
            [
                _binding(_gateway_client(claude), "claude-haiku-5-5"),
                _binding(_gateway_client(kimi), "kimi-k3"),
            ],
        )

        self.assertEqual(result["text"], "fine")
        roles = [message["role"] for message in chat_bodies[0]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "tool"])
        self.assertEqual(chat_bodies[0]["messages"][2]["tool_calls"][0]["id"], "tu_1")

    async def test_a_gateway_model_defers_the_json_format_while_its_tools_run(self) -> None:
        bodies: list[dict[str, Any]] = []
        replies = [_chat_tool_call(), _chat({"content": '{"name": "Anna"}'})]

        def respond(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json=replies[len(bodies) - 1])

        client = _gateway_client(respond)
        result, _ = await self._run(
            _routed_service(),
            [_binding(client, "kimi-k3"), _binding(client, "kimi-k3")],
            response_format=JSON_FORMAT,
            repair_json_output=True,
        )

        self.assertEqual(result["text"], '{"name": "Anna"}')
        self.assertTrue(all("response_format" not in body for body in bodies))

    async def test_a_first_party_openai_turn_keeps_the_json_format(self) -> None:
        bodies: list[dict[str, Any]] = []
        replies = [_chat_tool_call(), _chat({"content": '{"name": "Anna"}'})]

        def respond(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json=replies[len(bodies) - 1])

        client = _gateway_client(respond)
        openai = {"credential_type": CredentialType.openai, "base_url": None}
        await self._run(
            _routed_service(),
            [_binding(client, "gpt-4o", **openai), _binding(client, "gpt-4o", **openai)],
            response_format=JSON_FORMAT,
            repair_json_output=True,
        )

        self.assertTrue(all(body.get("response_format") for body in bodies))

    async def test_a_claude_turn_keeps_the_json_contract_in_system_on_every_turn(self) -> None:
        bodies: list[dict[str, Any]] = []
        replies = [
            _claude([{"type": "tool_use", "id": "tu_1", "name": "inspect", "input": {}}]),
            _claude([{"type": "text", "text": '{"name": "Anna"}'}]),
        ]

        def respond(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json=replies[len(bodies) - 1])

        client = _gateway_client(respond)
        result, _ = await self._run(
            _routed_service(),
            [_binding(client, "claude-haiku-5-5"), _binding(client, "claude-haiku-5-5")],
            response_format=JSON_FORMAT,
            repair_json_output=True,
        )

        self.assertEqual(result["text"], '{"name": "Anna"}')
        self.assertEqual(len(bodies), 2)
        self.assertEqual(len({body["system"] for body in bodies}), 1)
        self.assertIn("JSON", bodies[0]["system"])


if __name__ == "__main__":
    unittest.main()
