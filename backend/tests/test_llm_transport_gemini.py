"""Gemini generateContent transport: the only endpoint OpenCode serves Gemini on."""

import json
import unittest
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from app.models.schemas import CredentialType
from app.services.llm_service import LLMService
from app.services.llm_trace import LLMTraceContext
from app.services.llm_transport import ModelProtocolError, RequestOpts, ToolResult, TurnResult
from app.services.llm_transport_gemini import GeminiHistory, GeminiTransport

MODEL = "gemini-4-argon-contributor"
GATEWAY_V1 = "https://opencode.ai/inference/go/v1"
ENDPOINT = f"https://opencode.ai/inference/go/google/v1beta/models/{MODEL}:generateContent"
TOOL = {
    "type": "function",
    "function": {
        "name": "call_sub_workflow",
        "description": "Run a workflow",
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "enum": ["a"]},
                "inputs": {"type": "object", "additionalProperties": False, "default": {}},
            },
            "required": ["workflow_id"],
            "additionalProperties": False,
            "$schema": "http://json-schema.org/draft-07/schema#",
        },
    },
}


def _payload(parts: list[dict[str, Any]], **usage: int) -> dict[str, Any]:
    return {
        "candidates": [
            {"index": 0, "finishReason": "STOP", "content": {"role": "model", "parts": parts}}
        ],
        "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 6, **usage},
    }


def _client(payload: dict[str, Any], base_url: str = GATEWAY_V1) -> MagicMock:
    client = MagicMock()
    client.base_url = httpx.URL(base_url + "/")
    client.post.return_value.json.return_value = payload
    return client


def _status(message: str, status: int) -> Exception:
    error = Exception(message)
    error.status_code = status
    return error


