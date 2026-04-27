import asyncio
import json
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.deps import get_current_user
from app.api.workflows import (
    _persist_global_variables_from_execution,
    collect_referenced_workflows,
    extract_input_fields_from_workflow,
)
from app.db.models import (
    Credential,
    CredentialType,
    ExecutionHistory,
    OAuthAccessToken,
    User,
    Workflow,
    WorkflowShare,
)
from app.db.session import get_db
from app.models.schemas import (
    MCPConfigResponse,
    MCPFetchToolItem,
    MCPFetchToolsResponse,
    MCPInitializeResult,
    MCPJSONRPCRequest,
    MCPRegenerateKeyResponse,
    MCPTextContent,
    MCPToggleRequest,
    MCPTool,
    MCPToolInputProperty,
    MCPToolInputSchema,
    MCPToolResult,
    MCPToolsListResponse,
    MCPWorkflowItem,
)
from app.services.encryption import decrypt_config
from app.services.execution_cancellation import (
    clear_execution as clear_active_execution,
)
from app.services.execution_cancellation import (
    register_execution,
)
from app.services.global_variables_service import get_global_variables_context
from app.services.mcp_session import mcp_session_store
from app.services.workflow_executor import execute_workflow

router = APIRouter()


async def get_mcp_user(
    request: Request,
    x_mcp_key: str | None = Header(None, alias="X-MCP-Key"),
    db: AsyncSession = Depends(get_db),
) -> User:
    # 0. Check for short-lived SSE session token (?session=)
    session_param = request.query_params.get("session")
    if session_param:
        user_id_str = mcp_session_store.resolve(session_param)
        if user_id_str is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session token",
                headers={"WWW-Authenticate": 'Bearer realm="heym-mcp"'},
            )
        import uuid as _uuid

        user_result = await db.execute(select(User).where(User.id == _uuid.UUID(user_id_str)))
        user = user_result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return user

    # 1. Check for Bearer token (OAuth) — from header or ?token= query param
    auth_header = request.headers.get("Authorization", "")
    token_param = request.query_params.get("token")

    bearer_token = None
    if auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:]
    elif token_param:
        bearer_token = token_param

    if bearer_token:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(OAuthAccessToken).where(
                OAuthAccessToken.access_token == bearer_token,
                OAuthAccessToken.revoked.is_(False),
                OAuthAccessToken.expires_at > now,
            )
        )
        token_record = result.scalar_one_or_none()

        if token_record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired Bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_result = await db.execute(select(User).where(User.id == token_record.user_id))
        user = user_result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        return user

    # 2. Fall back to X-MCP-Key (existing behavior)
    api_key = x_mcp_key or request.query_params.get("key")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication. Provide Authorization: Bearer <token> or X-MCP-Key header",
            headers={"WWW-Authenticate": 'Bearer realm="heym-mcp"'},
        )

    result = await db.execute(select(User).where(User.mcp_api_key == api_key))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MCP API key",
        )

    return user


async def get_user_mcp_workflows(db: AsyncSession, user_id: uuid.UUID) -> list[Workflow]:
    owned_result = await db.execute(
        select(Workflow)
        .where(
            Workflow.mcp_enabled.is_(True),
            Workflow.owner_id == user_id,
        )
        .order_by(Workflow.name.asc())
    )
    owned_workflows = list(owned_result.scalars().all())

    shared_result = await db.execute(
        select(Workflow)
        .join(WorkflowShare, WorkflowShare.workflow_id == Workflow.id)
        .where(
            WorkflowShare.user_id == user_id,
            WorkflowShare.mcp_enabled.is_(True),
        )
        .order_by(Workflow.name.asc())
    )
    shared_workflows = list(shared_result.scalars().all())

    all_workflows = owned_workflows + shared_workflows
    all_workflows.sort(key=lambda w: w.name.lower())
    return all_workflows


async def get_all_user_workflows(db: AsyncSession, user_id: uuid.UUID) -> list[Workflow]:
    result = await db.execute(
        select(Workflow)
        .where(
            or_(
                Workflow.owner_id == user_id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == user_id)
                ),
            )
        )
        .order_by(Workflow.name.asc())
    )
    return list(result.scalars().all())


