"""Unit tests for mcp_tool_executor helper functions."""

import os
import unittest
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from mcp import types
from mcp.shared.message import SessionMessage

from app.services.mcp_tool_executor import (
    _execute_mcp_tool_async,
    _extract_tool_result,
    _mcp_tool_to_openai_format,
    _normalize_connection,
    _open_transport,
    _post_failure_message,
)


class NormalizeConnectionTests(unittest.TestCase):
    def test_args_json_string_parsed_to_list(self) -> None:
        conn = {"args": '["-y", "pkg"]'}
        result = _normalize_connection(conn)
        self.assertEqual(result["args"], ["-y", "pkg"])

    def test_args_already_list_unchanged(self) -> None:
        conn = {"args": ["-y", "pkg"]}
        result = _normalize_connection(conn)
        self.assertEqual(result["args"], ["-y", "pkg"])

    def test_args_none_becomes_empty_list(self) -> None:
        conn = {"args": None}
        result = _normalize_connection(conn)
        self.assertEqual(result["args"], [])

    def test_args_invalid_json_string_becomes_empty_list(self) -> None:
        conn = {"args": "not-json"}
        result = _normalize_connection(conn)
        self.assertEqual(result["args"], [])

    def test_headers_json_string_parsed_to_dict(self) -> None:
        conn = {"headers": '{"Authorization": "Bearer tok"}'}
        result = _normalize_connection(conn)
        self.assertEqual(result["headers"], {"Authorization": "Bearer tok"})

    def test_headers_already_dict_unchanged(self) -> None:
        conn = {"headers": {"X-Custom": "v"}}
        result = _normalize_connection(conn)
        self.assertEqual(result["headers"], {"X-Custom": "v"})

    def test_headers_none_becomes_empty_dict(self) -> None:
        conn = {"headers": None}
        result = _normalize_connection(conn)
        self.assertEqual(result["headers"], {})

    def test_headers_invalid_json_becomes_empty_dict(self) -> None:
        conn = {"headers": "not-json"}
        result = _normalize_connection(conn)
        self.assertEqual(result["headers"], {})

    def test_original_dict_not_mutated(self) -> None:
        original = {"args": '["-y"]', "headers": "{}"}
        _normalize_connection(original)
        self.assertEqual(original["args"], '["-y"]')


class ExtractToolResultTests(unittest.TestCase):
    def _text_result(self, text: str, is_error: bool = False) -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            isError=is_error,
        )

    def test_text_content_parsed_as_json(self) -> None:
        result = self._text_result('{"key": "value"}')
        extracted = _extract_tool_result(result)
        self.assertEqual(extracted, {"key": "value"})

    def test_text_content_non_json_returned_as_string(self) -> None:
        result = self._text_result("plain text")
        extracted = _extract_tool_result(result)
        self.assertEqual(extracted, "plain text")

    def test_error_result_returns_error_dict(self) -> None:
        result = self._text_result("something broke", is_error=True)
        extracted = _extract_tool_result(result)
        self.assertEqual(extracted, {"error": "something broke"})

    def test_empty_content_returns_none(self) -> None:
        result = types.CallToolResult(content=[], isError=False)
        extracted = _extract_tool_result(result)
        self.assertIsNone(extracted)

    def test_structured_content_takes_priority(self) -> None:
        result = types.CallToolResult(
            content=[types.TextContent(type="text", text='{"ignored": true}')],
            isError=False,
            structuredContent={"structured": True},
        )
        extracted = _extract_tool_result(result)
        self.assertEqual(extracted, {"structured": True})