class TestStart(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = GeminiTransport()

    def test_system_prompt_is_kept_out_of_the_contents(self) -> None:
        history = self.transport.start(
            system_instruction="be brief",
            conversation_history=[{"role": "assistant", "content": "earlier"}],
            user_message="now",
            image_input=None,
        )
        self.assertEqual(history.system, "be brief")
        self.assertEqual(
            history.contents,
            [
                {"role": "model", "parts": [{"text": "earlier"}]},
                {"role": "user", "parts": [{"text": "now"}]},
            ],
        )

    def test_a_data_uri_image_becomes_inline_data(self) -> None:
        history = self.transport.start(
            system_instruction=None,
            conversation_history=None,
            user_message="what is this",
            image_input="data:image/png;base64,AAAA",
        )
        self.assertEqual(
            history.contents[-1]["parts"],
            [{"text": "what is this"}, {"inlineData": {"mimeType": "image/png", "data": "AAAA"}}],
        )

    def test_a_remote_image_becomes_a_file_uri(self) -> None:
        history = self.transport.start(
            system_instruction=None,
            conversation_history=None,
            user_message="what is this",
            image_input="https://example.com/a.png",
        )
        self.assertEqual(
            history.contents[-1]["parts"][1],
            {"fileData": {"mimeType": "image/png", "fileUri": "https://example.com/a.png"}},
        )


class TestBuildKwargs(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = GeminiTransport()
        self.history = self.transport.start(
            system_instruction="sys", conversation_history=None, user_message="hi", image_input=None
        )

    def _build(self, tools: Any = None, **opts: Any) -> dict[str, Any]:
        return self.transport.build_kwargs(
            model=MODEL, history=self.history, tools=tools, opts=RequestOpts(**opts)
        )

    def test_the_model_is_not_a_body_field(self) -> None:
        self.assertNotIn("model", self._build())

    def test_system_and_contents(self) -> None:
        body = self._build()
        self.assertEqual(body["systemInstruction"], {"parts": [{"text": "sys"}]})
        self.assertEqual(body["contents"], self.history.contents)

    def test_declarations_drop_what_gemini_does_not_know(self) -> None:
        body = self._build(tools=[TOOL])
        declaration = body["tools"][0]["functionDeclarations"][0]
        self.assertEqual(declaration["name"], "call_sub_workflow")
        parameters = declaration["parameters"]
        self.assertNotIn("additionalProperties", parameters)
        self.assertNotIn("$schema", parameters)
        self.assertNotIn("additionalProperties", parameters["properties"]["inputs"])
        self.assertNotIn("default", parameters["properties"]["inputs"])
        self.assertEqual(parameters["properties"]["workflow_id"]["enum"], ["a"])
        self.assertEqual(parameters["required"], ["workflow_id"])
        self.assertIn("additionalProperties", TOOL["function"]["parameters"])

    def test_tool_choice_vocabulary_is_translated(self) -> None:
        def mode(choice: str | None) -> str:
            return self._build([TOOL], tool_choice=choice)["toolConfig"]["functionCallingConfig"][
                "mode"
            ]

        self.assertEqual(mode(None), "AUTO")
        self.assertEqual(mode("none"), "NONE")
        self.assertEqual(mode("required"), "ANY")

    def test_no_tools_means_no_tool_keys(self) -> None:
        body = self._build()
        self.assertNotIn("tools", body)
        self.assertNotIn("toolConfig", body)

    def test_generation_config(self) -> None:
        body = self._build(temperature=3.5, max_tokens=77)
        self.assertEqual(body["generationConfig"], {"temperature": 2.0, "maxOutputTokens": 77})
        self.assertNotIn("generationConfig", self._build())

    def test_json_modes_become_a_system_instruction(self) -> None:
        schema = {"type": "json_schema", "json_schema": {"schema": {"type": "object"}}}
        text = self._build(response_format=schema)["systemInstruction"]["parts"][0]["text"]
        self.assertTrue(text.startswith("sys"))
        self.assertIn("never the schema", text)
        self.assertNotIn(
            "responseMimeType", self._build(response_format=schema).get("generationConfig", {})
        )
        self.assertEqual(self.history.system, "sys")

    def test_extra_body_is_merged(self) -> None:
        self.assertEqual(self._build(extra_body={"safetySettings": []})["safetySettings"], [])


class TestCreate(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = GeminiTransport()
        self.history = self.transport.start(
            system_instruction=None, conversation_history=None, user_message="hi", image_input=None
        )

    def _create(self, client: Any, **opts: Any) -> TurnResult:
        return self.transport.create(
            client=client, model=MODEL, history=self.history, tools=None, opts=RequestOpts(**opts)
        )

    def test_posts_to_the_google_endpoint_of_the_gateway(self) -> None:
        client = _client(_payload([{"text": "pong"}]))
        self._create(client)
        args, kwargs = client.post.call_args
        self.assertEqual(args[0], ENDPOINT)
        self.assertNotIn("model", kwargs["body"])

    def test_the_zen_base_url_still_reaches_the_inference_endpoint(self) -> None:
        client = _client(_payload([{"text": "pong"}]), "https://opencode.ai/zen/go/v1")
        self._create(client)
        self.assertEqual(client.post.call_args.args[0], ENDPOINT)

    def test_text_and_usage_are_parsed_with_thinking_counted_as_output(self) -> None:
        client = _client(
            _payload([{"text": "pong", "thoughtSignature": "sig"}], thoughtsTokenCount=4)
        )
        turn = self._create(client)
        self.assertEqual(turn.text, "pong")
        self.assertEqual(turn.tool_calls, [])
        self.assertEqual(
            (turn.prompt_tokens, turn.completion_tokens, turn.total_tokens), (11, 10, 21)
        )
        self.assertEqual(turn.finish_reason, "STOP")

    def test_function_calls_become_tool_calls_and_keep_their_signature(self) -> None:
        parts = [
            {
                "thoughtSignature": "sig-1",
                "functionCall": {
                    "id": "call_1",
                    "name": "call_sub_workflow",
                    "args": {"workflow_id": "a"},
                },
            }
        ]
        turn = self._create(_client(_payload(parts)))
        self.assertEqual(len(turn.tool_calls), 1)
        call = turn.tool_calls[0]
        self.assertEqual((call.id, call.name), ("call_1", "call_sub_workflow"))
        self.assertEqual(json.loads(call.arguments), {"workflow_id": "a"})
        self.assertEqual(turn.raw_items[0]["thoughtSignature"], "sig-1")

    def test_a_call_without_an_id_gets_one_that_the_history_keeps(self) -> None:
        turn = self._create(_client(_payload([{"functionCall": {"name": "t", "args": {}}}])))
        self.assertTrue(turn.tool_calls[0].id)
        self.assertEqual(turn.raw_items[0]["functionCall"]["id"], turn.tool_calls[0].id)

    def test_a_blocked_request_is_an_error_with_the_reason(self) -> None:
        client = _client({"promptFeedback": {"blockReason": "SAFETY"}})
        with self.assertRaises(ValueError) as ctx:
            self._create(client)
        self.assertIn("SAFETY", str(ctx.exception))

    def test_json_mode_strips_a_wrapping_code_fence(self) -> None:
        client = _client(_payload([{"text": '```json\n{"a": 1}\n```'}]))
        turn = self._create(client, response_format={"type": "json_object"})
        self.assertEqual(turn.text, '{"a": 1}')

    def test_protocol_unsupported_names_the_way_out(self) -> None:
        error = _status('400 {"error":{"type":"ModelProtocolUnsupported"}}', 400)
        client = MagicMock()
        client.base_url = httpx.URL(GATEWAY_V1 + "/")
        client.post.side_effect = error
        with self.assertRaises(ModelProtocolError) as ctx:
            self._create(client)
        self.assertIn("Google", str(ctx.exception))

    def test_other_errors_pass_through_untouched(self) -> None:
        error = _status("rate limited", 429)
        client = MagicMock()
        client.base_url = httpx.URL(GATEWAY_V1 + "/")
        client.post.side_effect = error
        with self.assertRaises(Exception) as ctx:
            self._create(client)
        self.assertIs(ctx.exception, error)


class TestHistory(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = GeminiTransport()
        self.history = self.transport.start(
            system_instruction="sys", conversation_history=None, user_message="hi", image_input=None
        )
        self.parts = [
            {"thoughtSignature": "sig-1", "functionCall": {"id": "c1", "name": "a", "args": {}}},
            {"functionCall": {"id": "c2", "name": "b", "args": {}}},
        ]

    def test_the_model_turn_is_replayed_verbatim(self) -> None:
        self.transport.append_turn(
            self.history, TurnResult(text="", tool_calls=[], raw_items=self.parts)
        )
        self.assertEqual(self.history.contents[-1], {"role": "model", "parts": self.parts})

    def test_results_for_one_turn_share_one_user_content_and_carry_the_function_name(self) -> None:
        self.transport.append_turn(
            self.history, TurnResult(text="", tool_calls=[], raw_items=self.parts)
        )
        self.transport.append_tool_results(self.history, [ToolResult(call_id="c1", output="one")])
        self.transport.append_tool_results(
            self.history, [ToolResult(call_id="c2", output='{"k": 2}')]
        )
        last = self.history.contents[-1]
        self.assertEqual(last["role"], "user")
        self.assertEqual(
            last["parts"],
            [
                {"functionResponse": {"id": "c1", "name": "a", "response": {"result": "one"}}},
                {"functionResponse": {"id": "c2", "name": "b", "response": {"k": 2}}},
            ],
        )
        self.assertEqual(len(self.history.contents), 3)
        self.assertTrue(self.transport.last_item_is_tool_result(self.history))

    def test_a_plain_user_turn_is_not_a_tool_result(self) -> None:
        self.assertFalse(self.transport.last_item_is_tool_result(self.history))
        self.transport.append_user(self.history, "again")
        self.assertEqual(self.history.contents[-1], {"role": "user", "parts": [{"text": "again"}]})

    def test_dump_and_load_round_trip_with_a_refreshed_system_prompt(self) -> None:
        loaded = self.transport.load(self.transport.dump(self.history), "new")
        self.assertEqual(loaded.system, "new")
        self.assertEqual(loaded.contents, self.history.contents)
        self.assertIsNot(loaded.contents, self.history.contents)

    def test_trace_request_redacts_images_and_lists_declarations(self) -> None:
        history = self.transport.start(
            system_instruction="sys",
            conversation_history=None,
            user_message="x",
            image_input="data:image/png;base64,AAAA",
        )
        trace = self.transport.trace_request(history, [TOOL])
        self.assertEqual(trace["system"], "sys")
        self.assertEqual(trace["contents"][0]["parts"][1]["inlineData"]["data"], "[base64]")
        self.assertEqual(trace["tools"][0]["name"], "call_sub_workflow")
        self.assertEqual(history.contents[0]["parts"][1]["inlineData"]["data"], "AAAA")

    def test_final_text_is_the_turn_text(self) -> None:
        self.assertEqual(self.transport.final_text(TurnResult(text="done", tool_calls=[])), "done")


class TestCompress(unittest.IsolatedAsyncioTestCase):
    async def test_history_is_left_alone(self) -> None:
        history = GeminiHistory(system="s", contents=[{"role": "user", "parts": [{"text": "x"}]}])
        out, info = await GeminiTransport().compress(
            history, model=MODEL, client=MagicMock(), context_limit_tokens=1
        )
        self.assertIs(out, history)
        self.assertIsNone(info)


class TestTransportChoice(unittest.TestCase):
    def _service(self, base_url: str, *, toggle: bool = False) -> LLMService:
        return LLMService(CredentialType.custom, "key", base_url, use_responses_api=toggle)

    def test_gemini_uses_generate_content_on_the_gateway(self) -> None:
        self.assertEqual(self._service(GATEWAY_V1)._get_transport(MODEL).name, "generateContent")

    def test_the_responses_toggle_cannot_redirect_it(self) -> None:
        self.assertEqual(
            self._service(GATEWAY_V1, toggle=True)._get_transport(MODEL).name, "generateContent"
        )

    def test_other_gateways_are_never_switched_by_model_name(self) -> None:
        self.assertEqual(
            self._service("https://openrouter.ai/api/v1")._get_transport(MODEL).name,
            "chat.completions",
        )

    def test_the_format_is_not_deferred_for_a_transport_with_no_format_field(self) -> None:
        self.assertFalse(GeminiTransport.carries_response_format)


class TestOpenCodeSessionHeader(unittest.IsolatedAsyncioTestCase):
    """A new LLM call path must carry the conversation id like every other."""

    async def test_tool_roundtrip_and_followups_keep_the_conversation_id(self) -> None:
        seen: list[tuple[str, str]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append((request.url.path, request.headers["x-opencode-session"]))
            if len(seen) == 1:
                parts: list[dict[str, Any]] = [
                    {
                        "thoughtSignature": "sig",
                        "functionCall": {"id": "c1", "name": "inspect", "args": {}},
                    }
                ]
            else:
                parts = [{"text": "done"}]
            return httpx.Response(200, json=_payload(parts))

        def transport(**_kwargs: Any) -> httpx.Client:
            client = httpx.Client(transport=httpx.MockTransport(respond))
            self.addCleanup(client.close)
            return client

        def service(session_id: str) -> LLMService:
            return LLMService(
                CredentialType.custom,
                "test-key",
                GATEWAY_V1,
                trace_context=LLMTraceContext(
                    user_id=uuid.uuid4(), credential_id=uuid.uuid4(), session_id=session_id
                ),
            )

        with (
            patch("app.services.openai_client.guard_http_url"),
            patch("app.services.openai_client.build_guarded_http_client", side_effect=transport),
            patch("app.services.llm_service.record_llm_trace"),
            patch("app.services.context_compressor.get_context_limit", return_value=100000),
        ):
            tool_executor = MagicMock(return_value={"result": "inspected"})
            result = await service("conversation-1").execute_with_tools(
                MODEL,
                None,
                "inspect this",
                [{"name": "inspect", "parameters": {"type": "object", "properties": {}}}],
                tool_executor,
            )
            tool_executor.assert_called_once()
            self.assertEqual(result["text"], "done")
            await service("conversation-1").execute(MODEL, None, "follow up")
            await service("conversation-2").execute(MODEL, None, "new conversation")

        expected_path = f"/inference/go/google/v1beta/models/{MODEL}:generateContent"
        self.assertEqual([path for path, _ in seen], [expected_path] * 4)
        self.assertEqual([s for _, s in seen], ["conversation-1"] * 3 + ["conversation-2"])
