"""Documentation evidence survives the dashboard chat tool loop and its context limit."""

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import ai_assistant
from app.services.doc_index import DocIndexService


class ChatDocumentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_search_results_reach_the_next_model_request_as_markdown(self) -> None:
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
                patch.object(ai_assistant, "record_llm_trace"),
                patch.object(ai_assistant, "record_run_history"),
            ):
                events = [
                    event
                    async for event in ai_assistant.stream_dashboard_chat(
                        client,
                        "qwen3.8-flash",
                        "system",
                        [{"role": "user", "content": "Read the L0 recovery docs"}],
                        AsyncMock(),
                        SimpleNamespace(id=uuid.uuid4()),
                        "OpenAI",
                        "http://localhost",
                    )
                ]

        self.assertTrue(any('"type": "done"' in event for event in events))
        self.assertEqual(client.chat.completions.create.call_count, 2)
        messages = client.chat.completions.create.call_args.kwargs["messages"]
        tool_message = next(message for message in messages if message["role"] == "tool")
        self.assertLess(len(tool_message["content"]), 96_000)
        payload = json.loads(tool_message["content"])
        self.assertNotIn("summary", payload)
        self.assertEqual(len(payload["results"]), 5)
        for index, result in enumerate(payload["results"]):
            self.assertEqual(result["path"], f"/docs/reference/playbook-{index}")
            self.assertIn(f"Recovery evidence {index}: restore the snapshot.", result["content"])
