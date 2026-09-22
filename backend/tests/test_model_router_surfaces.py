"""Router credentials have no API key but must reach every routed LLM surface."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import playwright
from app.db.models import CredentialType
from app.services import agent_memory_service
from app.services.llm_trace import LLMTraceContext
from app.services.model_router import ModelRouter


def _router_config() -> dict:
    return {
        "decision_credential_id": str(uuid.uuid4()),
        "decision_model": "jev-latest",
        "routing_instructions": "Choose the model that fits the task.",
        "options": [
            {
                "id": "fast",
                "label": "Fast",
                "credential_id": str(uuid.uuid4()),
                "model": "gpt-4o-mini",
                "criteria": "Simple tasks",
                "is_default": True,
            },
            {
                "id": "deep",
                "label": "Deep",
                "credential_id": str(uuid.uuid4()),
                "model": "gpt-4o",
                "criteria": "Complex tasks",
            },
        ],
    }


def _credential(credential_type: CredentialType) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), name="Test credential", type=credential_type, encrypted_config="encrypted"
    )


class PlaywrightRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_step_and_heal_accept_router_without_an_api_key(self) -> None:
        credential = _credential(CredentialType.model_router)
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=credential))
        body = {
            "credentialId": str(credential.id),
            "model": "auto",
            "html": "<button>Submit</button>",
            "instructions": "Click Submit",
            "failedStep": {"action": "click", "selector": "#old-submit"},
        }
        for endpoint in (playwright.ai_step, playwright.ai_step_heal):
            with self.subTest(endpoint=endpoint.__name__):
                with (
                    patch.object(playwright, "validate_token", return_value=str(uuid.uuid4())),
                    patch.object(playwright, "decrypt_config", return_value=_router_config()),
                    patch.object(
                        playwright,
                        "execute_llm",
                        AsyncMock(
                            return_value={
                                "text": '{"steps": [{"action": "click", "text": "Submit"}]}'
                            }
                        ),
                    ) as execute,
                ):
                    result = await endpoint(body, x_execution_token="test-token", db=db)

                self.assertEqual(result["steps"], [{"action": "click", "text": "Submit"}])
                execute.assert_awaited_once()
                kwargs = execute.call_args.kwargs
                self.assertEqual(kwargs["api_key"], "")
                self.assertEqual(kwargs["model"], "auto")
                self.assertEqual(kwargs["credential_type"], "model_router")
                self.assertIsInstance(kwargs["router"], ModelRouter)
                self.assertEqual(kwargs["router"].credential_id, str(credential.id))

    async def test_ai_step_and_heal_still_reject_direct_credentials_without_a_key(self) -> None:
        credential = _credential(CredentialType.openai)
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=credential))
        for endpoint in (playwright.ai_step, playwright.ai_step_heal):
            with self.subTest(endpoint=endpoint.__name__):
                with (
                    patch.object(playwright, "validate_token", return_value=str(uuid.uuid4())),
                    patch.object(playwright, "decrypt_config", return_value={}),
                    patch.object(playwright, "execute_llm", AsyncMock()) as execute,
                    self.assertRaises(HTTPException) as ctx,
                ):
                    await endpoint(
                        {"credentialId": str(credential.id), "model": "gpt-4o"},
                        x_execution_token="test-token",
                        db=db,
                    )

                self.assertEqual(ctx.exception.status_code, 400)
                self.assertEqual(ctx.exception.detail, "Credential has no API key")
                execute.assert_not_awaited()


class AgentMemoryRouterTests(unittest.TestCase):
    def test_router_extracts_and_merges_memory_without_an_api_key(self) -> None:
        credential = _credential(CredentialType.model_router)
        workflow_id = uuid.uuid4()
        trace_context = LLMTraceContext(
            user_id=uuid.uuid4(), credential_id=credential.id, session_id="memory-conversation"
        )
        session = MagicMock()
        session.execute.return_value.scalars.return_value.first.return_value = credential
        session.execute.return_value.scalars.return_value.all.return_value = []
        parsed = {"entities": [], "relationships": []}
        with (
            patch.object(agent_memory_service, "SessionLocal") as session_factory,
            patch.object(agent_memory_service, "decrypt_config", return_value=_router_config()),
            patch.object(
                agent_memory_service,
                "execute_llm",
                AsyncMock(return_value={"text": '{"entities": [], "relationships": []}'}),
            ) as execute,
            patch.object(agent_memory_service, "apply_parsed_extraction_sync") as merge,
        ):
            session_factory.return_value.__enter__.return_value = session
            agent_memory_service.extract_and_merge_memory_sync(
                workflow_id,
                "agent-1",
                str(credential.id),
                "auto",
                "Remember my preference",
                {"text": "Remembered."},
                trace_context=trace_context,
            )

        execute.assert_awaited_once()
        kwargs = execute.call_args.kwargs
        self.assertEqual(kwargs["api_key"], "")
        self.assertEqual(kwargs["credential_type"], "model_router")
        self.assertEqual(kwargs["model"], "auto")
        self.assertIsInstance(kwargs["router"], ModelRouter)
        self.assertIs(kwargs["trace_context"], trace_context)
        merge.assert_called_once_with(session, workflow_id, "agent-1", parsed)
        session.commit.assert_called_once()

    def test_direct_credential_without_a_key_still_skips_memory_extraction(self) -> None:
        credential = _credential(CredentialType.openai)
        session = MagicMock()
        session.execute.return_value.scalars.return_value.first.return_value = credential
        with (
            patch.object(agent_memory_service, "SessionLocal") as session_factory,
            patch.object(agent_memory_service, "decrypt_config", return_value={}),
            patch.object(agent_memory_service, "execute_llm", AsyncMock()) as execute,
        ):
            session_factory.return_value.__enter__.return_value = session
            agent_memory_service.extract_and_merge_memory_sync(
                uuid.uuid4(),
                "agent-1",
                str(credential.id),
                "gpt-4o",
                "Remember my preference",
                {"text": "Remembered."},
            )

        execute.assert_not_awaited()
        session.commit.assert_not_called()
