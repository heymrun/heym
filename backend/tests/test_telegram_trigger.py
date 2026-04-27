"""Unit tests for the Telegram webhook endpoint."""

import asyncio
import json
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.datastructures import Headers


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

    async def test_missing_secret_configuration_allows_request(self) -> None:
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
            response = await telegram_webhook(node_id, request)
            await asyncio.sleep(0)

        self.assertEqual(response, {"ok": True})
        mock_execute_background.assert_awaited_once()

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
