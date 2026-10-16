"""A node that asked for JSON gets a repair turn when the reply is not what it asked for."""

import json
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.json_output import MAX_OUTPUT_REPAIRS
from app.services.llm_service import LLMService

SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
    "required": ["name", "age"],
}
RESPONSE_FORMAT = {"type": "json_schema", "json_schema": {"name": "output", "schema": SCHEMA}}
GOOD = '{"name": "Anna", "age": 31}'
BROKEN = 'Sure! Here is the JSON: {"name": "Anna", "age": '


def _reply(content: str, *, tool_calls: list[Any] | None = None, tokens: int = 10) -> MagicMock:
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "tool_calls" if tool_calls else "stop"
    choice.model_dump.return_value = {"message": {"content": content}}
    response = MagicMock()
    response.choices = [choice]
    response.usage.prompt_tokens = tokens
    response.usage.completion_tokens = 2
    response.usage.total_tokens = tokens + 2
    return response


def _tool_call(call_id: str = "call-1") -> MagicMock:
    call = MagicMock()
    call.id = call_id
    call.function.name = "lookup"
    call.function.arguments = "{}"
    return call


def _service(replies: list[Any]) -> tuple[LLMService, MagicMock]:
    client = MagicMock()
    client.base_url = "https://api.example.test/v1"
    client.chat.completions.create.side_effect = replies
    service = LLMService(CredentialType.custom, "key", "https://api.example.test/v1")
    return service, client


class TestExecuteRepair(unittest.IsolatedAsyncioTestCase):
    async def _run(self, replies: list[Any], **kwargs: Any) -> tuple[dict[str, Any], MagicMock]:
        service, client = _service(replies)
        with patch.object(service, "_get_client", return_value=(client, "Custom")):
            result = await service.execute(
                model="m",
                system_instruction="extract",
                user_message="Anna is 31",
                response_format=RESPONSE_FORMAT,
                **kwargs,
            )
        return result, client

    async def test_a_broken_reply_is_repaired_in_the_same_conversation(self) -> None:
        result, client = await self._run([_reply(BROKEN), _reply(GOOD)], repair_json_output=True)

        self.assertEqual(result["text"], GOOD)
        self.assertEqual(client.chat.completions.create.call_count, 2)
        second = client.chat.completions.create.call_args_list[1].kwargs["messages"]
        self.assertEqual(second[-2], {"role": "assistant", "content": BROKEN})
        self.assertEqual(second[-1]["role"], "user")
        self.assertIn("not valid JSON", second[-1]["content"])
        self.assertNotIn("tool_calls", second[-2])

    async def test_usage_adds_up_over_the_repair_turns(self) -> None:
        result, _ = await self._run(
            [_reply(BROKEN, tokens=10), _reply(GOOD, tokens=30)], repair_json_output=True
        )
        self.assertEqual(result["usage"]["prompt_tokens"], 40)
        self.assertEqual(result["usage"]["completion_tokens"], 4)
        self.assertEqual(result["usage"]["total_tokens"], 44)

    async def test_a_fenced_reply_is_unwrapped_without_a_second_call(self) -> None:
        result, client = await self._run([_reply(f"```json\n{GOOD}\n```")], repair_json_output=True)
        self.assertEqual(result["text"], GOOD)
        self.assertEqual(client.chat.completions.create.call_count, 1)

    async def test_a_reply_missing_a_required_field_is_repaired(self) -> None:
        result, client = await self._run(
            [_reply('{"name": "Anna"}'), _reply(GOOD)], repair_json_output=True
        )
        self.assertEqual(result["text"], GOOD)
        second = client.chat.completions.create.call_args_list[1].kwargs["messages"]
        self.assertIn("age", second[-1]["content"])

    async def test_repairs_stop_at_the_budget_and_the_last_reply_comes_back(self) -> None:
        replies = [_reply(BROKEN)] * (MAX_OUTPUT_REPAIRS + 1)
        result, client = await self._run(replies, repair_json_output=True)
        self.assertEqual(client.chat.completions.create.call_count, MAX_OUTPUT_REPAIRS + 1)
        self.assertEqual(result["text"], BROKEN)

    async def test_a_failing_repair_call_keeps_the_first_reply(self) -> None:
        result, client = await self._run(
            [_reply(BROKEN), RuntimeError("provider down")], repair_json_output=True
        )
        self.assertEqual(result["text"], BROKEN)
        self.assertEqual(client.chat.completions.create.call_count, 2)

    async def test_nothing_is_repaired_unless_the_node_asked(self) -> None:
        result, client = await self._run([_reply(BROKEN)])
        self.assertEqual(result["text"], BROKEN)
        self.assertEqual(client.chat.completions.create.call_count, 1)

    async def test_nothing_is_repaired_without_a_json_format(self) -> None:
        service, client = _service([_reply("just prose")])
        with patch.object(service, "_get_client", return_value=(client, "Custom")):
            result = await service.execute(
                model="m", system_instruction=None, user_message="hi", repair_json_output=True
            )
        self.assertEqual(result["text"], "just prose")
        self.assertEqual(client.chat.completions.create.call_count, 1)

    async def test_the_result_lists_what_was_wrong_with_each_rejected_reply(self) -> None:
        result, _ = await self._run([_reply(BROKEN), _reply(GOOD)], repair_json_output=True)
        self.assertEqual(len(result["json_repairs"]), 1)
        self.assertIn("not valid JSON", result["json_repairs"][0])

    async def test_a_clean_reply_carries_no_repair_record(self) -> None:
        result, _ = await self._run([_reply(GOOD)], repair_json_output=True)
        self.assertNotIn("json_repairs", result)

    async def test_the_trace_shows_the_repair_exchange(self) -> None:
        service, client = _service([_reply(BROKEN), _reply(GOOD)])
        recorded: list[dict[str, Any]] = []
        with (
            patch.object(service, "_get_client", return_value=(client, "Custom")),
            patch.object(service, "_record_trace", side_effect=lambda **kw: recorded.append(kw)),
        ):
            await service.execute(
                model="m",
                system_instruction=None,
                user_message="Anna is 31",
                response_format=RESPONSE_FORMAT,
                repair_json_output=True,
            )
        self.assertEqual(len(recorded), 1)
        messages = recorded[0]["request"]["messages"]
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])
        self.assertEqual(messages[1]["content"], BROKEN)
        self.assertEqual(len(recorded[0]["response"]["json_repairs"]), 1)


