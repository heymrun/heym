"""
Execute MCP (Model Context Protocol) tool calls via stdio, SSE, or Streamable HTTP transport.
"""

import asyncio
import ipaddress
import json
import logging
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

import anyio
import httpcore
import httpx
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from httpx_sse import aconnect_sse
from httpx_sse._exceptions import SSEError
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.message import SessionMessage

from app.config import settings
from app.services.mcp_stdio_sandbox import (
    build_sandboxed_command,
    force_remove_container,
)

logger = logging.getLogger(__name__)

_MCP_ALLOWED_URL_SCHEMES = ("http", "https")


def _resolve_mcp_host_addresses(
    hostname: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve an MCP URL host to every IP address it maps to.

    An IP literal resolves to itself; a DNS name is resolved via ``getaddrinfo``
    so all A/AAAA records are inspected (one safe-looking record is not enough).
    """
    host = hostname.strip("[]")
    if "%" in host:
        host = host.split("%", 1)[0]

    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    try:
        resolved = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("MCP server URL host could not be resolved") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for family, _, _, _, sockaddr in resolved:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        address = ipaddress.ip_address(sockaddr[0].split("%", 1)[0])
        key = address.compressed
        if key in seen:
            continue
        seen.add(key)
        addresses.append(address)

    if not addresses:
        raise ValueError("MCP server URL host could not be resolved")
    return addresses


def _is_public_mcp_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Whether an address is globally routable (IPv4-mapped IPv6 unwrapped first).

    ``is_global`` alone treats multicast (e.g. ``224.0.0.1``, ``239.255.255.250``)
    as public, so multicast is rejected explicitly.
    """
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def _guard_mcp_http_url(url: str) -> None:
    """Reject MCP http(s)/SSE URLs that could reach internal networks (SSRF guard).

    Any authenticated user can supply the ``url`` for the ``sse`` and
    ``streamable_http`` transports, so this validates the target before a request
    is ever made: only ``http``/``https`` schemes are allowed, and the host must
    resolve exclusively to globally routable addresses. This blocks loopback,
    private, link-local (including the ``169.254.169.254`` cloud-metadata
    endpoint), and other non-public destinations. Validating here (rather than in
    a single API route) covers every caller of ``_open_transport`` — the
    ``/api/mcp/fetch-tools`` preview, agent MCP connections, and ``mcpCall`` node
    execution.

    Self-hosted operators who intentionally point MCP at internal hosts can opt
    out with ``HEYM_MCP_ALLOW_PRIVATE_URLS=true``.

    This is the fast pre-connection check; ``_install_egress_pin`` additionally
    validates and pins the resolved IP at dial time so a DNS-rebinding answer
    cannot bounce the real connection onto an internal address.
    """
    if settings.mcp_allow_private_urls:
        return

    parsed = urlparse(url)
    if parsed.scheme.lower() not in _MCP_ALLOWED_URL_SCHEMES:
        raise ValueError("MCP server URL must use http or https")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("MCP server URL must include a host")

    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("MCP server URL includes an invalid port") from exc

    addresses = _resolve_mcp_host_addresses(hostname)
    if not all(_is_public_mcp_address(address) for address in addresses):
        raise ValueError("MCP server URL is not allowed (resolves to a non-public address)")


def _resolve_pinned_mcp_ip(host: str) -> str:
    """Resolve ``host`` and return a public IP to connect to, or raise.

    Every resolved address must be public; the returned literal is used as the
    actual TCP target so the connection cannot be rebound to an internal IP after
    validation (TLS SNI still uses the original hostname, so certs stay valid).
    """
    addresses = _resolve_mcp_host_addresses(host)
    if not all(_is_public_mcp_address(address) for address in addresses):
        raise ValueError("MCP server URL is not allowed (resolves to a non-public address)")
    return addresses[0].compressed


class _McpEgressPinBackend(httpcore.AsyncNetworkBackend):
    """Network backend that validates and pins the target IP at dial time.

    Wrapping the pool's backend means the anti-SSRF check runs against the IP the
    socket actually connects to (closing DNS rebinding), and also re-runs for any
    redirect hop or new origin the MCP client dials. Unix sockets are refused.
    """

    def __init__(self, inner: httpcore.AsyncNetworkBackend) -> None:
        self._inner = inner

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            pinned = _resolve_pinned_mcp_ip(host)
        except ValueError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        return await self._inner.connect_tcp(
            pinned,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("MCP server URL must use http or https")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _install_egress_pin(client: httpx.AsyncClient) -> None:
    """Wrap an httpx client's connection pool with the pinning egress backend.

    Best effort: if httpx/httpcore internals ever change shape, we skip silently
    and still rely on the pre-connection ``_guard_mcp_http_url`` check.
    """
    if settings.mcp_allow_private_urls:
        return
    transport = getattr(client, "_transport", None)
    pool = getattr(transport, "_pool", None)
    backend = getattr(pool, "_network_backend", None)
    if pool is None or backend is None:
        logger.debug("MCP egress pin not installed; httpx internals unavailable")
        return
    if isinstance(backend, _McpEgressPinBackend):
        return
    pool._network_backend = _McpEgressPinBackend(backend)


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
            # Build the client directly instead of create_mcp_http_client so the
            # SSRF guard is authoritative: follow_redirects=False stops a
            # guard-approved public URL from being redirected onto an internal
            # target, and trust_env=False keeps the connection direct so the
            # pinned egress backend (not an env proxy) governs the real dial.
            async with httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(timeout, read=sse_read_timeout),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                _install_egress_pin(client)
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


def _input_schema_from_tool(tool: Any) -> dict[str, Any]:
    """Return a JSON-schema-like inputSchema dict from an MCP tool object."""
    input_schema = getattr(tool, "inputSchema", None)
    if input_schema is None and isinstance(tool, dict):
        input_schema = tool.get("inputSchema")
    if hasattr(input_schema, "model_dump"):
        input_schema = input_schema.model_dump(by_alias=True, mode="json")
    return input_schema if isinstance(input_schema, dict) else {}


def _schema_required_keys(input_schema: dict[str, Any]) -> set[str]:
    required = input_schema.get("required")
    if not isinstance(required, list):
        return set()
    return {str(key) for key in required}


def _omit_empty_optional_arguments(
    arguments: dict[str, Any],
    input_schema: dict[str, Any],
) -> dict[str, Any]:
    """Drop blank optional args that UI forms may save for MCP schema fields."""
    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        return dict(arguments)

    required_keys = _schema_required_keys(input_schema)
    return {
        key: value
        for key, value in arguments.items()
        if not (value == "" and key in properties and key not in required_keys)
    }


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
        user_env = conn.get("env")
        if not command:
            raise ValueError("stdio connection requires 'command'")
        # Rewrite the command so the MCP server starts inside a hardened, throwaway
        # container instead of on the backend host (GHSA-378x-q589-34mv). This runs
        # before anything is spawned: once the child exists its side effects have
        # already fired, so no later check (including the MCP handshake, which needs
        # the child's pipes) can undo them.
        #
        # Only the caller's own env vars are forwarded. The MCP SDK merges those
        # over get_default_environment(), a deliberate allowlist (PATH, HOME, SHELL,
        # TERM, USER, LOGNAME), so PATH stays available for docker/npx/uvx without
        # handing the child SECRET_KEY, ENCRYPTION_KEY, DATABASE_URL or provider API
        # keys. Merging os.environ here would defeat that allowlist.
        sandboxed = build_sandboxed_command(
            command,
            args if isinstance(args, list) else [],
            user_env if isinstance(user_env, dict) else None,
        )
        if sandboxed.notes:
            logger.info("MCP stdio sandbox adjusted the command: %s", "; ".join(sandboxed.notes))
        server_params = StdioServerParameters(
            command=sandboxed.argv[0],
            args=sandboxed.argv[1:],
            env=sandboxed.env,
        )
        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                yield read_stream, write_stream
        finally:
            # The MCP SDK terminates the `docker run` client process, but a
            # detached container can outlive it (and with it the user's command).
            # Remove it explicitly so nothing survives the session.
            if sandboxed.container_name:
                await asyncio.to_thread(force_remove_container, sandboxed.container_name)

    elif transport == "sse":
        url = conn.get("url", "")
        headers = conn.get("headers") or {}
        if not url:
            raise ValueError("sse connection requires 'url'")
        _guard_mcp_http_url(url)
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
        _guard_mcp_http_url(url)
        # follow_redirects=False stops a redirect onto an internal target after
        # the check; trust_env=False keeps the dial direct so the pinned egress
        # backend (not an env proxy) governs the real connection.
        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=False, trust_env=False
        ) as http_client:
            _install_egress_pin(http_client)
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
            tools_result = await session.list_tools()
            selected_tool = next(
                (tool for tool in tools_result.tools if getattr(tool, "name", None) == tool_name),
                None,
            )
            available_tool_names = [tool.name for tool in tools_result.tools]
            if selected_tool is None:
                available_preview = ", ".join(available_tool_names[:20])
                if len(available_tool_names) > 20:
                    available_preview += f", ... ({len(available_tool_names)} total)"
                raise ValueError(
                    f"MCP tool '{tool_name}' is not available on this connection. "
                    f"Available tools: {available_preview or '(none)'}"
                )
            call_arguments = _omit_empty_optional_arguments(
                arguments or {},
                _input_schema_from_tool(selected_tool),
            )
            call_result = await session.call_tool(
                tool_name,
                arguments=call_arguments,
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