def workflow_to_mcp_tool(workflow: Workflow) -> MCPTool:
    input_fields = extract_input_fields_from_workflow(workflow)
    properties: dict[str, MCPToolInputProperty] = {}
    required: list[str] = []

    for field in input_fields:
        properties[field.key] = MCPToolInputProperty(
            type="string",
            description=f"Input field: {field.key}",
        )
        required.append(field.key)

    # Use workflow name directly, sanitized for MCP tool naming
    tool_name = workflow.name.lower().replace(" ", "_").replace("-", "_")
    tool_name = "".join(c if c.isalnum() or c == "_" else "" for c in tool_name)

    return MCPTool(
        name=tool_name,
        description=workflow.description or f"Execute workflow: {workflow.name}",
        inputSchema=MCPToolInputSchema(
            type="object",
            properties=properties,
            required=required,
        ),
    )


async def get_credentials_context_for_user(db: AsyncSession, user_id: uuid.UUID) -> dict[str, str]:
    from app.db.models import CredentialShare

    owned_result = await db.execute(select(Credential).where(Credential.owner_id == user_id))
    owned_credentials = owned_result.scalars().all()

    shared_result = await db.execute(
        select(Credential)
        .join(CredentialShare, CredentialShare.credential_id == Credential.id)
        .where(CredentialShare.user_id == user_id)
    )
    shared_credentials = shared_result.scalars().all()

    all_credentials = list(owned_credentials) + list(shared_credentials)

    context: dict[str, str] = {}
    for cred in all_credentials:
        try:
            config = decrypt_config(cred.encrypted_config)
            if cred.type == CredentialType.bearer:
                token = config.get("bearer_token", "")
                context[cred.name] = f"Bearer {token}" if token else ""
            elif cred.type == CredentialType.header:
                header_key = config.get("header_key", "")
                header_value = config.get("header_value", "")
                context[cred.name] = f"{header_key}: {header_value}" if header_key else header_value
            elif cred.type == CredentialType.slack:
                context[cred.name] = config.get("webhook_url", "")
            else:
                context[cred.name] = config.get("api_key", "")
        except Exception:
            pass
    return context


@router.get("/config", response_model=MCPConfigResponse)
async def get_mcp_config(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MCPConfigResponse:
    workflows = await get_all_user_workflows(db, current_user.id)

    shares_result = await db.execute(
        select(WorkflowShare).where(WorkflowShare.user_id == current_user.id)
    )
    shares_map = {s.workflow_id: s for s in shares_result.scalars().all()}

    workflow_items = []
    for w in workflows:
        input_fields = extract_input_fields_from_workflow(w)
        if w.owner_id == current_user.id:
            mcp_enabled = w.mcp_enabled
        else:
            share = shares_map.get(w.id)
            mcp_enabled = share.mcp_enabled if share else False

        workflow_items.append(
            MCPWorkflowItem(
                id=w.id,
                name=w.name,
                description=w.description,
                mcp_enabled=mcp_enabled,
                input_fields=input_fields,
            )
        )

    base_url = str(request.base_url).rstrip("/")
    mcp_endpoint_url = f"{base_url}/api/mcp/sse"

    return MCPConfigResponse(
        mcp_api_key=current_user.mcp_api_key,
        mcp_endpoint_url=mcp_endpoint_url,
        workflows=workflow_items,
    )


@router.post("/regenerate-key", response_model=MCPRegenerateKeyResponse)
async def regenerate_mcp_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MCPRegenerateKeyResponse:
    new_key = secrets.token_hex(32)
    current_user.mcp_api_key = new_key
    await db.flush()
    await db.refresh(current_user)

    return MCPRegenerateKeyResponse(mcp_api_key=new_key)


@router.patch("/workflows/{workflow_id}", response_model=MCPWorkflowItem)
async def toggle_workflow_mcp(
    workflow_id: uuid.UUID,
    toggle_data: MCPToggleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MCPWorkflowItem:
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            or_(
                Workflow.owner_id == current_user.id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(
                        WorkflowShare.user_id == current_user.id
                    )
                ),
            ),
        )
    )
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    if workflow.owner_id == current_user.id:
        workflow.mcp_enabled = toggle_data.mcp_enabled
        await db.flush()
        await db.refresh(workflow)
        mcp_enabled = workflow.mcp_enabled
    else:
        share_result = await db.execute(
            select(WorkflowShare).where(
                WorkflowShare.workflow_id == workflow_id,
                WorkflowShare.user_id == current_user.id,
            )
        )
        share = share_result.scalar_one_or_none()
        if share:
            share.mcp_enabled = toggle_data.mcp_enabled
            await db.flush()
            await db.refresh(share)
            mcp_enabled = share.mcp_enabled
        else:
            mcp_enabled = False

    input_fields = extract_input_fields_from_workflow(workflow)
    return MCPWorkflowItem(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        mcp_enabled=mcp_enabled,
        input_fields=input_fields,
    )


