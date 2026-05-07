"""
Execute MCP (Model Context Protocol) tool calls via stdio, SSE, or Streamable HTTP transport.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

import anyio
import httpx
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from httpx_sse import aconnect_sse
from httpx_sse._exceptions import SSEError
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)


def _extract_root_exception(exc: BaseException) -> BaseException:
    """
    Extract the root cause from ExceptionGroup for clearer error messages.
    MCP SSE client wraps httpx errors in TaskGroup ExceptionGroup.
    """
    if isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        return _extract_root_exception(exc.exceptions[0])
    return exc


def _remove_request_params(url: str) -> str:
    return urljoin(url, urlparse(url).path)


def _post_failure_message(
    session_message: SessionMessage,
    exc: BaseException,
) -> SessionMessage | Exception:
    root = session_message.message.root
    request_id = getattr(root, "id", None)
    if request_id is None:
        return exc

    status_code = -32000
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
    message = f"MCP SSE POST failed: {exc}"
    return SessionMessage(
        types.JSONRPCMessage(
            types.JSONRPCError(
                jsonrpc="2.0",
                id=request_id,
                error=types.ErrorData(code=status_code, message=message),
            )
        )
    )


@asynccontextmanager
async def _sse_client_fail_fast(
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> AsyncGenerator[tuple[Any, Any], None]:
    """
    SSE transport with the MCP SDK behaviour plus fail-fast POST errors.

    The upstream SDK logs POST failures but does not forward them to the read
    side, so callers can sit until their read timeout after a 401/403. This
    wrapper converts failed POSTs into JSON-RPC errors for request messages and
    closes the read stream immediately.
    """
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]
    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async with anyio.create_task_group() as tg:
        try:
            logger.debug("Connecting to SSE endpoint: %s", _remove_request_params(url))
            async with create_mcp_http_client(
                headers=headers,
                timeout=httpx.Timeout(timeout, read=sse_read_timeout),
            ) as client:
                async with aconnect_sse(client, "GET", url) as event_source:
                    event_source.response.raise_for_status()
                    logger.debug("SSE connection established")

                    async def sse_reader(
                        task_status: TaskStatus[str] = anyio.TASK_STATUS_IGNORED,
                    ) -> None:
                        try:
                            async for sse in event_source.aiter_sse():
                                logger.debug("Received SSE event: %s", sse.event)
                                if sse.event == "endpoint":
                                    endpoint_url = urljoin(url, sse.data)
                                    logger.debug("Received endpoint URL: %s", endpoint_url)
                                    url_parsed = urlparse(url)
                                    endpoint_parsed = urlparse(endpoint_url)
                                    if (
                                        url_parsed.netloc != endpoint_parsed.netloc
                                        or url_parsed.scheme != endpoint_parsed.scheme
                                    ):
                                        error_msg = (
                                            "Endpoint origin does not match connection origin: "
                                            f"{endpoint_url}"
                                        )
                                        logger.error(error_msg)
                                        raise ValueError(error_msg)
                                    task_status.started(endpoint_url)
                                elif sse.event == "message":
                                    if not sse.data:
                                        continue
                                    try:
                                        message = types.JSONRPCMessage.model_validate_json(sse.data)
                                        logger.debug("Received server message: %s", message)
                                    except Exception as exc:
                                        logger.exception("Error parsing server message")
                                        await read_stream_writer.send(exc)
                                        continue
                                    await read_stream_writer.send(SessionMessage(message))
                                else:
                                    logger.warning("Unknown SSE event: %s", sse.event)
                        except SSEError as exc:
                            logger.exception("Encountered SSE exception")
                            raise exc
                        except Exception as exc:
                            logger.exception("Error in sse_reader")
                            await read_stream_writer.send(exc)
                        finally:
                            await read_stream_writer.aclose()

                    async def post_writer(endpoint_url: str) -> None:
                        try:
                            async with write_stream_reader:
                                async for session_message in write_stream_reader:
                                    logger.debug("Sending client message: %s", session_message)
                                    try:
                                        response = await client.post(
                                            endpoint_url,
                                            json=session_message.message.model_dump(
                                                by_alias=True,
                                                mode="json",
                                                exclude_none=True,
                                            ),
                                        )
                                        response.raise_for_status()
                                    except Exception as exc:
                                        logger.exception("Error in post_writer")
                                        await read_stream_writer.send(
                                            _post_failure_message(session_message, exc)
                                        )
                                        await read_stream_writer.aclose()
                                        return
                                    logger.debug(
                                        "Client message sent successfully: %s",
                                        response.status_code,
                                    )
                        finally:
                            await write_stream.aclose()

                    endpoint_url = await tg.start(sse_reader)
                    logger.debug("Starting post writer with endpoint URL: %s", endpoint_url)
                    tg.start_soon(post_writer, endpoint_url)

                    try:
                        yield read_stream, write_stream
                    finally:
                        tg.cancel_scope.cancel()
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()


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
    env = conn.get("env")
    if isinstance(env, str) and env.strip():
        try:
            conn["env"] = json.loads(env)
        except json.JSONDecodeError:
            conn["env"] = {}
    elif env is not None and not isinstance(env, dict):
        conn["env"] = {}
    return conn


@asynccontextmanager
async def _open_transport(
    conn: dict[str, Any],
    timeout: float,
) -> AsyncGenerator[tuple[Any, Any], None]:
    """Normalize stdio/sse/streamable_http context managers to a (read, write) pair."""
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
        async with stdio_client(server_params) as (read_stream, write_stream):
            yield read_stream, write_stream

    elif transport == "sse":
        url = conn.get("url", "")
        headers = conn.get("headers") or {}
        if not url:
            raise ValueError("sse connection requires 'url'")
        async with _sse_client_fail_fast(
            url,
            headers=headers,
            timeout=min(5.0, timeout),
            sse_read_timeout=timeout,
        ) as (read_stream, write_stream):
            yield read_stream, write_stream

    elif transport == "streamable_http":
        url = conn.get("url", "")
        headers = conn.get("headers") or {}
        if not url:
            raise ValueError("streamable_http connection requires 'url'")
        async with httpx.AsyncClient(headers=headers, timeout=timeout) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (
                read_stream,
                write_stream,
                _get_session_id,
            ):
                yield read_stream, write_stream

    else:
        raise ValueError(f"Unknown MCP transport: {transport}")


async def _list_mcp_tools_async(connection: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    """List tools from MCP server (async)."""
    conn = _normalize_connection(connection)
    connection_id = conn.get("id", "default")
    label = conn.get("label") or connection_id

    tools_out: list[dict[str, Any]] = []
    read_timeout = timedelta(seconds=timeout) if timeout and timeout > 0 else None
    async with _open_transport(conn, timeout) as (read_stream, write_stream):
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
    read_timeout = timedelta(seconds=timeout) if timeout and timeout > 0 else None
    async with _open_transport(conn, timeout) as (read_stream, write_stream):
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
        connection: Dict with transport, and either (command, args, env) for stdio,
                    (url, headers) for sse, or (url, headers) for streamable_http.
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
        connection: Dict with transport, and either (command, args, env) for stdio,
                    (url, headers) for sse, or (url, headers) for streamable_http.
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
