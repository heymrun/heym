import asyncio
import json
import secrets
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.deps import get_current_user
from app.api.mcp import (
    _accept_sse_response_if_active,
    _add_mcp_workflow_trace,
    get_credentials_context_for_user,
    workflow_to_mcp_tool,
)
from app.api.workflows import _persist_global_variables_from_execution, collect_referenced_workflows
from app.db.models import (
    ExecutionHistory,
    MCPServer,
    MCPServerWorkflow,
    OAuthAccessToken,
    User,
    Workflow,
)
from app.db.session import get_db
from app.models.schemas import (
    MCPInitializeResult,
    MCPJSONRPCRequest,
    MCPServerCreate,
    MCPServerListResponse,
    MCPServerResponse,
    MCPServerWorkflowToggleRequest,
    MCPToolsListResponse,
)
from app.services.execution_cancellation import clear_execution as clear_active_execution
from app.services.execution_cancellation import register_execution
from app.services.global_variables_service import get_global_variables_context
from app.services.mcp_session import mcp_session_store, mcp_sse_channels
from app.services.workflow_executor import execute_workflow

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _fetch_server_for_user(
    db: AsyncSession, server_id: uuid.UUID, user_id: uuid.UUID
) -> MCPServer:
    result = await db.execute(
        select(MCPServer).where(MCPServer.id == server_id, MCPServer.user_id == user_id)
    )
    server = result.scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


async def _get_server_workflow_ids(db: AsyncSession, server_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(
        select(MCPServerWorkflow.workflow_id).where(MCPServerWorkflow.mcp_server_id == server_id)
    )
    return [row[0] for row in result.all()]


async def _get_server_workflows(db: AsyncSession, server_id: uuid.UUID) -> list[Workflow]:
    result = await db.execute(
        select(Workflow)
        .join(MCPServerWorkflow, MCPServerWorkflow.workflow_id == Workflow.id)
        .where(MCPServerWorkflow.mcp_server_id == server_id)
    )
    return list(result.scalars().all())


def _sanitize_tool_name(name: str) -> str:
    n = name.lower().replace(" ", "_").replace("-", "_")
    return "".join(c if c.isalnum() or c == "_" else "" for c in n)


# ---------------------------------------------------------------------------
# Auth dependency for MCP protocol endpoints (SSE / message / tools)
# ---------------------------------------------------------------------------


async def _get_named_server_context(
    server_id: uuid.UUID,
    request: Request,
    x_mcp_key: str | None = Header(None, alias="X-MCP-Key"),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, MCPServer]:
    # 0. Short-lived session token
    session_param = request.query_params.get("session")
    if session_param:
        resolve_result = mcp_session_store.resolve(session_param)
        if resolve_result is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session token",
            )
        user_id_str, sess_server_id = resolve_result
        if sess_server_id != str(server_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session token not valid for this server",
            )
        user_res = await db.execute(select(User).where(User.id == uuid.UUID(user_id_str)))
        user = user_res.scalar_one_or_none()
        server_res = await db.execute(select(MCPServer).where(MCPServer.id == server_id))
        server = server_res.scalar_one_or_none()
        if user is None or server is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User or server not found"
            )
        return user, server

    # 1. OAuth Bearer token
    auth_header = request.headers.get("Authorization", "")
    token_param = request.query_params.get("token")
    bearer_token: str | None = None
    if auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:]
    elif token_param:
        bearer_token = token_param

    if bearer_token:
        now = datetime.now(timezone.utc)
        token_res = await db.execute(
            select(OAuthAccessToken).where(
                OAuthAccessToken.access_token == bearer_token,
                OAuthAccessToken.revoked.is_(False),
                OAuthAccessToken.expires_at > now,
            )
        )
        token_record = token_res.scalar_one_or_none()
        if token_record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired Bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_res = await db.execute(select(User).where(User.id == token_record.user_id))
        user = user_res.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        server_res = await db.execute(
            select(MCPServer).where(MCPServer.id == server_id, MCPServer.user_id == user.id)
        )
        server = server_res.scalar_one_or_none()
        if server is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        return user, server

    # 2. Per-server API key
    api_key = x_mcp_key or request.query_params.get("key")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication. Provide Authorization: Bearer <token> or X-MCP-Key header",
            headers={"WWW-Authenticate": 'Bearer realm="heym-mcp"'},
        )
    server_res = await db.execute(
        select(MCPServer).where(MCPServer.api_key == api_key, MCPServer.id == server_id)
    )
    server = server_res.scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    user_res = await db.execute(select(User).where(User.id == server.user_id))
    user = user_res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user, server


# ---------------------------------------------------------------------------
# CRUD endpoints (JWT auth via get_current_user)
# ---------------------------------------------------------------------------


