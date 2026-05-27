import json
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.ai_assistant import (
    DashboardChatRequest,
    FileAttachment,
    _append_date_to_user_messages,
    _build_user_message,
    _build_workflow_builder_user_message,
    _build_workflow_editor_user_message,
    _extract_generated_workflow_config,
    create_and_run_generated_workflow_tool,
    dashboard_chat_stream,
    edit_and_run_generated_workflow_tool,
    stream_dashboard_chat,
)
from app.db.models import CredentialType, WebhookBodyMode, WorkflowAuthType, WorkflowVersion
from app.services.llm_trace import LLMTraceContext


def _normalize_chunks(chunks: list[str | bytes]) -> list[str]:
    normalized: list[str] = []
    for chunk in chunks:
        normalized.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return normalized


class DashboardChatApiTests(unittest.IsolatedAsyncioTestCase):
    def test_append_date_to_user_messages_only_changes_llm_copy(self) -> None:
        messages = [
            {"role": "assistant", "content": "Earlier answer"},
            {"role": "user", "content": "What happened today?"},
        ]
        now = datetime(2026, 5, 3, 12, 30, tzinfo=timezone.utc)

        result = _append_date_to_user_messages(messages, now)

        self.assertEqual(messages[-1]["content"], "What happened today?")
        self.assertEqual(result[0], messages[0])
        self.assertEqual(
            result[1],
            {
                "role": "user",
                "content": "What happened today?\n\nDate: 2026-05-03T12:30:00+00:00",
            },
        )

    async def test_stream_dashboard_chat_sends_date_with_user_message_to_llm(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="Done", tool_calls=None))]
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = response

        with (
            patch("app.api.ai_assistant.record_run_history"),
            patch(
                "app.api.ai_assistant.get_configured_timezone",
                return_value=timezone.utc,
            ),
        ):
            chunks = _normalize_chunks(
                [
                    chunk
                    async for chunk in stream_dashboard_chat(
                        fake_client,
                        "gpt-4o-mini",
                        "system prompt",
                        [{"role": "user", "content": "What is the latest? "}],
                        AsyncMock(),
                        user,
                        "OpenAI",
                        "http://localhost",
                    )
                ]
            )

        # Filter out the new `context` SSE events for this assertion; they carry
        # token-usage metadata orthogonal to what this test verifies.
        non_context_chunks = [c for c in chunks if '"type": "context"' not in c]
        self.assertEqual(
            non_context_chunks,
            [
                'data: {"type": "content", "text": "Done"}\n\n',
                'data: {"type": "done"}\n\n',
            ],
        )
        sent_messages = fake_client.chat.completions.create.call_args.kwargs["messages"]
        sent_kwargs = fake_client.chat.completions.create.call_args.kwargs
        self.assertEqual(sent_kwargs["temperature"], 0.1)
        self.assertEqual(sent_messages[0], {"role": "system", "content": "system prompt"})
        self.assertIn("What is the latest?", sent_messages[1]["content"])
        self.assertRegex(
            sent_messages[1]["content"],
            r"\n\nDate: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$",
        )

    async def test_dashboard_chat_appends_doc_context_rules_and_datetime(self) -> None:
        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.type = CredentialType.openai
        credential.encrypted_config = "encrypted-config"

        current_user = MagicMock()
        current_user.id = uuid.uuid4()

        http_request = MagicMock()
        http_request.is_disconnected = AsyncMock(return_value=False)

        captured: dict[str, object] = {}

        async def fake_stream_dashboard_chat(
            _client: object,
            _model: str,
            system_prompt: str,
            messages: list[dict],
            _db: object,
            _user: object,
            _provider: str,
            _public_base_url: str,
            _trace_context: object,
            _cancel_event: object,
            _attachment: object = None,
            _selected_credential: object = None,
        ):
            captured["system_prompt"] = system_prompt
            captured["messages"] = messages
            captured["trace_context"] = _trace_context
            yield 'data: {"type":"done"}\n\n'

        request = DashboardChatRequest(
            credential_id=credential.id,
            model="gpt-4o-mini",
            message="What does this page explain?",
            conversation_history=[
                {"role": "assistant", "content": "Earlier answer"},
            ],
            chat_surface="documentation",
            user_rules=(
                "The user is currently reading the Heym documentation page: "
                "/docs/nodes/llm-node. Prioritize answers relevant to this page."
            ),
            client_local_datetime="4/10/2026, 10:15:00 AM",
        )

        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=credential),
            ),
            patch("app.api.ai_assistant.decrypt_config", return_value={"api_key": "test"}),
            patch(
                "app.api.ai_assistant.get_openai_client",
                return_value=(MagicMock(), "openai"),
            ),
            patch(
                "app.api.ai_assistant.get_workflows_for_user_with_inputs",
                AsyncMock(return_value=[]),
            ),
            patch("app.api.ai_assistant._load_agents_md_content", return_value="AGENTS context"),
            patch("app.api.ai_assistant.build_public_base_url", return_value="http://localhost"),
            patch(
                "app.api.ai_assistant.stream_dashboard_chat",
                side_effect=fake_stream_dashboard_chat,
            ),
        ):
            response = await dashboard_chat_stream(
                http_request=http_request,
                request=request,
                current_user=current_user,
                db=AsyncMock(),
            )
            chunks = _normalize_chunks([chunk async for chunk in response.body_iterator])

        self.assertEqual(chunks, ['data: {"type":"done"}\n\n'])
        self.assertIn("AGENTS context", captured["system_prompt"])
        self.assertIn(
            "User preferences / custom instructions (follow these when relevant):",
            captured["system_prompt"],
        )
        self.assertIn("/docs/nodes/llm-node", captured["system_prompt"])
        self.assertIn(
            "Current user local date and time: 4/10/2026, 10:15:00 AM",
            captured["system_prompt"],
        )
        self.assertIn("search the internet, load websites", captured["system_prompt"])
        self.assertIn("Research-before-create behavior", captured["system_prompt"])
        self.assertIn("first try to use available workflows", captured["system_prompt"])
        self.assertIn("Heym-only creation behavior", captured["system_prompt"])
        self.assertIn("Do not recommend alternative platforms", captured["system_prompt"])
        self.assertIn("AI Builder DSL generator", captured["system_prompt"])
        self.assertEqual(captured["trace_context"].node_label, "Documentation Chat")
        self.assertEqual(captured["trace_context"].source, "dashboard_chat")
        self.assertEqual(
            captured["messages"],
            [
                {"role": "assistant", "content": "Earlier answer"},
                {"role": "user", "content": "What does this page explain?"},
            ],
        )

    async def test_dashboard_chat_uses_dashboard_trace_label_by_default(self) -> None:
        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.type = CredentialType.openai
        credential.encrypted_config = "encrypted-config"

        current_user = MagicMock()
        current_user.id = uuid.uuid4()

        http_request = MagicMock()
        http_request.is_disconnected = AsyncMock(return_value=False)

        captured: dict[str, object] = {}

        async def fake_stream_dashboard_chat(
            _client: object,
            _model: str,
            _system_prompt: str,
            _messages: list[dict],
            _db: object,
            _user: object,
            _provider: str,
            _public_base_url: str,
            _trace_context: object,
            _cancel_event: object,
            _attachment: object = None,
            _selected_credential: object = None,
        ):
            captured["trace_context"] = _trace_context
            yield 'data: {"type":"done"}\n\n'

        request = DashboardChatRequest(
            credential_id=credential.id,
            model="gpt-4o-mini",
            message="Hello",
        )

        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=credential),
            ),
            patch("app.api.ai_assistant.decrypt_config", return_value={"api_key": "test"}),
            patch(
                "app.api.ai_assistant.get_openai_client",
                return_value=(MagicMock(), "openai"),
            ),
            patch(
                "app.api.ai_assistant.get_workflows_for_user_with_inputs",
                AsyncMock(return_value=[]),
            ),
            patch("app.api.ai_assistant._load_agents_md_content", return_value=""),
            patch("app.api.ai_assistant.build_public_base_url", return_value="http://localhost"),
            patch(
                "app.api.ai_assistant.stream_dashboard_chat",
                side_effect=fake_stream_dashboard_chat,
            ),
        ):
            response = await dashboard_chat_stream(
                http_request=http_request,
                request=request,
                current_user=current_user,
                db=AsyncMock(),
            )
            _ = [chunk async for chunk in response.body_iterator]

        self.assertEqual(captured["trace_context"].node_label, "Dashboard Chat")
        self.assertEqual(captured["trace_context"].source, "dashboard_chat")

    async def test_dashboard_chat_records_error_trace_with_label(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        trace_context = LLMTraceContext(
            user_id=user.id,
            credential_id=uuid.uuid4(),
            workflow_id=None,
            node_label="Dashboard Chat",
            source="dashboard_chat",
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = RuntimeError("model failed")

        with (
            patch("app.api.ai_assistant.record_llm_trace") as record_trace,
            patch("app.api.ai_assistant.record_run_history"),
        ):
            chunks = _normalize_chunks(
                [
                    chunk
                    async for chunk in stream_dashboard_chat(
                        fake_client,
                        "gpt-4o-mini",
                        "system prompt",
                        [{"role": "user", "content": "Hello"}],
                        AsyncMock(),
                        user,
                        "OpenAI",
                        "http://localhost",
                        trace_context,
                    )
                ]
            )

        self.assertEqual(chunks, ['data: {"type": "error", "message": "model failed"}\n\n'])
        record_trace.assert_called_once()
        trace_kwargs = record_trace.call_args.kwargs
        self.assertEqual(trace_kwargs["context"].node_label, "Dashboard Chat")
        self.assertEqual(trace_kwargs["context"].source, "dashboard_chat")
        self.assertEqual(trace_kwargs["error"], "model failed")

    async def test_dashboard_chat_keeps_only_latest_25_history_messages(self) -> None:
        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.type = CredentialType.openai
        credential.encrypted_config = "encrypted-config"

        current_user = MagicMock()
        current_user.id = uuid.uuid4()

        http_request = MagicMock()
        http_request.is_disconnected = AsyncMock(return_value=False)

        captured: dict[str, object] = {}

        async def fake_stream_dashboard_chat(
            _client: object,
            _model: str,
            _system_prompt: str,
            messages: list[dict],
            _db: object,
            _user: object,
            _provider: str,
            _public_base_url: str,
            _trace_context: object,
            _cancel_event: object,
            _attachment: object = None,
            _selected_credential: object = None,
        ):
            captured["messages"] = messages
            yield 'data: {"type":"done"}\n\n'

        history = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"msg-{index}"}
            for index in range(30)
        ]
        request = DashboardChatRequest(
            credential_id=credential.id,
            model="gpt-4o-mini",
            message="latest-question",
            conversation_history=history,
        )

        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=credential),
            ),
            patch("app.api.ai_assistant.decrypt_config", return_value={"api_key": "test"}),
            patch(
                "app.api.ai_assistant.get_openai_client",
                return_value=(MagicMock(), "openai"),
            ),
            patch(
                "app.api.ai_assistant.get_workflows_for_user_with_inputs",
                AsyncMock(return_value=[]),
            ),
            patch("app.api.ai_assistant._load_agents_md_content", return_value=""),
            patch("app.api.ai_assistant.build_public_base_url", return_value="http://localhost"),
            patch(
                "app.api.ai_assistant.stream_dashboard_chat",
                side_effect=fake_stream_dashboard_chat,
            ),
        ):
            response = await dashboard_chat_stream(
                http_request=http_request,
                request=request,
                current_user=current_user,
                db=AsyncMock(),
            )
            _ = [chunk async for chunk in response.body_iterator]

        messages = captured["messages"]
        self.assertEqual(len(messages), 26)
        self.assertEqual(messages[0]["content"], "msg-5")
        self.assertEqual(messages[-1], {"role": "user", "content": "latest-question"})

    async def test_dashboard_chat_forwards_step_events_to_sse_stream(self) -> None:
        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.type = CredentialType.openai
        credential.encrypted_config = "encrypted-config"

        current_user = MagicMock()
        current_user.id = uuid.uuid4()

        http_request = MagicMock()
        http_request.is_disconnected = AsyncMock(return_value=False)

        async def fake_stream_dashboard_chat(
            _client: object,
            _model: str,
            _system_prompt: str,
            _messages: list[dict],
            _db: object,
            _user: object,
            _provider: str,
            _public_base_url: str,
            _trace_context: object,
            _cancel_event: object,
            _attachment: object = None,
            _selected_credential: object = None,
        ):
            yield 'data: {"type":"step","label":"Searching documentation..."}\n\n'
            yield 'data: {"type":"done"}\n\n'

        request = DashboardChatRequest(
            credential_id=credential.id,
            model="gpt-4o-mini",
            message="Explain this page",
        )

        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=credential),
            ),
            patch("app.api.ai_assistant.decrypt_config", return_value={"api_key": "test"}),
            patch(
                "app.api.ai_assistant.get_openai_client",
                return_value=(MagicMock(), "openai"),
            ),
            patch(
                "app.api.ai_assistant.get_workflows_for_user_with_inputs",
                AsyncMock(return_value=[]),
            ),
            patch("app.api.ai_assistant._load_agents_md_content", return_value=""),
            patch("app.api.ai_assistant.build_public_base_url", return_value="http://localhost"),
            patch(
                "app.api.ai_assistant.stream_dashboard_chat",
                side_effect=fake_stream_dashboard_chat,
            ),
        ):
            response = await dashboard_chat_stream(
                http_request=http_request,
                request=request,
                current_user=current_user,
                db=AsyncMock(),
            )
            chunks = _normalize_chunks([chunk async for chunk in response.body_iterator])

        self.assertEqual(
            chunks,
            [
                'data: {"type":"step","label":"Searching documentation..."}\n\n',
                'data: {"type":"done"}\n\n',
            ],
        )


