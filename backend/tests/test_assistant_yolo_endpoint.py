"""The workflow-assistant endpoint in YOLO mode: prompt, tool turn wiring, sessions."""

import json
import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.ai_assistant import AIAssistantRequest, workflow_assistant_stream
from app.db.models import CredentialType
from app.services.assistant_yolo import YOLO_TRACE_NODE_LABEL
from app.services.workflow_dsl_prompt import YOLO_PROTOCOL_PROMPT

WORKFLOW_ID = uuid.uuid4()
OTHER_ID = str(uuid.uuid4())


def _request(**overrides: Any) -> AIAssistantRequest:
    payload: dict[str, Any] = {
        "credential_id": uuid.uuid4(),
        "model": "gpt-test",
        "message": "Build an echo workflow",
        "current_workflow": {"id": str(WORKFLOW_ID), "name": "Echo", "nodes": [], "edges": []},
        "available_workflows": [{"id": OTHER_ID, "name": "Lookup"}],
        "conversation_id": uuid.uuid4(),
    }
    payload.update(overrides)
    return AIAssistantRequest(**payload)


async def _call(request: AIAssistantRequest) -> dict[str, Any]:
    """Run the endpoint with fakes and return what it handed to each stream."""
    captured: dict[str, Any] = {"turn": None, "stream_prompt": None, "session_ids": []}
    credential = SimpleNamespace(
        id=request.credential_id, type=CredentialType.openai, encrypted_config={}
    )
    user = SimpleNamespace(id=uuid.uuid4(), user_rules=None)
    http_request = MagicMock()
    http_request.is_disconnected = AsyncMock(return_value=False)

    async def fake_turn(**kwargs: Any):
        captured["turn"] = kwargs
        yield 'data: {"type": "done"}\n\n'

    async def fake_stream(_client: object, _model: str, system_prompt: str, *_a: Any, **_k: Any):
        captured["stream_prompt"] = system_prompt
        yield 'data: {"type": "done"}\n\n'

    def fake_client(_type: object, _config: object, *, session_id: str | None = None):
        captured["session_ids"].append(session_id)
        return object(), "OpenAI"

    with (
        patch("app.api.ai_assistant.get_credential_for_user", AsyncMock(return_value=credential)),
        patch("app.api.ai_assistant.decrypt_config", return_value={"api_key": "test"}),
        patch("app.api.ai_assistant.get_openai_client", side_effect=fake_client),
        patch(
            "app.api.ai_assistant.template_service.list_node_templates",
            AsyncMock(return_value=[]),
        ),
        patch("app.api.ai_assistant._load_installed_plugins", AsyncMock(return_value=[])),
        patch("app.api.ai_assistant.build_credentials_prompt", AsyncMock(return_value="")),
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
        captured["chunks"] = [chunk async for chunk in response.body_iterator]
    return captured


class WorkflowAssistantYoloEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_yolo_request_uses_the_tool_turn_with_the_protocol(self) -> None:
        captured = await _call(_request(yolo_mode=True))

        turn = captured["turn"]
        self.assertIsNotNone(turn)
        self.assertIsNone(captured["stream_prompt"])
        self.assertIn(YOLO_PROTOCOL_PROMPT, turn["system_prompt"])
        self.assertEqual(turn["workflow_names"], {OTHER_ID: "Lookup"})
        self.assertEqual(turn["editing_workflow_id"], str(WORKFLOW_ID))
        self.assertEqual(turn["trace_context"].node_label, YOLO_TRACE_NODE_LABEL)
        self.assertIsInstance(turn["cancel_event"], Event)
        self.assertIn('data: {"type": "done"}\n\n', captured["chunks"])

    async def test_non_yolo_request_keeps_the_streaming_path(self) -> None:
        captured = await _call(_request())

        self.assertIsNone(captured["turn"])
        self.assertNotIn(YOLO_PROTOCOL_PROMPT, captured["stream_prompt"])

    async def test_ask_mode_ignores_the_yolo_flag(self) -> None:
        captured = await _call(_request(yolo_mode=True, ask_mode=True))

        self.assertIsNone(captured["turn"])
        self.assertNotIn(YOLO_PROTOCOL_PROMPT, captured["stream_prompt"])

    async def test_other_workflow_runs_with_the_assistant_trigger_and_session(self) -> None:
        conversation_id = uuid.uuid4()
        captured = await _call(_request(yolo_mode=True, conversation_id=conversation_id))
        run_tool = AsyncMock(
            return_value=json.dumps({"status": "success", "outputs": {"answer": 42}})
        )

        with patch("app.api.ai_assistant.run_execute_workflow_tool", run_tool):
            outcome = await captured["turn"]["run_workflow"](OTHER_ID, {"text": "hi"})

        self.assertEqual(outcome.status, "success")
        self.assertIn("answer", outcome.llm_content)
        self.assertTrue(outcome.summary.startswith("Status: success"))
        kwargs = run_tool.call_args.kwargs
        self.assertEqual(kwargs["workflow_id_str"], OTHER_ID)
        self.assertEqual(kwargs["inputs"], {"text": "hi"})
        self.assertEqual(kwargs["trigger_source"], "ai_assistant")
        self.assertEqual(kwargs["llm_session_id"], str(conversation_id))
        self.assertIs(kwargs["cancel_event"], captured["turn"]["cancel_event"])


class WorkflowAssistantYoloSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_follow_up_turns_reuse_the_conversation_session(self) -> None:
        conversation_id = uuid.uuid4()

        first = await _call(_request(yolo_mode=True, conversation_id=conversation_id))
        follow_up = await _call(
            _request(
                yolo_mode=True,
                conversation_id=conversation_id,
                message='[YOLO run report] Attempt 1 of 5 finished with status "error".',
            )
        )

        self.assertEqual(first["session_ids"], [str(conversation_id)])
        self.assertEqual(follow_up["session_ids"], [str(conversation_id)])

    async def test_a_new_conversation_gets_a_new_session(self) -> None:
        first = await _call(_request(yolo_mode=True))
        second = await _call(_request(yolo_mode=True))

        self.assertNotEqual(first["session_ids"], second["session_ids"])

    async def test_missing_conversation_id_falls_back_to_a_generated_session(self) -> None:
        captured = await _call(_request(yolo_mode=True, conversation_id=None))

        (session_id,) = captured["session_ids"]
        self.assertTrue(session_id)
        uuid.UUID(session_id)