class TestToolLoopRepair(unittest.IsolatedAsyncioTestCase):
    async def test_the_final_answer_is_repaired_without_rerunning_tools(self) -> None:
        service, client = _service(
            [_reply("", tool_calls=[_tool_call()]), _reply(BROKEN), _reply(GOOD)]
        )
        executor = MagicMock(return_value={"found": True})
        with (
            patch.object(service, "_get_client", return_value=(client, "Custom")),
            patch("app.services.context_compressor.get_context_limit", return_value=100000),
        ):
            result = await service.execute_with_tools(
                model="m",
                system_instruction="extract",
                user_message="Anna is 31",
                tools=[{"name": "lookup", "description": "d", "parameters": {}}],
                tool_executor=executor,
                response_format=RESPONSE_FORMAT,
                repair_json_output=True,
            )

        self.assertEqual(result["text"], GOOD)
        self.assertEqual(len(result["json_repairs"]), 1)
        self.assertEqual(executor.call_count, 1)
        self.assertEqual(client.chat.completions.create.call_count, 3)
        self.assertEqual(len(result["tool_calls"]), 1)
        last = client.chat.completions.create.call_args_list[2].kwargs["messages"]
        self.assertEqual(last[-2]["content"], BROKEN)
        self.assertIn("not valid JSON", last[-1]["content"])
        self.assertIn("tools", client.chat.completions.create.call_args_list[2].kwargs)
        json.loads(result["text"])

    async def test_a_reply_that_already_passes_costs_nothing_extra(self) -> None:
        service, client = _service([_reply(GOOD)])
        with (
            patch.object(service, "_get_client", return_value=(client, "Custom")),
            patch("app.services.context_compressor.get_context_limit", return_value=100000),
        ):
            result = await service.execute_with_tools(
                model="m",
                system_instruction=None,
                user_message="Anna is 31",
                tools=[{"name": "lookup", "description": "d", "parameters": {}}],
                tool_executor=MagicMock(),
                response_format=RESPONSE_FORMAT,
                repair_json_output=True,
            )
        self.assertEqual(result["text"], GOOD)
        self.assertEqual(client.chat.completions.create.call_count, 1)

    async def test_without_the_flag_a_broken_reply_is_returned_as_before(self) -> None:
        service, client = _service([_reply(BROKEN)])
        with (
            patch.object(service, "_get_client", return_value=(client, "Custom")),
            patch("app.services.context_compressor.get_context_limit", return_value=100000),
        ):
            result = await service.execute_with_tools(
                model="m",
                system_instruction=None,
                user_message="Anna is 31",
                tools=[{"name": "lookup", "description": "d", "parameters": {}}],
                tool_executor=MagicMock(),
                response_format=RESPONSE_FORMAT,
            )
        self.assertEqual(result["text"], BROKEN)
        self.assertEqual(client.chat.completions.create.call_count, 1)


