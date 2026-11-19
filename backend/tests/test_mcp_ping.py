"""MCP: Heym's endpoints answer ping with an empty result, as the base protocol requires."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api import mcp, mcp_servers


def _request(method: str) -> MagicMock:
    request = MagicMock()
    request.json = AsyncMock(return_value={"jsonrpc": "2.0", "id": 7, "method": method})
    return request


class McpPingTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_endpoints_answer_ping_with_an_empty_result(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        server = SimpleNamespace(id=uuid.uuid4())
        want = {"jsonrpc": "2.0", "id": 7, "result": {}}

        self.assertEqual(await mcp._dispatch_mcp_jsonrpc(_request("ping"), user, AsyncMock()), want)
        self.assertEqual(
            await mcp_servers._dispatch_named_server_jsonrpc(
                server.id, _request("ping"), (user, server), AsyncMock()
            ),
            want,
        )

    async def test_an_unknown_method_is_still_not_found(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())

        answer = await mcp._dispatch_mcp_jsonrpc(_request("nope/nothing"), user, AsyncMock())

        self.assertEqual(answer["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
