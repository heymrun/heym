"""Unit tests for mcp_tool_executor helper functions."""

import unittest
from unittest.mock import MagicMock

from mcp import types

from app.services.mcp_tool_executor import (
    _extract_tool_result,
    _mcp_tool_to_openai_format,
    _normalize_connection,
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
