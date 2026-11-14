"""Comprehensive tests for MCP endpoint migration: /api/mcp and /api/mcp/servers/{id}/mcp.

Verifies:
- Default MCP endpoint migrated to `/api/mcp` while preserving `/api/mcp/sse`
- Named MCP servers migrated to `/api/mcp/servers/{id}/mcp` while preserving `/api/mcp/servers/{id}/sse`
- GET requests to new `/mcp` routes return 405 Method Not Allowed
- GET requests to legacy `/sse` routes return 200 SSE stream
- POST requests on both routes execute JSON-RPC: initialize, tools/list, tools/call
- Streaming response behavior
- Mcp-Session-Id header lifecycle and elicitation session support
- Authentication failures (missing key, invalid key) on new routes
- Named-server ownership checks on new routes
"""

import json
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, status
from starlette.testclient import TestClient

from app.api import mcp, mcp_servers
from app.db.models import MCPServer, User
from app.services.heym_agent.settings import AgentSettings
from app.services.mcp_elicitation import MCP_SESSION_HEADER
from app.services.secret_tokens import hash_secret


class _FakeSession:
    def __init__(self, query_result=None) -> None:
        self._result = query_result

    async def execute(self, stmt, *args, **kwargs):
        res = MagicMock()
        res.scalar_one_or_none.return_value = self._result
        res.scalars.return_value.all.return_value = [self._result] if self._result else []
        return res

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def flush(self) -> None:
        pass

    def add(self, obj) -> None:
        pass


class _FakeSessionContext:
    def __init__(self, session=None) -> None:
        self.session = session or _FakeSession()

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, *args) -> None:
        pass


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


def _tools_list_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }


def _tool_call_request(tool_name: str = "test_wf") -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"input": "test"},
        },
    }


def _mock_workflow(name: str = "Test Workflow") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name=name,
        description="A test workflow",
        nodes=[{"id": "node_1", "type": "code", "data": {}}],
        edges=[],
        mcp_enabled=True,
        updated_at=datetime.now(timezone.utc),
        concurrency_limit=None,
    )


