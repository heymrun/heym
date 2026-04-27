"""Unit tests for the Slack webhook endpoint."""

import hashlib
import hmac
import json
import time
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.datastructures import Headers


def _make_signature(signing_secret: str, timestamp: str, body: str) -> str:
    """Helper: compute a valid Slack HMAC-SHA256 signature."""
    base = f"v0:{timestamp}:{body}"
    return "v0=" + hmac.new(signing_secret.encode(), base.encode(), hashlib.sha256).hexdigest()


def _make_request(body_bytes: bytes, headers: dict) -> MagicMock:
    """Build a minimal mock Request with the given body and headers."""
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/slack/webhook/test",
        "headers": Headers(headers).raw,
        "query_string": b"",
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    return Request(scope, receive)


class TestSlackUrlVerification(unittest.IsolatedAsyncioTestCase):
    """Slack sends url_verification; endpoint must echo challenge, no workflow execution."""

    async def test_url_verification_returns_challenge(self) -> None:
        from app.api.slack import slack_webhook

        body_dict = {"type": "url_verification", "challenge": "abc123xyz"}
        raw_body = json.dumps(body_dict).encode()
        request = _make_request(raw_body, {"content-type": "application/json"})

        with patch("app.api.slack._find_workflow_by_node_id", new=AsyncMock()) as mock_find:
            response = await slack_webhook("some-node-id", request)

        self.assertEqual(response, {"challenge": "abc123xyz"})
        mock_find.assert_not_called()


class TestSlackValidSignature(unittest.IsolatedAsyncioTestCase):
    """Valid signature + known node_id → 200 ok, background task scheduled."""

    async def test_valid_event_triggers_workflow(self) -> None:
        from app.api.slack import slack_webhook

        node_id = str(uuid.uuid4())
        signing_secret = "test_secret_abc"
        timestamp = str(int(time.time()))
        body_dict = {"type": "message", "event": {"type": "message", "text": "hello"}}
        raw_body = json.dumps(body_dict).encode()
        signature = _make_signature(signing_secret, timestamp, raw_body.decode())

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.owner_id = uuid.uuid4()
        mock_workflow.nodes = [
            {
                "id": node_id,
                "type": "slackTrigger",
                "data": {"label": "slackTrigger", "credentialId": str(uuid.uuid4())},
            }
        ]
        mock_workflow.edges = []

        request = _make_request(
            raw_body,
            {
                "x-slack-request-timestamp": timestamp,
                "x-slack-signature": signature,
                "content-type": "application/json",
            },
        )

        with (
            patch(
                "app.api.slack._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.slack._get_signing_secret",
                new=AsyncMock(return_value=signing_secret),
            ),
            patch(
                "app.api.slack._execute_workflow_background",
                new=AsyncMock(),
            ) as mock_bg,
        ):
            response = await slack_webhook(node_id, request)

        self.assertEqual(response, {"ok": True})
        mock_bg.assert_called_once()


class TestSlackInvalidSignature(unittest.IsolatedAsyncioTestCase):
    """Wrong HMAC → 403, workflow not executed."""

    async def test_invalid_signature_returns_403(self) -> None:
        from app.api.slack import slack_webhook

        node_id = str(uuid.uuid4())
        timestamp = str(int(time.time()))
        body_dict = {"type": "message", "event": {}}
        raw_body = json.dumps(body_dict).encode()

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {"id": node_id, "type": "slackTrigger", "data": {"credentialId": "cred-1"}}
        ]

        request = _make_request(
            raw_body,
            {
                "x-slack-request-timestamp": timestamp,
                "x-slack-signature": "v0=badhash",
                "content-type": "application/json",
            },
        )

        with (
            patch(
                "app.api.slack._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.slack._get_signing_secret",
                new=AsyncMock(return_value="real_secret"),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await slack_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 403)


class TestSlackReplayAttack(unittest.IsolatedAsyncioTestCase):
    """Timestamp > 5 min old → 403 regardless of otherwise valid signature."""

    async def test_old_timestamp_returns_403(self) -> None:
        from app.api.slack import slack_webhook

        node_id = str(uuid.uuid4())
        signing_secret = "secret"
        old_timestamp = str(int(time.time()) - 400)  # 400 seconds ago, beyond 300s tolerance
        body_dict = {"type": "message", "event": {}}
        raw_body = json.dumps(body_dict).encode()
        signature = _make_signature(signing_secret, old_timestamp, raw_body.decode())

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {"id": node_id, "type": "slackTrigger", "data": {"credentialId": "cred-1"}}
        ]

        request = _make_request(
            raw_body,
            {
                "x-slack-request-timestamp": old_timestamp,
                "x-slack-signature": signature,
                "content-type": "application/json",
            },
        )

        with (
            patch(
                "app.api.slack._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.slack._get_signing_secret",
                new=AsyncMock(return_value=signing_secret),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await slack_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 403)


class TestSlackUnknownNode(unittest.IsolatedAsyncioTestCase):
    """node_id not found in any workflow → 404."""

    async def test_unknown_node_id_returns_404(self) -> None:
        from app.api.slack import slack_webhook

        node_id = str(uuid.uuid4())
        body_dict = {"type": "message", "event": {}}
        raw_body = json.dumps(body_dict).encode()
        request = _make_request(raw_body, {"content-type": "application/json"})

        with patch(
            "app.api.slack._find_workflow_by_node_id",
            new=AsyncMock(return_value=None),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await slack_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
