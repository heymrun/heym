"""The global MCP server lists and runs the user memory tools for the key's owner."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Request

from app.api import mcp as mcp_api


def _request(body: dict) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}

    return Request(
        {"type": "http", "method": "POST", "path": "/api/mcp", "headers": [], "query_string": b""},
        receive,
    )


def _workflow(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), name=name, description=None, nodes=[], edges=[], concurrency_limit=None
    )


class GlobalToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_tools_are_listed_without_heym_chat(self) -> None:
        with patch("app.api.mcp.extract_input_fields_from_workflow", return_value=[]):
            tools = await mcp_api.global_mcp_tools(
                [_workflow("Daily report")], SimpleNamespace(enabled=False)
            )
        names = [t.name for t in tools]
        self.assertIn("daily_report", names)
        self.assertIn("get_user_memory", names)
        self.assertIn("set_user_memory", names)
        self.assertNotIn("heym_chat", names)

    async def test_a_workflow_with_a_reserved_name_is_left_out(self) -> None:
        with patch("app.api.mcp.extract_input_fields_from_workflow", return_value=[]):
            tools = await mcp_api.global_mcp_tools(
                [_workflow("Get User Memory")], SimpleNamespace(enabled=False)
            )
        names = [t.name for t in tools]
        self.assertEqual(names.count("get_user_memory"), 1)
        memory_tool = next(t for t in tools if t.name == "get_user_memory")
        self.assertIn("User Rules", memory_tool.description or "")


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_list_includes_memory_tools(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        with (
            patch.object(mcp_api, "get_user_mcp_workflows", AsyncMock(return_value=[])),
            patch.object(
                mcp_api.agent_settings,
                "get_global_agent_settings",
                AsyncMock(return_value=SimpleNamespace(enabled=False)),
            ),
        ):
            response = await mcp_api._dispatch_mcp_jsonrpc(
                _request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}),
                user,
                AsyncMock(),
            )
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertEqual(names, ["get_user_memory", "set_user_memory"])

    async def test_tools_call_runs_the_memory_tool_for_the_key_owner(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        arguments = {"mode": "append", "content": "Prefers short answers"}
        with patch.object(
            mcp_api,
            "call_user_memory_tool",
            AsyncMock(return_value={"status": "added", "content": "Prefers short answers"}),
        ) as call_tool:
            response = await mcp_api._dispatch_mcp_jsonrpc(
                _request(
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "method": "tools/call",
                        "params": {"name": "set_user_memory", "arguments": arguments},
                    }
                ),
                user,
                db,
            )
        call_tool.assert_awaited_once_with(db, user, "set_user_memory", arguments, source="mcp")
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(json.loads(response["result"]["content"][0]["text"])["status"], "added")

    async def test_a_tool_error_is_an_mcp_error_result(self) -> None:
        with patch.object(
            mcp_api,
            "call_user_memory_tool",
            AsyncMock(return_value={"status": "refused", "error": "looks like a key"}),
        ):
            response = await mcp_api._dispatch_mcp_jsonrpc(
                _request(
                    {
                        "jsonrpc": "2.0",
                        "id": 8,
                        "method": "tools/call",
                        "params": {"name": "set_user_memory", "arguments": None},
                    }
                ),
                SimpleNamespace(id=uuid.uuid4()),
                AsyncMock(),
            )
        self.assertTrue(response["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