class TestDefaultMCPEndpoints(unittest.IsolatedAsyncioTestCase):
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
        """GET /api/mcp is not an SSE endpoint and must return 405 Method Not Allowed."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        response = self.client.get("/api/mcp")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    async def test_get_legacy_sse_endpoint_returns_streaming(self) -> None:
        """GET /api/mcp/sse remains the legacy SSE handshake (handler level)."""
        request = MagicMock()
        request.base_url = "http://localhost:10105/"
        request.headers.get = MagicMock(return_value=None)
        request.is_disconnected = AsyncMock(return_value=True)

        response = await mcp.mcp_sse_endpoint(request=request, mcp_user=self.user)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))
        first_event = await response.body_iterator.__anext__()
        self.assertIn("event: endpoint", first_event)
        self.assertIn("/api/mcp/message?session=", first_event)

    def test_get_legacy_sse_endpoint_route_returns_streaming(self) -> None:
        """GET /api/mcp/sse exercised via registered FastAPI route returns 200 and text/event-stream."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        with patch("starlette.requests.Request.is_disconnected", AsyncMock(return_value=True)):
            with self.client.stream("GET", "/api/mcp/sse") as response:
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/event-stream", response.headers.get("content-type", ""))
                lines = list(response.iter_lines())
                self.assertTrue(any(line.startswith("event: endpoint") for line in lines))
                self.assertTrue(any("/api/mcp/message?session=" in line for line in lines))

    def test_post_new_mcp_initialize(self) -> None:
        """POST /api/mcp handles initialize and sets Mcp-Session-Id header."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        response = self.client.post("/api/mcp", json=_init_request())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("jsonrpc"), "2.0")
        self.assertIn("capabilities", data.get("result", {}))
        self.assertIn(MCP_SESSION_HEADER.lower(), response.headers)

    def test_post_legacy_sse_initialize(self) -> None:
        """POST /api/mcp/sse continues handling initialize identically."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        response = self.client.post("/api/mcp/sse", json=_init_request())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("jsonrpc"), "2.0")
        self.assertIn("capabilities", data.get("result", {}))
        self.assertIn(MCP_SESSION_HEADER.lower(), response.headers)

    def test_post_new_mcp_tools_list(self) -> None:
        """POST /api/mcp handles tools/list."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        wf = _mock_workflow("Sync Data")
        with (
            patch("app.api.mcp.async_session_maker", return_value=_FakeSessionContext()),
            patch("app.api.mcp.get_user_mcp_workflows", AsyncMock(return_value=[wf])),
            patch(
                "app.api.mcp.agent_settings.get_global_agent_settings",
                AsyncMock(
                    return_value=AgentSettings(enabled=False, credential_id=None, model=None)
                ),
            ),
        ):
            response = self.client.post("/api/mcp", json=_tools_list_request())
            self.assertEqual(response.status_code, 200)
            data = response.json()
            tools = data["result"]["tools"]
            self.assertTrue(any(t["name"] == "sync_data" for t in tools))

    def test_post_new_mcp_tool_call(self) -> None:
        """POST /api/mcp handles tools/call and executes workflow."""
        self.app.dependency_overrides[mcp.get_mcp_user_for_sse] = lambda: self.user
        wf = _mock_workflow("Calculate")
        mock_exec_result = SimpleNamespace(
            status="success",
            outputs={"total": 42},
            node_results={},
            sub_workflow_executions=[],
            execution_time_ms=12,
        )
        with (
            patch("app.api.mcp.async_session_maker", return_value=_FakeSessionContext()),
            patch("app.api.mcp.get_user_mcp_workflows", AsyncMock(return_value=[wf])),
            patch("app.api.mcp.dispatch_workflow", AsyncMock(return_value=mock_exec_result)),
            patch("app.api.mcp.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.mcp.get_credentials_context_for_user", AsyncMock(return_value={})),
            patch("app.api.mcp.audit_workflow_run", MagicMock()),
            patch("app.api.mcp.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.mcp._add_mcp_workflow_trace", MagicMock()),
        ):
            response = self.client.post("/api/mcp", json=_tool_call_request("calculate"))
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers.get("content-type", ""))
            data_line = next(
                line for line in response.text.splitlines() if line.startswith("data: ")
            )
            data = json.loads(data_line[6:])
            content = data["result"]["content"]
            self.assertEqual(content[0]["text"], json.dumps({"total": 42}, indent=2))

    def test_default_mcp_auth_failure_missing_header(self) -> None:
        """POST /api/mcp without authentication header returns 401."""
        response = self.client.post("/api/mcp", json=_init_request())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_default_mcp_auth_failure_invalid_key(self) -> None:
        """POST /api/mcp with invalid X-MCP-Key header returns 401."""
        with patch("app.api.mcp.async_session_maker", return_value=_FakeSessionContext()):
            response = self.client.post(
                "/api/mcp",
                json=_init_request(),
                headers={"X-MCP-Key": "wrong-key"},
            )
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestNamedMCPEndpoints(unittest.IsolatedAsyncioTestCase):
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

    def test_get_named_mcp_endpoint_returns_405(self) -> None:
        """GET /api/mcp/servers/{id}/mcp returns 405 Method Not Allowed."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.server,
        )
        response = self.client.get(f"/api/mcp/servers/{self.server.id}/mcp")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    async def test_get_named_sse_endpoint_returns_streaming(self) -> None:
        """GET /api/mcp/servers/{id}/sse returns 200 SSE streaming handshake (handler level)."""
        request = MagicMock()
        request.base_url = "http://localhost:10105/"
        request.headers.get = MagicMock(return_value=None)
        request.is_disconnected = AsyncMock(return_value=True)

        response = await mcp_servers.named_server_sse(
            server_id=self.legacy_server.id,
            request=request,
            server=(self.user, self.legacy_server),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))
        first_event = await response.body_iterator.__anext__()
        self.assertIn("event: endpoint", first_event)
        self.assertIn(f"/api/mcp/servers/{self.legacy_server.id}/message?session=", first_event)

    def test_get_named_sse_endpoint_route_returns_streaming(self) -> None:
        """GET /api/mcp/servers/{id}/sse exercised via registered FastAPI route returns 200 and text/event-stream."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.legacy_server,
        )
        with patch("starlette.requests.Request.is_disconnected", AsyncMock(return_value=True)):
            with self.client.stream(
                "GET", f"/api/mcp/servers/{self.legacy_server.id}/sse"
            ) as response:
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/event-stream", response.headers.get("content-type", ""))
                lines = list(response.iter_lines())
                self.assertTrue(any(line.startswith("event: endpoint") for line in lines))
                self.assertTrue(
                    any(
                        f"/api/mcp/servers/{self.legacy_server.id}/message?session=" in line
                        for line in lines
                    )
                )

    def test_post_named_mcp_initialize(self) -> None:
        """POST /api/mcp/servers/{id}/mcp handles initialize and sets session header."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.server,
        )
        response = self.client.post(
            f"/api/mcp/servers/{self.server.id}/mcp",
            json=_init_request(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("jsonrpc"), "2.0")
        self.assertIn("capabilities", data.get("result", {}))
        self.assertIn(MCP_SESSION_HEADER.lower(), response.headers)

    def test_post_named_sse_backward_compatible(self) -> None:
        """POST /api/mcp/servers/{id}/sse continues working identically for legacy servers."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.legacy_server,
        )
        response = self.client.post(
            f"/api/mcp/servers/{self.legacy_server.id}/sse",
            json=_init_request(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("jsonrpc"), "2.0")
        self.assertIn("capabilities", data.get("result", {}))

    def test_post_named_mcp_tools_list(self) -> None:
        """POST /api/mcp/servers/{id}/mcp lists tools assigned to the server."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.server,
        )
        wf = _mock_workflow("CRM Lead")
        with (
            patch("app.api.mcp_servers.async_session_maker", return_value=_FakeSessionContext()),
            patch("app.api.mcp_servers._get_server_workflows", AsyncMock(return_value=[wf])),
            patch(
                "app.api.mcp_servers.agent_settings.get_server_agent_settings",
                AsyncMock(
                    return_value=AgentSettings(enabled=False, credential_id=None, model=None)
                ),
            ),
        ):
            response = self.client.post(
                f"/api/mcp/servers/{self.server.id}/mcp",
                json=_tools_list_request(),
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            tools = data["result"]["tools"]
            self.assertEqual(len(tools), 1)
            self.assertEqual(tools[0]["name"], "crm_lead")

    def test_post_named_mcp_tool_call(self) -> None:
        """POST /api/mcp/servers/{id}/mcp calls tool assigned to server."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.server,
        )
        wf = _mock_workflow("CRM Lead")
        mock_exec_result = SimpleNamespace(
            status="success",
            outputs={"lead_id": 999},
            node_results={},
            sub_workflow_executions=[],
            execution_time_ms=10,
        )
        with (
            patch("app.api.mcp.async_session_maker", return_value=_FakeSessionContext()),
            patch("app.api.mcp_servers.async_session_maker", return_value=_FakeSessionContext()),
            patch("app.api.mcp_servers._get_server_workflows", AsyncMock(return_value=[wf])),
            patch(
                "app.api.mcp_servers.dispatch_workflow", AsyncMock(return_value=mock_exec_result)
            ),
            patch("app.api.mcp_servers.collect_referenced_workflows", AsyncMock(return_value={})),
            patch(
                "app.api.mcp_servers.get_credentials_context_for_user", AsyncMock(return_value={})
            ),
            patch("app.api.mcp_servers.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.mcp_servers.audit_workflow_run", MagicMock()),
            patch("app.api.mcp_servers.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.mcp_servers._add_mcp_workflow_trace", MagicMock()),
            patch("app.api.mcp_servers._persist_global_variables_from_execution", AsyncMock()),
        ):
            response = self.client.post(
                f"/api/mcp/servers/{self.server.id}/mcp",
                json=_tool_call_request("crm_lead"),
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers.get("content-type", ""))
            data_line = next(
                line for line in response.text.splitlines() if line.startswith("data: ")
            )
            data = json.loads(data_line[6:])
            content = data["result"]["content"]
            self.assertEqual(content[0]["text"], json.dumps({"lead_id": 999}, indent=2))

    def test_named_mcp_auth_failure_missing_key(self) -> None:
        """POST /api/mcp/servers/{id}/mcp without authentication header returns 401."""
        response = self.client.post(
            f"/api/mcp/servers/{self.server.id}/mcp",
            json=_init_request(),
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_named_mcp_auth_failure_invalid_key(self) -> None:
        """POST /api/mcp/servers/{id}/mcp with invalid X-MCP-Key returns 401."""
        with patch("app.api.mcp_servers.async_session_maker", return_value=_FakeSessionContext()):
            response = self.client.post(
                f"/api/mcp/servers/{self.server.id}/mcp",
                json=_init_request(),
                headers={"X-MCP-Key": "wrong-key"},
            )
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_session_lifecycle_with_session_header(self) -> None:
        """Client can pass Mcp-Session-Id header from initialize into follow-up calls."""
        self.app.dependency_overrides[mcp_servers._get_named_server_context_for_sse] = lambda: (
            self.user,
            self.server,
        )
        # 1. Initialize
        init_res = self.client.post(
            f"/api/mcp/servers/{self.server.id}/mcp",
            json=_init_request(),
        )
        session_id = init_res.headers.get(MCP_SESSION_HEADER.lower())
        self.assertIsNotNone(session_id)

        # 2. Subsequent call with session header
        wf = _mock_workflow("Followup Tool")
        with (
            patch("app.api.mcp_servers.async_session_maker", return_value=_FakeSessionContext()),
            patch("app.api.mcp_servers._get_server_workflows", AsyncMock(return_value=[wf])),
            patch(
                "app.api.mcp_servers.agent_settings.get_server_agent_settings",
                AsyncMock(
                    return_value=AgentSettings(enabled=False, credential_id=None, model=None)
                ),
            ),
        ):
            list_res = self.client.post(
                f"/api/mcp/servers/{self.server.id}/mcp",
                json=_tools_list_request(),
                headers={MCP_SESSION_HEADER: session_id},
            )
            self.assertEqual(list_res.status_code, 200)
            self.assertEqual(len(list_res.json()["result"]["tools"]), 1)

    def test_named_mcp_access_denied_other_user(self) -> None:
        """POST /api/mcp/servers/{id}/mcp returns 403 when authenticated user does not own server."""
        other_user = User(
            id=uuid.uuid4(),
            email="other@example.com",
            name="Other",
            is_active=True,
        )
        token_record = SimpleNamespace(user_id=other_user.id)

        async def fake_execute(stmt, *args, **kwargs):
            res = MagicMock()
            stmt_str = str(stmt)
            if "oauth_access_tokens" in stmt_str:
                res.scalar_one_or_none.return_value = token_record
            elif "users" in stmt_str:
                res.scalar_one_or_none.return_value = other_user
            else:
                res.scalar_one_or_none.return_value = None
            return res

        fake_session = MagicMock()
        fake_session.execute = AsyncMock(side_effect=fake_execute)

        with patch(
            "app.api.mcp_servers.async_session_maker",
            return_value=_FakeSessionContext(fake_session),
        ):
            response = self.client.post(
                f"/api/mcp/servers/{self.server.id}/mcp",
                json=_init_request(),
                headers={"Authorization": "Bearer valid-token"},
            )
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