class TestNodesAskForRepair(unittest.TestCase):
    """Only a node whose JSON output is switched on opts in to repair turns."""

    @staticmethod
    def _patches() -> tuple[Any, Any]:
        mock_cred = MagicMock()
        mock_cred.type = MagicMock()
        mock_cred.type.value = "openai"
        mock_cred.encrypted_config = b"enc"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_cred
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        return (
            patch("app.db.session.SessionLocal", return_value=mock_db),
            patch("app.services.encryption.decrypt_config", return_value={"api_key": "key"}),
        )

    def _llm_call(self, json_output: bool) -> dict[str, Any]:
        captured: list[dict[str, Any]] = []

        def fake_execute_llm(**kwargs: Any) -> Any:
            captured.append(kwargs)

            async def _coro() -> dict[str, Any]:
                return {"text": "{}", "model": kwargs["model"]}

            return _coro()

        from app.services.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.actor_user_id = __import__("uuid").uuid4()
        session_patch, decrypt_patch = self._patches()
        with (
            patch("app.services.llm_service.execute_llm", fake_execute_llm),
            session_patch,
            decrypt_patch,
        ):
            executor._execute_llm_node(
                credential_id="cred-1",
                node_id="llm-1",
                model="gpt-4o-mini",
                system_instruction=None,
                user_message="hello",
                temperature=0.7,
                reasoning_effort=None,
                max_tokens=None,
                json_output_enabled=json_output,
                json_output_schema=json.dumps(SCHEMA) if json_output else None,
                image_input=None,
            )
        return captured[0]

    def test_llm_node_with_json_output_asks_for_repair(self) -> None:
        self.assertTrue(self._llm_call(True)["repair_json_output"])

    def test_llm_node_without_json_output_does_not(self) -> None:
        self.assertFalse(self._llm_call(False).get("repair_json_output", False))

    def _agent_call(self, json_output: bool, with_tools: bool) -> dict[str, Any]:
        captured: list[dict[str, Any]] = []

        def fake(**kwargs: Any) -> Any:
            captured.append(kwargs)

            async def _coro() -> dict[str, Any]:
                return {"text": "{}", "model": kwargs["model"], "tool_calls": [], "usage": {}}

            return _coro()

        from app.services.workflow_executor import WorkflowExecutor

        data: dict[str, Any] = {
            "label": "agent",
            "credentialId": "cred-1",
            "model": "m",
            "userMessage": "hi",
            "jsonOutputEnabled": json_output,
            "jsonOutputSchema": json.dumps(SCHEMA) if json_output else "",
        }
        nodes = [{"id": "a1", "type": "agent", "data": data}]
        if with_tools:
            data["tools"] = [{"name": "t", "description": "d", "code": "def run(**kw): return 1"}]
        executor = WorkflowExecutor(nodes=nodes, edges=[])
        executor.actor_user_id = __import__("uuid").uuid4()
        session_patch, decrypt_patch = self._patches()
        with (
            patch("app.services.llm_service.execute_llm_with_tools", fake),
            patch("app.services.llm_service.execute_llm", fake),
            patch(
                "app.services.agent_memory_service.augment_system_instruction_with_memory",
                side_effect=lambda si, *a, **kw: si,
            ),
            session_patch,
            decrypt_patch,
        ):
            executor._execute_agent_node("a1", {}, data)
        return captured[0]

    def test_agent_with_tools_and_json_output_asks_for_repair(self) -> None:
        self.assertTrue(self._agent_call(True, True)["repair_json_output"])

    def test_agent_without_tools_and_json_output_asks_for_repair(self) -> None:
        self.assertTrue(self._agent_call(True, False)["repair_json_output"])

    def test_agent_without_json_output_does_not(self) -> None:
        self.assertFalse(self._agent_call(False, True).get("repair_json_output", False))