class McpToolToOpenAiFormatTests(unittest.TestCase):
    def _make_tool(self, name: str = "my_tool", description: str = "A tool") -> types.Tool:
        tool = MagicMock(spec=types.Tool)
        tool.name = name
        tool.description = description
        tool.inputSchema = {"type": "object", "properties": {}}
        return tool

    def test_name_mapped_correctly(self) -> None:
        tool = self._make_tool(name="search_web")
        conn = {"transport": "sse", "url": "https://example.com"}
        result = _mcp_tool_to_openai_format(tool, conn, "conn1", "my_server")
        self.assertEqual(result["name"], "search_web")

    def test_description_mapped_correctly(self) -> None:
        tool = self._make_tool(description="Searches the web")
        conn = {}
        result = _mcp_tool_to_openai_format(tool, conn, "c1", "srv")
        self.assertEqual(result["description"], "Searches the web")

    def test_source_is_mcp(self) -> None:
        tool = self._make_tool()
        result = _mcp_tool_to_openai_format(tool, {}, "c1", "srv")
        self.assertEqual(result["_source"], "mcp")

    def test_connection_id_and_server_set(self) -> None:
        tool = self._make_tool()
        result = _mcp_tool_to_openai_format(tool, {}, "conn-id", "server-label")
        self.assertEqual(result["_connection_id"], "conn-id")
        self.assertEqual(result["_mcp_server"], "server-label")

    def test_parameters_from_input_schema(self) -> None:
        tool = self._make_tool()
        tool.inputSchema = {"type": "object", "properties": {"q": {"type": "string"}}}
        result = _mcp_tool_to_openai_format(tool, {}, "c", "s")
        self.assertEqual(result["parameters"]["properties"]["q"]["type"], "string")


class SSEPostFailureMessageTests(unittest.TestCase):
    def test_http_status_error_becomes_jsonrpc_error_for_pending_request(self) -> None:
        request = httpx.Request("POST", "https://example.com/message")
        response = httpx.Response(401, request=request)
        exc = httpx.HTTPStatusError(
            "Client error '401 Unauthorized'",
            request=request,
            response=response,
        )
        session_message = SessionMessage(
            types.JSONRPCMessage(
                types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id=7,
                    method="tools/list",
                )
            )
        )

        result = _post_failure_message(session_message, exc)

        self.assertIsInstance(result, SessionMessage)
        root = result.message.root
        self.assertIsInstance(root, types.JSONRPCError)
        self.assertEqual(root.id, 7)
        self.assertEqual(root.error.code, 401)
        self.assertIn("MCP SSE POST failed", root.error.message)

    def test_notification_post_failure_returns_exception(self) -> None:
        exc = RuntimeError("closed")
        session_message = SessionMessage(
            types.JSONRPCMessage(
                types.JSONRPCNotification(
                    jsonrpc="2.0",
                    method="notifications/initialized",
                )
            )
        )

        result = _post_failure_message(session_message, exc)

        self.assertIs(result, exc)


class ListMcpToolsErrorPathTests(unittest.TestCase):
    """list_mcp_tools raises ValueError before any network I/O for bad configs."""

    def test_unknown_transport_raises(self) -> None:
        from app.services.mcp_tool_executor import list_mcp_tools

        with self.assertRaises(ValueError) as ctx:
            list_mcp_tools({"transport": "websocket"}, timeout_seconds=5.0)
        self.assertIn("Unknown MCP transport", str(ctx.exception))

    def test_stdio_missing_command_raises(self) -> None:
        from app.services.mcp_tool_executor import list_mcp_tools

        with self.assertRaises(ValueError) as ctx:
            list_mcp_tools({"transport": "stdio"}, timeout_seconds=5.0)
        self.assertIn("command", str(ctx.exception))

    def test_sse_missing_url_raises(self) -> None:
        from app.services.mcp_tool_executor import list_mcp_tools

        with self.assertRaises(ValueError) as ctx:
            list_mcp_tools({"transport": "sse"}, timeout_seconds=5.0)
        self.assertIn("url", str(ctx.exception))

    def test_streamable_http_missing_url_raises(self) -> None:
        from app.services.mcp_tool_executor import list_mcp_tools

        with self.assertRaises(ValueError) as ctx:
            list_mcp_tools({"transport": "streamable_http"}, timeout_seconds=5.0)
        self.assertIn("url", str(ctx.exception))


class ExecuteMcpToolSessionToolListTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_tool_lists_tools_in_same_session_first(self) -> None:
        calls: list[str] = []

        @asynccontextmanager
        async def fake_open_transport(_conn: dict, _timeout: float):
            yield object(), object()

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                self.initialize = AsyncMock(side_effect=lambda: calls.append("initialize"))
                self.list_tools = AsyncMock(
                    side_effect=lambda: (
                        calls.append("list_tools")
                        or SimpleNamespace(tools=[SimpleNamespace(name="search")])
                    )
                )
                self.call_tool = AsyncMock(
                    side_effect=lambda *_args, **_kwargs: (
                        calls.append("call_tool")
                        or types.CallToolResult(
                            content=[types.TextContent(type="text", text='{"ok": true}')],
                            isError=False,
                        )
                    )
                )

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> None:
                return None

        with (
            patch("app.services.mcp_tool_executor._open_transport", fake_open_transport),
            patch("app.services.mcp_tool_executor.ClientSession", FakeSession),
        ):
            result = await _execute_mcp_tool_async(
                {"transport": "stdio", "command": "fake"},
                "search",
                {"q": "hello"},
                5,
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls, ["initialize", "list_tools", "call_tool"])

    async def test_missing_tool_raises_with_available_tools(self) -> None:
        @asynccontextmanager
        async def fake_open_transport(_conn: dict, _timeout: float):
            yield object(), object()

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                self.initialize = AsyncMock()
                self.list_tools = AsyncMock(
                    return_value=SimpleNamespace(
                        tools=[
                            SimpleNamespace(name="list_notifications"),
                            SimpleNamespace(name="manage_notification_subscription"),
                        ]
                    )
                )
                self.call_tool = AsyncMock()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> None:
                return None

        with (
            patch("app.services.mcp_tool_executor._open_transport", fake_open_transport),
            patch("app.services.mcp_tool_executor.ClientSession", FakeSession),
        ):
            with self.assertRaises(ValueError) as ctx:
                await _execute_mcp_tool_async(
                    {"transport": "stdio", "command": "fake"},
                    "manage_repository_notification_subscription",
                    {},
                    5,
                )

        self.assertIn("is not available on this connection", str(ctx.exception))
        self.assertIn("list_notifications", str(ctx.exception))

    async def test_call_tool_omits_empty_optional_schema_arguments(self) -> None:
        captured_arguments: list[dict[str, Any]] = []
        input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
                "search_depth": {"type": "string", "enum": ["basic", "advanced"]},
                "include_images": {"type": "boolean"},
                "include_domains": {"type": "array", "items": {"type": "string"}},
                "country": {"type": "string"},
            },
            "required": ["query"],
        }

        @asynccontextmanager
        async def fake_open_transport(
            _conn: dict[str, Any],
            _timeout: float,
        ) -> AsyncGenerator[tuple[object, object], None]:
            yield object(), object()

        class FakeSession:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                self.initialize = AsyncMock()
                self.list_tools = AsyncMock(
                    return_value=SimpleNamespace(
                        tools=[SimpleNamespace(name="tavily_search", inputSchema=input_schema)]
                    )
                )
                self.call_tool = AsyncMock(side_effect=self._call_tool)

            async def _call_tool(
                self,
                *_args: Any,
                **kwargs: Any,
            ) -> types.CallToolResult:
                captured_arguments.append(kwargs["arguments"])
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text='{"ok": true}')],
                    isError=False,
                )

            async def __aenter__(self) -> "FakeSession":
                return self

            async def __aexit__(self, *_args: Any) -> None:
                return None

        with (
            patch("app.services.mcp_tool_executor._open_transport", fake_open_transport),
            patch("app.services.mcp_tool_executor.ClientSession", FakeSession),
        ):
            result = await _execute_mcp_tool_async(
                {"transport": "stdio", "command": "fake"},
                "tavily_search",
                {
                    "query": "ai workflow news",
                    "max_results": "",
                    "search_depth": "",
                    "include_images": "",
                    "include_domains": "",
                    "country": "",
                },
                5,
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured_arguments, [{"query": "ai workflow news"}])

    async def test_call_tool_keeps_empty_required_schema_arguments(self) -> None:
        captured_arguments: list[dict[str, Any]] = []
        input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        }

        @asynccontextmanager
        async def fake_open_transport(
            _conn: dict[str, Any],
            _timeout: float,
        ) -> AsyncGenerator[tuple[object, object], None]:
            yield object(), object()

        class FakeSession:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                self.initialize = AsyncMock()
                self.list_tools = AsyncMock(
                    return_value=SimpleNamespace(
                        tools=[SimpleNamespace(name="tavily_search", inputSchema=input_schema)]
                    )
                )
                self.call_tool = AsyncMock(side_effect=self._call_tool)

            async def _call_tool(
                self,
                *_args: Any,
                **kwargs: Any,
            ) -> types.CallToolResult:
                captured_arguments.append(kwargs["arguments"])
                return types.CallToolResult(content=[], isError=False)

            async def __aenter__(self) -> "FakeSession":
                return self

            async def __aexit__(self, *_args: Any) -> None:
                return None

        with (
            patch("app.services.mcp_tool_executor._open_transport", fake_open_transport),
            patch("app.services.mcp_tool_executor.ClientSession", FakeSession),
        ):
            await _execute_mcp_tool_async(
                {"transport": "stdio", "command": "fake"},
                "tavily_search",
                {"query": "", "max_results": ""},
                5,
            )

        self.assertEqual(captured_arguments, [{"query": ""}])


