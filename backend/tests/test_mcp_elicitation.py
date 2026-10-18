"""MCP client capabilities and URL-mode elicitation across both transports."""

import asyncio
import json
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request

from app.api.mcp import handle_mcp_message, mcp_sse_post_endpoint
from app.api.mcp_servers import named_server_sse_post
from app.services.mcp_elicitation import (
    FALLBACK_PROTOCOL_VERSION,
    LATEST_PROTOCOL_VERSION,
    MCP_SESSION_HEADER,
    MCPClientChannel,
    decode_client_session,
    elicitation_complete_notification,
    elicitation_modes,
    encode_client_session,
    is_client_response,
    negotiate_protocol_version,
    parse_elicitation_reply,
    url_elicitation_request,
)
from app.services.mcp_session import MCPSSEChannelStore, mcp_session_store, mcp_sse_channels


def _request(
    path: str,
    body: dict[str, Any],
    *,
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": headers or [],
            "query_string": query_string,
        },
        receive,
    )


def _initialize(capabilities: dict[str, Any], version: str = "2025-11-25") -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": version,
            "capabilities": capabilities,
            "clientInfo": {"name": "test", "version": "1"},
        },
    }


def _tool_call(msg_id: str = "call-1") -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": "tools/call",
        "params": {"name": "heym_chat", "arguments": {"message": "hi"}},
    }


class _FakeSessionContext:
    def __init__(self) -> None:
        self.session = AsyncMock()

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


class ProtocolVersionTests(unittest.TestCase):
    def test_a_version_heym_speaks_is_echoed(self) -> None:
        for version in ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"):
            self.assertEqual(negotiate_protocol_version(version), version)

    def test_a_newer_version_gets_the_latest(self) -> None:
        self.assertEqual(negotiate_protocol_version("2026-06-01"), LATEST_PROTOCOL_VERSION)

    def test_anything_else_keeps_the_old_answer(self) -> None:
        for requested in (None, "", "2024-10-07", 3):
            self.assertEqual(negotiate_protocol_version(requested), FALLBACK_PROTOCOL_VERSION)


class ElicitationModesTests(unittest.TestCase):
    def test_declared_modes(self) -> None:
        cases = [
            (None, frozenset()),
            ({}, frozenset()),
            ({"elicitation": {}}, frozenset({"form"})),
            ({"elicitation": {"url": {}}}, frozenset({"url"})),
            ({"elicitation": {"form": {}, "url": {}}}, frozenset({"form", "url"})),
        ]
        for capabilities, expected in cases:
            with self.subTest(capabilities=capabilities):
                self.assertEqual(elicitation_modes(capabilities), expected)

    def test_session_id_round_trips_for_the_same_user_and_server(self) -> None:
        user_id, server_id = uuid.uuid4(), uuid.uuid4()
        token = encode_client_session(
            user_id=user_id, server_id=server_id, modes=frozenset({"url"})
        )

        self.assertEqual(
            decode_client_session(token, user_id=user_id, server_id=server_id),
            frozenset({"url"}),
        )
        self.assertEqual(
            decode_client_session(token, user_id=uuid.uuid4(), server_id=server_id), frozenset()
        )
        self.assertEqual(decode_client_session(token, user_id=user_id, server_id=None), frozenset())

    def test_other_tokens_declare_nothing(self) -> None:
        user_id = uuid.uuid4()
        sse_token = mcp_session_store.create(str(user_id))
        for token in (None, "", "not-a-jwt", sse_token):
            with self.subTest(token=token):
                self.assertEqual(
                    decode_client_session(token, user_id=user_id, server_id=None), frozenset()
                )

    def test_sse_channels_forget_modes_with_the_session(self) -> None:
        store = MCPSSEChannelStore()
        store.set_elicitation_modes("gone", frozenset({"url"}))
        self.assertEqual(store.elicitation_modes("gone"), frozenset())

        store.register("live")
        store.set_elicitation_modes("live", frozenset({"url"}))
        self.assertEqual(store.elicitation_modes("live"), frozenset({"url"}))
        store.unregister("live")
        self.assertEqual(store.elicitation_modes("live"), frozenset())