class DashboardChatWorkflowBuilderTests(unittest.IsolatedAsyncioTestCase):
    def test_extract_generated_workflow_config_from_json_block(self) -> None:
        content = """
Here is the workflow:
```json
{
  "name": "Daily Digest",
  "description": "Summarizes updates every morning.",
  "nodes": [{"id": "input", "type": "textInput", "data": {"label": "request"}}],
  "edges": [],
}
```
"""
        config = _extract_generated_workflow_config(content, "Create a daily digest")

        self.assertEqual(config["name"], "Daily Digest")
        self.assertEqual(config["description"], "Summarizes updates every morning.")
        self.assertEqual(config["nodes"][0]["id"], "input")
        self.assertEqual(config["edges"], [])

    async def test_create_and_run_generated_workflow_saves_and_executes(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        user.user_rules = None

        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.owner_id = user.id
        credential.type = CredentialType.openai

        builder_content = """
```json
{
  "name": "Echo Assistant",
  "description": "Echoes the incoming text through an LLM.",
  "nodes": [
    {
      "id": "input",
      "type": "textInput",
      "position": {"x": 0, "y": 0},
      "data": {"label": "request", "inputFields": [{"key": "text"}]}
    },
    {
      "id": "llm",
      "type": "llm",
      "position": {"x": 260, "y": 0},
      "data": {
        "label": "reply",
        "credentialId": "YOUR_CREDENTIAL_ID",
        "model": "",
        "userMessage": "$request.text"
      }
    }
  ],
  "edges": [{"id": "e1", "source": "input", "target": "llm"}]
}
```
"""
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=builder_content))]
        client = MagicMock()
        client.chat.completions.create.return_value = response

        db = MagicMock()
        credential_result = MagicMock()
        credential_result.scalars.return_value.all.return_value = [credential.id]
        db.execute = AsyncMock(return_value=credential_result)
        db.flush = AsyncMock()

        with (
            patch(
                "app.api.ai_assistant.template_service.list_node_templates",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.api.ai_assistant.run_execute_workflow_tool",
                AsyncMock(
                    return_value='{"status":"success","outputs":{"text":"done"},"node_results":[]}'
                ),
            ) as run_tool,
        ):
            raw_result = await create_and_run_generated_workflow_tool(
                db=db,
                user=user,
                client=client,
                model="gpt-4o-mini",
                selected_credential=credential,
                selected_model="gpt-4o-mini",
                goal="Create an echo workflow",
                inputs={"text": "hello"},
                available_workflows=[],
                public_base_url="http://localhost",
            )

        saved_workflow = db.add.call_args.args[0]
        self.assertEqual(saved_workflow.name, "Echo Assistant")
        self.assertEqual(saved_workflow.nodes[1]["data"]["credentialId"], str(credential.id))
        self.assertEqual(saved_workflow.nodes[1]["data"]["model"], "gpt-4o-mini")
        run_tool.assert_awaited_once()
        self.assertEqual(run_tool.call_args.args[2], str(saved_workflow.id))
        self.assertEqual(run_tool.call_args.args[3], {"text": "hello"})

        result = json.loads(raw_result)
        self.assertEqual(result["status"], "created_and_ran")
        self.assertEqual(result["workflow_name"], "Echo Assistant")
        self.assertEqual(result["workflow_url"], f"/workflows/{saved_workflow.id}")
        self.assertIn('Open "Echo Assistant" in a new tab', result["workflow_link_markdown"])
        self.assertEqual(result["workflow_preview"]["id"], str(saved_workflow.id))
        self.assertEqual(result["workflow_preview"]["nodes"][1]["id"], "llm")
        self.assertEqual(result["execution"]["status"], "success")
        builder_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(builder_kwargs["temperature"], 0.0)

    async def test_edit_and_run_generated_workflow_updates_same_workflow(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        user.user_rules = None

        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.owner_id = user.id
        credential.type = CredentialType.openai

        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.name = "Echo Assistant"
        workflow.description = "Old description"
        workflow.nodes = [
            {
                "id": "input",
                "type": "textInput",
                "position": {"x": 0, "y": 0},
                "data": {"label": "request", "inputFields": [{"key": "text"}]},
            }
        ]
        workflow.edges = []
        workflow.auth_type = WorkflowAuthType.anonymous
        workflow.auth_header_key = None
        workflow.auth_header_value = None
        workflow.webhook_body_mode = WebhookBodyMode.generic
        workflow.cache_ttl_seconds = None
        workflow.rate_limit_requests = None
        workflow.rate_limit_window_seconds = None

        builder_content = """
```json
{
  "name": "Echo Assistant With Output",
  "description": "Echoes text and formats it.",
  "nodes": [
    {
      "id": "input",
      "type": "textInput",
      "position": {"x": 0, "y": 0},
      "data": {"label": "request", "inputFields": [{"key": "text"}]}
    },
    {
      "id": "output",
      "type": "output",
      "position": {"x": 260, "y": 0},
      "data": {"label": "done", "message": "$request.text"}
    }
  ],
  "edges": [{"id": "e1", "source": "input", "target": "output"}]
}
```
"""
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=builder_content))]
        client = MagicMock()
        client.chat.completions.create.return_value = response

        db = MagicMock()
        credential_result = MagicMock()
        credential_result.scalars.return_value.all.return_value = [credential.id]
        max_version_result = MagicMock()
        max_version_result.scalar.return_value = 3
        db.execute = AsyncMock(side_effect=[credential_result, max_version_result])
        db.flush = AsyncMock()

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch(
                "app.api.ai_assistant.template_service.list_node_templates",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.api.ai_assistant.run_execute_workflow_tool",
                AsyncMock(
                    return_value='{"status":"success","outputs":{"text":"done"},"node_results":[]}'
                ),
            ) as run_tool,
        ):
            raw_result = await edit_and_run_generated_workflow_tool(
                db=db,
                user=user,
                client=client,
                model="gpt-4o-mini",
                selected_credential=credential,
                selected_model="gpt-4o-mini",
                workflow_id=str(workflow.id),
                instructions="Add an output node",
                inputs={"text": "hello"},
                available_workflows=[],
                public_base_url="http://localhost",
            )

        self.assertEqual(workflow.name, "Echo Assistant With Output")
        self.assertEqual(workflow.description, "Echoes text and formats it.")
        self.assertEqual(workflow.nodes[1]["id"], "output")
        self.assertEqual(workflow.edges[0]["target"], "output")
        saved_version = db.add.call_args.args[0]
        self.assertIsInstance(saved_version, WorkflowVersion)
        self.assertEqual(saved_version.workflow_id, workflow.id)
        self.assertEqual(saved_version.version_number, 4)
        self.assertEqual(
            saved_version.nodes,
            [
                {
                    "id": "input",
                    "type": "textInput",
                    "position": {"x": 0, "y": 0},
                    "data": {"label": "request", "inputFields": [{"key": "text"}]},
                }
            ],
        )
        self.assertEqual(saved_version.edges, [])
        run_tool.assert_awaited_once()
        self.assertEqual(run_tool.call_args.args[2], str(workflow.id))

        result = json.loads(raw_result)
        self.assertEqual(result["status"], "edited_and_ran")
        self.assertEqual(result["workflow_id"], str(workflow.id))
        self.assertEqual(result["workflow_preview"]["nodes"][1]["id"], "output")
        self.assertEqual(result["execution"]["status"], "success")
        builder_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(builder_kwargs["temperature"], 0.0)

    def test_workflow_builder_prompt_requires_discovery_for_current_web_sources(self) -> None:
        prompt = _build_workflow_builder_user_message(
            "Notify Slack when n8n, Needle, or Activepieces releases new features",
            {},
            None,
        )

        self.assertIn("do not hardcode guessed source URLs", prompt)
        self.assertIn("find official release or changelog sources", prompt)

    def test_workflow_editor_prompt_allows_renaming_updated_workflow(self) -> None:
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.name = "Old Workflow"
        workflow.description = "Old description"
        workflow.nodes = [
            {
                "id": "input",
                "type": "textInput",
                "position": {"x": 0, "y": 0},
                "data": {"label": "old input"},
            }
        ]
        workflow.edges = []

        prompt = _build_workflow_editor_user_message(
            workflow,
            "Make this workflow fetch Google results instead",
            {},
            None,
        )

        self.assertIn("Update the workflow name, description, and node labels", prompt)
        self.assertIn("Preserve node ids", prompt)
        self.assertNotIn("Preserve node ids, labels", prompt)


