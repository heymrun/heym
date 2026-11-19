"""A workflow that fails while running is an MCP tool result with isError on every server."""

import unittest
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import mcp, mcp_servers

OWNER = uuid.uuid4()
WORKFLOW = SimpleNamespace(
    id=uuid.uuid4(),
    name="Invoice sync",
    owner_id=OWNER,
    description=None,
    nodes=[{"id": "t", "type": "textInput", "data": {"label": "t"}}],
    edges=[],
    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    concurrency_limit=None,
    workflow_timeout_seconds=None,
)


def _request() -> MagicMock:
    request = MagicMock()
    request.json = AsyncMock(
        return_value={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "invoice_sync", "arguments": {}},
        }
    )
    return request


def _patches(module, stack: ExitStack) -> None:
    stack.enter_context(
        patch.object(module, "collect_referenced_workflows", AsyncMock(return_value={}))
    )
    stack.enter_context(
        patch.object(
            module, "dispatch_workflow", AsyncMock(side_effect=RuntimeError("provider down"))
        )
    )
    stack.enter_context(patch.object(module, "register_execution", MagicMock()))
    stack.enter_context(patch.object(module, "clear_active_execution", MagicMock()))
    stack.enter_context(patch.object(module, "_add_mcp_workflow_trace", MagicMock()))
    for name in (
        "get_credentials_context_for_user",
        "get_credentials_context",
        "get_global_variables_context",
    ):
        if hasattr(module, name):
            stack.enter_context(patch.object(module, name, AsyncMock(return_value={})))
    if hasattr(module, "_maybe_mint_file_upload_jsonrpc_response"):
        stack.enter_context(
            patch.object(
                module, "_maybe_mint_file_upload_jsonrpc_response", AsyncMock(return_value=None)
            )
        )


class McpToolErrorResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_server_reports_the_failure_as_a_tool_error(self) -> None:
        with ExitStack() as stack:
            _patches(mcp, stack)
            stack.enter_context(
                patch.object(mcp, "get_user_mcp_workflows", AsyncMock(return_value=[WORKFLOW]))
            )
            answer = await mcp._dispatch_mcp_jsonrpc(
                _request(), SimpleNamespace(id=OWNER), AsyncMock()
            )

        self.assertNotIn("error", answer)
        self.assertTrue(answer["result"]["isError"])
        self.assertEqual(
            answer["result"]["content"],
            [{"type": "text", "text": "Execution error: provider down"}],
        )

    async def test_named_server_answers_the_same_way(self) -> None:
        server = SimpleNamespace(id=uuid.uuid4())
        with ExitStack() as stack:
            _patches(mcp_servers, stack)
            stack.enter_context(
                patch.object(
                    mcp_servers, "_get_server_workflows", AsyncMock(return_value=[WORKFLOW])
                )
            )
            stack.enter_context(
                patch.object(
                    mcp_servers.agent_settings,
                    "get_server_agent_settings",
                    AsyncMock(return_value=SimpleNamespace(enabled=False)),
                )
            )
            answer = await mcp_servers._dispatch_named_server_jsonrpc(
                server.id, _request(), (SimpleNamespace(id=OWNER), server), AsyncMock()
            )

        self.assertTrue(answer["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