class TestFormatWaitsForTheFinalAnswerWhenToolsAreInPlay(unittest.IsolatedAsyncioTestCase):
    """glm-5.3-flash and mimo-v2.6-pro never call a tool when json_schema rides on the same
    request, and answer with an empty object instead. The format goes on the last turn only."""

    TOOLS = [{"name": "lookup", "description": "d", "parameters": {}}]

    async def _run(
        self,
        replies: list[Any],
        *,
        credential_type: CredentialType = CredentialType.custom,
        base_url: str | None = "https://api.example.test/v1",
        repair: bool = True,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], MagicMock]:
        client = MagicMock()
        client.base_url = "https://api.example.test/v1"
        client.chat.completions.create.side_effect = replies
        service = LLMService(credential_type, "key", base_url)
        with (
            patch.object(service, "_get_client", return_value=(client, "Custom")),
            patch("app.services.context_compressor.get_context_limit", return_value=100000),
        ):
            result = await service.execute_with_tools(
                model="m",
                system_instruction="extract",
                user_message="Anna is 31",
                tools=self.TOOLS if tools is None else tools,
                tool_executor=MagicMock(return_value={"found": True}),
                response_format=RESPONSE_FORMAT,
                repair_json_output=repair,
            )
        return result, client

    def _kwargs(self, client: MagicMock) -> list[dict[str, Any]]:
        return [call.kwargs for call in client.chat.completions.create.call_args_list]

    async def test_tool_turns_carry_no_response_format_on_a_custom_gateway(self) -> None:
        result, client = await self._run([_reply("", tool_calls=[_tool_call()]), _reply(GOOD)])
        calls = self._kwargs(client)
        self.assertNotIn("response_format", calls[0])
        self.assertNotIn("response_format", calls[1])
        self.assertEqual(result["text"], GOOD)

    async def test_the_repair_turn_brings_the_format_back_and_forbids_tools(self) -> None:
        _, client = await self._run(
            [_reply("", tool_calls=[_tool_call()]), _reply(BROKEN), _reply(GOOD)]
        )
        repair_call = self._kwargs(client)[2]
        self.assertEqual(repair_call["response_format"], RESPONSE_FORMAT)
        self.assertEqual(repair_call["tool_choice"], "none")
        self.assertEqual(self._kwargs(client)[1].get("tool_choice"), "auto")

    async def test_a_valid_final_answer_needs_no_format_turn(self) -> None:
        _, client = await self._run([_reply(GOOD)])
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertNotIn("response_format", self._kwargs(client)[0])

    async def test_openai_itself_keeps_the_format_on_every_turn(self) -> None:
        _, client = await self._run(
            [_reply("", tool_calls=[_tool_call()]), _reply(GOOD)],
            credential_type=CredentialType.openai,
            base_url=None,
        )
        for call in self._kwargs(client):
            self.assertEqual(call["response_format"], RESPONSE_FORMAT)

    async def test_an_openai_compatible_base_url_is_treated_like_a_gateway(self) -> None:
        _, client = await self._run(
            [_reply("", tool_calls=[_tool_call()]), _reply(GOOD)],
            credential_type=CredentialType.openai,
            base_url="https://gateway.example.test/v1",
        )
        self.assertNotIn("response_format", self._kwargs(client)[0])

    async def test_without_the_repair_flag_nothing_changes(self) -> None:
        _, client = await self._run([_reply(GOOD)], repair=False)
        self.assertEqual(self._kwargs(client)[0]["response_format"], RESPONSE_FORMAT)

    async def test_a_node_without_tools_keeps_the_format(self) -> None:
        _, client = await self._run([_reply(GOOD)], tools=[])
        self.assertEqual(self._kwargs(client)[0]["response_format"], RESPONSE_FORMAT)
