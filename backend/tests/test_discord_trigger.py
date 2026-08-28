"""Unit tests for the Discord Interactions webhook endpoint."""

import json
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from starlette.datastructures import Headers

from app.db.models import ExecutionHistory
from app.services.workflow_executor import ExecutionResult


def _generate_keypair() -> tuple[str, Ed25519PrivateKey]:
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = private_key.public_key().public_bytes_raw().hex()
    return public_key_hex, private_key


def _make_signature(
    private_key: Ed25519PrivateKey,
    timestamp: str,
    body: str,
) -> str:
    message = timestamp.encode("utf-8") + body.encode("utf-8")
    return private_key.sign(message).hex()


def _make_request(body_bytes: bytes, headers: dict) -> MagicMock:
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/discord/webhook/test",
        "headers": Headers(headers).raw,
        "query_string": b"",
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    return Request(scope, receive)


class TestDiscordPing(unittest.IsolatedAsyncioTestCase):
    async def test_ping_requires_valid_signature_and_returns_pong(self) -> None:
        from app.api.discord import discord_webhook

        public_key_hex, private_key = _generate_keypair()
        node_id = str(uuid.uuid4())
        timestamp = str(int(time.time()))
        body_dict = {"type": 1}
        raw_body = json.dumps(body_dict).encode()
        signature = _make_signature(private_key, timestamp, raw_body.decode())

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {
                "id": node_id,
                "type": "discordTrigger",
                "data": {"credentialId": str(uuid.uuid4())},
            }
        ]

        request = _make_request(
            raw_body,
            {
                "content-type": "application/json",
                "x-signature-timestamp": timestamp,
                "x-signature-ed25519": signature,
            },
        )

        with (
            patch(
                "app.api.discord._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ) as mock_find,
            patch(
                "app.api.discord._get_public_key",
                new=AsyncMock(return_value=public_key_hex),
            ),
        ):
            response = await discord_webhook(node_id, request)

        self.assertEqual(response, {"type": 1})
        mock_find.assert_awaited_once()

    async def test_ping_with_invalid_signature_returns_401(self) -> None:
        from app.api.discord import discord_webhook

        public_key_hex, _private_key = _generate_keypair()
        node_id = str(uuid.uuid4())
        timestamp = str(int(time.time()))
        raw_body = json.dumps({"type": 1}).encode()

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {
                "id": node_id,
                "type": "discordTrigger",
                "data": {"credentialId": str(uuid.uuid4())},
            }
        ]

        request = _make_request(
            raw_body,
            {
                "content-type": "application/json",
                "x-signature-timestamp": timestamp,
                "x-signature-ed25519": "bad" * 16,
            },
        )

        with (
            patch(
                "app.api.discord._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.discord._get_public_key",
                new=AsyncMock(return_value=public_key_hex),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await discord_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 401)


class TestDiscordValidSignature(unittest.IsolatedAsyncioTestCase):
    async def test_valid_interaction_triggers_workflow(self) -> None:
        from app.api.discord import discord_webhook

        public_key_hex, private_key = _generate_keypair()
        node_id = str(uuid.uuid4())
        timestamp = str(int(time.time()))
        body_dict = {
            "type": 2,
            "token": "interaction-token",
            "data": {"name": "hello", "options": []},
        }
        raw_body = json.dumps(body_dict).encode()
        signature = _make_signature(private_key, timestamp, raw_body.decode())

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.owner_id = uuid.uuid4()
        mock_workflow.nodes = [
            {
                "id": node_id,
                "type": "discordTrigger",
                "data": {"label": "discordTrigger", "credentialId": str(uuid.uuid4())},
            }
        ]
        mock_workflow.edges = []

        request = _make_request(
            raw_body,
            {
                "x-signature-timestamp": timestamp,
                "x-signature-ed25519": signature,
                "content-type": "application/json",
            },
        )

        with (
            patch(
                "app.api.discord._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.discord._get_public_key",
                new=AsyncMock(return_value=public_key_hex),
            ),
            patch(
                "app.api.discord._execute_workflow_background",
                new=AsyncMock(),
            ) as mock_bg,
        ):
            response = await discord_webhook(node_id, request)

        self.assertEqual(response, {"type": 5})
        mock_bg.assert_called_once()

    async def test_background_execution_persists_trigger_input_fields(self) -> None:
        from app.api.discord import _execute_workflow_background

        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=owner_id,
            name="Discord workflow",
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
            patch("app.api.discord.async_session_maker") as mock_session_maker,
            patch("app.api.discord.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.discord.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.discord.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.discord.dispatch_workflow", AsyncMock(return_value=execution_result)),
            patch("app.api.discord.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.discord._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.discord._send_discord_followup_message", AsyncMock()),
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = db
            mock_session.__aexit__.return_value = None
            mock_session_maker.return_value = mock_session

            await _execute_workflow_background(
                workflow,
                "discord-node",
                {"type": 2, "token": "interaction-token", "data": {"name": "hello"}},
                {"x-signature-timestamp": "123"},
            )

        history = next(row for row in added_rows if isinstance(row, ExecutionHistory))
        self.assertEqual(history.trigger_source, "Discord")
        self.assertEqual(history.inputs["triggered_by"], "Discord")
        self.assertEqual(history.inputs["trigger_node_id"], "discord-node")
        self.assertEqual(history.inputs["data"]["name"], "hello")
        self.assertIn("triggered_at", history.inputs)


class TestDiscordInvalidSignature(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_signature_returns_401(self) -> None:
        from app.api.discord import discord_webhook

        public_key_hex, _private_key = _generate_keypair()
        node_id = str(uuid.uuid4())
        timestamp = str(int(time.time()))
        body_dict = {"type": 2, "data": {"name": "hello"}}
        raw_body = json.dumps(body_dict).encode()

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {"id": node_id, "type": "discordTrigger", "data": {"credentialId": "cred-1"}}
        ]

        request = _make_request(
            raw_body,
            {
                "x-signature-timestamp": timestamp,
                "x-signature-ed25519": "bad" * 16,
                "content-type": "application/json",
            },
        )

        with (
            patch(
                "app.api.discord._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.discord._get_public_key",
                new=AsyncMock(return_value=public_key_hex),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await discord_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 401)


class TestDiscordReplayAttack(unittest.IsolatedAsyncioTestCase):
    async def test_old_timestamp_returns_401(self) -> None:
        from app.api.discord import discord_webhook

        public_key_hex, private_key = _generate_keypair()
        node_id = str(uuid.uuid4())
        old_timestamp = str(int(time.time()) - 400)
        body_dict = {"type": 2, "data": {"name": "hello"}}
        raw_body = json.dumps(body_dict).encode()
        signature = _make_signature(private_key, old_timestamp, raw_body.decode())

        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {"id": node_id, "type": "discordTrigger", "data": {"credentialId": "cred-1"}}
        ]

        request = _make_request(
            raw_body,
            {
                "x-signature-timestamp": old_timestamp,
                "x-signature-ed25519": signature,
                "content-type": "application/json",
            },
        )

        with (
            patch(
                "app.api.discord._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.discord._get_public_key",
                new=AsyncMock(return_value=public_key_hex),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await discord_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 401)


class TestDiscordUnknownNode(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_node_id_returns_404(self) -> None:
        from app.api.discord import discord_webhook

        node_id = str(uuid.uuid4())
        body_dict = {"type": 2, "data": {"name": "hello"}}
        raw_body = json.dumps(body_dict).encode()
        request = _make_request(raw_body, {"content-type": "application/json"})

        with patch(
            "app.api.discord._find_workflow_by_node_id",
            new=AsyncMock(return_value=None),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await discord_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 404)


class TestDiscordCredentialRequirements(unittest.IsolatedAsyncioTestCase):
    async def test_missing_credential_returns_400(self) -> None:
        from app.api.discord import discord_webhook

        node_id = str(uuid.uuid4())
        raw_body = json.dumps({"type": 2, "data": {"name": "hello"}}).encode()
        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [{"id": node_id, "type": "discordTrigger", "data": {}}]
        request = _make_request(raw_body, {"content-type": "application/json"})

        with patch(
            "app.api.discord._find_workflow_by_node_id",
            new=AsyncMock(return_value=mock_workflow),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await discord_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("credential", ctx.exception.detail.lower())

    async def test_unresolvable_public_key_returns_400(self) -> None:
        from app.api.discord import discord_webhook

        node_id = str(uuid.uuid4())
        raw_body = json.dumps({"type": 2, "data": {"name": "hello"}}).encode()
        mock_workflow = MagicMock()
        mock_workflow.id = uuid.uuid4()
        mock_workflow.nodes = [
            {
                "id": node_id,
                "type": "discordTrigger",
                "data": {"credentialId": str(uuid.uuid4())},
            }
        ]
        request = _make_request(raw_body, {"content-type": "application/json"})

        with (
            patch(
                "app.api.discord._find_workflow_by_node_id",
                new=AsyncMock(return_value=mock_workflow),
            ),
            patch(
                "app.api.discord._get_public_key",
                new=AsyncMock(return_value=None),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await discord_webhook(node_id, request)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("public key", ctx.exception.detail.lower())


class TestDiscordFollowUpHelpers(unittest.IsolatedAsyncioTestCase):
    async def test_send_followup_uses_output_result(self) -> None:
        from app.api.discord import _send_discord_followup_message

        interaction_body = {
            "application_id": "1234567890",
            "token": "interaction-token",
        }
        workflow_outputs = {"reply": {"result": "Hello from workflow"}}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"id":"1"}'

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_client_factory = MagicMock()
        mock_client_factory.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_factory.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.discord.httpx.AsyncClient", return_value=mock_client_factory):
            await _send_discord_followup_message(interaction_body, workflow_outputs)

        mock_client.post.assert_awaited_once_with(
            "https://discord.com/api/v10/webhooks/1234567890/interaction-token",
            json={"content": "Hello from workflow"},
        )

    async def test_send_followup_skips_empty_outputs(self) -> None:
        from app.api.discord import _send_discord_followup_message

        interaction_body = {
            "application_id": "1234567890",
            "token": "interaction-token",
        }

        mock_client = MagicMock()
        mock_client.post = AsyncMock()

        mock_client_factory = MagicMock()
        mock_client_factory.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_factory.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.discord.httpx.AsyncClient", return_value=mock_client_factory):
            await _send_discord_followup_message(interaction_body, {"reply": {"result": "   "}})

        mock_client.post.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
