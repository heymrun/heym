"""
Tests for MCP SSE endpoint origin-mismatch fix (issue #78).

BEFORE (broken)
---------------
All SSE endpoints called `str(request.base_url)` to build the message endpoint URL.
In a reverse-proxy / Docker deployment, `request.base_url` reflects the *internal*
container address (e.g. http://127.0.0.1:10105/), not the public domain.

The MCP client connects from the public origin (https://aiwf.asuka.com.tr) and then
receives a message endpoint URL like:

    http://127.0.0.1:10105/api/mcp/servers/<id>/message?session=tok

Python MCP SDK and mcpo both enforce same-origin validation between the SSE connection
origin and the message endpoint origin, so the connection is rejected with:

    "Endpoint origin does not match connection origin"

AFTER (fixed)
-------------
1. SSE endpoints (/sse, /{server_id}/sse) now return *relative* URLs:
       /api/mcp/message?session=tok
       /api/mcp/servers/<id>/message?session=tok
   The client resolves them against the origin it connected from — no mismatch.

2. The /config endpoint (returns the SSE URL for users to configure their MCP clients)
   now reads X-Forwarded-Proto and X-Forwarded-Host headers set by the reverse proxy
   to reconstruct the correct public URL. Falls back to request.base_url when those
   headers are absent (local / direct access).
"""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request

from app.api.mcp import get_mcp_config, handle_mcp_message, mcp_sse_endpoint
from app.api.mcp_servers import handle_named_server_message, named_server_sse
from app.config import settings
from app.models.schemas import MCPInitializeResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    base_url: str = "http://127.0.0.1:10105/", headers: dict | None = None
) -> MagicMock:
    """Build a minimal Starlette Request mock."""
    req = MagicMock()
    req.base_url = base_url  # str() on a string is a no-op → safe for str(request.base_url)
    _headers = headers or {}
    req.headers.get = MagicMock(side_effect=lambda key, default=None: _headers.get(key, default))
    req.is_disconnected = AsyncMock(return_value=True)  # disconnect after first chunk
    return req


async def _first_sse_event(response) -> str:
    """Collect the first SSE chunk from a StreamingResponse."""
    async for chunk in response.body_iterator:
        return chunk
    return ""


def _make_empty_db() -> AsyncMock:
    """DB mock that returns empty scalars — sufficient for get_mcp_config."""
    db = AsyncMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=[])
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    db.execute = AsyncMock(return_value=result)
    return db


def _make_json_request(path: str, body: dict, query_string: bytes = b"") -> Request:
    async def receive() -> dict[str, object]:
        return {
            "type": "http.request",
            "body": json.dumps(body).encode("utf-8"),
            "more_body": False,
        }

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"content-type", b"application/json")],
            "query_string": query_string,
        },
        receive,
    )


class MCPInitializeVersionTests(unittest.TestCase):
    def test_initialize_result_uses_application_version(self) -> None:
        result = MCPInitializeResult()

        self.assertEqual(result.serverInfo.version, settings.resolved_version)
        self.assertNotEqual(result.serverInfo.version, "1.0.0")


# ---------------------------------------------------------------------------
# /sse  (default MCP endpoint)
# ---------------------------------------------------------------------------


