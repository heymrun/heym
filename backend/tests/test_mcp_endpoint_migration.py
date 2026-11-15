"""Tests for MCP endpoint migration: /api/mcp and /api/mcp/servers/{id}/mcp.

Verifies:
- Default MCP endpoint migrated to /api/mcp while preserving /api/mcp/sse
- Trailing slashes on new routes (/api/mcp/ and /api/mcp/servers/{id}/mcp/) return 200 without redirect
- Named MCP servers use /api/mcp/servers/{id}/mcp while preserving /api/mcp/servers/{id}/sse
- GET requests to new /mcp routes return 405 Method Not Allowed
- GET requests to legacy /sse routes return 200 SSE stream
- POST requests on both routes execute JSON-RPC initialize
- Default config endpoint advertises /api/mcp
"""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, status
from starlette.testclient import TestClient

from app.api import mcp, mcp_servers
from app.db.models import MCPServer, User
from app.services.mcp_elicitation import MCP_SESSION_HEADER
from app.services.secret_tokens import hash_secret


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mcp.router, prefix="/api/mcp")
    app.include_router(mcp_servers.router, prefix="/api/mcp/servers")
    return app


def _init_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"elicitation": {"url": {}}},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }


class TestDefaultMCPEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _make_app()
        self.user = User(
            id=uuid.uuid4(),
            email="user@example.com",
            name="Test User",
            is_active=True,
            mcp_api_key=hash_secret("valid-default-key"),
            mcp_chat_enabled=False,
            mcp_chat_credential_id=None,
            mcp_chat_model=None,
            mcp_a2a_enabled=False,
        )
        self.client = TestClient(self.app)

    def test_get_new_mcp_endpoint_returns_405(self) -> None:
        """GET /api/mcp is not an SSE endpoint and returns 405 Method Not Allowed."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        response = self.client.get("/api/mcp")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_post_new_mcp_endpoint(self) -> None:
        """POST /api/mcp handles initialize and returns 200 with session header."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        response = self.client.post("/api/mcp", json=_init_request())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data.get("jsonrpc"), "2.0")
        self.assertIn("capabilities", data.get("result", {}))
        self.assertIn(MCP_SESSION_HEADER.lower(), response.headers)

    def test_post_new_mcp_endpoint_trailing_slash(self) -> None:
        """POST /api/mcp/ handles initialize directly with 200, avoiding a 307 redirect."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        response = self.client.post("/api/mcp/", json=_init_request(), follow_redirects=False)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data.get("jsonrpc"), "2.0")
        self.assertIn("capabilities", data.get("result", {}))

    def test_tools_list_on_new_default_endpoint(self) -> None:
        """POST /api/mcp dispatches tools/list over the new Streamable HTTP endpoint."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        db = AsyncMock()
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=db)
        session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.api.mcp.async_session_maker", return_value=session),
            patch("app.api.mcp.get_user_mcp_workflows", AsyncMock(return_value=[])),
            patch(
                "app.api.mcp.agent_settings.get_global_agent_settings",
                AsyncMock(return_value=MagicMock(enabled=False)),
            ),
            patch("app.api.mcp.global_mcp_tools", AsyncMock(return_value=[])),
        ):
            response = self.client.post(
                "/api/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], 2)
        self.assertEqual(data["result"]["tools"], [])

    def test_tools_call_on_new_default_endpoint(self) -> None:
        """POST /api/mcp dispatches tools/call and returns the JSON-RPC tool-not-found result."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        db = AsyncMock()
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=db)
        session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.api.mcp.async_session_maker", return_value=session),
            patch("app.api.mcp.get_user_mcp_workflows", AsyncMock(return_value=[])),
        ):
            response = self.client.post(
                "/api/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "missing_tool", "arguments": {}},
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))
        self.assertIn("Tool not found: missing_tool", response.text)

    def test_get_legacy_sse_endpoint_route_returns_streaming(self) -> None:
        """GET /api/mcp/sse continues serving the legacy SSE handshake stream."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        with patch("starlette.requests.Request.is_disconnected", AsyncMock(return_value=True)):
            with self.client.stream("GET", "/api/mcp/sse") as response:
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIn("text/event-stream", response.headers.get("content-type", ""))
                lines = list(response.iter_lines())
                self.assertTrue(any(line.startswith("event: endpoint") for line in lines))
                self.assertTrue(any("/api/mcp/message?session=" in line for line in lines))

    def test_post_legacy_sse_endpoint(self) -> None:
        """POST /api/mcp/sse continues handling initialize identically for legacy clients."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        response = self.client.post("/api/mcp/sse", json=_init_request())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data.get("jsonrpc"), "2.0")
        self.assertIn("capabilities", data.get("result", {}))

    def test_get_mcp_config_returns_mcp_endpoint(self) -> None:
        """GET /api/mcp/config returns /api/mcp as the default mcp_endpoint_url."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        self.app.dependency_overrides[mcp.get_current_user] = lambda: self.user
        self.app.dependency_overrides[mcp.get_db] = lambda: mock_db
        with patch("app.api.mcp.get_all_user_workflows", AsyncMock(return_value=[])):
            response = self.client.get("/api/mcp/config")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            data = response.json()
            self.assertTrue(data["mcp_endpoint_url"].endswith("/api/mcp"))
            self.assertFalse(data["mcp_endpoint_url"].endswith("/api/mcp/sse"))


class TestNamedMCPEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _make_app()
        self.user = User(
            id=uuid.uuid4(),
            email="owner@example.com",
            name="Owner",
            is_active=True,
        )
        self.server = MCPServer(
            id=uuid.uuid4(),
            user_id=self.user.id,
            name="CRM Server",
            api_key=hash_secret("named-secret-key"),
            chat_enabled=False,
            endpoint_path="mcp",
        )
        self.legacy_server = MCPServer(
            id=uuid.uuid4(),
            user_id=self.user.id,
            name="Legacy Server",
            api_key=hash_secret("legacy-secret-key"),
            chat_enabled=False,
            endpoint_path="sse",
        )
        self.client = TestClient(self.app)

    def _post_named_endpoint_with_key(self, api_key: str | None) -> tuple[object, AsyncMock]:
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=db)
        session.__aexit__ = AsyncMock(return_value=None)
        headers = {"X-MCP-Key": api_key} if api_key is not None else {}

        with patch("app.api.mcp_servers.async_session_maker", return_value=session):
            response = self.client.post(
                f"/api/mcp/servers/{self.server.id}/mcp",
                json=_init_request(),
                headers=headers,
            )
        return response, db

    def test_named_mcp_endpoint_rejects_missing_api_key(self) -> None:
        """The new named /mcp route requires its X-MCP-Key header."""
        response, db = self._post_named_endpoint_with_key(None)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        db.execute.assert_not_called()

    def test_named_mcp_endpoint_rejects_wrong_api_key(self) -> None:
        """The new named /mcp route rejects an incorrect X-MCP-Key."""
        response, db = self._post_named_endpoint_with_key("wrong-api-key")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        db.execute.assert_awaited_once()

    def test_named_mcp_endpoint_rejects_another_servers_api_key(self) -> None:
        """A different named server's key cannot authenticate against this server ID."""
        response, db = self._post_named_endpoint_with_key("another-servers-api-key")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        db.execute.assert_awaited_once()

    def test_get_named_mcp_endpoint_returns_405(self) -> None:
        """GET /api/mcp/servers/{id}/mcp returns 405 Method Not Allowed."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.server,
        )
        response = self.client.get(f"/api/mcp/servers/{self.server.id}/mcp")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_post_named_mcp_endpoint(self) -> None:
        """POST /api/mcp/servers/{id}/mcp handles initialize and sets session header."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.server,
        )
        response = self.client.post(
            f"/api/mcp/servers/{self.server.id}/mcp",
            json=_init_request(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data.get("jsonrpc"), "2.0")
        self.assertIn("capabilities", data.get("result", {}))
        self.assertIn(MCP_SESSION_HEADER.lower(), response.headers)

    def test_post_named_mcp_endpoint_trailing_slash(self) -> None:
        """POST /api/mcp/servers/{id}/mcp/ handles initialize directly with 200, avoiding redirect."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.server,
        )
        response = self.client.post(
            f"/api/mcp/servers/{self.server.id}/mcp/",
            json=_init_request(),
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data.get("jsonrpc"), "2.0")
        self.assertIn("capabilities", data.get("result", {}))

    def test_get_named_legacy_sse_endpoint_route_returns_streaming(self) -> None:
        """GET /api/mcp/servers/{id}/sse returns 200 SSE streaming handshake."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.legacy_server,
        )
        with patch("starlette.requests.Request.is_disconnected", AsyncMock(return_value=True)):
            with self.client.stream(
                "GET", f"/api/mcp/servers/{self.legacy_server.id}/sse"
            ) as response:
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIn("text/event-stream", response.headers.get("content-type", ""))
                lines = list(response.iter_lines())
                self.assertTrue(any(line.startswith("event: endpoint") for line in lines))
                self.assertTrue(
                    any(
                        f"/api/mcp/servers/{self.legacy_server.id}/message?session=" in line
                        for line in lines
                    )
                )

    def test_post_named_legacy_sse_endpoint(self) -> None:
        """POST /api/mcp/servers/{id}/sse continues working identically for legacy servers."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.legacy_server,
        )
        response = self.client.post(
            f"/api/mcp/servers/{self.legacy_server.id}/sse",
            json=_init_request(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data.get("jsonrpc"), "2.0")
        self.assertIn("capabilities", data.get("result", {}))
