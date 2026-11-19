"""Streamable HTTP: a notification POSTed to an MCP endpoint gets 202 Accepted with no body."""

import unittest
import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import mcp, mcp_servers

USER = SimpleNamespace(id=uuid.uuid4())
SERVER = SimpleNamespace(id=uuid.uuid4())


class McpNotificationStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(mcp.router, prefix="/api/mcp")
        app.include_router(mcp_servers.router, prefix="/api/mcp/servers")
        app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: USER
        app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            USER,
            SERVER,
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


if __name__ == "__main__":
    unittest.main()
