import asyncio
import json
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request

from app.api.mcp import (
    _dispatch_mcp_jsonrpc,
    handle_mcp_message,
    mcp_sse_post_endpoint,
)
from app.api.mcp_servers import _dispatch_named_server_jsonrpc, named_server_sse_post
from app.services.mcp_session import mcp_sse_channels


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
            "headers": [(b"origin", b"https://heym.run")],
            "query_string": query_string,
        },
        receive,
    )


def _tool_call_body(
    *,
    name: str = "file_upload",
    msg_id: int | str = 1,
    progress_token: str | None = None,
) -> dict:
    params: dict[str, object] = {"name": name, "arguments": {}}
    if progress_token is not None:
        params["_meta"] = {"progressToken": progress_token}
    return {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": params}


def _file_upload_workflow() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="File Upload",
        description="Upload a file",
        nodes=[
            {
                "id": "upload1",
                "type": "fileUploadTrigger",
                "data": {
                    "label": "fileUpload",
                    "ttlMinutes": 60,
                    "maxSizeMb": 100,
                    "allowedTypes": "",
                },
            }
        ],
        edges=[],
    )


def _slot() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        expires_at=datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc),
        max_size_bytes=100 * 1024 * 1024,
        allowed_mime=[],
    )


class _FakeSessionContext:
    def __init__(self) -> None:
        self.session = AsyncMock()
        self.session.commit = AsyncMock()
        self.session.rollback = AsyncMock()

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


class MCPJsonRpcFileUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_jsonrpc_file_upload_mints_slot_instead_of_empty_file(self) -> None:
        workflow = _file_upload_workflow()
        user = SimpleNamespace(id=workflow.owner_id)
        db = AsyncMock()
        db.commit = AsyncMock()

        with (
            patch("app.api.mcp.get_user_mcp_workflows", AsyncMock(return_value=[workflow])),
            patch(
                "app.api.mcp.file_intake_service.mint_slot",
                AsyncMock(return_value=(_slot(), "TOK")),
            ),
            patch("app.api.mcp.file_intake_service.write_audit", AsyncMock()),
            patch("app.api.mcp.execute_workflow") as execute_mock,
        ):
            response = await _dispatch_mcp_jsonrpc(
                request=_make_json_request("/api/mcp/sse", _tool_call_body()),
                mcp_user=user,
                db=db,
            )

        execute_mock.assert_not_called()
        text = response["result"]["content"][0]["text"]
        payload = json.loads(text)
        self.assertEqual(payload["upload_url"], "https://heym.run/api/file-intake/u/TOK")
        self.assertIn("curl", payload)
        self.assertNotEqual(payload, {"fileUpload": {"file": {}, "uploaded_at": None}})

    async def test_named_jsonrpc_file_upload_mints_slot_instead_of_empty_file(self) -> None:
        workflow = _file_upload_workflow()
        user = SimpleNamespace(id=workflow.owner_id)
        server = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        db.commit = AsyncMock()

        with (
            patch(
                "app.api.mcp_servers._get_server_workflows",
                AsyncMock(return_value=[workflow]),
            ),
            patch(
                "app.api.mcp.file_intake_service.mint_slot",
                AsyncMock(return_value=(_slot(), "TOK")),
            ),
            patch("app.api.mcp.file_intake_service.write_audit", AsyncMock()),
            patch("app.api.mcp_servers.execute_workflow") as execute_mock,
        ):
            response = await _dispatch_named_server_jsonrpc(
                server_id=server.id,
                request=_make_json_request(
                    f"/api/mcp/servers/{server.id}/sse",
                    _tool_call_body(),
                ),
                server=(user, server),
                db=db,
            )

        execute_mock.assert_not_called()
        text = response["result"]["content"][0]["text"]
        payload = json.loads(text)
        self.assertEqual(payload["upload_url"], "https://heym.run/api/file-intake/u/TOK")
        self.assertIn("curl", payload)
        self.assertNotEqual(payload, {"fileUpload": {"file": {}, "uploaded_at": None}})


class MCPJsonRpcProgressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        mcp_sse_channels.unregister("progress-session")

    async def test_legacy_sse_tool_call_returns_accepted_and_pushes_progress(self) -> None:
        queue = mcp_sse_channels.register("progress-session")
        done = asyncio.Event()

        async def fake_dispatch(*_args: object, **_kwargs: object) -> dict:
            await done.wait()
            return {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": "{}"}], "isError": False},
            }

        session_context = _FakeSessionContext()
        with (
            patch("app.api.mcp._MCP_PROGRESS_INTERVAL_SECONDS", 0.01),
            patch("app.api.mcp._dispatch_mcp_jsonrpc", AsyncMock(side_effect=fake_dispatch)),
            patch("app.api.mcp.async_session_maker", MagicMock(return_value=session_context)),
        ):
            response = await handle_mcp_message(
                request=_make_json_request(
                    "/api/mcp/message",
                    _tool_call_body(progress_token="progress-1"),
                    b"session=progress-session",
                ),
                mcp_user=SimpleNamespace(id=uuid.uuid4()),
                db=AsyncMock(),
            )

            self.assertEqual(response.status_code, 202)
            progress = json.loads(await asyncio.wait_for(queue.get(), timeout=0.2))
            self.assertEqual(progress["method"], "notifications/progress")
            self.assertEqual(progress["params"]["progressToken"], "progress-1")

            done.set()
            final: dict | None = None
            for _ in range(5):
                payload = json.loads(await asyncio.wait_for(queue.get(), timeout=0.2))
                if payload.get("id") == 1:
                    final = payload
                    break

            self.assertIsNotNone(final)
            self.assertEqual(final["id"], 1)
            self.assertFalse(final["result"]["isError"])

    async def test_streamable_http_tool_call_streams_heartbeat_progress_and_final(self) -> None:
        done = asyncio.Event()

        async def fake_dispatch(*_args: object, **_kwargs: object) -> dict:
            await done.wait()
            return {
                "jsonrpc": "2.0",
                "id": "call-1",
                "result": {"content": [{"type": "text", "text": "{}"}], "isError": False},
            }

        session_context = _FakeSessionContext()
        with (
            patch("app.api.mcp._MCP_PROGRESS_INTERVAL_SECONDS", 0.01),
            patch("app.api.mcp._dispatch_mcp_jsonrpc", AsyncMock(side_effect=fake_dispatch)),
            patch("app.api.mcp.async_session_maker", MagicMock(return_value=session_context)),
        ):
            response = await mcp_sse_post_endpoint(
                request=_make_json_request(
                    "/api/mcp/sse",
                    _tool_call_body(msg_id="call-1", progress_token="progress-2"),
                ),
                mcp_user=SimpleNamespace(id=uuid.uuid4()),
            )

            body_iterator = response.body_iterator
            first_chunk = await asyncio.wait_for(body_iterator.__anext__(), timeout=0.2)
            second_chunk = await asyncio.wait_for(body_iterator.__anext__(), timeout=0.2)
            self.assertTrue(first_chunk.startswith(": keep-alive"))
            self.assertGreater(len(first_chunk), 1024)
            self.assertIn("notifications/progress", second_chunk)

            done.set()
            chunks: list[str] = []
            for _ in range(5):
                chunk = await asyncio.wait_for(body_iterator.__anext__(), timeout=0.2)
                chunks.append(chunk)
                if '"id": "call-1"' in chunk:
                    break
            await body_iterator.aclose()

        self.assertTrue(any('"id": "call-1"' in chunk for chunk in chunks))
        session_context.session.commit.assert_awaited_once()

    async def test_named_streamable_http_tool_call_streams_keepalive_and_final(self) -> None:
        done = asyncio.Event()
        server = SimpleNamespace(id=uuid.uuid4())

        async def fake_dispatch(*_args: object, **_kwargs: object) -> dict:
            await done.wait()
            return {
                "jsonrpc": "2.0",
                "id": "named-call-1",
                "result": {"content": [{"type": "text", "text": "{}"}], "isError": False},
            }

        session_context = _FakeSessionContext()
        with (
            patch("app.api.mcp._MCP_PROGRESS_INTERVAL_SECONDS", 0.01),
            patch(
                "app.api.mcp_servers._dispatch_named_server_jsonrpc",
                AsyncMock(side_effect=fake_dispatch),
            ),
            patch("app.api.mcp.async_session_maker", MagicMock(return_value=session_context)),
        ):
            response = await named_server_sse_post(
                server_id=server.id,
                request=_make_json_request(
                    f"/api/mcp/servers/{server.id}/sse",
                    _tool_call_body(msg_id="named-call-1", progress_token="progress-3"),
                ),
                server=(SimpleNamespace(id=uuid.uuid4()), server),
            )

            body_iterator = response.body_iterator
            first_chunk = await asyncio.wait_for(body_iterator.__anext__(), timeout=0.2)
            second_chunk = await asyncio.wait_for(body_iterator.__anext__(), timeout=0.2)
            self.assertTrue(first_chunk.startswith(": keep-alive"))
            self.assertGreater(len(first_chunk), 1024)
            self.assertIn("notifications/progress", second_chunk)

            done.set()
            chunks: list[str] = []
            for _ in range(5):
                chunk = await asyncio.wait_for(body_iterator.__anext__(), timeout=0.2)
                chunks.append(chunk)
                if '"id": "named-call-1"' in chunk:
                    break
            await body_iterator.aclose()

        self.assertTrue(any('"id": "named-call-1"' in chunk for chunk in chunks))
        session_context.session.commit.assert_awaited_once()