@router.get("", response_model=MCPServerListResponse)
async def list_mcp_servers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MCPServerListResponse:
    result = await db.execute(
        select(MCPServer).where(MCPServer.user_id == current_user.id).order_by(MCPServer.created_at)
    )
    servers = list(result.scalars().all())
    items = []
    for s in servers:
        workflow_ids = await _get_server_workflow_ids(db, s.id)
        items.append(
            MCPServerResponse(
                id=s.id,
                name=s.name,
                api_key=s.api_key,
                created_at=s.created_at,
                workflow_ids=workflow_ids,
            )
        )
    return MCPServerListResponse(servers=items)


@router.post("", response_model=MCPServerResponse, status_code=201)
async def create_mcp_server(
    body: MCPServerCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MCPServerResponse:
    server = MCPServer(
        user_id=current_user.id,
        name=body.name,
        api_key=secrets.token_urlsafe(48),
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)
    return MCPServerResponse(
        id=server.id,
        name=server.name,
        api_key=server.api_key,
        created_at=server.created_at,
        workflow_ids=[],
    )


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    server = await _fetch_server_for_user(db, server_id, current_user.id)
    await db.delete(server)
    await db.commit()


@router.post("/{server_id}/regenerate-key", response_model=MCPServerResponse)
async def regenerate_server_key(
    server_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MCPServerResponse:
    server = await _fetch_server_for_user(db, server_id, current_user.id)
    server.api_key = secrets.token_urlsafe(48)
    await db.commit()
    await db.refresh(server)
    workflow_ids = await _get_server_workflow_ids(db, server.id)
    return MCPServerResponse(
        id=server.id,
        name=server.name,
        api_key=server.api_key,
        created_at=server.created_at,
        workflow_ids=workflow_ids,
    )


@router.patch("/{server_id}/workflows/{workflow_id}")
async def toggle_server_workflow(
    server_id: uuid.UUID,
    workflow_id: uuid.UUID,
    body: MCPServerWorkflowToggleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _fetch_server_for_user(db, server_id, current_user.id)

    wf_res = await db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.owner_id == current_user.id)
    )
    if wf_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if body.enabled:
        existing = await db.execute(
            select(MCPServerWorkflow).where(
                MCPServerWorkflow.mcp_server_id == server_id,
                MCPServerWorkflow.workflow_id == workflow_id,
            )
        )
        if existing.scalar_one_or_none() is None:
            db.add(MCPServerWorkflow(mcp_server_id=server_id, workflow_id=workflow_id))
            await db.commit()
    else:
        await db.execute(
            delete(MCPServerWorkflow).where(
                MCPServerWorkflow.mcp_server_id == server_id,
                MCPServerWorkflow.workflow_id == workflow_id,
            )
        )
        await db.commit()

    return {"enabled": body.enabled}


# ---------------------------------------------------------------------------
# MCP Protocol endpoints (SSE, message, tools) — named server
# ---------------------------------------------------------------------------


@router.get("/{server_id}/tools", response_model=MCPToolsListResponse)
async def list_named_server_tools(
    server: tuple[User, MCPServer] = Depends(_get_named_server_context),
    db: AsyncSession = Depends(get_db),
) -> MCPToolsListResponse:
    _, mcp_server = server
    workflows = await _get_server_workflows(db, mcp_server.id)
    tools = [workflow_to_mcp_tool(w) for w in workflows]
    return MCPToolsListResponse(tools=tools)


@router.get("/{server_id}/sse")
async def named_server_sse(
    server_id: uuid.UUID,
    request: Request,
    server: tuple[User, MCPServer] = Depends(_get_named_server_context),
) -> StreamingResponse:
    user, mcp_server = server
    session_token = mcp_session_store.create(str(user.id), server_id=str(mcp_server.id))
    message_endpoint = f"/api/mcp/servers/{server_id}/message?session={session_token}"

    async def event_generator() -> AsyncGenerator[str, None]:
        response_queue = mcp_sse_channels.register(session_token)
        try:
            yield f"event: endpoint\ndata: {message_endpoint}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(response_queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: message\ndata: {payload}\n\n"
        finally:
            mcp_sse_channels.unregister(session_token)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{server_id}/sse")
async def named_server_sse_post(
    server_id: uuid.UUID,
    request: Request,
    server: tuple[User, MCPServer] = Depends(_get_named_server_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Streamable HTTP transport (MCP 2025-03-26): POST directly to SSE endpoint."""
    return await _dispatch_named_server_jsonrpc(
        server_id=server_id, request=request, server=server, db=db
    )


async def _dispatch_named_server_jsonrpc(
    server_id: uuid.UUID,
    request: Request,
    server: tuple[User, MCPServer],
    db: AsyncSession,
) -> dict:
    body = await request.json()
    msg = MCPJSONRPCRequest(**body)
    user, mcp_server = server

    if msg.id is None:
        return {"jsonrpc": "2.0"}

    if msg.method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg.id,
            "result": MCPInitializeResult().model_dump(),
        }

    if msg.method == "tools/list":
        workflows = await _get_server_workflows(db, mcp_server.id)
        tools = [workflow_to_mcp_tool(w) for w in workflows]
        return {
            "jsonrpc": "2.0",
            "id": msg.id,
            "result": {"tools": [t.model_dump() for t in tools]},
        }

    if msg.method == "tools/call":
        tool_name = msg.params.get("name", "")
        arguments = msg.params.get("arguments", {})

        workflows = await _get_server_workflows(db, mcp_server.id)
        target_workflow = None
        for w in workflows:
            if _sanitize_tool_name(w.name) == tool_name:
                target_workflow = w
                break

        if target_workflow is None:
            return {
                "jsonrpc": "2.0",
                "id": msg.id,
                "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
            }

        if not target_workflow.nodes:
            return {
                "jsonrpc": "2.0",
                "id": msg.id,
                "error": {"code": -32602, "message": "Workflow has no nodes"},
            }

        enriched_inputs = {"headers": {}, "query": {}, "body": arguments}
        workflow_cache = await collect_referenced_workflows(db, target_workflow.nodes)
        credentials_context = await get_credentials_context_for_user(db, user.id)
        global_variables_context = await get_global_variables_context(db, user.id)

        execution_id = uuid.uuid4()
        cancel_event = register_execution(workflow_id=target_workflow.id, execution_id=execution_id)
        try:
            execution_result = await asyncio.to_thread(
                execute_workflow,
                workflow_id=target_workflow.id,
                nodes=target_workflow.nodes,
                edges=target_workflow.edges,
                inputs=enriched_inputs,
                workflow_cache=workflow_cache,
                test_run=False,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=user.id,
                cancel_event=cancel_event,
            )

            history_entry = ExecutionHistory(
                workflow_id=target_workflow.id,
                inputs=enriched_inputs,
                outputs=execution_result.outputs,
                node_results=execution_result.node_results,
                status=execution_result.status,
                execution_time_ms=execution_result.execution_time_ms,
                trigger_source="MCP",
            )
            db.add(history_entry)

            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=target_workflow.id,
                owner_id=target_workflow.owner_id,
                workflow_name_snapshot=target_workflow.name,
                status=execution_result.status,
                execution_time_ms=execution_result.execution_time_ms,
            )

            for sub_exec in execution_result.sub_workflow_executions:
                sub_history = ExecutionHistory(
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    inputs=sub_exec.inputs,
                    outputs=sub_exec.outputs,
                    node_results=sub_exec.node_results,
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                    trigger_source=sub_exec.trigger_source,
                )
                db.add(sub_history)

            await _persist_global_variables_from_execution(
                db,
                user.id,
                target_workflow.nodes,
                workflow_cache,
                execution_result.node_results,
                execution_result.sub_workflow_executions,
            )

            _add_mcp_workflow_trace(
                db,
                user_id=user.id,
                workflow=target_workflow,
                tool_name=tool_name,
                arguments=arguments,
                execution_result=execution_result,
            )
            await db.flush()

            output_text = json.dumps(execution_result.outputs, indent=2, ensure_ascii=False)
            return {
                "jsonrpc": "2.0",
                "id": msg.id,
                "result": {
                    "content": [{"type": "text", "text": output_text}],
                    "isError": execution_result.status == "error",
                },
            }
        except Exception as e:
            _add_mcp_workflow_trace(
                db,
                user_id=user.id,
                workflow=target_workflow,
                tool_name=tool_name,
                arguments=arguments,
                execution_result=None,
                error=str(e),
            )
            await db.flush()
            return {
                "jsonrpc": "2.0",
                "id": msg.id,
                "result": {
                    "content": [{"type": "text", "text": f"Execution error: {e}"}],
                    "isError": True,
                },
            }
        finally:
            clear_active_execution(execution_id)

    return {
        "jsonrpc": "2.0",
        "id": msg.id,
        "error": {"code": -32601, "message": f"Method not found: {msg.method}"},
    }


@router.post("/{server_id}/message", response_model=None)
async def handle_named_server_message(
    server_id: uuid.UUID,
    request: Request,
    server: tuple[User, MCPServer] = Depends(_get_named_server_context),
    db: AsyncSession = Depends(get_db),
) -> dict | Response:
    response = await _dispatch_named_server_jsonrpc(
        server_id=server_id, request=request, server=server, db=db
    )
    sse_response = await _accept_sse_response_if_active(request, response)
    return sse_response or response
