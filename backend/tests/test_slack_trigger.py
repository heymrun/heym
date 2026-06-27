"""Unit tests for the Slack webhook endpoint."""

import hashlib
import hmac
import json
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.datastructures import Headers

from app.db.models import ExecutionHistory
from app.services.workflow_executor import ExecutionResult


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

    async def test_background_execution_persists_trigger_input_fields(self) -> None:
        from app.api.slack import _execute_workflow_background

        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=owner_id,
            name="Slack workflow",
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
            patch("app.api.slack.async_session_maker") as mock_session_maker,
            patch("app.api.slack.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.slack.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.slack.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.slack.execute_workflow", return_value=execution_result),
            patch("app.api.slack.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.slack._persist_global_variables_from_execution", AsyncMock()),
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = db
            mock_session.__aexit__.return_value = None
            mock_session_maker.return_value = mock_session

            await _execute_workflow_background(
                workflow,
                "slack-node",
                {"event": {"type": "message", "text": "hello"}},
                {"x-slack-request-timestamp": "123"},
            )

        history = next(row for row in added_rows if isinstance(row, ExecutionHistory))
        self.assertEqual(history.trigger_source, "Slack")
        self.assertEqual(history.inputs["triggered_by"], "Slack")
        self.assertEqual(history.inputs["trigger_node_id"], "slack-node")
        self.assertEqual(history.inputs["event"]["event"]["text"], "hello")


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


class TestSlackFailClosedNoCredential(unittest.IsolatedAsyncioTestCase):
    """Regression for GHSA-pm6h-x3h5-j38h finding H1.

    Slack webhook must reject with 400 when the trigger node has no credentialId.
    Previously this case fell through and triggered the workflow with the owner's
    credentials. Client-facing message is the generic
    "invalid webhook credential configuration" so probing the webhook URL doesn't
    reveal which nodes are misconfigured.
    """

    async def test_no_credential_id_returns_400(self) -> None:
        from app.api.slack import slack_webhook

        node_id = str(uuid.uuid4())
        raw_body = json.dumps({"type": "message", "event": {}}).encode()
        request = _make_request(raw_body, {"content-type": "application/json"})

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {
                "id": node_id,
                "type": "slackTrigger",
                "data": {},  # no credentialId
            }
        ]

        with (
            patch(
                "app.api.slack._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.slack._execute_workflow_background",
                new=AsyncMock(return_value=None),
            ) as mock_execute_background,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await slack_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "invalid webhook credential configuration")
        mock_execute_background.assert_not_awaited()


class TestSlackFailClosedEmptySecret(unittest.IsolatedAsyncioTestCase):
    """Slack webhook must reject with 400 when the credential exists but has an
    empty signing_secret. Previously this case fell through and triggered the
    workflow with the owner's credentials.
    """

    async def test_empty_signing_secret_returns_400(self) -> None:
        from app.api.slack import slack_webhook

        node_id = str(uuid.uuid4())
        credential_id = str(uuid.uuid4())
        raw_body = json.dumps({"type": "message", "event": {}}).encode()
        request = _make_request(raw_body, {"content-type": "application/json"})

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {
                "id": node_id,
                "type": "slackTrigger",
                "data": {"credentialId": credential_id},
            }
        ]

        with (
            patch(
                "app.api.slack._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.slack._get_signing_secret",
                new=AsyncMock(return_value=""),  # empty secret
            ),
            patch(
                "app.api.slack._execute_workflow_background",
                new=AsyncMock(return_value=None),
            ) as mock_execute_background,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await slack_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "invalid webhook credential configuration")
        mock_execute_background.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
