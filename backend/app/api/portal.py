import asyncio
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.deps import get_client_ip, get_current_user
from app.api.workflows import (
    _persist_global_variables_from_execution,
    _sanitize_headers,
    collect_referenced_workflows,
    extract_input_fields_from_workflow,
    get_credentials_context,
    get_workflow_for_user,
)
from app.db.models import ExecutionHistory, PortalSession, User, Workflow, WorkflowPortalUser
from app.db.session import get_db
from app.models.schemas import (
    PortalExecuteRequest,
    PortalInfoResponse,
    PortalLoginRequest,
    PortalLoginResponse,
    PortalSettingsResponse,
    PortalSettingsUpdate,
    PortalUserCreate,
    PortalUserResponse,
    WorkflowExecuteResponse,
)
from app.services.auth import hash_password, verify_password
from app.services.execution_cancellation import (
    cancel_execution as cancel_active_execution,
)
from app.services.execution_cancellation import (
    clear_execution as clear_active_execution,
)
from app.services.execution_cancellation import (
    register_execution,
)
from app.services.global_variables_service import get_global_variables_context
from app.services.hitl_service import build_public_base_url, persist_pending_hitl_execution
from app.services.portal_progress import PortalProgressTracker
from app.services.portal_rate_limiter import portal_login_limiter
from app.services.workflow_executor import (
    ExecutionResult,
    WorkflowCancelledError,
    execute_workflow,
    execute_workflow_streaming,
)

router = APIRouter()

_session_ttl_hours = 168


def _generate_session_token() -> str:
    return secrets.token_urlsafe(32)


async def _create_session(
    db: AsyncSession, workflow_id: uuid.UUID, username: str
) -> tuple[str, datetime]:
    token = _generate_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=_session_ttl_hours)

    session = PortalSession(
        token=token,
        workflow_id=workflow_id,
        username=username,
        expires_at=expires_at,
    )
    db.add(session)
    await db.flush()

    return token, expires_at


async def _validate_session(db: AsyncSession, token: str, workflow_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(PortalSession).where(
            PortalSession.token == token, PortalSession.workflow_id == workflow_id
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        return False

    if session.expires_at < datetime.now(timezone.utc):
        await db.delete(session)
        await db.flush()
        return False

    return True


@router.get("/{slug}/info", response_model=PortalInfoResponse)
async def get_portal_info(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> PortalInfoResponse:
    result = await db.execute(
        select(Workflow).where(Workflow.portal_slug == slug, Workflow.portal_enabled.is_(True))
    )
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portal not found",
        )

    users_result = await db.execute(
        select(WorkflowPortalUser).where(WorkflowPortalUser.workflow_id == workflow.id).limit(1)
    )
    has_users = users_result.scalar_one_or_none() is not None

    return PortalInfoResponse(
        workflow_name=workflow.name,
        workflow_description=workflow.description,
        requires_auth=has_users,
        stream_enabled=workflow.portal_stream_enabled,
        file_upload_enabled=workflow.portal_file_upload_enabled,
        file_config=workflow.portal_file_config or {},
        input_fields=extract_input_fields_from_workflow(workflow),
    )


@router.post("/{slug}/login", response_model=PortalLoginResponse)
async def portal_login(
    slug: str,
    login_data: PortalLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PortalLoginResponse:
    result = await db.execute(
        select(Workflow).where(Workflow.portal_slug == slug, Workflow.portal_enabled.is_(True))
    )
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portal not found",
        )

    client_ip = get_client_ip(request)
    workflow_id_str = str(workflow.id)

    is_banned, ban_remaining = portal_login_limiter.is_banned(workflow_id_str, client_ip)
    if is_banned:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in {ban_remaining} seconds.",
            headers={"Retry-After": str(ban_remaining)},
        )

    user_result = await db.execute(
        select(WorkflowPortalUser).where(
            WorkflowPortalUser.workflow_id == workflow.id,
            WorkflowPortalUser.username == login_data.username,
        )
    )
    portal_user = user_result.scalar_one_or_none()

    if portal_user is None or not verify_password(login_data.password, portal_user.hashed_password):
        is_now_banned, ban_seconds = portal_login_limiter.record_failed_attempt(
            workflow_id_str, client_ip
        )
        if is_now_banned:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Try again in {ban_seconds} seconds.",
                headers={"Retry-After": str(ban_seconds)},
            )
        remaining = portal_login_limiter.get_remaining_attempts(workflow_id_str, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid credentials. {remaining} attempts remaining.",
        )

    portal_login_limiter.record_successful_login(workflow_id_str, client_ip)

    token, expires_at = await _create_session(db, workflow.id, login_data.username)
    await db.commit()

    return PortalLoginResponse(session_token=token, expires_at=expires_at)


