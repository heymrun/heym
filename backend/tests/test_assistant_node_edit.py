"""Canvas AI Assistant turns focused on one node: prompt section and endpoint wiring."""

import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.ai_assistant import AIAssistantRequest, workflow_assistant_stream
from app.db.models import CredentialType
from app.services.assistant_node_edit import (
    NODE_EDIT_TRACE_NODE_LABEL,
    build_node_edit_prompt,
    find_workflow_node,
)
from app.services.assistant_yolo import YOLO_TRACE_NODE_LABEL
from app.services.workflow_dsl_prompt import YOLO_PROTOCOL_PROMPT

WORKFLOW: dict[str, Any] = {
    "id": str(uuid.uuid4()),
    "name": "LinkedIn watcher",
    "nodes": [
        {"id": "input-1", "type": "textInput", "data": {"label": "userInput"}},
        {"id": "cond-1", "type": "condition", "data": {"label": "checkLinkedIn"}},
    ],
    "edges": [{"id": "e1", "source": "input-1", "target": "cond-1"}],
}


class FindWorkflowNodeTests(unittest.TestCase):
    def test_finds_the_node_by_id(self) -> None:
        node = find_workflow_node(WORKFLOW, "cond-1")
        self.assertIsNotNone(node)
        self.assertEqual(node["type"], "condition")

    def test_returns_none_for_missing_inputs(self) -> None:
        self.assertIsNone(find_workflow_node(WORKFLOW, "missing"))
        self.assertIsNone(find_workflow_node(WORKFLOW, None))
        self.assertIsNone(find_workflow_node(None, "cond-1"))
        self.assertIsNone(find_workflow_node({"nodes": "broken"}, "cond-1"))


class BuildNodeEditPromptTests(unittest.TestCase):
    def test_agent_prompt_scopes_the_turn_to_the_node(self) -> None:
        prompt = build_node_edit_prompt(WORKFLOW, "cond-1", ask_mode=False)

        self.assertIn("## Node Edit Mode", prompt)
        self.assertIn("`checkLinkedIn` (type `condition`, id `cond-1`)", prompt)
        self.assertIn('{"nodes": [<the node>], "edges": []}', prompt)
        self.assertIn("override any instruction above", prompt)

    def test_ask_prompt_only_names_the_focus(self) -> None:
        prompt = build_node_edit_prompt(WORKFLOW, "cond-1", ask_mode=True)

        self.assertIn("## Node in Focus", prompt)
        self.assertIn("checkLinkedIn", prompt)
        self.assertNotIn("```json", prompt)

    def test_unknown_or_missing_node_adds_nothing(self) -> None:
        self.assertEqual(build_node_edit_prompt(WORKFLOW, "gone", ask_mode=False), "")
        self.assertEqual(build_node_edit_prompt(WORKFLOW, None, ask_mode=False), "")
        self.assertEqual(build_node_edit_prompt(None, "cond-1", ask_mode=True), "")


def _request(**overrides: Any) -> AIAssistantRequest:
    payload: dict[str, Any] = {
        "credential_id": uuid.uuid4(),
        "model": "gpt-test",
        "message": "Change this node to check follower engagement",
        "current_workflow": WORKFLOW,
        "conversation_id": uuid.uuid4(),
    }
    payload.update(overrides)
    return AIAssistantRequest(**payload)


async def _call(request: AIAssistantRequest) -> dict[str, Any]:
    """Run the endpoint with fakes and return the system prompt and trace of the turn."""
    captured: dict[str, Any] = {}
    credential = SimpleNamespace(
        id=request.credential_id, type=CredentialType.openai, encrypted_config={}
    )
    user = SimpleNamespace(id=uuid.uuid4(), user_rules=None)
    http_request = MagicMock()
    http_request.is_disconnected = AsyncMock(return_value=False)

    async def fake_turn(**kwargs: Any):
        captured["system_prompt"] = kwargs["system_prompt"]
        captured["trace_context"] = kwargs["trace_context"]
        yield 'data: {"type": "done"}\n\n'

    async def fake_stream(
        _client: object,
        _model: str,
        system_prompt: str,
        _messages: list[dict],
        _provider: str,
        trace_context: object,
        **_k: Any,
    ):
        captured["system_prompt"] = system_prompt
        captured["trace_context"] = trace_context
        yield 'data: {"type": "done"}\n\n'

    with (
        patch("app.api.ai_assistant.get_credential_for_user", AsyncMock(return_value=credential)),
        patch("app.api.ai_assistant.decrypt_config", return_value={"api_key": "test"}),
        patch("app.api.ai_assistant.get_openai_client", return_value=(object(), "OpenAI")),
        patch(
            "app.api.ai_assistant.template_service.list_node_templates",
            AsyncMock(return_value=[]),
        ),
        patch("app.api.ai_assistant._load_installed_plugins", AsyncMock(return_value=[])),
        patch("app.api.ai_assistant.build_credentials_prompt", AsyncMock(return_value="")),
        patch("app.api.ai_assistant.build_data_tables_prompt", AsyncMock(return_value="")),
        patch("app.api.ai_assistant.build_public_base_url", return_value="http://localhost"),
        patch("app.api.ai_assistant.stream_yolo_assistant_turn", fake_turn),
        patch("app.api.ai_assistant.stream_llm_response", fake_stream),
    ):
        response = await workflow_assistant_stream(
            http_request=http_request,
            request=request,
            current_user=user,
            db=AsyncMock(),
        )
        _ = [chunk async for chunk in response.body_iterator]
    return captured


class WorkflowAssistantNodeEditEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_target_node_adds_the_node_edit_section(self) -> None:
        captured = await _call(_request(target_node_id="cond-1"))

        self.assertIn("## Node Edit Mode", captured["system_prompt"])
        self.assertEqual(captured["trace_context"].node_label, NODE_EDIT_TRACE_NODE_LABEL)

    async def test_node_edit_rules_follow_the_yolo_protocol(self) -> None:
        captured = await _call(_request(target_node_id="cond-1", yolo_mode=True))

        prompt = captured["system_prompt"]
        self.assertGreater(prompt.index("## Node Edit Mode"), prompt.index(YOLO_PROTOCOL_PROMPT))
        self.assertEqual(captured["trace_context"].node_label, YOLO_TRACE_NODE_LABEL)

    async def test_ask_mode_gets_the_focus_hint_only(self) -> None:
        captured = await _call(_request(target_node_id="cond-1", ask_mode=True))

        self.assertIn("## Node in Focus", captured["system_prompt"])
        self.assertNotIn("## Node Edit Mode", captured["system_prompt"])
        self.assertEqual(captured["trace_context"].node_label, "AI Ask")

    async def test_without_a_target_the_prompt_is_unchanged(self) -> None:
        captured = await _call(_request())

        self.assertNotIn("## Node Edit Mode", captured["system_prompt"])
        self.assertEqual(captured["trace_context"].node_label, "AI Builder")

    async def test_unknown_target_falls_back_to_a_whole_workflow_turn(self) -> None:
        captured = await _call(_request(target_node_id="deleted-node"))

        self.assertNotIn("## Node Edit Mode", captured["system_prompt"])
        self.assertEqual(captured["trace_context"].node_label, "AI Builder")


if __name__ == "__main__":
    unittest.main()
