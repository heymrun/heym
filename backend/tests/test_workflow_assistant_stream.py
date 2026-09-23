import asyncio
import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.ai_assistant import AIAssistantRequest, workflow_assistant_stream
from app.db.models import CredentialType


class WorkflowAssistantStreamHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_emits_hidden_heartbeat_while_waiting_for_model_stream(self) -> None:
        release_stream = Event()
        credential_id = uuid.uuid4()
        user = SimpleNamespace(id=uuid.uuid4())
        credential = SimpleNamespace(
            id=credential_id,
            type=CredentialType.openai,
            encrypted_config={},
        )

        async def fake_stream_llm_response(*_args: object, **_kwargs: object):
            await asyncio.to_thread(release_stream.wait)
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
            patch("app.api.ai_assistant.WORKFLOW_ASSISTANT_SSE_HEARTBEAT_SECONDS", 0.001),
        ):
            response = await workflow_assistant_stream(
                request=AIAssistantRequest(
                    credential_id=credential_id,
                    model="gpt-test",
                    message="hello",
                    ask_mode=True,
                ),
                current_user=user,
                db=AsyncMock(),
            )

            stream = response.body_iterator
            self.assertEqual(await stream.__anext__(), ": heartbeat\n\n")

            release_stream.set()
            while True:
                chunk = await stream.__anext__()
                if chunk == 'data: {"type": "done"}\n\n':
                    break
                self.assertEqual(chunk, ": heartbeat\n\n")

            # Payload and sentinel are two `call_soon_threadsafe` hops, so a keepalive can
            # land between them; only "nothing but heartbeats, then the end" is guaranteed.
            for _ in range(200):
                try:
                    trailing = await stream.__anext__()
                except StopAsyncIteration:
                    break
                self.assertEqual(trailing, ": heartbeat\n\n")
            else:
                self.fail("the stream kept emitting heartbeats after the source finished")


class WorkflowAssistantHttpCredentialsTests(unittest.IsolatedAsyncioTestCase):
    async def test_builder_prompt_includes_http_credentials_section(self) -> None:
        section = "\n\n## Credentials for HTTP requests\n\n- `google` (google)\n"
        credential_id = uuid.uuid4()
        user = SimpleNamespace(id=uuid.uuid4(), user_rules=None)
        credential = SimpleNamespace(
            id=credential_id,
            type=CredentialType.openai,
            encrypted_config={},
        )
        db = AsyncMock()
        captured: dict[str, str] = {}

        async def fake_stream_llm_response(
            _client: object, _model: str, system_prompt: str, *_args: object, **_kwargs: object
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
            patch("app.api.ai_assistant._load_installed_plugins", AsyncMock(return_value=[])),
            patch(
                "app.api.ai_assistant.build_http_credentials_prompt",
                AsyncMock(return_value=section),
            ) as http_credentials_prompt,
            patch("app.api.ai_assistant.stream_llm_response", fake_stream_llm_response),
        ):
            response = await workflow_assistant_stream(
                request=AIAssistantRequest(
                    credential_id=credential_id,
                    model="gpt-test",
                    message="Call the Google Maps API",
                ),
                current_user=user,
                db=db,
            )
            async for chunk in response.body_iterator:
                if chunk == 'data: {"type": "done"}\n\n':
                    break

        self.assertIn(section, captured["system_prompt"])
        http_credentials_prompt.assert_awaited_once_with(db, user.id, interactive=True)
