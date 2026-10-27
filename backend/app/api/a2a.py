"""A2A 1.0 (JSON-RPC binding) for the Heym Agent, on the global and every named MCP server.

The agent is the one `heym_chat` runs; this router only speaks A2A. Credentials come from
headers alone, exactly as for MCP: `Authorization: Bearer <OAuth token>` or the server's
key in `X-MCP-Key`. The `?session=` handshake token MCP's legacy SSE uses is refused here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from app.api.mcp import _mcp_stream_headers, _run_mcp_protocol_limited, get_mcp_user
from app.api.mcp_servers import _get_named_server_context, _get_server_workflows
from app.db.models import MCPServer, User
from app.db.session import async_session_maker
from app.services.a2a import errors
from app.services.a2a.agent_card import (
    CardWorkflow,
    extended_card,
    global_endpoint_url,
    public_card,
    server_endpoint_url,
)
from app.services.a2a.executor import A2AExecutor
from app.services.a2a.models import (
    AgentCard,
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    SendMessageRequest,
    StreamResponse,
    SubscribeToTaskRequest,
)
from app.services.a2a.task_store import SqlTaskStore, TaskScope, TaskStore
from app.services.a2a.version import A2A_VERSION_HEADER, check_version
from app.services.audit_log import audit
from app.services.heym_agent import settings as agent_settings
from app.services.heym_agent.settings import AgentSettings
from app.services.hitl_service import build_default_public_base_url, build_public_base_url

router = APIRouter()
well_known_router = APIRouter()
logger = logging.getLogger(__name__)

STREAM_KEEPALIVE_SECONDS = 15.0
_KEEPALIVE = ": keepalive\n\n"
_STREAMING_METHODS = frozenset({"SendStreamingMessage", "SubscribeToTask"})
_PUSH_METHODS = frozenset(
    {
        "CreateTaskPushNotificationConfig",
        "GetTaskPushNotificationConfig",
        "ListTaskPushNotificationConfigs",
        "DeleteTaskPushNotificationConfig",
    }
)
_AUDITED_METHODS = frozenset({"SendMessage", "SendStreamingMessage", "CancelTask"})


# ---------------------------------------------------------------------------
# Authentication and dependencies
# ---------------------------------------------------------------------------


def _reject_query_credentials(request: Request) -> None:
    if "session" in request.query_params:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "A2A takes credentials from headers only: Authorization: Bearer <token> or "
                "X-MCP-Key."
            ),
            headers={"WWW-Authenticate": 'Bearer realm="heym-a2a"'},
        )


async def get_a2a_user(
    request: Request, x_mcp_key: str | None = Header(None, alias="X-MCP-Key")
) -> User:
    """The global server's user. A short session, so a stream never pins a connection."""
    _reject_query_credentials(request)
    async with async_session_maker() as db:
        return await get_mcp_user(request=request, x_mcp_key=x_mcp_key, db=db)


async def get_a2a_server(
    server_id: uuid.UUID,
    request: Request,
    x_mcp_key: str | None = Header(None, alias="X-MCP-Key"),
) -> tuple[User, MCPServer]:
    """A named server and its owner, from that server's credentials."""
    _reject_query_credentials(request)
    async with async_session_maker() as db:
        return await _get_named_server_context(
            server_id=server_id, request=request, x_mcp_key=x_mcp_key, db=db
        )


def get_task_store() -> TaskStore:
    return SqlTaskStore()


async def _load_global_settings(user_id: uuid.UUID) -> AgentSettings:
    async with async_session_maker() as db:
        return await agent_settings.get_global_agent_settings(db, user_id)


async def _load_server_settings(server_id: uuid.UUID, user_id: uuid.UUID) -> AgentSettings:
    async with async_session_maker() as db:
        return await agent_settings.get_server_agent_settings(db, server_id, user_id)


# ---------------------------------------------------------------------------
# Agent Cards
# ---------------------------------------------------------------------------


@well_known_router.get("/.well-known/agent-card.json")
async def global_agent_card() -> JSONResponse:
    """The domain card, served only while some user's global server answers A2A."""
    async with async_session_maker() as db:
        if not await agent_settings.any_global_a2a_enabled(db):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    base = build_default_public_base_url()
    card = public_card(endpoint_url=global_endpoint_url(base), public_base_url=base)
    return JSONResponse(card.wire())


