"""MCP tool names stay unique when workflow names sanitize alike."""

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Request

from app.api.mcp import _dispatch_mcp_jsonrpc, workflow_tool_names
from app.api.mcp_servers import _dispatch_named_server_jsonrpc
from app.services.heym_agent.settings import AgentSettings

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _workflow(name: str, age_days: int, owner_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=owner_id or uuid.uuid4(),
        name=name,
        description=None,
        nodes=[{"id": "t", "type": "textInput", "data": {"label": "t"}}],
        edges=[],
        created_at=_NOW - timedelta(days=age_days),
        concurrency_limit=None,
    )


def _request(method: str, params: dict) -> Request:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {"type": "http", "method": "POST", "path": "/api/mcp", "headers": [], "query_string": b""},
        receive,
    )


class WorkflowToolNamesTests(unittest.TestCase):
    def test_distinct_names_are_unchanged(self) -> None:
        a, b = _workflow("Invoice sync", 2), _workflow("Refund check", 1)

        self.assertEqual(
            workflow_tool_names([a, b], None), {a.id: "invoice_sync", b.id: "refund_check"}
        )

    def test_repeated_names_get_a_suffix_and_the_oldest_keeps_the_plain_name(self) -> None:
        newer = _workflow("Invoice-Sync", 1)
        older = _workflow("Invoice sync", 5)
        newest = _workflow("invoice sync", 0)

        names = workflow_tool_names([newer, older, newest], None)

        self.assertEqual(names[older.id], "invoice_sync")
        self.assertEqual(names[newer.id], "invoice_sync_2")
        self.assertEqual(names[newest.id], "invoice_sync_3")

    def test_a_suffix_never_takes_another_workflow_name(self) -> None:
        first = _workflow("Report", 3)
        literal = _workflow("Report 2", 2)
        repeat = _workflow("report", 1)

        names = workflow_tool_names([first, literal, repeat], None)

        self.assertEqual(len(set(names.values())), 3)
        self.assertEqual(names[literal.id], "report_2")

    def test_the_user_own_workflow_keeps_the_plain_name_before_an_older_shared_one(self) -> None:
        user_id = uuid.uuid4()
        shared_older = _workflow("Invoice sync", 30)
        own_newer = _workflow("Invoice sync", 1, owner_id=user_id)
        own_newest = _workflow("Invoice-Sync", 0, owner_id=user_id)

        names = workflow_tool_names([shared_older, own_newest, own_newer], user_id)

        self.assertEqual(names[own_newer.id], "invoice_sync")
        self.assertEqual(names[own_newest.id], "invoice_sync_2")
        self.assertEqual(names[shared_older.id], "invoice_sync_3")


class DuplicateWorkflowToolCallTests(unittest.IsolatedAsyncioTestCase):
    async def _list_and_call(
        self, dispatch: object, workflows: list, user: SimpleNamespace | None = None
    ) -> tuple[list, dict]:
        user = user or SimpleNamespace(id=uuid.uuid4())
        chat_off = AgentSettings(enabled=False, credential_id=None, model=None)
        called: dict[str, object] = {}

        async def mint(*_args: object, **kwargs: object) -> dict:
            return {"jsonrpc": "2.0", "id": 1, "result": {"workflow": kwargs["workflow"].id}}

        with (
            patch("app.api.mcp.get_user_mcp_workflows", AsyncMock(return_value=workflows)),
            patch("app.api.mcp_servers._get_server_workflows", AsyncMock(return_value=workflows)),
            patch(
                "app.api.mcp.agent_settings.get_global_agent_settings",
                AsyncMock(return_value=chat_off),
            ),
            patch(
                "app.api.mcp_servers.agent_settings.get_server_agent_settings",
                AsyncMock(return_value=chat_off),
            ),
            patch("app.api.mcp._maybe_mint_file_upload_jsonrpc_response", side_effect=mint),
            patch("app.api.mcp_servers._maybe_mint_file_upload_jsonrpc_response", side_effect=mint),
        ):
            listed = await dispatch(_request("tools/list", {}), user)
            names = [t["name"] for t in listed["result"]["tools"]]
            for name in ("invoice_sync", "invoice_sync_2"):
                response = await dispatch(_request("tools/call", {"name": name}), user)
                called[name] = response["result"]["workflow"]
        return names, called

    async def _assert_each_workflow_is_reachable(self, dispatch: object) -> None:
        newer = _workflow("Invoice-Sync", 1)
        older = _workflow("Invoice sync", 5)

        names, called = await self._list_and_call(dispatch, [newer, older])

        self.assertIn("invoice_sync", names)
        self.assertIn("invoice_sync_2", names)
        self.assertEqual(called, {"invoice_sync": older.id, "invoice_sync_2": newer.id})

    async def _assert_the_user_own_workflow_keeps_the_plain_name(self, dispatch: object) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        own_newer = _workflow("Invoice sync", 1, owner_id=user.id)
        shared_older = _workflow("Invoice sync", 30)

        _, called = await self._list_and_call(dispatch, [own_newer, shared_older], user)

        self.assertEqual(called, {"invoice_sync": own_newer.id, "invoice_sync_2": shared_older.id})

    async def _default_server(self, request: Request, user: object) -> dict:
        return await _dispatch_mcp_jsonrpc(request=request, mcp_user=user, db=AsyncMock())

    async def _named_server(self, request: Request, user: object) -> dict:
        server = SimpleNamespace(id=uuid.uuid4())
        return await _dispatch_named_server_jsonrpc(
            server_id=server.id, request=request, server=(user, server), db=AsyncMock()
        )

    async def test_default_server_calls_each_workflow(self) -> None:
        await self._assert_each_workflow_is_reachable(self._default_server)

    async def test_named_server_calls_each_workflow(self) -> None:
        await self._assert_each_workflow_is_reachable(self._named_server)

    async def test_default_server_keeps_the_plain_name_on_the_user_own_workflow(self) -> None:
        await self._assert_the_user_own_workflow_keeps_the_plain_name(self._default_server)

    async def test_named_server_keeps_the_plain_name_on_the_owner_workflow(self) -> None:
        await self._assert_the_user_own_workflow_keeps_the_plain_name(self._named_server)


if __name__ == "__main__":
    unittest.main()