@router.get("/tools", response_model=MCPToolsListResponse)
async def list_mcp_tools(
    mcp_user: User = Depends(get_mcp_user),
    db: AsyncSession = Depends(get_db),
) -> MCPToolsListResponse:
    workflows = await get_user_mcp_workflows(db, mcp_user.id)
    tools = [workflow_to_mcp_tool(w) for w in workflows]
    return MCPToolsListResponse(tools=tools)


@router.post("/fetch-tools", response_model=MCPFetchToolsResponse)
async def fetch_mcp_tools(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> MCPFetchToolsResponse:
    """
    Connect to an MCP server (stdio or SSE) and return its tool names and descriptions.
    Used by the editor to preview available tools before saving.
    """
    from app.services.mcp_tool_executor import list_mcp_tools

    body = await request.json()
    connection = body.get("connection") or {}
    timeout_seconds = float(connection.get("timeoutSeconds") or 30)

    conn = dict(connection)
    conn.setdefault("id", conn.get("label", "default"))

    try:
        raw_tools = await asyncio.to_thread(list_mcp_tools, conn, timeout_seconds)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    tools = [
        MCPFetchToolItem(name=t.get("name", ""), description=t.get("description") or "")
        for t in raw_tools
    ]
    return MCPFetchToolsResponse(tools=tools)


@router.post("/tools/call", response_model=MCPToolResult)
async def call_mcp_tool(
    request: Request,
    mcp_user: User = Depends(get_mcp_user),
    db: AsyncSession = Depends(get_db),
) -> MCPToolResult:
    body = await request.json()
    tool_name = body.get("name", "")
    arguments = body.get("arguments", {})

    workflows = await get_user_mcp_workflows(db, mcp_user.id)
    target_workflow = None

    for w in workflows:
        # Match by sanitized workflow name
        w_tool_name = w.name.lower().replace(" ", "_").replace("-", "_")
        w_tool_name = "".join(c if c.isalnum() or c == "_" else "" for c in w_tool_name)
        if w_tool_name == tool_name:
            target_workflow = w
            break

    if target_workflow is None:
        return MCPToolResult(
            content=[MCPTextContent(text=f"Tool not found: {tool_name}")],
            isError=True,
        )

    if not target_workflow.nodes:
        return MCPToolResult(
            content=[MCPTextContent(text="Workflow has no nodes")],
            isError=True,
        )

    enriched_inputs = {
        "headers": {},
        "query": {},
        "body": arguments,
    }

    workflow_cache = await collect_referenced_workflows(db, target_workflow.nodes)
    credentials_context = await get_credentials_context_for_user(db, mcp_user.id)
    global_variables_context = await get_global_variables_context(db, mcp_user.id)

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
            cancel_event=cancel_event,
        )

        # Save execution history with MCP trigger source
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
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=uuid.UUID(sub_exec.workflow_id),
                owner_id=None,
                workflow_name_snapshot=sub_exec.workflow_name or "Sub-workflow",
                status=sub_exec.status,
                execution_time_ms=sub_exec.execution_time_ms,
            )

        await _persist_global_variables_from_execution(
            db,
            mcp_user.id,
            target_workflow.nodes,
            workflow_cache,
            execution_result.node_results,
            execution_result.sub_workflow_executions,
        )

        await db.flush()

        output_text = json.dumps(execution_result.outputs, indent=2, ensure_ascii=False)

        return MCPToolResult(
            content=[MCPTextContent(text=output_text)],
            isError=execution_result.status == "error",
        )
    except Exception as e:
        return MCPToolResult(
            content=[MCPTextContent(text=f"Execution error: {str(e)}")],
            isError=True,
        )
    finally:
        clear_active_execution(execution_id)