class DefaultSSEOriginTests(unittest.IsolatedAsyncioTestCase):
    """Tests for mcp_sse_endpoint in app/api/mcp.py."""

    @patch("app.api.mcp.mcp_session_store")
    async def test_returns_relative_url_when_behind_proxy(self, mock_store: MagicMock) -> None:
        """
        AFTER: SSE event contains a relative message URL even when base_url is internal.

        BEFORE this fix the event data would have been:
            http://127.0.0.1:10105/api/mcp/message?session=tok
        which causes origin mismatch in MCP clients.
        """
        mock_store.create.return_value = "tok"
        # Simulate reverse-proxy: backend sees internal address
        request = _make_request("http://127.0.0.1:10105/")
        user = SimpleNamespace(id=uuid.uuid4())

        response = await mcp_sse_endpoint(request=request, mcp_user=user, db=AsyncMock())
        event = await _first_sse_event(response)

        self.assertIn("event: endpoint", event)
        self.assertIn("/api/mcp/message?session=tok", event)
        # Internal host must not leak into the SSE event
        self.assertNotIn("127.0.0.1", event)
        self.assertNotIn("http://", event)

    @patch("app.api.mcp.mcp_session_store")
    async def test_returns_relative_url_when_accessed_directly(self, mock_store: MagicMock) -> None:
        """
        AFTER: relative URL is also correct for direct (non-proxy) access.
        Client resolves /api/mcp/message against localhost:10105 itself.
        """
        mock_store.create.return_value = "local-tok"
        request = _make_request("http://localhost:10105/")
        user = SimpleNamespace(id=uuid.uuid4())

        response = await mcp_sse_endpoint(request=request, mcp_user=user, db=AsyncMock())
        event = await _first_sse_event(response)

        self.assertIn("/api/mcp/message?session=local-tok", event)
        self.assertNotIn("localhost", event)
        self.assertNotIn("http://", event)

    @patch("app.api.mcp.mcp_session_store")
    async def test_session_token_is_embedded_in_url(self, mock_store: MagicMock) -> None:
        """Session token produced by mcp_session_store is present in the endpoint URL."""
        mock_store.create.return_value = "unique-session-xyz"
        request = _make_request()
        user = SimpleNamespace(id=uuid.uuid4())

        response = await mcp_sse_endpoint(request=request, mcp_user=user, db=AsyncMock())
        event = await _first_sse_event(response)

        self.assertIn("session=unique-session-xyz", event)

    @patch("app.api.mcp.mcp_session_store")
    async def test_message_response_is_sent_over_sse_stream(self, mock_store: MagicMock) -> None:
        """Legacy SSE transport receives JSON-RPC responses as event: message."""
        mock_store.create.return_value = "stream-tok"
        request = _make_request()
        request.is_disconnected = AsyncMock(return_value=False)
        user = SimpleNamespace(id=uuid.uuid4())

        response = await mcp_sse_endpoint(request=request, mcp_user=user, db=AsyncMock())
        body_iterator = response.body_iterator
        first_event = await body_iterator.__anext__()

        post_response = await handle_mcp_message(
            request=_make_json_request(
                "/api/mcp/message",
                {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                b"session=stream-tok",
            ),
            mcp_user=user,
            db=AsyncMock(),
        )
        message_event = await body_iterator.__anext__()
        await body_iterator.aclose()

        self.assertEqual(post_response.status_code, 202)
        self.assertIn("event: endpoint", first_event)
        self.assertIn("event: message", message_event)
        self.assertIn('"id": 1', message_event)
        self.assertIn('"result"', message_event)


# ---------------------------------------------------------------------------
# /{server_id}/sse  (named server endpoint)
# ---------------------------------------------------------------------------


class NamedServerSSEOriginTests(unittest.IsolatedAsyncioTestCase):
    """Tests for named_server_sse in app/api/mcp_servers.py."""

    @patch("app.api.mcp_servers.mcp_session_store")
    async def test_returns_relative_url_when_behind_proxy(self, mock_store: MagicMock) -> None:
        """
        AFTER: named SSE event contains a relative message URL.

        BEFORE this fix the event data would have been:
            http://127.0.0.1:10105/api/mcp/servers/<id>/message?session=tok
        """
        mock_store.create.return_value = "named-tok"
        server_id = uuid.uuid4()
        user = SimpleNamespace(id=uuid.uuid4())
        mcp_server = SimpleNamespace(id=server_id)
        request = _make_request("http://127.0.0.1:10105/")

        response = await named_server_sse(
            server_id=server_id,
            request=request,
            server=(user, mcp_server),
        )
        event = await _first_sse_event(response)

        expected_path = f"/api/mcp/servers/{server_id}/message?session=named-tok"
        self.assertIn("event: endpoint", event)
        self.assertIn(expected_path, event)
        self.assertNotIn("127.0.0.1", event)
        self.assertNotIn("http://", event)

    @patch("app.api.mcp_servers.mcp_session_store")
    async def test_server_id_is_embedded_in_url(self, mock_store: MagicMock) -> None:
        """The correct server_id appears in the relative message path."""
        mock_store.create.return_value = "tok-2"
        server_id = uuid.uuid4()
        user = SimpleNamespace(id=uuid.uuid4())
        mcp_server = SimpleNamespace(id=server_id)
        request = _make_request()

        response = await named_server_sse(
            server_id=server_id,
            request=request,
            server=(user, mcp_server),
        )
        event = await _first_sse_event(response)

        self.assertIn(str(server_id), event)

    @patch("app.api.mcp_servers.mcp_session_store")
    async def test_named_message_response_is_sent_over_sse_stream(
        self, mock_store: MagicMock
    ) -> None:
        """Named legacy SSE transport also emits JSON-RPC responses on SSE."""
        mock_store.create.return_value = "named-stream-tok"
        server_id = uuid.uuid4()
        user = SimpleNamespace(id=uuid.uuid4())
        mcp_server = SimpleNamespace(id=server_id)
        request = _make_request()
        request.is_disconnected = AsyncMock(return_value=False)

        response = await named_server_sse(
            server_id=server_id,
            request=request,
            server=(user, mcp_server),
        )
        body_iterator = response.body_iterator
        first_event = await body_iterator.__anext__()

        post_response = await handle_named_server_message(
            server_id=server_id,
            request=_make_json_request(
                f"/api/mcp/servers/{server_id}/message",
                {"jsonrpc": "2.0", "id": "init-1", "method": "initialize"},
                b"session=named-stream-tok",
            ),
            server=(user, mcp_server),
            db=AsyncMock(),
        )
        message_event = await body_iterator.__anext__()
        await body_iterator.aclose()

        self.assertEqual(post_response.status_code, 202)
        self.assertIn("event: endpoint", first_event)
        self.assertIn("event: message", message_event)
        self.assertIn('"id": "init-1"', message_event)
        self.assertIn('"result"', message_event)


# ---------------------------------------------------------------------------
# /config  (returns absolute SSE URL for client-side configuration)
# ---------------------------------------------------------------------------


class MCPConfigURLTests(unittest.IsolatedAsyncioTestCase):
    """Tests for get_mcp_config in app/api/mcp.py."""

    @patch("app.api.mcp.get_all_user_workflows", new_callable=AsyncMock, return_value=[])
    async def test_config_uses_forwarded_headers_over_internal_base_url(self, _: AsyncMock) -> None:
        """
        AFTER: X-Forwarded-Proto + X-Forwarded-Host produce the public SSE URL.

        BEFORE this fix, request.base_url ("http://127.0.0.1:10105/") was used directly,
        producing an unusable URL for users copying it into their MCP client config.
        """
        user = SimpleNamespace(id=uuid.uuid4(), mcp_api_key="key-abc")
        request = _make_request(
            "http://127.0.0.1:10105/",
            headers={
                "x-forwarded-proto": "https",
                "x-forwarded-host": "aiwf.asuka.com.tr",
            },
        )

        result = await get_mcp_config(request=request, current_user=user, db=_make_empty_db())

        self.assertEqual(result.mcp_endpoint_url, "https://aiwf.asuka.com.tr/api/mcp/sse")
        self.assertNotIn("127.0.0.1", result.mcp_endpoint_url)

    @patch("app.api.mcp.get_all_user_workflows", new_callable=AsyncMock, return_value=[])
    async def test_config_falls_back_to_base_url_without_forwarded_headers(
        self, _: AsyncMock
    ) -> None:
        """
        AFTER: when no X-Forwarded headers are present (local dev / direct access),
        request.base_url is used — same behaviour as before the fix.
        """
        user = SimpleNamespace(id=uuid.uuid4(), mcp_api_key="key-local")
        request = _make_request("http://localhost:10105/")

        result = await get_mcp_config(request=request, current_user=user, db=_make_empty_db())

        self.assertEqual(result.mcp_endpoint_url, "http://localhost:10105/api/mcp/sse")

    @patch("app.api.mcp.get_all_user_workflows", new_callable=AsyncMock, return_value=[])
    async def test_config_forwarded_headers_take_priority_over_host_header(
        self, _: AsyncMock
    ) -> None:
        """
        X-Forwarded-Host takes precedence over the bare Host header when both are present.
        """
        user = SimpleNamespace(id=uuid.uuid4(), mcp_api_key="key-fwd")
        request = _make_request(
            "http://127.0.0.1:10105/",
            headers={
                "x-forwarded-proto": "https",
                "x-forwarded-host": "prod.example.com",
                "host": "internal-lb.internal:10105",
            },
        )

        result = await get_mcp_config(request=request, current_user=user, db=_make_empty_db())

        self.assertEqual(result.mcp_endpoint_url, "https://prod.example.com/api/mcp/sse")

    @patch("app.api.mcp.get_all_user_workflows", new_callable=AsyncMock, return_value=[])
    async def test_config_uses_host_header_when_x_forwarded_host_absent(self, _: AsyncMock) -> None:
        """
        When X-Forwarded-Host is absent but X-Forwarded-Proto + Host are present,
        the combination is used to construct the URL.
        """
        user = SimpleNamespace(id=uuid.uuid4(), mcp_api_key="key-host")
        request = _make_request(
            "http://127.0.0.1:10105/",
            headers={
                "x-forwarded-proto": "https",
                "host": "example.com",
            },
        )

        result = await get_mcp_config(request=request, current_user=user, db=_make_empty_db())

        self.assertEqual(result.mcp_endpoint_url, "https://example.com/api/mcp/sse")
