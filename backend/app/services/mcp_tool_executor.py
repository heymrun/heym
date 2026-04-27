"""
Execute MCP (Model Context Protocol) tool calls via stdio or SSE transport.
"""

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

from mcp import types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)


def _extract_root_exception(exc: BaseException) -> BaseException:
    """
    Extract the root cause from ExceptionGroup for clearer error messages.
    MCP SSE client wraps httpx errors in TaskGroup ExceptionGroup.
    """
    if isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        return _extract_root_exception(exc.exceptions[0])
    return exc


def _mcp_tool_to_openai_format(
    tool: types.Tool,
    connection: dict[str, Any],
    connection_id: str,
    mcp_server_label: str,
) -> dict[str, Any]:
    """Convert MCP Tool to OpenAI function calling format."""
    input_schema = tool.inputSchema if hasattr(tool, "inputSchema") else {}
    if not input_schema:
        input_schema = {"type": "object", "properties": {}, "required": []}
    return {
        "name": tool.name,
        "description": tool.description or "",
        "parameters": input_schema,
        "_source": "mcp",
        "_connection": connection,
        "_connection_id": connection_id,
        "_mcp_server": mcp_server_label,
    }


def _extract_tool_result(call_result: types.CallToolResult) -> object:
    """Extract JSON-serializable result from MCP CallToolResult."""
    if call_result.isError and call_result.content:
        for block in call_result.content:
            if isinstance(block, types.TextContent):
                return {"error": block.text}
        return {"error": "Unknown MCP tool error"}
    if not call_result.content:
        return None
    parts: list[str] = []
    for block in call_result.content:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
    if call_result.structuredContent is not None:
        return call_result.structuredContent
    if parts:
        try:
            return json.loads(parts[0])
        except json.JSONDecodeError:
            return "\n".join(parts)
    return None


def _normalize_connection(connection: dict[str, Any]) -> dict[str, Any]:
    """Parse args/headers from JSON strings if needed."""
    conn = dict(connection)
    args = conn.get("args")
    if isinstance(args, str) and args.strip():
        try:
            conn["args"] = json.loads(args)
        except json.JSONDecodeError:
            conn["args"] = []
    elif not isinstance(args, list):
        conn["args"] = args or []
    headers = conn.get("headers")
    if isinstance(headers, str) and headers.strip():
        try:
            conn["headers"] = json.loads(headers)
        except json.JSONDecodeError:
            conn["headers"] = {}
    elif not isinstance(headers, dict):
        conn["headers"] = headers or {}
    return conn


async def _list_mcp_tools_async(connection: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    """List tools from MCP server (async)."""
    conn = _normalize_connection(connection)
    transport = conn.get("transport", "stdio")
    connection_id = conn.get("id", "default")
    label = conn.get("label") or connection_id

    if transport == "stdio":
        command = conn.get("command", "")
        args = conn.get("args") or []
        env = conn.get("env")
        if not command:
            raise ValueError("stdio connection requires 'command'")
        server_params = StdioServerParameters(
            command=command,
            args=args if isinstance(args, list) else [],
            env=env,
        )
        transport_ctx = stdio_client(server_params)
    elif transport == "sse":
        url = conn.get("url", "")
        headers = conn.get("headers") or {}
        if not url:
            raise ValueError("sse connection requires 'url'")
        transport_ctx = sse_client(
            url,
            headers=headers,
            timeout=min(5.0, timeout),
            sse_read_timeout=timeout,
        )
    else:
        raise ValueError(f"Unknown MCP transport: {transport}")

    tools_out: list[dict[str, Any]] = []
    read_timeout = timedelta(seconds=timeout) if timeout and timeout > 0 else None
    async with transport_ctx as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=read_timeout,
        ) as session:
            await session.initialize()
            result = await session.list_tools()
            for tool in result.tools:
                tools_out.append(_mcp_tool_to_openai_format(tool, conn, connection_id, label))
    return tools_out


async def _execute_mcp_tool_async(
    connection: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float,
) -> object:
    """Execute a tool on MCP server (async)."""
    conn = _normalize_connection(connection)
    transport = conn.get("transport", "stdio")

    if transport == "stdio":
        command = conn.get("command", "")
        args = conn.get("args") or []
        env = conn.get("env")
        if not command:
            raise ValueError("stdio connection requires 'command'")
        server_params = StdioServerParameters(
            command=command,
            args=args if isinstance(args, list) else [],
            env=env,
        )
        transport_ctx = stdio_client(server_params)
    elif transport == "sse":
        url = conn.get("url", "")
        headers = conn.get("headers") or {}
        if not url:
            raise ValueError("sse connection requires 'url'")
        transport_ctx = sse_client(
            url,
            headers=headers,
            timeout=min(5.0, timeout),
            sse_read_timeout=timeout,
        )
    else:
        raise ValueError(f"Unknown MCP transport: {transport}")

    read_timeout = timedelta(seconds=timeout) if timeout and timeout > 0 else None
    async with transport_ctx as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=read_timeout,
        ) as session:
            await session.initialize()
            call_result = await session.call_tool(
                tool_name,
                arguments=arguments or {},
                read_timeout_seconds=read_timeout,
            )
            return _extract_tool_result(call_result)


def list_mcp_tools(
    connection: dict[str, Any], timeout_seconds: float = 30.0
) -> list[dict[str, Any]]:
    """
    List tools from an MCP server. Runs async code in a new event loop (thread-safe).

    Args:
        connection: Dict with transport, and either (command, args, env) for stdio
                    or (url, headers) for sse.
        timeout_seconds: Max time for the operation.

    Returns:
        List of tools in OpenAI function format with _source, _connection_id, _mcp_server.
    """
    try:
        return asyncio.run(_list_mcp_tools_async(connection, timeout_seconds))
    except Exception as e:
        root = _extract_root_exception(e)
        logger.exception("MCP list_tools failed: %s", root)
        raise root from e


def execute_mcp_tool(
    connection: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    timeout_seconds: float = 30.0,
) -> object:
    """
    Execute a tool on an MCP server. Runs async code in a new event loop (thread-safe).

    Args:
        connection: Dict with transport, and either (command, args, env) for stdio
                    or (url, headers) for sse.
        tool_name: Name of the tool to call.
        arguments: Dict of arguments to pass.
        timeout_seconds: Max execution time.

    Returns:
        JSON-serializable tool result.
    """
    try:
        return asyncio.run(
            _execute_mcp_tool_async(connection, tool_name, arguments, timeout_seconds)
        )
    except Exception as e:
        root = _extract_root_exception(e)
        logger.exception("MCP call_tool failed: %s", root)
        raise root from e