@router.get("/servers/{server_id}/agent-card.json")
async def server_agent_card(server_id: uuid.UUID) -> JSONResponse:
    """A named server's card, served only while its A2A is on."""
    async with async_session_maker() as db:
        if not await agent_settings.server_a2a_enabled(db, server_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    base = build_default_public_base_url()
    card = public_card(endpoint_url=server_endpoint_url(base, server_id), public_base_url=base)
    return JSONResponse(card.wire())


# ---------------------------------------------------------------------------
# JSON-RPC endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=None)
async def global_a2a(
    request: Request,
    user: User = Depends(get_a2a_user),
    store: TaskStore = Depends(get_task_store),
) -> Response:
    """A2A JSON-RPC for the user's global MCP server."""

    async def card() -> AgentCard:
        base = build_default_public_base_url()
        return extended_card(
            endpoint_url=global_endpoint_url(base),
            public_base_url=base,
            server_name=None,
            workflows=[],
        )

    return await _handle(
        request,
        user=user,
        scope=TaskScope(user.id, None),
        store=store,
        load_settings=lambda: _load_global_settings(user.id),
        card=card,
    )


@router.post("/servers/{server_id}", response_model=None)
async def server_a2a(
    request: Request,
    server: tuple[User, MCPServer] = Depends(get_a2a_server),
    store: TaskStore = Depends(get_task_store),
) -> Response:
    """A2A JSON-RPC for one named MCP server."""
    user, mcp_server = server

    async def card() -> AgentCard:
        async with async_session_maker() as db:
            workflows = await _get_server_workflows(db, mcp_server.id)
        base = build_default_public_base_url()
        return extended_card(
            endpoint_url=server_endpoint_url(base, mcp_server.id),
            public_base_url=base,
            server_name=mcp_server.name,
            workflows=[CardWorkflow(w.id, w.name, w.description) for w in workflows],
        )

    return await _handle(
        request,
        user=user,
        scope=TaskScope(user.id, mcp_server.id),
        store=store,
        load_settings=lambda: _load_server_settings(mcp_server.id, user.id),
        card=card,
    )


async def _handle(
    request: Request,
    *,
    user: User,
    scope: TaskScope,
    store: TaskStore,
    load_settings: Callable[[], Awaitable[AgentSettings]],
    card: Callable[[], Awaitable[AgentCard]],
) -> Response:
    try:
        body = await request.json()
    except ValueError:
        parse_error = errors.A2AError(errors.PARSE_ERROR, "Parse error")
        return JSONResponse(errors.jsonrpc_error(None, parse_error))
    request_id = body.get("id") if isinstance(body, dict) else None
    if (
        not isinstance(body, dict)
        or body.get("jsonrpc") != "2.0"
        or not isinstance(body.get("method"), str)
        or "id" not in body
    ):
        invalid = errors.A2AError(errors.INVALID_REQUEST, "Invalid Request")
        return JSONResponse(errors.jsonrpc_error(request_id, invalid))
    method: str = body["method"]
    params = body.get("params") or {}
    try:
        if not isinstance(params, dict):
            raise errors.invalid_params("params must be an object.")
        check_version(
            request.headers.get(A2A_VERSION_HEADER) or request.query_params.get(A2A_VERSION_HEADER),
            method,
        )
        settings = await load_settings()
        if not settings.a2a_reachable:
            raise errors.unsupported(
                "A2A is turned off for this server. Turn it on in Heym's MCP / A2A tab."
            )
        executor = A2AExecutor(
            scope=scope,
            settings=settings,
            public_base_url=build_public_base_url(request),
            store=store,
        )
        if method in _STREAMING_METHODS:
            events = await _open_stream(executor, method, params)
            _audit(user, scope, method)
            return StreamingResponse(
                _sse(request_id, events),
                media_type="text/event-stream",
                headers=_mcp_stream_headers(),
            )
        result = await _run_mcp_protocol_limited(lambda: _call(executor, method, params, card))
        _audit(user, scope, method)
        return JSONResponse(errors.jsonrpc_result(request_id, result))
    except errors.A2AError as exc:
        return JSONResponse(errors.jsonrpc_error(request_id, exc))
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ())) or "params"
        invalid = errors.invalid_params(f"Invalid {where}: {first.get('msg', 'invalid')}")
        return JSONResponse(errors.jsonrpc_error(request_id, invalid))


async def _call(
    executor: A2AExecutor,
    method: str,
    params: dict[str, Any],
    card: Callable[[], Awaitable[AgentCard]],
) -> dict[str, Any]:
    if method == "SendMessage":
        task = await executor.send_message(SendMessageRequest.model_validate(params))
        return {"task": task.wire()}
    if method == "GetTask":
        return (await executor.get_task(GetTaskRequest.model_validate(params))).wire()
    if method == "ListTasks":
        return (await executor.list_tasks(ListTasksRequest.model_validate(params))).wire()
    if method == "CancelTask":
        return (await executor.cancel_task(CancelTaskRequest.model_validate(params))).wire()
    if method == "GetExtendedAgentCard":
        return (await card()).wire()
    if method in _PUSH_METHODS:
        raise errors.push_not_supported()
    raise errors.A2AError(errors.METHOD_NOT_FOUND, f"Method not found: {method}")


async def _open_stream(
    executor: A2AExecutor, method: str, params: dict[str, Any]
) -> AsyncIterator[StreamResponse]:
    """Validate and start before the response begins, so refusals are plain JSON-RPC errors."""
    if method == "SendStreamingMessage":
        return await executor.stream_message(SendMessageRequest.model_validate(params))
    return await executor.subscribe(SubscribeToTaskRequest.model_validate(params))


def _sse_data(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _sse(request_id: Any, events: AsyncIterator[StreamResponse]) -> AsyncIterator[str]:
    """JSON-RPC responses as SSE events, with keepalive comments while the agent works."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for event in events:
                await queue.put(_sse_data(errors.jsonrpc_result(request_id, event.wire())))
        except errors.A2AError as exc:
            await queue.put(_sse_data(errors.jsonrpc_error(request_id, exc)))
        except Exception:
            logger.exception("A2A stream failed")
            failure = errors.A2AError(errors.INTERNAL_ERROR, "The stream failed.")
            await queue.put(_sse_data(errors.jsonrpc_error(request_id, failure)))
        finally:
            await queue.put(None)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=STREAM_KEEPALIVE_SECONDS)
            except TimeoutError:
                yield _KEEPALIVE
                continue
            if item is None:
                break
            yield item
    finally:
        if not pump_task.done():
            pump_task.cancel()


def _audit(user: User, scope: TaskScope, method: str) -> None:
    if method not in _AUDITED_METHODS:
        return
    audit(
        action=f"a2a.{method}",
        actor=user,
        target_type="mcp_server" if scope.server_id else "mcp_global_server",
        target_id=scope.server_id,
    )
