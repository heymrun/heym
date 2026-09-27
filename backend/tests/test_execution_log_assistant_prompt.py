import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.ai_assistant import (
    EXECUTION_LOG_NODE_OUTPUT_MAX_CHARS,
    EXECUTION_LOG_TOTAL_MAX_CHARS,
    AIAssistantRequest,
    _append_execution_log_to_prompt,
    _prepare_execution_log_for_prompt,
    workflow_assistant_stream,
)
from app.db.models import CredentialType


class ExecutionLogAssistantPromptTests(unittest.TestCase):
    def test_append_execution_log_to_prompt_returns_unchanged_when_missing(self) -> None:
        base = "Base system prompt"
        self.assertEqual(_append_execution_log_to_prompt(base, None), base)
        self.assertEqual(_append_execution_log_to_prompt(base, {}), base)
        self.assertEqual(_append_execution_log_to_prompt(base, {"node_results": []}), base)

    def test_append_execution_log_to_prompt_includes_console_log_message(self) -> None:
        execution_log = {
            "execution_status": "error",
            "execution_time_ms": 42.5,
            "final_outputs": None,
            "node_results": [
                {
                    "node_id": "n1",
                    "node_label": "logEntry",
                    "node_type": "consoleLog",
                    "status": "success",
                    "execution_time_ms": 1.2,
                    "output": {"logMessage": "upstream failed"},
                    "error": None,
                }
            ],
        }

        prompt = _append_execution_log_to_prompt("Base prompt", execution_log)

        self.assertIn("## Latest Workflow Execution Log", prompt)
        self.assertIn("upstream failed", prompt)
        self.assertIn('"node_type": "consoleLog"', prompt)
        self.assertIn("Do not invent node results", prompt)

    def test_prepare_execution_log_for_prompt_truncates_large_node_output(self) -> None:
        large_output = {"text": "x" * (EXECUTION_LOG_NODE_OUTPUT_MAX_CHARS + 500)}
        prepared = _prepare_execution_log_for_prompt(
            {
                "execution_status": "success",
                "node_results": [
                    {
                        "node_id": "n1",
                        "node_label": "agent",
                        "node_type": "agent",
                        "status": "success",
                        "execution_time_ms": 1.0,
                        "output": large_output,
                        "error": None,
                    }
                ],
            }
        )

        serialized = prepared["node_results"][0]["output"]
        self.assertIsInstance(serialized, str)
        self.assertLessEqual(len(serialized), EXECUTION_LOG_NODE_OUTPUT_MAX_CHARS)
        self.assertTrue(str(serialized).endswith("...[truncated]"))

    def test_append_execution_log_to_prompt_truncates_total_payload(self) -> None:
        execution_log = {
            "execution_status": "success",
            "execution_time_ms": 10.0,
            "final_outputs": None,
            "node_results": [
                {
                    "node_id": f"n{i}",
                    "node_label": f"node-{i}",
                    "node_type": "set",
                    "status": "success",
                    "execution_time_ms": 1.0,
                    "output": {"text": "y" * 1500},
                    "error": None,
                }
                for i in range(20)
            ],
        }

        prompt = _append_execution_log_to_prompt("Base prompt", execution_log)
        json_block = prompt.split("```json\n", 1)[1].rsplit("\n```", 1)[0]

        self.assertLessEqual(len(json_block), EXECUTION_LOG_TOTAL_MAX_CHARS)
        self.assertTrue(json_block.endswith("...[truncated]"))


class WorkflowAssistantStreamExecutionLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_workflow_assistant_stream_appends_execution_log_to_system_prompt(self) -> None:
        credential_id = uuid.uuid4()
        user = SimpleNamespace(id=uuid.uuid4(), user_rules=None)
        credential = SimpleNamespace(
            id=credential_id,
            type=CredentialType.openai,
            encrypted_config={},
        )
        captured: dict[str, str] = {}

        async def fake_stream_llm_response(
            _client: object,
            _model: str,
            system_prompt: str,
            _messages: object,
            _provider: str,
            _trace_context: object,
            **_kwargs: object,
        ):
            captured["system_prompt"] = system_prompt
            yield 'data: {"type": "done"}\n\n'

        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=credential),
            ),
            patch("app.api.ai_assistant.decrypt_config", return_value={"api_key": "test"}),
            patch("app.api.ai_assistant.get_openai_client", return_value=(object(), "openai")),
            patch(
                "app.api.ai_assistant.template_service.list_node_templates",
                AsyncMock(return_value=[]),
            ),
            patch("app.api.ai_assistant.stream_llm_response", fake_stream_llm_response),
        ):
            response = await workflow_assistant_stream(
                http_request=MagicMock(),
                request=AIAssistantRequest(
                    credential_id=credential_id,
                    model="gpt-test",
                    message="what failed?",
                    ask_mode=True,
                    execution_log={
                        "execution_status": "error",
                        "execution_time_ms": 12.3,
                        "final_outputs": None,
                        "node_results": [
                            {
                                "node_id": "n1",
                                "node_label": "http",
                                "node_type": "http",
                                "status": "error",
                                "execution_time_ms": 12.3,
                                "output": {},
                                "error": "timeout",
                            }
                        ],
                    },
                ),
                current_user=user,
                db=AsyncMock(),
            )

            stream = response.body_iterator
            async for chunk in stream:
                if chunk == 'data: {"type": "done"}\n\n':
                    break

        self.assertIn("## Latest Workflow Execution Log", captured["system_prompt"])
        self.assertIn('"error": "timeout"', captured["system_prompt"])
