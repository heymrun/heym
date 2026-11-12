"""Playwright AI step LLM calls are traced against the workflow node that ran them."""

import json
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.api import playwright
from app.db.models import CredentialType
from app.services.llm_trace import LLMTraceContext
from app.services.node_execution.nodes.playwright_node import _execute_playwright_node
from app.services.playwright_execution_tokens import (
    PlaywrightExecutionClaims,
    create_token,
    validate_token,
)
from app.services.workflow_executor import WorkflowExecutor

OPENCODE_BASE_URL = "https://opencode.ai/zen/go/v1"
STEPS_JSON = json.dumps({"steps": [{"action": "click", "selector": "#submit"}]})


def _credential() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), name="OpenCode", type=CredentialType.custom, encrypted_config="x"
    )


def _db_returning(credential: SimpleNamespace) -> AsyncMock:
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=credential))
    return db


def _body(credential: SimpleNamespace, **extra: object) -> dict:
    return {
        "credentialId": str(credential.id),
        "model": "test-model",
        "html": "<button id='submit'>Submit</button>",
        "instructions": "Click Submit",
        "failedStep": {"action": "click", "selector": "#old-submit"},
        **extra,
    }


class NodeTokenCarriesRunContextTests(unittest.TestCase):
    def test_ai_step_token_names_the_workflow_node_and_session(self) -> None:
        user_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        node_data = {
            "label": "Browser",
            "playwrightMode": "steps",
            "playwrightSteps": [
                {"action": "navigate", "url": "https://example.com"},
                {"action": "aiStep", "instructions": "click login", "model": "gpt-test"},
            ],
        }
        executor = WorkflowExecutor(
            nodes=[{"id": "pw1", "type": "playwright", "data": node_data}],
            edges=[],
            workflow_id=workflow_id,
            trace_user_id=user_id,
            execution_id="exec-42",
        )
        captured: dict[str, object] = {}

        def fake_build(code: str, *args: object, **kwargs: object) -> str:
            captured.update(kwargs)
            return "print('noop')"

        with (
            patch(
                "app.services.node_execution.nodes.playwright_node._build_playwright_script",
                fake_build,
            ),
            patch("subprocess.Popen") as popen,
        ):
            popen.return_value.returncode = 0
            _execute_playwright_node(executor, node_data, {}, "pw1", "Browser")

        claims = validate_token(str(captured["heym_execution_token"]))
        self.assertEqual(
            claims,
            PlaywrightExecutionClaims(
                user_id=str(user_id),
                workflow_id=str(workflow_id),
                node_id="pw1",
                node_label="Browser",
                session_id="exec-42",
            ),
        )


class AiStepTraceContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_step_and_heal_trace_against_the_node(self) -> None:
        user_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        credential = _credential()
        token = create_token(
            str(user_id),
            workflow_id=str(workflow_id),
            node_id="pw1",
            node_label="Browser",
            session_id="exec-42",
        )
        for endpoint in (playwright.ai_step, playwright.ai_step_heal):
            with self.subTest(endpoint=endpoint.__name__):
                with (
                    patch.object(playwright, "decrypt_config", return_value={"api_key": "k"}),
                    patch.object(
                        playwright, "execute_llm", AsyncMock(return_value={"text": STEPS_JSON})
                    ) as execute,
                ):
                    await endpoint(
                        _body(credential), x_execution_token=token, db=_db_returning(credential)
                    )

                context = execute.call_args.kwargs["trace_context"]
                self.assertIsInstance(context, LLMTraceContext)
                self.assertEqual(context.user_id, user_id)
                self.assertEqual(context.credential_id, credential.id)
                self.assertEqual(context.workflow_id, workflow_id)
                self.assertEqual(context.node_id, "pw1")
                self.assertEqual(context.node_label, "Browser")
                self.assertEqual(context.source, "workflow")
                self.assertEqual(context.session_id, "exec-42")

    async def test_token_without_run_context_still_traces_the_call(self) -> None:
        user_id = uuid.uuid4()
        credential = _credential()
        token = create_token(str(user_id))
        with (
            patch.object(playwright, "decrypt_config", return_value={"api_key": "k"}),
            patch.object(
                playwright, "execute_llm", AsyncMock(return_value={"text": STEPS_JSON})
            ) as execute,
        ):
            await playwright.ai_step(
                _body(credential), x_execution_token=token, db=_db_returning(credential)
            )

        context = execute.call_args.kwargs["trace_context"]
        self.assertEqual(context.user_id, user_id)
        self.assertEqual(context.credential_id, credential.id)
        self.assertIsNone(context.workflow_id)
        self.assertIsNone(context.node_id)

    async def test_saved_steps_make_no_llm_call(self) -> None:
        credential = _credential()
        saved = [{"action": "click", "selector": "#saved"}]
        with patch.object(playwright, "execute_llm", AsyncMock()) as execute:
            result = await playwright.ai_step(
                _body(credential, saveStepsForFuture=True, savedSteps=saved),
                x_execution_token=create_token(str(uuid.uuid4())),
                db=_db_returning(credential),
            )
        self.assertEqual(result, {"steps": saved})
        execute.assert_not_awaited()


class AiStepRecordsTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_llm_call_records_trace_and_keeps_the_run_session(self) -> None:
        sessions: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            sessions.append(request.headers["x-opencode-session"])
            return httpx.Response(
                200,
                json={
                    "id": "test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": STEPS_JSON},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                },
            )

        def transport(**_kwargs: Any) -> httpx.Client:
            client = httpx.Client(transport=httpx.MockTransport(respond))
            self.addCleanup(client.close)
            return client

        workflow_id = uuid.uuid4()
        credential = _credential()
        token = create_token(
            str(uuid.uuid4()),
            workflow_id=str(workflow_id),
            node_id="pw1",
            node_label="Browser",
            session_id="exec-42",
        )
        with (
            patch.object(
                playwright,
                "decrypt_config",
                return_value={"api_key": "k", "base_url": OPENCODE_BASE_URL},
            ),
            patch("app.services.openai_client.guard_http_url"),
            patch("app.services.openai_client.build_guarded_http_client", side_effect=transport),
            patch("app.services.llm_service.record_llm_trace") as record,
        ):
            for endpoint in (playwright.ai_step, playwright.ai_step_heal):
                await endpoint(
                    _body(credential), x_execution_token=token, db=_db_returning(credential)
                )

        self.assertEqual(record.call_count, 2)
        for call in record.call_args_list:
            context = call.kwargs["context"]
            self.assertEqual(context.workflow_id, workflow_id)
            self.assertEqual(context.node_label, "Browser")
            self.assertEqual(call.kwargs["total_tokens"], 5)
            self.assertIsNone(call.kwargs["error"])
        self.assertTrue(sessions)
        self.assertEqual(set(sessions), {"exec-42"})


if __name__ == "__main__":
    unittest.main()
