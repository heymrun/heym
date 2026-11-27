"""Streamable HTTP: a notification POSTed to an MCP endpoint gets 202 Accepted with no body."""

import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api import mcp, mcp_servers

USER = SimpleNamespace(id=uuid.uuid4())
SERVER = SimpleNamespace(id=uuid.uuid4())


class McpNotificationStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(mcp.router, prefix="/api/mcp")
        app.include_router(mcp_servers.router, prefix="/api/mcp/servers")

        def _get_user_for_sse(request: Request) -> Any:
            request.state.mcp_auth_source = "oauth"
            request.state.mcp_key_version = None
            return USER

        def _get_named_context_for_sse(request: Request) -> Any:
            request.state.mcp_auth_source = "oauth"
            request.state.mcp_key_version = None
            return (USER, SERVER)

        app.dependency_overrides[mcp.get_mcp_user_for_sse] = _get_user_for_sse
        app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = (
            _get_named_context_for_sse
        )
        self.client = TestClient(app)

    def test_a_notification_gets_202_with_no_body(self) -> None:
        for path in ("/api/mcp", f"/api/mcp/servers/{SERVER.id}/mcp"):
            with self.subTest(path=path):
                response = self.client.post(
                    path, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
                )

                self.assertEqual((response.status_code, response.text), (202, ""))

    def test_a_request_still_gets_its_response(self) -> None:
        response = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 1)
        self.assertIn("result", response.json())

    def _legacy_sse_paths(self) -> tuple[str, str]:
        return "/api/mcp/sse", f"/api/mcp/servers/{SERVER.id}/sse"

    def test_a_streamable_session_get_on_a_legacy_sse_url_gets_405(self) -> None:
        # After a 202, Streamable HTTP clients GET the same URL with their session id.
        for path in self._legacy_sse_paths():
            with self.subTest(path=path):
                with (
                    patch.object(mcp.mcp_session_store, "create", return_value="tok") as create,
                    # Without the guard the stream opens; close it at once instead of hanging.
                    patch(
                        "starlette.requests.Request.is_disconnected", AsyncMock(return_value=True)
                    ),
                ):
                    response = self.client.get(path, headers={"Mcp-Session-Id": "abc"})

                self.assertEqual(response.status_code, 405)
                self.assertEqual(response.headers.get("allow"), "POST")
                create.assert_not_called()

    def test_a_plain_get_on_a_legacy_sse_url_still_opens_the_stream(self) -> None:
        for path in self._legacy_sse_paths():
            with self.subTest(path=path):
                with patch(
                    "starlette.requests.Request.is_disconnected", AsyncMock(return_value=True)
                ):
                    with self.client.stream("GET", path) as response:
                        self.assertEqual(response.status_code, 200)
                        lines = list(response.iter_lines())

                self.assertIn("event: endpoint", lines)
                self.assertTrue(any("message?session=" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
