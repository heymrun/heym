"""Documentation evidence survives both chat surfaces and their model context limits."""

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import ai_assistant
from app.db.models import CredentialType
from app.services.doc_index import DocIndexService
from app.services.llm_trace import LLMTraceContext


class ChatDocumentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_search_results_reach_the_next_model_request_as_markdown(self) -> None:
        await self._assert_documentation_evidence("dashboard")

    async def test_docs_chat_preserves_large_results_and_the_current_page_context(self) -> None:
        await self._assert_documentation_evidence("documentation")

    async def _assert_documentation_evidence(
        self, surface: Literal["dashboard", "documentation"]
    ) -> None:
        call = SimpleNamespace(
            id="docs-1",
            type="function",
            function=SimpleNamespace(
                name="search_documentation", arguments=json.dumps({"query": "L0 recovery"})
            ),
        )
        client = MagicMock()
        client.base_url = "https://llm.example/v1"
        client.chat.completions.create.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                usage=None,
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="Found the playbook.", tool_calls=None)
                    )
                ],
                usage=None,
            ),
        ]
        credential = SimpleNamespace(
            id=uuid.uuid4(), type=CredentialType.custom, encrypted_config="test-config"
        )
        request = ai_assistant.DashboardChatRequest(
            credential_id=credential.id,
            model="qwen3.8-flash",
            message="Read the L0 recovery docs",
            conversation_id=uuid.uuid4(),
            chat_surface=surface,
            user_rules="The user is reading /docs/reference/playbook-0.",
        )
        http_request = MagicMock()
        http_request.is_disconnected = AsyncMock(return_value=False)

        def bind_model(
            *_args: Any, trace_context: LLMTraceContext, **_kwargs: Any
        ) -> tuple[Any, str, str, LLMTraceContext]:
            return client, "OpenAI", request.model, trace_context

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(5):
                path = root / "reference" / f"playbook-{index}.md"
                path.parent.mkdir(exist_ok=True)
                path.write_text(
                    f"# Incident Playbook {index} (L0)\n\n"
                    + "General background.\n\n" * 3000
                    + f"## Recovery\n\nRecovery evidence {index}: restore the snapshot.\n\n"
                    + "Other background.\n\n" * 3000,
                    encoding="utf-8",
                )
            with (
                patch.object(DocIndexService, "get_instance", return_value=DocIndexService(root)),
                patch.object(
                    ai_assistant, "get_credential_for_user", AsyncMock(return_value=credential)
                ),
                patch.object(ai_assistant, "decrypt_config", return_value={}),
                patch.object(ai_assistant, "resolve_model_binding", side_effect=bind_model),
                patch.object(
                    ai_assistant, "get_workflows_for_user_with_inputs", AsyncMock(return_value=[])
                ),
                patch.object(ai_assistant, "_load_agents_md_content", return_value=""),
                patch.object(ai_assistant, "build_credentials_prompt", AsyncMock(return_value="")),
                patch.object(
                    ai_assistant, "build_public_base_url", return_value="http://localhost"
                ),
                patch.object(ai_assistant, "record_llm_trace"),
                patch.object(ai_assistant, "record_run_history"),
            ):
                response = await ai_assistant.dashboard_chat_stream(
                    http_request=http_request,
                    request=request,
                    db=AsyncMock(),
                    current_user=SimpleNamespace(id=uuid.uuid4()),
                )
                events = [
                    event.decode() if isinstance(event, bytes) else event
                    async for event in response.body_iterator
                ]

        self.assertTrue(any('"type": "done"' in event for event in events))
        self.assertEqual(client.chat.completions.create.call_count, 2)
        messages = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertIn("/docs/reference/playbook-0", messages[0]["content"])
        tool_message = next(message for message in messages if message["role"] == "tool")
        self.assertLess(len(tool_message["content"]), 96_000)
        payload = json.loads(tool_message["content"])
        self.assertNotIn("summary", payload)
        self.assertEqual(len(payload["results"]), 5)
        for index, result in enumerate(payload["results"]):
            self.assertEqual(result["path"], f"/docs/reference/playbook-{index}")
            self.assertIn(f"Recovery evidence {index}: restore the snapshot.", result["content"])