class BuildUserMessageTests(unittest.TestCase):
    def test_no_attachment_returns_string_content(self) -> None:
        result = _build_user_message("Hello", None)
        self.assertEqual(result, {"role": "user", "content": "Hello"})

    def test_text_attachment_embeds_in_content(self) -> None:
        attachment = FileAttachment(name="notes.txt", kind="text", content="line1\nline2")
        result = _build_user_message("Summarize this", attachment)
        self.assertEqual(result["role"], "user")
        self.assertIsInstance(result["content"], str)
        self.assertIn("Summarize this", result["content"])
        self.assertIn("[ATTACHED FILE: notes.txt]", result["content"])
        self.assertIn("line1\nline2", result["content"])

    def test_pdf_attachment_embeds_in_content(self) -> None:
        attachment = FileAttachment(name="report.pdf", kind="pdf", content="Extracted text")
        result = _build_user_message("Analyze this", attachment)
        self.assertIsInstance(result["content"], str)
        self.assertIn("[ATTACHED FILE: report.pdf]", result["content"])
        self.assertIn("Extracted text", result["content"])

    def test_image_attachment_embeds_metadata_only(self) -> None:
        attachment = FileAttachment(
            name="photo.png", kind="image", content="data:image/png;base64,abc123"
        )
        result = _build_user_message("Describe this", attachment)
        self.assertEqual(result["role"], "user")
        self.assertIsInstance(result["content"], str)
        self.assertIn("Describe this", result["content"])
        self.assertIn("[ATTACHED IMAGE: photo.png]", result["content"])
        # base64 data must NOT appear in the LLM context to avoid context overflow
        self.assertNotIn("data:image/png;base64,abc123", result["content"])


class DashboardChatAttachmentIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_dashboard_chat_injects_routing_instructions_when_attachment_present(
        self,
    ) -> None:
        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.type = CredentialType.openai
        credential.encrypted_config = "encrypted-config"

        current_user = MagicMock()
        current_user.id = uuid.uuid4()

        http_request = MagicMock()
        http_request.is_disconnected = AsyncMock(return_value=False)

        captured: dict[str, object] = {}

        async def fake_stream(
            _client: object,
            _model: str,
            system_prompt: str,
            messages: list[dict],
            _db: object,
            _user: object,
            _provider: str,
            _public_base_url: str,
            _trace_context: object,
            _cancel_event: object,
            _attachment: object = None,
            _selected_credential: object = None,
        ):
            captured["system_prompt"] = system_prompt
            captured["messages"] = messages
            yield 'data: {"type":"done"}\n\n'

        request = DashboardChatRequest(
            credential_id=credential.id,
            model="gpt-4o-mini",
            message="Analyze this",
            attachment=FileAttachment(name="data.csv", kind="text", content="a,b\n1,2"),
        )

        db = AsyncMock()

        with (
            patch("app.api.ai_assistant.get_credential_for_user", return_value=credential),
            patch("app.api.ai_assistant.decrypt_config", return_value={}),
            patch("app.api.ai_assistant.get_openai_client", return_value=(MagicMock(), "openai")),
            patch(
                "app.api.ai_assistant.get_workflows_for_user_with_inputs",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("app.api.ai_assistant._load_agents_md_content", return_value=None),
            patch("app.api.ai_assistant.build_public_base_url", return_value="http://localhost"),
            patch("app.api.ai_assistant.stream_dashboard_chat", side_effect=fake_stream),
        ):
            response = await dashboard_chat_stream(
                http_request=http_request,
                request=request,
                current_user=current_user,
                db=db,
            )
            _chunks = [chunk async for chunk in response.body_iterator]

        self.assertIn("route its content", captured["system_prompt"])
        last_msg = captured["messages"][-1]
        self.assertIsInstance(last_msg["content"], str)
        self.assertIn("[ATTACHED FILE: data.csv]", last_msg["content"])
        self.assertIn("a,b\n1,2", last_msg["content"])


class DashboardChatBreakdownTests(unittest.IsolatedAsyncioTestCase):
    def test_context_breakdown_keys_and_values(self) -> None:
        from app.api.ai_assistant import _context_breakdown
        from app.services.context_compressor import _estimate_tokens

        history = [{"role": "user", "content": "hello"}]
        breakdown = _context_breakdown(
            base_system_prompt="sys",
            agents_md="agents",
            workflows_block="wf",
            user_rules="rules",
            history=history,
            attachment_content=None,
        )

        self.assertIn("system", breakdown)
        self.assertIn("agents_md", breakdown)
        self.assertIn("workflows", breakdown)
        self.assertIn("user_rules", breakdown)
        self.assertIn("history", breakdown)
        self.assertIn("attachment", breakdown)
        self.assertEqual(breakdown["attachment"], 0)
        self.assertEqual(breakdown["history"], _estimate_tokens(history))

    def test_context_breakdown_empty_inputs_return_zero(self) -> None:
        from app.api.ai_assistant import _context_breakdown

        breakdown = _context_breakdown(
            base_system_prompt="",
            agents_md="",
            workflows_block="",
            user_rules="",
            history=[],
            attachment_content=None,
        )
        self.assertEqual(breakdown["system"], 0)
        self.assertEqual(breakdown["agents_md"], 0)
        self.assertEqual(breakdown["workflows"], 0)
        self.assertEqual(breakdown["user_rules"], 0)
        self.assertEqual(breakdown["history"], 0)
        self.assertEqual(breakdown["attachment"], 0)


class DashboardChatToolEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_emits_tool_start_and_tool_end(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()

        tool_call_msg = MagicMock()
        tool_call_msg.content = None
        tc = MagicMock()
        tc.id = "tc_abc"
        tc.function.name = "list_workflows"
        tc.function.arguments = "{}"
        tool_call_msg.tool_calls = [tc]

        final_msg = MagicMock()
        final_msg.content = "Here are your workflows."
        final_msg.tool_calls = None

        response_with_tools = MagicMock()
        response_with_tools.choices = [MagicMock(message=tool_call_msg)]
        response_with_tools.usage = MagicMock(
            prompt_tokens=10, completion_tokens=5, total_tokens=15
        )

        response_final = MagicMock()
        response_final.choices = [MagicMock(message=final_msg)]
        response_final.usage = MagicMock(prompt_tokens=20, completion_tokens=8, total_tokens=28)

        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [response_with_tools, response_final]

        db_mock = AsyncMock()
        with (
            patch("app.api.ai_assistant.record_run_history"),
            patch(
                "app.api.ai_assistant.get_workflows_for_user_with_inputs",
                new=AsyncMock(return_value=[]),
            ),
        ):
            chunks = _normalize_chunks(
                [
                    chunk
                    async for chunk in stream_dashboard_chat(
                        fake_client,
                        "gpt-4o-mini",
                        "system",
                        [{"role": "user", "content": "list workflows"}],
                        db_mock,
                        user,
                        "OpenAI",
                        "http://localhost",
                    )
                ]
            )

        joined = "".join(chunks)
        self.assertIn('"type": "tool_start"', joined)
        self.assertIn('"id": "tc_abc"', joined)
        self.assertIn('"type": "tool_end"', joined)
        self.assertNotIn('"type": "step"', joined)


class DashboardChatContextEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_emits_context_event_with_prompt_tokens(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        final_msg = MagicMock()
        final_msg.content = "ok"
        final_msg.tool_calls = None
        response = MagicMock()
        response.choices = [MagicMock(message=final_msg)]
        response.usage = MagicMock(prompt_tokens=42, completion_tokens=3, total_tokens=45)
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = response

        with patch("app.api.ai_assistant.record_run_history"):
            chunks = _normalize_chunks(
                [
                    chunk
                    async for chunk in stream_dashboard_chat(
                        fake_client,
                        "gpt-4o-mini",
                        "system",
                        [{"role": "user", "content": "hi"}],
                        AsyncMock(),
                        user,
                        "OpenAI",
                        "http://localhost",
                    )
                ]
            )

        joined = "".join(chunks)
        self.assertIn('"type": "context"', joined)
        self.assertIn('"used": 42', joined)
        self.assertIn('"limit": 128000', joined)


class DashboardChatCompressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_emits_compressed_when_compression_runs(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        final_msg = MagicMock()
        final_msg.content = "ok"
        final_msg.tool_calls = None
        response = MagicMock()
        response.choices = [MagicMock(message=final_msg)]
        response.usage = MagicMock(prompt_tokens=10, completion_tokens=3, total_tokens=13)
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = response

        fake_compressed = [
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "summary"},
        ]
        fake_info = {
            "messages_compressed": 18,
            "messages_before_count": 22,
            "messages_after_count": 4,
            "tokens_before": 98_000,
            "tokens_after": 12_000,
            "elapsed_ms": 412.0,
        }
        with (
            patch("app.api.ai_assistant.record_run_history"),
            patch(
                "app.services.context_compressor.maybe_compress_messages",
                new=AsyncMock(return_value=(fake_compressed, fake_info)),
            ),
        ):
            chunks = _normalize_chunks(
                [
                    chunk
                    async for chunk in stream_dashboard_chat(
                        fake_client,
                        "gpt-4o-mini",
                        "system",
                        [{"role": "user", "content": "hi"}],
                        AsyncMock(),
                        user,
                        "OpenAI",
                        "http://localhost",
                    )
                ]
            )

        joined = "".join(chunks)
        self.assertIn('"type": "compressed"', joined)
        self.assertIn('"messages_compressed": 18', joined)
        self.assertIn('"tokens_before": 98000', joined)


class ContextSummaryEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_context_summary_returns_breakdown(self) -> None:
        from app.api.chats import SystemPromptParts, get_context_summary
        from app.models.chat_schemas import ContextSummaryResponse

        conv_id = uuid.uuid4()
        user = MagicMock()
        user.id = uuid.uuid4()
        user.user_rules = ""

        conversation = MagicMock()
        conversation.id = conv_id
        conversation.user_id = user.id

        mock_db = AsyncMock()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=conversation)
        scalars_result = MagicMock()
        scalars_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[scalar_result, scalars_result])

        fake_credential = MagicMock()
        fake_credential.encrypted_config = "{}"
        fake_credential.type = "openai"

        fake_parts = SystemPromptParts(
            full_system_prompt="sys",
            base_system_prompt="sys",
            agents_md="",
            workflows_block="",
            user_rules="",
        )

        with (
            patch(
                "app.api.chats.get_accessible_credential",
                new=AsyncMock(return_value=fake_credential),
            ),
            patch("app.api.chats.decrypt_config", return_value={"api_key": "x"}),
            patch("app.api.chats.get_openai_client", return_value=(MagicMock(), "OpenAI")),
            patch(
                "app.api.chats._assemble_system_prompt_parts",
                new=AsyncMock(return_value=fake_parts),
            ),
            patch(
                "app.api.ai_assistant._context_breakdown",
                return_value={
                    "system": 1,
                    "agents_md": 0,
                    "workflows": 0,
                    "user_rules": 0,
                    "history": 0,
                    "attachment": 0,
                },
            ),
            patch(
                "app.services.context_compressor.get_context_limit",
                return_value=128_000,
            ),
        ):
            result = await get_context_summary(
                conversation_id=conv_id,
                credential_id=uuid.uuid4(),
                model="gpt-4o-mini",
                current_user=user,
                db=mock_db,
            )

        self.assertIsInstance(result, ContextSummaryResponse)
        self.assertEqual(result.limit, 128_000)
        self.assertEqual(result.used, 1)
        self.assertEqual(result.breakdown.system, 1)