@router.post("/message")
async def handle_mcp_message(
    request: Request,
    mcp_user: User = Depends(get_mcp_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    body = await request.json()
    msg = MCPJSONRPCRequest(**body)

    if msg.id is None:
        if msg.method == "notifications/initialized":
            return {"jsonrpc": "2.0"}
        return {"jsonrpc": "2.0"}

    if msg.method == "initialize":
        result = MCPInitializeResult()
        return {
            "jsonrpc": "2.0",
            "id": msg.id,
            "result": result.model_dump(),
        }

    if msg.method == "tools/list":
        workflows = await get_user_mcp_workflows(db, mcp_user.id)
        tools = [workflow_to_mcp_tool(w) for w in workflows]
        return {
            "jsonrpc": "2.0",
            "id": msg.id,
            "result": {"tools": [t.model_dump() for t in tools]},
        }

    if msg.method == "tools/call":
        tool_name = msg.params.get("name", "")
        arguments = msg.params.get("arguments", {})

        workflows = await get_user_mcp_workflows(db, mcp_user.id)
        target_workflow = None

        for w in workflows:
            # Match by sanitized workflow name
            w_tool_name = w.name.lower().replace(" ", "_").replace("-", "_")
            w_tool_name = "".join(c if c.isalnum() or c == "_" else "" for c in w_tool_name)
            if w_tool_name == tool_name:
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

        enriched_inputs = {
            "headers": {},
            "query": {},
            "body": arguments,
        }

        workflow_cache = await collect_referenced_workflows(db, target_workflow.nodes)
        credentials_context = await get_credentials_context_for_user(db, mcp_user.id)

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
                cancel_event=cancel_event,
            )

            # Save execution history with MCP trigger source
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
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    owner_id=None,
                    workflow_name_snapshot=sub_exec.workflow_name or "Sub-workflow",
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
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
            return {
                "jsonrpc": "2.0",
                "id": msg.id,
                "error": {"code": -32603, "message": f"Execution error: {str(e)}"},
            }
        finally:
            clear_active_execution(execution_id)

    return {
        "jsonrpc": "2.0",
        "id": msg.id,
        "error": {"code": -32601, "message": f"Method not found: {msg.method}"},
    }


@router.post("/sse")
async def mcp_sse_post_endpoint(
    request: Request,
    mcp_user: User = Depends(get_mcp_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    body = await request.json()
    msg = MCPJSONRPCRequest(**body)

    if msg.id is None:
        return {"jsonrpc": "2.0"}

    if msg.method == "initialize":
        result = MCPInitializeResult()
        return {
            "jsonrpc": "2.0",
            "id": msg.id,
            "result": result.model_dump(),
        }

    if msg.method == "tools/list":
        workflows = await get_user_mcp_workflows(db, mcp_user.id)
        tools = [workflow_to_mcp_tool(w) for w in workflows]
        return {
            "jsonrpc": "2.0",
            "id": msg.id,
            "result": {"tools": [t.model_dump() for t in tools]},
        }

    if msg.method == "tools/call":
        tool_name = msg.params.get("name", "")
        arguments = msg.params.get("arguments", {})

        workflows = await get_user_mcp_workflows(db, mcp_user.id)
        target_workflow = None

        for w in workflows:
            # Match by sanitized workflow name
            w_tool_name = w.name.lower().replace(" ", "_").replace("-", "_")
            w_tool_name = "".join(c if c.isalnum() or c == "_" else "" for c in w_tool_name)
            if w_tool_name == tool_name:
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

        enriched_inputs = {
            "headers": {},
            "query": {},
            "body": arguments,
        }

        workflow_cache = await collect_referenced_workflows(db, target_workflow.nodes)
        credentials_context = await get_credentials_context_for_user(db, mcp_user.id)

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
                cancel_event=cancel_event,
            )

            # Save execution history with MCP trigger source
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
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    owner_id=None,
                    workflow_name_snapshot=sub_exec.workflow_name or "Sub-workflow",
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
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
            return {
                "jsonrpc": "2.0",
                "id": msg.id,
                "error": {"code": -32603, "message": f"Execution error: {str(e)}"},
            }
        finally:
            clear_active_execution(execution_id)

    return {
        "jsonrpc": "2.0",
        "id": msg.id,
        "error": {"code": -32601, "message": f"Method not found: {msg.method}"},
    }


@router.get("/sse")
async def mcp_sse_endpoint(
    request: Request,
    mcp_user: User = Depends(get_mcp_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    base_url = str(request.base_url).rstrip("/")

    # Issue a short-lived session token so the long-lived credential
    # (MCP API key or OAuth bearer) never appears in the message endpoint URL
    # or server access logs.
    session_token = mcp_session_store.create(str(mcp_user.id))
    message_endpoint = f"{base_url}/api/mcp/message?session={session_token}"

    async def event_generator():
        yield f"event: endpoint\ndata: {message_endpoint}\n\n"

        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(30)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