@router.post("/{slug}/execute", response_model=WorkflowExecuteResponse)
async def portal_execute(
    slug: str,
    execute_data: PortalExecuteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WorkflowExecuteResponse:
    result = await db.execute(
        select(Workflow).where(Workflow.portal_slug == slug, Workflow.portal_enabled.is_(True))
    )
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portal not found",
        )

    users_result = await db.execute(
        select(WorkflowPortalUser).where(WorkflowPortalUser.workflow_id == workflow.id).limit(1)
    )
    has_users = users_result.scalar_one_or_none() is not None

    if has_users:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        token = auth_header[7:]
        if not await _validate_session(db, token, workflow.id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session",
            )

    if not workflow.nodes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workflow has no nodes",
        )

    enriched_inputs = {
        "headers": _sanitize_headers(dict(request.headers)),
        "query": dict(request.query_params),
        "body": execute_data.inputs,
    }

    workflow_cache = await collect_referenced_workflows(db, workflow.nodes)
    credentials_context = await get_credentials_context(db, workflow.owner_id)
    global_variables_context = await get_global_variables_context(db, workflow.owner_id)

    conversation_history_dicts = [
        {"role": msg.role, "content": msg.content} for msg in execute_data.conversation_history
    ]

    execution_result = await asyncio.to_thread(
        execute_workflow,
        workflow_id=workflow.id,
        nodes=workflow.nodes,
        edges=workflow.edges,
        inputs=enriched_inputs,
        workflow_cache=workflow_cache,
        test_run=False,
        credentials_context=credentials_context,
        global_variables_context=global_variables_context,
        trace_user_id=workflow.owner_id,
        conversation_history=conversation_history_dicts if conversation_history_dicts else None,
    )

    if execution_result.status == "pending":
        history_entry, _ = await persist_pending_hitl_execution(
            db=db,
            workflow=workflow,
            enriched_inputs=enriched_inputs,
            execution_result=execution_result,
            trigger_source="portal",
            credentials_owner_id=workflow.owner_id,
            trace_user_id=workflow.owner_id,
            public_base_url=build_public_base_url(request),
        )
        await db.flush()
        return WorkflowExecuteResponse(
            workflow_id=execution_result.workflow_id,
            status=execution_result.status,
            outputs=execution_result.outputs,
            node_results=execution_result.node_results,
            execution_time_ms=execution_result.execution_time_ms,
            execution_history_id=history_entry.id,
        )
    history_entry = ExecutionHistory(
        workflow_id=workflow.id,
        inputs=enriched_inputs,
        outputs=execution_result.outputs,
        node_results=execution_result.node_results,
        status=execution_result.status,
        execution_time_ms=execution_result.execution_time_ms,
        trigger_source="portal",
    )
    db.add(history_entry)
    await upsert_workflow_analytics_snapshot(
        db,
        workflow_id=workflow.id,
        owner_id=workflow.owner_id,
        workflow_name_snapshot=workflow.name,
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
        workflow.owner_id,
        workflow.nodes,
        workflow_cache,
        execution_result.node_results,
        execution_result.sub_workflow_executions,
    )
    await db.flush()

    return WorkflowExecuteResponse(
        workflow_id=execution_result.workflow_id,
        status=execution_result.status,
        outputs=execution_result.outputs,
        node_results=execution_result.node_results,
        execution_time_ms=execution_result.execution_time_ms,
        execution_history_id=history_entry.id,
    )


