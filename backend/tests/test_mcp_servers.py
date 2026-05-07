import secrets
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.mcp_servers import (
    _get_named_server_context,
    create_mcp_server,
    delete_mcp_server,
    list_mcp_servers,
    list_named_server_tools,
    toggle_server_workflow,
)
from app.models.schemas import MCPServerCreate, MCPServerWorkflowToggleRequest


def _make_server(user_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        name="Test Server",
        api_key=secrets.token_urlsafe(48),
        created_at=datetime.now(timezone.utc),
    )


def _make_workflow(owner_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=owner_id,
        name="My Workflow",
    )


class MCPServerCreateTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_server_returns_server_with_api_key(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        server_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        added_server: list = []

        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: added_server.append(obj))
        db.commit = AsyncMock()

        async def mock_refresh(obj: object) -> None:
            obj.id = server_id  # type: ignore[attr-defined]
            obj.created_at = now  # type: ignore[attr-defined]

        db.refresh = mock_refresh

        result = await create_mcp_server(
            body=MCPServerCreate(name="CRM Tools"),
            current_user=user,
            db=db,
        )

        self.assertEqual(result.name, "CRM Tools")
        self.assertTrue(result.api_key)
        self.assertEqual(result.id, server_id)
        self.assertEqual(len(result.workflow_ids), 0)
        db.commit.assert_called_once()


class MCPServerListTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_returns_only_user_servers(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        server = _make_server(user.id)

        db = AsyncMock()
        # First execute: list servers; second execute: workflow_ids per server
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(
                    scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[server])))
                ),
                MagicMock(all=MagicMock(return_value=[])),
            ]
        )

        result = await list_mcp_servers(current_user=user, db=db)
        self.assertEqual(len(result.servers), 1)
        self.assertEqual(result.servers[0].name, "Test Server")


class MCPServerDeleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_existing_server(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        server = _make_server(user.id)

        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=server))
        )
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        await delete_mcp_server(server_id=server.id, current_user=user, db=db)

        db.delete.assert_called_once_with(server)
        db.commit.assert_called_once()

    async def test_delete_nonexistent_server_raises_404(self) -> None:
        from fastapi import HTTPException

        user = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with self.assertRaises(HTTPException) as ctx:
            await delete_mcp_server(server_id=uuid.uuid4(), current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, 404)


class MCPServerToggleWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_toggle_add_creates_join_row(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        server = _make_server(user.id)
        workflow = _make_workflow(user.id)

        db = AsyncMock()
        # execute calls: 1=find server, 2=find workflow, 3=find existing join row
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=server)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # no existing row
            ]
        )
        db.add = MagicMock()
        db.commit = AsyncMock()

        await toggle_server_workflow(
            server_id=server.id,
            workflow_id=workflow.id,
            body=MCPServerWorkflowToggleRequest(enabled=True),
            current_user=user,
            db=db,
        )

        db.add.assert_called_once()
        db.commit.assert_called_once()

    async def test_toggle_remove_deletes_join_row(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        server = _make_server(user.id)
        workflow = _make_workflow(user.id)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=server)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
                MagicMock(),  # delete result
            ]
        )
        db.commit = AsyncMock()

        await toggle_server_workflow(
            server_id=server.id,
            workflow_id=workflow.id,
            body=MCPServerWorkflowToggleRequest(enabled=False),
            current_user=user,
            db=db,
        )


class MCPServerToolsListTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_list_returns_only_server_workflows(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        server = _make_server(user.id)
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=user.id,
            name="CRM Sync",
            description="Syncs CRM",
            nodes=[{"id": "n1", "type": "manual", "data": {}}],
            edges=[],
        )

        db = AsyncMock()

        with patch("app.api.mcp_servers._get_server_workflows", AsyncMock(return_value=[workflow])):
            result = await list_named_server_tools(server=(user, server), db=db)

        self.assertEqual(len(result.tools), 1)
        self.assertEqual(result.tools[0].name, "crm_sync")


class MCPServerAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_api_key_raises_401(self) -> None:
        from fastapi import HTTPException, Request

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/mcp/servers/xxx/sse",
                "headers": [(b"x-mcp-key", b"wrong-key")],
                "query_string": b"",
            }
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with self.assertRaises(HTTPException) as ctx:
            await _get_named_server_context(
                server_id=uuid.uuid4(),
                request=request,
                x_mcp_key="wrong-key",
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 401)

    async def test_session_token_wrong_server_raises_403(self) -> None:
        from fastapi import HTTPException, Request

        from app.services.mcp_session import mcp_session_store

        user_id = str(uuid.uuid4())
        other_server_id = str(uuid.uuid4())
        token = mcp_session_store.create(user_id, server_id=other_server_id)

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/mcp/servers/xxx/sse",
                "headers": [],
                "query_string": f"session={token}".encode(),
            }
        )

        db = AsyncMock()

        with self.assertRaises(HTTPException) as ctx:
            await _get_named_server_context(
                server_id=uuid.uuid4(),  # different server
                request=request,
                x_mcp_key=None,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_session_token_auth_does_not_query_database(self) -> None:
        from fastapi import Request

        from app.services.mcp_session import mcp_session_store

        user_id = str(uuid.uuid4())
        server_id = uuid.uuid4()
        token = mcp_session_store.create(user_id, server_id=str(server_id))

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": f"/api/mcp/servers/{server_id}/message",
                "headers": [],
                "query_string": f"session={token}".encode(),
            }
        )

        db = AsyncMock()

        user, server = await _get_named_server_context(
            server_id=server_id,
            request=request,
            x_mcp_key=None,
            db=db,
        )

        self.assertEqual(str(user.id), user_id)
        self.assertEqual(server.id, server_id)
        db.execute.assert_not_called()


class MCPServerDefaultUnaffectedTests(unittest.TestCase):
    def test_default_server_session_has_none_server_id(self) -> None:
        from app.services.mcp_session import mcp_session_store

        token = mcp_session_store.create("user-abc")
        result = mcp_session_store.resolve(token)
        self.assertIsNotNone(result)
        user_id, server_id = result
        self.assertEqual(user_id, "user-abc")
        self.assertIsNone(server_id)
