import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.ai_assistant import (
    DashboardChatRequest,
    FileAttachment,
    _build_user_message,
    dashboard_chat_stream,
    stream_dashboard_chat,
)
from app.db.models import CredentialType
from app.services.llm_trace import LLMTraceContext


def _normalize_chunks(chunks: list[str | bytes]) -> list[str]:
    normalized: list[str] = []
    for chunk in chunks:
        normalized.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return normalized


class DashboardChatApiTests(unittest.IsolatedAsyncioTestCase):
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

    def test_image_attachment_builds_multipart_content(self) -> None:
        attachment = FileAttachment(
            name="photo.png", kind="image", content="data:image/png;base64,abc123"
        )
        result = _build_user_message("Describe this", attachment)
        self.assertEqual(result["role"], "user")
        content = result["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(len(content), 2)
        self.assertEqual(content[0], {"type": "text", "text": "Describe this"})
        self.assertEqual(
            content[1], {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}}
        )


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
