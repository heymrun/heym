"""Unit tests for the Telegram webhook endpoint."""

import asyncio
import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.datastructures import Headers

from app.db.models import ExecutionHistory
from app.services.workflow_executor import ExecutionResult


def _make_request(body_bytes: bytes, headers: dict[str, str]) -> MagicMock:
    """Build a minimal mock Request with the given body and headers."""
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/telegram/webhook/test",
        "headers": Headers(headers).raw,
        "query_string": b"",
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    return Request(scope, receive)


class TestTelegramTriggerWebhook(unittest.IsolatedAsyncioTestCase):
    async def test_valid_secret_token_schedules_workflow(self) -> None:
        from app.api.telegram import telegram_webhook

        node_id = str(uuid.uuid4())
        body_dict = {
            "update_id": 99,
            "message": {"message_id": 7, "chat": {"id": 12345}, "text": "hello"},
        }
        raw_body = json.dumps(body_dict).encode()
        request = _make_request(
            raw_body,
            {
                "content-type": "application/json",
                "x-telegram-bot-api-secret-token": "expected-secret",
            },
        )

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.owner_id = uuid.uuid4()
        mock_workflow.nodes = [
            {
                "id": node_id,
                "type": "telegramTrigger",
                "data": {"label": "telegramEvent", "credentialId": str(uuid.uuid4())},
            }
        ]

        with (
            patch(
                "app.api.telegram._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.telegram._get_telegram_config",
                new=AsyncMock(
                    return_value={"bot_token": "123:token", "secret_token": "expected-secret"}
                ),
            ),
            patch(
                "app.api.telegram._execute_workflow_background",
                new=AsyncMock(return_value=None),
            ) as mock_execute_background,
        ):
            response = await telegram_webhook(node_id, request)
            await asyncio.sleep(0)

        self.assertEqual(response, {"ok": True})
        mock_execute_background.assert_awaited_once()

    async def test_background_execution_persists_trigger_input_fields(self) -> None:
        from app.api.telegram import _execute_workflow_background

        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=owner_id,
            name="Telegram workflow",
            nodes=[],
            edges=[],
        )
        added_rows: list[object] = []
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow)),
            add=added_rows.append,
            commit=AsyncMock(),
        )
        execution_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"ok": True},
            execution_time_ms=12.3,
            node_results=[],
            sub_workflow_executions=[],
        )

        with (
            patch("app.api.telegram.async_session_maker") as mock_session_maker,
            patch("app.api.telegram.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.telegram.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.telegram.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.telegram.execute_workflow", return_value=execution_result),
            patch("app.api.telegram.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.telegram._persist_global_variables_from_execution", AsyncMock()),
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = db
            mock_session.__aexit__.return_value = None
            mock_session_maker.return_value = mock_session

            await _execute_workflow_background(
                workflow,
                "telegram-node",
                {"message": {"message_id": 7, "chat": {"id": 12345}, "text": "hello"}},
                {"x-telegram-bot-api-secret-token": "expected-secret"},
            )

        history = next(row for row in added_rows if isinstance(row, ExecutionHistory))
        self.assertEqual(history.trigger_source, "telegram")
        self.assertEqual(history.inputs["triggered_by"], "telegram")
        self.assertEqual(history.inputs["trigger_node_id"], "telegram-node")
        self.assertEqual(history.inputs["message"]["text"], "hello")
        self.assertIn("triggered_at", history.inputs)

    async def test_invalid_secret_token_returns_403(self) -> None:
        from app.api.telegram import telegram_webhook

        node_id = str(uuid.uuid4())
        raw_body = json.dumps({"message": {"chat": {"id": 1}, "text": "hello"}}).encode()
        request = _make_request(
            raw_body,
            {
                "content-type": "application/json",
                "x-telegram-bot-api-secret-token": "wrong-secret",
            },
        )

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {
                "id": node_id,
                "type": "telegramTrigger",
                "data": {"credentialId": str(uuid.uuid4())},
            }
        ]

        with (
            patch(
                "app.api.telegram._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.telegram._get_telegram_config",
                new=AsyncMock(
                    return_value={"bot_token": "123:token", "secret_token": "real-secret"}
                ),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await telegram_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_missing_secret_configuration_rejects_request(self) -> None:
        """Regression for GHSA-pm6h-x3h5-j38h finding H2.

        Telegram webhook must reject with 400 when the credential exists but has
        an empty secret_token. Previously this case fell through and triggered
        the workflow with the owner's credentials. This test was previously
        asserting the allow behavior; it now asserts the fail-closed behavior.
        """
        from app.api.telegram import telegram_webhook

        node_id = str(uuid.uuid4())
        raw_body = json.dumps({"message": {"chat": {"id": 1}, "text": "hello"}}).encode()
        request = _make_request(raw_body, {"content-type": "application/json"})

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {
                "id": node_id,
                "type": "telegramTrigger",
                "data": {"credentialId": str(uuid.uuid4())},
            }
        ]

        with (
            patch(
                "app.api.telegram._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.telegram._get_telegram_config",
                new=AsyncMock(return_value={"bot_token": "123:token", "secret_token": ""}),
            ),
            patch(
                "app.api.telegram._execute_workflow_background",
                new=AsyncMock(return_value=None),
            ) as mock_execute_background,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await telegram_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "invalid webhook credential configuration")
        mock_execute_background.assert_not_awaited()

    async def test_no_credential_id_rejects_request(self) -> None:
        """Telegram webhook must reject with 400 when the trigger node has no
        credentialId. Previously this case fell through and triggered the workflow.
        """
        from app.api.telegram import telegram_webhook

        node_id = str(uuid.uuid4())
        raw_body = json.dumps({"message": {"chat": {"id": 1}, "text": "hello"}}).encode()
        request = _make_request(raw_body, {"content-type": "application/json"})

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {
                "id": node_id,
                "type": "telegramTrigger",
                "data": {},  # no credentialId
            }
        ]

        with (
            patch(
                "app.api.telegram._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.telegram._execute_workflow_background",
                new=AsyncMock(return_value=None),
            ) as mock_execute_background,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await telegram_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "invalid webhook credential configuration")
        mock_execute_background.assert_not_awaited()

    async def test_unknown_node_id_returns_404(self) -> None:
        from app.api.telegram import telegram_webhook

        node_id = str(uuid.uuid4())
        raw_body = json.dumps({"message": {"chat": {"id": 1}, "text": "hello"}}).encode()
        request = _make_request(raw_body, {"content-type": "application/json"})

        with patch(
            "app.api.telegram._find_workflow_by_node_id",
            new=AsyncMock(return_value=None),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await telegram_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