@router.post("/{slug}/execute/stream")
async def portal_execute_stream(
    slug: str,
    execute_data: PortalExecuteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    import queue
    from concurrent.futures import ThreadPoolExecutor

    result = await db.execute(
        select(Workflow).where(Workflow.portal_slug == slug, Workflow.portal_enabled.is_(True))
    )
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portal not found",
        )

    users_result = await db.execute(
        select(WorkflowPortalUser).where(WorkflowPortalUser.workflow_id == workflow.id).limit(1)
    )
    has_users = users_result.scalar_one_or_none() is not None

    if has_users:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        token = auth_header[7:]
        if not await _validate_session(db, token, workflow.id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session",
            )

    if not workflow.nodes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workflow has no nodes",
        )

    enriched_inputs = {
        "headers": _sanitize_headers(dict(request.headers)),
        "query": dict(request.query_params),
        "body": execute_data.inputs,
    }

    workflow_cache = await collect_referenced_workflows(db, workflow.nodes)
    credentials_context = await get_credentials_context(db, workflow.owner_id)
    global_variables_context = await get_global_variables_context(db, workflow.owner_id)
    public_base_url = build_public_base_url(request)
    execution_id = uuid.uuid4()
    cancel_event = register_execution(workflow_id=workflow.id, execution_id=execution_id)

    conversation_history_dicts = [
        {"role": msg.role, "content": msg.content} for msg in execute_data.conversation_history
    ]

    event_queue: queue.Queue = queue.Queue()
    final_result: dict = {}
    progress_tracker = PortalProgressTracker()

    def run_executor():
        nonlocal final_result
        try:
            for event in execute_workflow_streaming(
                workflow_id=workflow.id,
                nodes=workflow.nodes,
                edges=workflow.edges,
                inputs=enriched_inputs,
                workflow_cache=workflow_cache,
                test_run=False,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=workflow.owner_id,
                conversation_history=conversation_history_dicts
                if conversation_history_dicts
                else None,
                cancel_event=cancel_event,
                public_base_url=public_base_url,
            ):
                event_queue.put(event)
                if event.get("type") == "execution_complete":
                    final_result = event
        except WorkflowCancelledError:
            return
        finally:
            event_queue.put(None)
            clear_active_execution(execution_id)

    async def event_generator():
        nonlocal final_result
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = loop.run_in_executor(pool, run_executor)
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "execution_started",
                        "execution_id": str(execution_id),
                    }
                )
                + "\n\n"
            )

            while True:
                if await request.is_disconnected():
                    cancel_event.set()
                    break
                try:
                    event = event_queue.get(block=True, timeout=0.01)
                    if event is None:
                        break
                    event = progress_tracker.observe_event(event)
                    if (
                        event.get("type") == "execution_complete"
                        and event.get("status") == "pending"
                    ):
                        pending_result = ExecutionResult(
                            workflow_id=uuid.UUID(str(event["workflow_id"])),
                            status="pending",
                            outputs=event.get("outputs", {}),
                            execution_time_ms=event.get("execution_time_ms", 0),
                            node_results=event.get("node_results", []),
                            sub_workflow_executions=event.get("sub_workflow_executions", []),
                            pending_review=event.get("_pending_review"),
                            resume_snapshot=event.get("_resume_snapshot"),
                        )
                        history_entry, _ = await persist_pending_hitl_execution(
                            db=db,
                            workflow=workflow,
                            enriched_inputs=enriched_inputs,
                            execution_result=pending_result,
                            trigger_source="portal",
                            credentials_owner_id=workflow.owner_id,
                            trace_user_id=workflow.owner_id,
                            public_base_url=public_base_url,
                        )
                        event["outputs"] = pending_result.outputs
                        event["node_results"] = pending_result.node_results
                        event["execution_history_id"] = str(history_entry.id)
                        final_result = event
                    sanitized_event = {
                        key: value for key, value in event.items() if not key.startswith("_")
                    }
                    yield f"data: {json.dumps(sanitized_event)}\n\n"
                except queue.Empty:
                    if await request.is_disconnected():
                        cancel_event.set()
                        break
                    if future.done():
                        while not event_queue.empty():
                            event = event_queue.get_nowait()
                            if event is None:
                                break
                            event = progress_tracker.observe_event(event)
                            if (
                                event.get("type") == "execution_complete"
                                and event.get("status") == "pending"
                            ):
                                pending_result = ExecutionResult(
                                    workflow_id=uuid.UUID(str(event["workflow_id"])),
                                    status="pending",
                                    outputs=event.get("outputs", {}),
                                    execution_time_ms=event.get("execution_time_ms", 0),
                                    node_results=event.get("node_results", []),
                                    sub_workflow_executions=event.get(
                                        "sub_workflow_executions", []
                                    ),
                                    pending_review=event.get("_pending_review"),
                                    resume_snapshot=event.get("_resume_snapshot"),
                                )
                                history_entry, _ = await persist_pending_hitl_execution(
                                    db=db,
                                    workflow=workflow,
                                    enriched_inputs=enriched_inputs,
                                    execution_result=pending_result,
                                    trigger_source="portal",
                                    credentials_owner_id=workflow.owner_id,
                                    trace_user_id=workflow.owner_id,
                                    public_base_url=public_base_url,
                                )
                                event["outputs"] = pending_result.outputs
                                event["node_results"] = pending_result.node_results
                                event["execution_history_id"] = str(history_entry.id)
                                final_result = event
                            sanitized_event = {
                                key: value
                                for key, value in event.items()
                                if not key.startswith("_")
                            }
                            yield f"data: {json.dumps(sanitized_event)}\n\n"
                        break
                    await asyncio.sleep(0.001)
                except Exception:
                    cancel_event.set()
                    break

            if final_result and final_result.get("status") != "pending":
                await _persist_global_variables_from_execution(
                    db,
                    workflow.owner_id,
                    workflow.nodes,
                    workflow_cache,
                    final_result.get("node_results", []),
                    final_result.get("sub_workflow_executions", []),
                )
                history_entry = ExecutionHistory(
                    workflow_id=workflow.id,
                    inputs=enriched_inputs,
                    outputs=final_result.get("outputs", {}),
                    node_results=final_result.get("node_results", []),
                    status=final_result.get("status", "error"),
                    execution_time_ms=final_result.get("execution_time_ms", 0),
                    trigger_source="portal",
                )
                db.add(history_entry)
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status=final_result.get("status", "error"),
                    execution_time_ms=float(final_result.get("execution_time_ms", 0)),
                )

                for sub_exec in final_result.get("sub_workflow_executions", []):
                    sub_history = ExecutionHistory(
                        workflow_id=uuid.UUID(sub_exec["workflow_id"]),
                        inputs=sub_exec["inputs"],
                        outputs=sub_exec["outputs"],
                        node_results=sub_exec.get("node_results", []),
                        status=sub_exec["status"],
                        execution_time_ms=sub_exec["execution_time_ms"],
                        trigger_source=sub_exec.get("trigger_source", "SUB_WORKFLOW"),
                    )
                    db.add(sub_history)
                    await upsert_workflow_analytics_snapshot(
                        db,
                        workflow_id=uuid.UUID(sub_exec["workflow_id"]),
                        owner_id=None,
                        workflow_name_snapshot=sub_exec.get("workflow_name") or "Sub-workflow",
                        status=sub_exec["status"],
                        execution_time_ms=float(sub_exec["execution_time_ms"]),
                    )

                await db.flush()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{slug}/executions/{execution_id}/cancel")