class StdioEnvMergeTests(unittest.IsolatedAsyncioTestCase):
    """stdio transport must never hand os.environ to the MCP server it starts.

    This class previously asserted the opposite, on the premise that os.environ
    had to be merged in so PATH would be available for docker/npx/uvx. That
    premise was wrong: the MCP SDK's get_default_environment() already includes
    PATH (plus HOME, SHELL, TERM, USER, LOGNAME) and already merges the caller's
    env over it, so merging os.environ only served to leak SECRET_KEY,
    ENCRYPTION_KEY, DATABASE_URL and provider API keys into a third-party MCP
    server. See GHSA-378x-q589-34mv.
    """

    async def test_user_env_passed_without_os_environ(self) -> None:
        with (
            patch("app.services.mcp_tool_executor.StdioServerParameters") as mock_params,
            patch("app.services.mcp_tool_executor.stdio_client") as mock_stdio_client,
            patch.dict(
                os.environ,
                {"HEYM_MCP_STDIO_SANDBOX": "subprocess", "SECRET_KEY": "super-secret-value"},
            ),
        ):
            mock_stdio_client.return_value.__aenter__ = AsyncMock(return_value=(object(), object()))
            mock_stdio_client.return_value.__aexit__ = AsyncMock(return_value=None)

            conn = {
                "transport": "stdio",
                "command": "uvx",
                "args": ["some-server"],
                "env": {"SECRET_TOKEN": "abc123"},
            }

            try:
                async with _open_transport(conn, 5.0):
                    pass
            except Exception:
                pass

            mock_params.assert_called_once()
            passed_env = mock_params.call_args.kwargs.get("env")

            self.assertEqual(
                passed_env,
                {"SECRET_TOKEN": "abc123"},
                "only the caller's own env vars may reach the MCP server",
            )
            self.assertNotIn("SECRET_KEY", passed_env)
            self.assertNotIn("PATH", passed_env, "PATH comes from the SDK's safe default, not us")

    async def test_no_user_env_passes_none(self) -> None:
        with (
            patch("app.services.mcp_tool_executor.StdioServerParameters") as mock_params,
            patch("app.services.mcp_tool_executor.stdio_client") as mock_stdio_client,
            patch.dict(os.environ, {"HEYM_MCP_STDIO_SANDBOX": "subprocess"}),
        ):
            mock_stdio_client.return_value.__aenter__ = AsyncMock(return_value=(object(), object()))
            mock_stdio_client.return_value.__aexit__ = AsyncMock(return_value=None)

            conn = {"transport": "stdio", "command": "uvx", "args": ["some-server"]}

            try:
                async with _open_transport(conn, 5.0):
                    pass
            except Exception:
                pass

            mock_params.assert_called_once()
            passed_env = mock_params.call_args.kwargs.get("env")
            self.assertIsNone(
                passed_env, "no user env -> SDK applies get_default_environment() alone"
            )
