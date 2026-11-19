"""MCP: Heym's client reads every tools/list page, following nextCursor."""

import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_client_server_memory_streams

from app.services import mcp_tool_executor as executor

CONNECTION = {"transport": "stdio", "command": "paged-server"}


def _paged_server(pages: list[list[str]], repeat_last_cursor: bool = False) -> Server:
    """A real MCP SDK server whose tools/list spans ``pages``."""
    server = Server("paged")

    async def list_tools(request: types.ListToolsRequest | None) -> types.ServerResult:
        cursor = request.params.cursor if request is not None and request.params else None
        index = int(cursor) if cursor else 0
        is_last = index == len(pages) - 1
        next_cursor = None
        if not is_last:
            next_cursor = str(index + 1)
        elif repeat_last_cursor:
            next_cursor = str(index)
        return types.ServerResult(
            types.ListToolsResult(
                tools=[
                    types.Tool(name=name, inputSchema={"type": "object"}) for name in pages[index]
                ],
                nextCursor=next_cursor,
            )
        )

    server.request_handlers[types.ListToolsRequest] = list_tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=f"called {name}")]

    return server


def _transport(server: Server):
    @asynccontextmanager
    async def open_transport(_connection, _timeout):
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:
                group.start_soon(
                    lambda: server.run(
                        server_streams[0], server_streams[1], server.create_initialization_options()
                    )
                )
                yield client_streams
                group.cancel_scope.cancel()

    return open_transport


class McpClientPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_page_is_listed_and_a_later_page_tool_can_be_called(self) -> None:
        server = _paged_server([["a"], ["b"], ["c"]])
        with patch.object(executor, "_open_transport", _transport(server)):
            listed = await executor._list_mcp_tools_async(CONNECTION, 5)
            called = await executor._execute_mcp_tool_async(CONNECTION, "c", {}, 5)

        self.assertEqual([tool["name"] for tool in listed], ["a", "b", "c"])
        self.assertEqual(called, "called c")

    async def test_a_cursor_that_repeats_stops_the_listing(self) -> None:
        server = _paged_server([["a"], ["b"]], repeat_last_cursor=True)
        with patch.object(executor, "_open_transport", _transport(server)):
            listed = await executor._list_mcp_tools_async(CONNECTION, 5)

        self.assertEqual([tool["name"] for tool in listed], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