async def portal_cancel_execution(
    slug: str,
    execution_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await db.execute(
        select(Workflow).where(Workflow.portal_slug == slug, Workflow.portal_enabled.is_(True))
    )
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portal not found",
        )

    users_result = await db.execute(
        select(WorkflowPortalUser).where(WorkflowPortalUser.workflow_id == workflow.id).limit(1)
    )
    has_users = users_result.scalar_one_or_none() is not None

    if has_users:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        token = auth_header[7:]
        if not await _validate_session(db, token, workflow.id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session",
            )

    cancelled = cancel_active_execution(workflow_id=workflow.id, execution_id=execution_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found or already finished",
        )

    return {"status": "cancel_requested"}


@router.put("/{workflow_id}/portal", response_model=PortalSettingsResponse)
async def update_portal_settings(
    workflow_id: uuid.UUID,
    settings_data: PortalSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalSettingsResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    if workflow.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can modify portal settings",
        )

    if settings_data.portal_slug is not None:
        existing = await db.execute(
            select(Workflow).where(
                Workflow.portal_slug == settings_data.portal_slug, Workflow.id != workflow_id
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This slug is already in use",
            )
        workflow.portal_slug = settings_data.portal_slug

    if settings_data.portal_enabled is not None:
        workflow.portal_enabled = settings_data.portal_enabled
    if settings_data.portal_stream_enabled is not None:
        workflow.portal_stream_enabled = settings_data.portal_stream_enabled
    if settings_data.portal_file_upload_enabled is not None:
        workflow.portal_file_upload_enabled = settings_data.portal_file_upload_enabled
    if settings_data.portal_file_config is not None:
        workflow.portal_file_config = {
            k: v.model_dump() for k, v in settings_data.portal_file_config.items()
        }

    await db.flush()
    await db.refresh(workflow)

    return PortalSettingsResponse(
        portal_enabled=workflow.portal_enabled,
        portal_slug=workflow.portal_slug,
        portal_stream_enabled=workflow.portal_stream_enabled,
        portal_file_upload_enabled=workflow.portal_file_upload_enabled,
        portal_file_config=workflow.portal_file_config or {},
        input_fields=extract_input_fields_from_workflow(workflow),
    )


@router.get("/{workflow_id}/portal", response_model=PortalSettingsResponse)
async def get_portal_settings(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalSettingsResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    return PortalSettingsResponse(
        portal_enabled=workflow.portal_enabled,
        portal_slug=workflow.portal_slug,
        portal_stream_enabled=workflow.portal_stream_enabled,
        portal_file_upload_enabled=workflow.portal_file_upload_enabled,
        portal_file_config=workflow.portal_file_config or {},
        input_fields=extract_input_fields_from_workflow(workflow),
    )


@router.get("/{workflow_id}/portal/users", response_model=list[PortalUserResponse])
async def list_portal_users(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PortalUserResponse]:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    result = await db.execute(
        select(WorkflowPortalUser)
        .where(WorkflowPortalUser.workflow_id == workflow_id)
        .order_by(WorkflowPortalUser.username.asc())
    )
    users = result.scalars().all()

    return [PortalUserResponse.model_validate(u) for u in users]


@router.post("/{workflow_id}/portal/users", response_model=PortalUserResponse)
async def create_portal_user(
    workflow_id: uuid.UUID,
    user_data: PortalUserCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalUserResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    if workflow.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can manage portal users",
        )

    existing = await db.execute(
        select(WorkflowPortalUser).where(
            WorkflowPortalUser.workflow_id == workflow_id,
            WorkflowPortalUser.username == user_data.username,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    portal_user = WorkflowPortalUser(
        workflow_id=workflow_id,
        username=user_data.username,
        hashed_password=hash_password(user_data.password),
    )
    db.add(portal_user)
    await db.flush()
    await db.refresh(portal_user)

    return PortalUserResponse.model_validate(portal_user)


@router.delete("/{workflow_id}/portal/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portal_user(
    workflow_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    if workflow.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can manage portal users",
        )

    result = await db.execute(
        select(WorkflowPortalUser).where(
            WorkflowPortalUser.id == user_id, WorkflowPortalUser.workflow_id == workflow_id
        )
    )
    portal_user = result.scalar_one_or_none()

    if portal_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    await db.delete(portal_user)