class ElicitationMessageTests(unittest.TestCase):
    def test_url_request_and_reply_share_the_elicitation_id(self) -> None:
        elicitation_id = uuid.uuid4()
        request = url_elicitation_request(elicitation_id, "https://heym.run/x", "Add a key")

        self.assertEqual(request["method"], "elicitation/create")
        self.assertEqual(
            request["params"],
            {
                "mode": "url",
                "elicitationId": str(elicitation_id),
                "url": "https://heym.run/x",
                "message": "Add a key",
            },
        )
        for action in ("accept", "decline", "cancel"):
            reply = parse_elicitation_reply(
                {"jsonrpc": "2.0", "id": request["id"], "result": {"action": action}}
            )
            self.assertEqual((reply.elicitation_id, reply.action), (elicitation_id, action))
        error = parse_elicitation_reply(
            {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32602, "message": "no"}}
        )
        self.assertEqual(error.action, "error")

    def test_other_replies_are_ignored(self) -> None:
        for body in (
            {"jsonrpc": "2.0", "id": 4, "result": {"action": "accept"}},
            {"jsonrpc": "2.0", "id": "heym-elicit-nope", "result": {"action": "accept"}},
            {"jsonrpc": "2.0", "id": f"heym-elicit-{uuid.uuid4()}", "result": {"action": "x"}},
        ):
            self.assertIsNone(parse_elicitation_reply(body))

    def test_only_replies_count_as_client_responses(self) -> None:
        self.assertTrue(is_client_response({"jsonrpc": "2.0", "id": "a", "result": {}}))
        self.assertTrue(is_client_response({"jsonrpc": "2.0", "id": "a", "error": {}}))
        self.assertFalse(is_client_response(_tool_call()))
        self.assertFalse(is_client_response({"jsonrpc": "2.0", "method": "notifications/x"}))
        self.assertFalse(is_client_response([{"jsonrpc": "2.0", "id": "a", "result": {}}]))

    def test_completion_notification(self) -> None:
        elicitation_id = uuid.uuid4()
        self.assertEqual(
            elicitation_complete_notification(elicitation_id),
            {
                "jsonrpc": "2.0",
                "method": "notifications/elicitation/complete",
                "params": {"elicitationId": str(elicitation_id)},
            },
        )


class StreamableTransportTests(unittest.IsolatedAsyncioTestCase):
    async def _post(self, body: dict[str, Any], **kwargs: Any) -> Any:
        with patch(
            "app.api.mcp.async_session_maker", MagicMock(return_value=_FakeSessionContext())
        ):
            return await mcp_sse_post_endpoint(
                request=_request("/api/mcp/sse", body, **kwargs),
                mcp_user=SimpleNamespace(id=self.user_id),
            )

    def setUp(self) -> None:
        self.user_id = uuid.uuid4()

    async def test_initialize_negotiates_and_hands_out_a_session_id(self) -> None:
        response = await self._post(_initialize({"elicitation": {"url": {}}}))

        payload = json.loads(response.body)
        self.assertEqual(payload["result"]["protocolVersion"], "2025-11-25")
        token = response.headers[MCP_SESSION_HEADER]
        self.assertEqual(
            decode_client_session(token, user_id=self.user_id, server_id=None),
            frozenset({"url"}),
        )

    async def test_an_old_client_keeps_its_version(self) -> None:
        response = await self._post(_initialize({}, version="2024-11-05"))

        self.assertEqual(json.loads(response.body)["result"]["protocolVersion"], "2024-11-05")

    async def test_tool_calls_reach_the_client_on_their_own_stream(self) -> None:
        token = encode_client_session(
            user_id=self.user_id, server_id=None, modes=frozenset({"url"})
        )
        seen: dict[str, MCPClientChannel] = {}
        elicitation = url_elicitation_request(uuid.uuid4(), "https://heym.run/x", "Add a key")

        async def fake_dispatch(*_args: object, **kwargs: Any) -> dict[str, Any]:
            client = kwargs["client"]
            seen["client"] = client
            await client.send(elicitation)
            return {"jsonrpc": "2.0", "id": "call-1", "result": {"content": [], "isError": False}}

        with (
            patch("app.api.mcp._dispatch_mcp_jsonrpc", AsyncMock(side_effect=fake_dispatch)),
            patch("app.api.mcp.async_session_maker", MagicMock(return_value=_FakeSessionContext())),
        ):
            response = await mcp_sse_post_endpoint(
                request=_request(
                    "/api/mcp/sse",
                    _tool_call(),
                    headers=[(MCP_SESSION_HEADER.lower().encode(), token.encode())],
                ),
                mcp_user=SimpleNamespace(id=self.user_id),
            )
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        self.assertTrue(seen["client"].supports_url_elicitation)
        messages = [c for c in chunks if c.startswith("event: message")]
        self.assertIn('"method": "elicitation/create"', messages[0])
        self.assertIn('"id": "call-1"', messages[-1])

    async def test_a_client_reply_is_stored_and_accepted(self) -> None:
        elicitation_id = uuid.uuid4()
        record = AsyncMock()
        session_context = _FakeSessionContext()
        with (
            patch("app.api.mcp.record_elicitation_reply", record),
            patch("app.api.mcp.async_session_maker", MagicMock(return_value=session_context)),
        ):
            response = await mcp_sse_post_endpoint(
                request=_request(
                    "/api/mcp/sse",
                    {
                        "jsonrpc": "2.0",
                        "id": f"heym-elicit-{elicitation_id}",
                        "result": {"action": "decline"},
                    },
                ),
                mcp_user=SimpleNamespace(id=self.user_id),
            )

        self.assertEqual(response.status_code, 202)
        _db, user_id, reply = record.await_args.args
        self.assertEqual(
            (user_id, reply.elicitation_id, reply.action), (self.user_id, elicitation_id, "decline")
        )
        session_context.session.commit.assert_awaited_once()

    async def test_named_server_session_ids_are_bound_to_the_server(self) -> None:
        server = SimpleNamespace(id=uuid.uuid4())
        with patch(
            "app.api.mcp.async_session_maker", MagicMock(return_value=_FakeSessionContext())
        ):
            response = await named_server_sse_post(
                server_id=server.id,
                request=_request(
                    f"/api/mcp/servers/{server.id}/sse", _initialize({"elicitation": {"url": {}}})
                ),
                server=(SimpleNamespace(id=self.user_id), server),
            )

        token = response.headers[MCP_SESSION_HEADER]
        self.assertEqual(
            decode_client_session(token, user_id=self.user_id, server_id=server.id),
            frozenset({"url"}),
        )
        self.assertEqual(
            decode_client_session(token, user_id=self.user_id, server_id=None), frozenset()
        )


class LegacySSETransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        mcp_sse_channels.unregister("elicit-session")

    async def test_initialize_declares_modes_and_tool_calls_get_them(self) -> None:
        queue = mcp_sse_channels.register("elicit-session")
        user = SimpleNamespace(id=uuid.uuid4())

        await handle_mcp_message(
            request=_request(
                "/api/mcp/message",
                _initialize({"elicitation": {"form": {}, "url": {}}}),
                query_string=b"session=elicit-session",
            ),
            mcp_user=user,
            db=AsyncMock(),
        )
        initialized = json.loads(await asyncio.wait_for(queue.get(), timeout=0.2))
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(
            mcp_sse_channels.elicitation_modes("elicit-session"), frozenset({"form", "url"})
        )

        seen: dict[str, MCPClientChannel] = {}

        async def fake_dispatch(*_args: object, **kwargs: Any) -> dict[str, Any]:
            seen["client"] = kwargs["client"]
            await kwargs["client"].send(elicitation_complete_notification(uuid.uuid4()))
            return {"jsonrpc": "2.0", "id": "call-1", "result": {"content": [], "isError": False}}

        with (
            patch("app.api.mcp._dispatch_mcp_jsonrpc", AsyncMock(side_effect=fake_dispatch)),
            patch("app.api.mcp.async_session_maker", MagicMock(return_value=_FakeSessionContext())),
        ):
            response = await handle_mcp_message(
                request=_request(
                    "/api/mcp/message", _tool_call(), query_string=b"session=elicit-session"
                ),
                mcp_user=user,
                db=AsyncMock(),
            )
            self.assertEqual(response.status_code, 202)
            notification = json.loads(await asyncio.wait_for(queue.get(), timeout=0.5))
            final = json.loads(await asyncio.wait_for(queue.get(), timeout=0.5))

        self.assertTrue(seen["client"].supports_url_elicitation)
        self.assertEqual(notification["method"], "notifications/elicitation/complete")
        self.assertEqual(final["id"], "call-1")


if __name__ == "__main__":
    unittest.main()
