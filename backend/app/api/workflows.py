import asyncio
import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import String, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.deps import get_client_ip, get_current_user, get_current_user_optional
from app.db.models import (
    Credential,
    CredentialType,
    ExecutionHistory,
    RunHistory,
    Team,
    TeamMember,
    User,
    Workflow,
    WorkflowAuthType,
    WorkflowShare,
    WorkflowTeamShare,
    WorkflowVersion,
)
from app.db.session import async_session_maker, get_db
from app.models.schemas import (
    ActiveExecutionItem,
    ExecutionHistoryListResponse,
    ExecutionHistoryResponse,
    ExecutionHistoryWithWorkflowResponse,
    HistoryListResponse,
    InputFieldSchema,
    OutputNodeSchema,
    RevertVersionRequest,
    TeamShareRequest,
    TeamShareResponse,
    WorkflowCreate,
    WorkflowExecuteResponse,
    WorkflowListResponse,
    WorkflowListWithInputsResponse,
    WorkflowResponse,
    WorkflowShareRequest,
    WorkflowShareResponse,
    WorkflowUpdate,
    WorkflowVersionDiffResponse,
    WorkflowVersionResponse,
)
from app.services.cache_rate_limit import rate_limiter, response_cache
from app.services.encryption import decrypt_config
from app.services.execution_cancellation import (
    cancel_execution as cancel_active_execution,
)
from app.services.execution_cancellation import (
    clear_execution as clear_active_execution,
)
from app.services.execution_cancellation import (
    list_active_executions,
    register_execution,
)
from app.services.global_variables_service import (
    get_global_variables_context,
    upsert_global_variable,
)
from app.services.hitl_service import (
    build_public_base_url,
    persist_pending_hitl_execution,
)
from app.services.workflow_executor import (
    ExecutionResult,
    WorkflowCancelledError,
    _serialize_sub_workflow_executions,
    _to_json_compatible,
    execute_workflow,
    execute_workflow_streaming,
)
from app.services.workflow_version import calculate_workflow_diff

_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-execution-token",
        "x-mcp-key",
        "proxy-authorization",
        "x-api-key",
        "x-auth-token",
        "x-csrf-token",
        "x-session-token",
    }
)
_INTERNAL_STREAM_TRIGGER_SOURCES: frozenset[str] = frozenset({"Canvas", "Quick Drawer"})


def _coerce_bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _sanitize_headers(raw_headers: dict[str, str]) -> dict[str, str]:
    """Return lowercased headers with sensitive entries removed."""
    return {k.lower(): v for k, v in raw_headers.items() if k.lower() not in _SENSITIVE_HEADERS}


def _sanitize_invalid_unicode(value: Any) -> Any:
    """Replace lone surrogate code points so workflow JSON always serializes as UTF-8."""
    if isinstance(value, str):
        return "".join("\ufffd" if 0xD800 <= ord(char) <= 0xDFFF else char for char in value)
    if isinstance(value, list):
        return [_sanitize_invalid_unicode(item) for item in value]
    if isinstance(value, dict):
        return {
            _sanitize_invalid_unicode(key): _sanitize_invalid_unicode(item)
            for key, item in value.items()
        }
    return value


def _build_workflow_response(workflow: Workflow) -> WorkflowResponse:
    """Return a workflow response with UTF-8-safe node and edge payloads."""
    response = WorkflowResponse.model_validate(workflow)
    response.nodes = _sanitize_invalid_unicode(response.nodes)
    response.edges = _sanitize_invalid_unicode(response.edges)
    response.sse_node_config = _sanitize_invalid_unicode(response.sse_node_config or {})
    return response


async def _persist_global_variables_from_execution(
    db: AsyncSession,
    owner_id: uuid.UUID,
    workflow_nodes: list[dict],
    workflow_cache: dict[str, dict],
    node_results: list[dict],
    sub_workflow_executions: list,
) -> None:
    """Extract isGlobal variable node outputs and upsert to global variables."""

    async def _upsert_from_results(nodes: list[dict], results: list[dict]) -> None:
        nodes_by_id = {n.get("id"): n for n in nodes if n.get("id")}
        for nr in results:
            if not isinstance(nr, dict) or nr.get("node_type") != "variable":
                continue
            node_id = nr.get("node_id")
            node = nodes_by_id.get(node_id) if node_id else None
            if not node or not node.get("data", {}).get("isGlobal"):
                continue
            output = nr.get("output") or {}
            name = output.get("name")
            value = output.get("value")
            value_type = output.get("type", "string")
            if name is not None:
                await upsert_global_variable(db, owner_id, name, value, value_type)

    await _upsert_from_results(workflow_nodes, node_results)

    for sub in sub_workflow_executions:
        sub_node_results = (
            sub.node_results if hasattr(sub, "node_results") else sub.get("node_results", [])
        )
        sub_wf_id = sub.workflow_id if hasattr(sub, "workflow_id") else sub.get("workflow_id", "")
        sub_wf = workflow_cache.get(str(sub_wf_id), {})
        sub_nodes = sub_wf.get("nodes", [])
        await _upsert_from_results(sub_nodes, sub_node_results)


def _persist_playwright_save_steps(
    workflow: Workflow,
    node_results: list[dict],
    db: AsyncSession,
) -> None:
    """Persist saveSteps from Playwright node outputs into workflow steps."""

    def _apply_saved_steps(steps: list[dict], save_steps: dict) -> bool:
        changed = False
        for idx_str, saved_steps in save_steps.items():
            try:
                idx = int(idx_str)
            except (ValueError, TypeError):
                continue
            if 0 <= idx < len(steps) and steps[idx].get("action") == "aiStep":
                steps[idx]["savedSteps"] = saved_steps
                changed = True
        return changed

    nodes = workflow.nodes if isinstance(workflow.nodes, list) else []
    if not nodes:
        return
    nodes_by_id = {n.get("id"): n for n in nodes if n.get("id")}
    modified = False
    for nr in node_results or []:
        if nr.get("node_type") != "playwright":
            continue
        output = nr.get("output") or {}
        save_steps = output.get("saveSteps")
        if not save_steps or not isinstance(save_steps, dict):
            continue
        node_id = nr.get("node_id")
        node = nodes_by_id.get(node_id)
        if not node:
            continue
        data = node.get("data") or {}
        steps = data.get("playwrightSteps") or []
        if not steps:
            continue
        if any(key in save_steps for key in ("main", "fallback")):
            main_save_steps = save_steps.get("main")
            if isinstance(main_save_steps, dict):
                modified = _apply_saved_steps(steps, main_save_steps) or modified

            fallback_steps = data.get("playwrightAuthFallbackSteps") or []
            fallback_save_steps = save_steps.get("fallback")
            if isinstance(fallback_save_steps, dict) and fallback_steps:
                modified = _apply_saved_steps(fallback_steps, fallback_save_steps) or modified
        else:
            modified = _apply_saved_steps(steps, save_steps) or modified
    if modified:
        flag_modified(workflow, "nodes")


async def _finalize_allow_downstream_history(
    *,
    history_entry_id: uuid.UUID,
    workflow_id: uuid.UUID,
    workflow_name: str,
    owner_id: uuid.UUID,
    credentials_owner_id: uuid.UUID,
    workflow_nodes: list[dict],
    workflow_cache: dict[str, dict],
    execution_result: ExecutionResult,
) -> None:
    """Persist output allowDownstream work after the API response has returned."""
    try:
        await asyncio.to_thread(execution_result.join_allow_downstream)
        async with async_session_maker() as bg_db:
            history_result = await bg_db.execute(
                select(ExecutionHistory).where(ExecutionHistory.id == history_entry_id)
            )
            history_entry = history_result.scalar_one_or_none()
            if history_entry is not None:
                history_entry.outputs = _to_json_compatible(execution_result.outputs)
                history_entry.node_results = _to_json_compatible(execution_result.node_results)
                history_entry.status = execution_result.status
                history_entry.execution_time_ms = execution_result.execution_time_ms
                flag_modified(history_entry, "outputs")
                flag_modified(history_entry, "node_results")

            for sub_exec in execution_result.sub_workflow_executions:
                sub_history = ExecutionHistory(
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    inputs=_to_json_compatible(sub_exec.inputs),
                    outputs=_to_json_compatible(sub_exec.outputs),
                    node_results=_to_json_compatible(sub_exec.node_results),
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                    trigger_source=sub_exec.trigger_source,
                )
                bg_db.add(sub_history)
                await upsert_workflow_analytics_snapshot(
                    bg_db,
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    owner_id=None,
                    workflow_name_snapshot=sub_exec.workflow_name or "Sub-workflow",
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                )

            await _persist_global_variables_from_execution(
                bg_db,
                credentials_owner_id,
                workflow_nodes,
                workflow_cache,
                _to_json_compatible(execution_result.node_results),
                execution_result.sub_workflow_executions,
            )
            await upsert_workflow_analytics_snapshot(
                bg_db,
                workflow_id=workflow_id,
                owner_id=owner_id,
                workflow_name_snapshot=workflow_name,
                status=execution_result.status,
                execution_time_ms=execution_result.execution_time_ms,
            )
            await bg_db.commit()
    except Exception:
        pass


router = APIRouter()


async def get_workflow_for_user(
    db: AsyncSession, workflow_id: uuid.UUID, user_id: uuid.UUID
) -> Workflow | None:
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            or_(
                Workflow.owner_id == user_id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == user_id)
                ),
                Workflow.id.in_(
                    select(WorkflowTeamShare.workflow_id).where(
                        WorkflowTeamShare.team_id.in_(
                            select(TeamMember.team_id).where(TeamMember.user_id == user_id)
                        )
                    )
                ),
            ),
        )
    )
    return result.scalar_one_or_none()


async def user_has_workflow_access(
    db: AsyncSession, workflow: Workflow, user_id: uuid.UUID
) -> bool:
    if workflow.owner_id == user_id:
        return True
    share_result = await db.execute(
        select(WorkflowShare).where(
            WorkflowShare.workflow_id == workflow.id,
            WorkflowShare.user_id == user_id,
        )
    )
    if share_result.scalar_one_or_none() is not None:
        return True

    team_share_result = await db.execute(
        select(WorkflowTeamShare)
        .join(TeamMember, TeamMember.team_id == WorkflowTeamShare.team_id)
        .where(
            WorkflowTeamShare.workflow_id == workflow.id,
            TeamMember.user_id == user_id,
        )
    )
    return team_share_result.scalar_one_or_none() is not None


def extract_input_fields_from_workflow(workflow: Workflow) -> list[InputFieldSchema]:
    nodes = workflow.nodes or []
    edges = workflow.edges or []

    target_node_ids = {edge.get("target") for edge in edges if edge.get("target")}
    start_nodes = [
        node
        for node in nodes
        if node.get("id") not in target_node_ids
        and node.get("type") == "textInput"
        and node.get("data", {}).get("active") is not False
    ]

    input_fields: list[InputFieldSchema] = []
    for node in start_nodes:
        node_data = node.get("data", {})
        node_fields = node_data.get("inputFields") or [{"key": "text"}]
        for field in node_fields:
            input_fields.append(
                InputFieldSchema(
                    key=field.get("key", "text"),
                    default_value=field.get("defaultValue"),
                )
            )

    return input_fields


def get_node_output_expression(node: dict) -> str | None:
    node_type = node.get("type", "")
    node_data = node.get("data", {})
    label = node_data.get("label", "")

    if node_type == "output":
        return node_data.get("message")
    if node_type == "llm":
        output_type = node_data.get("outputType", "text")
        if output_type == "image":
            return f"${label}.image"
        return f"${label}.text"
    if node_type == "agent":
        return f"${label}.text"
    if node_type == "http":
        return f"${label}.body"
    if node_type == "set":
        mappings = node_data.get("mappings", [])
        if mappings:
            keys = [m.get("key") for m in mappings if m.get("key")]
            if len(keys) == 1:
                return f"${label}.{keys[0]}"
            if keys:
                return f"${label}.{{{', '.join(keys)}}}"
        return f"${label}.text"
    if node_type == "jsonOutputMapper":
        mappings = node_data.get("mappings", [])
        if mappings:
            keys = [m.get("key") for m in mappings if m.get("key")]
            if len(keys) == 1:
                return f"${label}.{keys[0]}"
            if keys:
                return f"${label}.{{{', '.join(keys)}}}"
        return f"${label} (JSON response body when sole terminal)"
    if node_type == "variable":
        return f"${label}.value"
    if node_type == "execute":
        return f"${label}.outputs.output.result"
    if node_type == "condition":
        return f"${label} (branches: true/false)"
    if node_type == "switch":
        return f"${label} (branches: case-0, case-1, ...)"
    if node_type == "loop":
        return f"${label}.results (array of iteration outputs)"
    if node_type == "merge":
        return f"${label}.merged"
    if node_type == "slack":
        return f"${label}.success"
    if node_type == "textInput":
        input_fields = node_data.get("inputFields", [{"key": "text"}])
        keys = [f.get("key", "text") for f in input_fields]
        if len(keys) == 1:
            return f"${label}.{keys[0]}"
        return f"${label}.{{{', '.join(keys)}}}"
    return None


def extract_output_node_from_workflow(workflow: Workflow) -> OutputNodeSchema | None:
    nodes = workflow.nodes or []
    edges = workflow.edges or []

    if not nodes:
        return None

    source_node_ids = {edge.get("source") for edge in edges if edge.get("source")}

    end_nodes = [
        node
        for node in nodes
        if node.get("id") not in source_node_ids
        and node.get("data", {}).get("active") is not False
        and node.get("type") not in ("sticky", "errorHandler")
    ]

    output_nodes = [n for n in end_nodes if n.get("type") == "output"]
    if output_nodes:
        node = output_nodes[0]
        node_data = node.get("data", {})
        return OutputNodeSchema(
            label=node_data.get("label", ""),
            node_type="output",
            output_expression=node_data.get("message"),
        )

    json_mapper_nodes = [n for n in end_nodes if n.get("type") == "jsonOutputMapper"]
    if json_mapper_nodes:
        node = json_mapper_nodes[0]
        node_data = node.get("data", {})
        return OutputNodeSchema(
            label=node_data.get("label", ""),
            node_type="jsonOutputMapper",
            output_expression=get_node_output_expression(node),
        )

    if end_nodes:
        node = end_nodes[0]
        node_data = node.get("data", {})
        return OutputNodeSchema(
            label=node_data.get("label", ""),
            node_type=node.get("type", ""),
            output_expression=get_node_output_expression(node),
        )

    return None


def get_first_node_type(workflow: Workflow) -> str | None:
    nodes = workflow.nodes or []
    edges = workflow.edges or []

    if not nodes:
        return None

    target_node_ids = {edge.get("target") for edge in edges if edge.get("target")}
    start_nodes = [
        node
        for node in nodes
        if node.get("id") not in target_node_ids
        and node.get("data", {}).get("active") is not False
        and node.get("type") not in ("sticky", "errorHandler")
    ]

    if start_nodes:
        return start_nodes[0].get("type")

    active_nodes = [
        node
        for node in nodes
        if node.get("data", {}).get("active") is not False
        and node.get("type") not in ("sticky", "errorHandler")
    ]
    if active_nodes:
        return active_nodes[0].get("type")

    return None


@router.get("", response_model=list[WorkflowListResponse])
async def list_workflows(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowListResponse]:
    result = await db.execute(
        select(Workflow)
        .where(
            or_(
                Workflow.owner_id == current_user.id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(
                        WorkflowShare.user_id == current_user.id
                    )
                ),
                Workflow.id.in_(
                    select(WorkflowTeamShare.workflow_id).where(
                        WorkflowTeamShare.team_id.in_(
                            select(TeamMember.team_id).where(TeamMember.user_id == current_user.id)
                        )
                    )
                ),
            )
        )
        .order_by(Workflow.updated_at.desc())
    )
    workflows = result.scalars().all()

    shares_result = await db.execute(
        select(WorkflowShare).where(WorkflowShare.user_id == current_user.id)
    )
    shares_map = {s.workflow_id: s for s in shares_result.scalars().all()}

    response_list = []
    for w in workflows:
        if w.owner_id == current_user.id:
            folder_id = w.folder_id
            scheduled_for_deletion = w.scheduled_for_deletion
        else:
            share = shares_map.get(w.id)
            folder_id = share.folder_id if share else None
            scheduled_for_deletion = None

        response = WorkflowListResponse(
            id=w.id,
            name=w.name,
            description=w.description,
            folder_id=folder_id,
            first_node_type=get_first_node_type(w),
            scheduled_for_deletion=scheduled_for_deletion,
            created_at=w.created_at,
            updated_at=w.updated_at,
        )
        response_list.append(response)

    return response_list


@router.get("/with-inputs", response_model=list[WorkflowListWithInputsResponse])
async def list_workflows_with_inputs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowListWithInputsResponse]:
    result = await db.execute(
        select(Workflow)
        .where(
            or_(
                Workflow.owner_id == current_user.id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(
                        WorkflowShare.user_id == current_user.id
                    )
                ),
                Workflow.id.in_(
                    select(WorkflowTeamShare.workflow_id).where(
                        WorkflowTeamShare.team_id.in_(
                            select(TeamMember.team_id).where(TeamMember.user_id == current_user.id)
                        )
                    )
                ),
            )
        )
        .order_by(Workflow.updated_at.desc())
    )
    workflows = result.scalars().all()

    return [
        WorkflowListWithInputsResponse(
            id=w.id,
            name=w.name,
            description=w.description,
            input_fields=extract_input_fields_from_workflow(w),
            output_node=extract_output_node_from_workflow(w),
            created_at=w.created_at,
            updated_at=w.updated_at,
        )
        for w in workflows
    ]


def _run_history_display_name(run_type: str) -> str:
    if run_type == "dashboard_chat":
        return "Dashboard Chat"
    if run_type == "workflow_assistant":
        return "Workflow Assistant"
    return run_type


def _run_steps_to_node_results(steps: list) -> list:
    """Convert run_history.steps (tool call steps) to node_results shape for API."""
    out = []
    for i, step in enumerate(steps or []):
        if not isinstance(step, dict):
            continue
        label = step.get("label", "Step")
        tool = step.get("tool")
        request = step.get("request", {})
        response_summary = step.get("response_summary", "")
        step_ms = step.get("execution_time_ms", 0.0)
        if not isinstance(step_ms, (int, float)):
            step_ms = 0.0
        out.append(
            {
                "node_id": f"step-{i}",
                "node_label": label,
                "node_type": tool if tool else "assistant",
                "status": "success",
                "output": {"request": request, "response_summary": response_summary},
                "execution_time_ms": float(step_ms),
                "error": None,
            }
        )
    return out


def _output_summary_for_chat(outputs: dict) -> str:
    """Short summary of outputs for chat tool (avoid huge payloads)."""
    if not outputs or not isinstance(outputs, dict):
        return ""
    keys = list(outputs.keys())[:3]
    if not keys:
        return ""
    parts = []
    for k in keys:
        v = outputs.get(k)
        if isinstance(v, str):
            parts.append(f"{k}: {v[:80]}{'...' if len(v) > 80 else ''}")
        else:
            parts.append(f"{k}: {str(v)[:60]}{'...' if len(str(v)) > 60 else ''}")
    return " | ".join(parts) if parts else str(outputs)[:120]


async def get_recent_executions_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 50,
    since_hours: int | None = 24,
) -> list[dict]:
    """
    Return recent execution and run history for the user, for dashboard chat.
    Each item: workflow_name, run_type, started_at (iso), status, execution_time_ms,
    trigger_source, output_summary.
    """
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=since_hours)) if since_hours else None

    exec_query = (
        select(ExecutionHistory, Workflow)
        .join(Workflow, ExecutionHistory.workflow_id == Workflow.id)
        .where(
            or_(
                Workflow.owner_id == user_id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == user_id)
                ),
            )
        )
        .order_by(ExecutionHistory.started_at.desc())
        .limit(limit)
    )
    if since is not None:
        exec_query = exec_query.where(ExecutionHistory.started_at >= since)
    exec_result = await db.execute(exec_query)
    exec_rows = exec_result.all()

    run_query = (
        select(RunHistory)
        .where(RunHistory.user_id == user_id)
        .order_by(RunHistory.started_at.desc())
        .limit(limit)
    )
    if since is not None:
        run_query = run_query.where(RunHistory.started_at >= since)
    run_result = await db.execute(run_query)
    run_rows = run_result.scalars().all()

    items: list[dict] = []
    for history, workflow in exec_rows:
        started = history.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        items.append(
            {
                "workflow_name": workflow.name,
                "run_type": "workflow",
                "started_at": started.isoformat(),
                "status": history.status,
                "execution_time_ms": history.execution_time_ms or 0,
                "trigger_source": history.trigger_source or "",
                "output_summary": _output_summary_for_chat(history.outputs or {}),
            }
        )
    for run in run_rows:
        started = run.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        items.append(
            {
                "workflow_name": _run_history_display_name(run.run_type),
                "run_type": run.run_type,
                "started_at": started.isoformat(),
                "status": run.status,
                "execution_time_ms": run.execution_time_ms or 0,
                "trigger_source": run.trigger_source or "",
                "output_summary": _output_summary_for_chat(run.outputs or {}),
            }
        )
    items.sort(key=lambda x: x["started_at"], reverse=True)
    return items[:limit]


@router.get(
    "/history/all/{entry_id}",
    response_model=ExecutionHistoryWithWorkflowResponse,
)
async def get_execution_history_entry(
    entry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExecutionHistoryWithWorkflowResponse:
    """Get full detail of a single execution history entry (workflow or run)."""
    # Try ExecutionHistory first
    exec_result = await db.execute(
        select(ExecutionHistory, Workflow)
        .join(Workflow, ExecutionHistory.workflow_id == Workflow.id)
        .where(ExecutionHistory.id == entry_id)
        .where(
            or_(
                Workflow.owner_id == current_user.id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(
                        WorkflowShare.user_id == current_user.id
                    )
                ),
            )
        )
    )
    row = exec_result.first()
    if row:
        history, workflow = row
        return ExecutionHistoryWithWorkflowResponse(
            id=history.id,
            workflow_id=history.workflow_id,
            workflow_name=workflow.name,
            run_type="workflow",
            inputs=history.inputs,
            outputs=history.outputs,
            node_results=history.node_results or [],
            status=history.status,
            execution_time_ms=history.execution_time_ms,
            started_at=history.started_at,
            trigger_source=history.trigger_source,
        )
    # Try RunHistory
    run_result = await db.execute(
        select(RunHistory).where(
            RunHistory.id == entry_id,
            RunHistory.user_id == current_user.id,
        )
    )
    run = run_result.scalar_one_or_none()
    if run:
        return ExecutionHistoryWithWorkflowResponse(
            id=run.id,
            workflow_id=run.workflow_id,
            workflow_name=_run_history_display_name(run.run_type),
            run_type=run.run_type,
            inputs=run.inputs,
            outputs=run.outputs,
            node_results=_run_steps_to_node_results(getattr(run, "steps", None) or []),
            status=run.status,
            execution_time_ms=run.execution_time_ms,
            started_at=run.started_at,
            trigger_source=run.trigger_source,
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Execution history entry not found",
    )


@router.get("/history/all", response_model=HistoryListResponse)
async def list_all_execution_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    execution_status: str | None = Query(default=None, alias="status"),
    trigger_source: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
) -> HistoryListResponse:
    """List execution history (lightweight, paginated)."""
    # Workflow execution history (light)
    exec_query = (
        select(ExecutionHistory, Workflow)
        .join(Workflow, ExecutionHistory.workflow_id == Workflow.id)
        .where(
            or_(
                Workflow.owner_id == current_user.id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(
                        WorkflowShare.user_id == current_user.id
                    )
                ),
            )
        )
    )
    if workflow_id:
        exec_query = exec_query.where(ExecutionHistory.workflow_id == workflow_id)
    if trigger_source:
        exec_query = exec_query.where(ExecutionHistory.trigger_source == trigger_source)
    if execution_status:
        exec_query = exec_query.where(ExecutionHistory.status == execution_status)
    if search:
        pattern = f"%{search}%"
        exec_query = exec_query.where(
            or_(
                Workflow.name.ilike(pattern),
                ExecutionHistory.status.ilike(pattern),
                ExecutionHistory.trigger_source.ilike(pattern),
                cast(ExecutionHistory.inputs, String).ilike(pattern),
                cast(ExecutionHistory.outputs, String).ilike(pattern),
                cast(ExecutionHistory.node_results, String).ilike(pattern),
            )
        )
    exec_query = exec_query.order_by(ExecutionHistory.started_at.desc())
    exec_result = await db.execute(exec_query)
    exec_rows = exec_result.all()
    workflow_items = [
        ExecutionHistoryListResponse(
            id=history.id,
            workflow_id=history.workflow_id,
            workflow_name=workflow.name,
            run_type="workflow",
            started_at=history.started_at,
            status=history.status,
            execution_time_ms=history.execution_time_ms,
            trigger_source=history.trigger_source,
        )
        for history, workflow in exec_rows
    ]
    # Chat/assistant run history (light) – skipped when filtering by workflow_id
    run_items: list[ExecutionHistoryListResponse] = []
    if not workflow_id:
        run_query = select(RunHistory).where(RunHistory.user_id == current_user.id)
        if trigger_source:
            run_query = run_query.where(RunHistory.trigger_source == trigger_source)
        if execution_status:
            run_query = run_query.where(RunHistory.status == execution_status)
        if search:
            pattern = f"%{search}%"
            run_query = run_query.where(
                or_(
                    RunHistory.status.ilike(pattern),
                    RunHistory.trigger_source.ilike(pattern),
                    RunHistory.run_type.ilike(pattern),
                    cast(RunHistory.inputs, String).ilike(pattern),
                    cast(RunHistory.outputs, String).ilike(pattern),
                )
            )
        run_query = run_query.order_by(RunHistory.started_at.desc())
        run_result = await db.execute(run_query)
        run_rows = run_result.scalars().all()
        run_items = [
            ExecutionHistoryListResponse(
                id=run.id,
                workflow_id=run.workflow_id,
                workflow_name=_run_history_display_name(run.run_type),
                run_type=run.run_type,
                started_at=run.started_at,
                status=run.status,
                execution_time_ms=run.execution_time_ms,
                trigger_source=run.trigger_source,
            )
            for run in run_rows
        ]
    merged = workflow_items + run_items
    merged.sort(key=lambda x: x.started_at, reverse=True)
    total = len(merged)
    items = merged[offset : offset + limit]
    return HistoryListResponse(total=total, items=items)


@router.delete("/history/all", status_code=status.HTTP_204_NO_CONTENT)
async def clear_all_execution_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    accessible_workflows = select(Workflow.id).where(
        or_(
            Workflow.owner_id == current_user.id,
            Workflow.id.in_(
                select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == current_user.id)
            ),
        )
    )
    await db.execute(
        ExecutionHistory.__table__.delete().where(
            ExecutionHistory.workflow_id.in_(accessible_workflows)
        )
    )
    await db.execute(RunHistory.__table__.delete().where(RunHistory.user_id == current_user.id))


@router.get("/executions/active", response_model=list[ActiveExecutionItem])
async def list_active_workflow_executions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ActiveExecutionItem]:
    """Return all currently running executions belonging to the authenticated user."""
    handles = list_active_executions()
    if not handles:
        return []

    workflow_ids = list({h.workflow_id for h in handles})
    result = await db.execute(
        select(Workflow).where(
            Workflow.id.in_(workflow_ids),
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
    accessible: dict[uuid.UUID, str] = {w.id: w.name for w in result.scalars().all()}

    return [
        ActiveExecutionItem(
            execution_id=str(h.execution_id),
            workflow_id=str(h.workflow_id),
            workflow_name=accessible[h.workflow_id],
            started_at=h.started_at,
        )
        for h in handles
        if h.workflow_id in accessible
    ]


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    workflow_data: WorkflowCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    workflow = Workflow(
        name=workflow_data.name,
        description=workflow_data.description,
        owner_id=current_user.id,
        nodes=[],
        edges=[],
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return _build_workflow_response(workflow)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    response = _build_workflow_response(workflow)
    if workflow.owner_id != current_user.id:
        share_result = await db.execute(
            select(WorkflowShare).where(
                WorkflowShare.workflow_id == workflow_id,
                WorkflowShare.user_id == current_user.id,
            )
        )
        share = share_result.scalar_one_or_none()
        response.folder_id = share.folder_id if share else None

    return response


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: uuid.UUID,
    workflow_data: WorkflowUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    should_create_version = False
    old_nodes = workflow.nodes
    old_edges = workflow.edges
    old_auth_type = workflow.auth_type
    old_auth_header_key = workflow.auth_header_key
    old_auth_header_value = workflow.auth_header_value
    old_webhook_body_mode = workflow.webhook_body_mode
    old_cache_ttl_seconds = workflow.cache_ttl_seconds
    old_rate_limit_requests = workflow.rate_limit_requests
    old_rate_limit_window_seconds = workflow.rate_limit_window_seconds
    sanitized_nodes = _sanitize_invalid_unicode(workflow_data.nodes)
    sanitized_edges = _sanitize_invalid_unicode(workflow_data.edges)
    sanitized_sse_node_config = _sanitize_invalid_unicode(workflow_data.sse_node_config)

    if workflow_data.name is not None:
        workflow.name = workflow_data.name
    if workflow_data.description is not None:
        workflow.description = workflow_data.description
    if sanitized_nodes is not None:
        if sanitized_nodes != old_nodes:
            should_create_version = True
        workflow.nodes = sanitized_nodes
    if sanitized_edges is not None:
        if sanitized_edges != old_edges:
            should_create_version = True
        workflow.edges = sanitized_edges
    if workflow_data.auth_type is not None:
        if workflow_data.auth_type != old_auth_type:
            should_create_version = True
        workflow.auth_type = workflow_data.auth_type
    if workflow_data.auth_header_key is not None:
        workflow.auth_header_key = workflow_data.auth_header_key
    if workflow_data.auth_header_value is not None:
        workflow.auth_header_value = workflow_data.auth_header_value
    if workflow_data.webhook_body_mode is not None:
        if workflow_data.webhook_body_mode != old_webhook_body_mode:
            should_create_version = True
        workflow.webhook_body_mode = workflow_data.webhook_body_mode
    if workflow_data.cache_ttl_seconds is not None:
        workflow.cache_ttl_seconds = (
            workflow_data.cache_ttl_seconds if workflow_data.cache_ttl_seconds > 0 else None
        )
    if workflow_data.rate_limit_requests is not None:
        workflow.rate_limit_requests = (
            workflow_data.rate_limit_requests if workflow_data.rate_limit_requests > 0 else None
        )
    if workflow_data.rate_limit_window_seconds is not None:
        workflow.rate_limit_window_seconds = (
            workflow_data.rate_limit_window_seconds
            if workflow_data.rate_limit_window_seconds > 0
            else None
        )
    if workflow_data.sse_enabled is not None:
        workflow.sse_enabled = workflow_data.sse_enabled
    if workflow_data.sse_node_config is not None:
        workflow.sse_node_config = sanitized_sse_node_config

    if should_create_version:
        max_version_result = await db.execute(
            select(func.max(WorkflowVersion.version_number)).where(
                WorkflowVersion.workflow_id == workflow_id
            )
        )
        max_version = max_version_result.scalar() or 0
        new_version_number = max_version + 1

        workflow_version = WorkflowVersion(
            workflow_id=workflow_id,
            version_number=new_version_number,
            name=workflow.name,
            description=workflow.description,
            nodes=old_nodes,
            edges=old_edges,
            auth_type=old_auth_type,
            auth_header_key=old_auth_header_key,
            auth_header_value=old_auth_header_value,
            webhook_body_mode=old_webhook_body_mode,
            cache_ttl_seconds=old_cache_ttl_seconds,
            rate_limit_requests=old_rate_limit_requests,
            rate_limit_window_seconds=old_rate_limit_window_seconds,
            created_by_id=current_user.id,
        )
        db.add(workflow_version)

    await db.flush()
    await db.commit()
    await db.refresh(workflow)
    from app.services.websocket_trigger_service import websocket_trigger_manager

    websocket_trigger_manager.request_sync()
    return _build_workflow_response(workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: uuid.UUID,
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
            detail="Only the owner can delete this workflow",
        )

    # Delete only the snapshots that would violate the unique constraint when
    # workflow_id is set to NULL by the FK (i.e. a null-workflow row already
    # exists for the same owner_id + bucket_start). The rest keep their row
    # with workflow_id=NULL, preserving historical analytics data.
    await db.execute(
        text(
            """
            DELETE FROM workflow_analytics_snapshots wf
            WHERE wf.workflow_id = :workflow_id
              AND EXISTS (
                  SELECT 1 FROM workflow_analytics_snapshots n
                  WHERE n.workflow_id IS NULL
                    AND n.owner_id IS NOT DISTINCT FROM wf.owner_id
                    AND n.bucket_start = wf.bucket_start
              )
        """
        ),
        {"workflow_id": str(workflow_id)},
    )
    await db.delete(workflow)


@router.put("/{workflow_id}/schedule-deletion", response_model=WorkflowListResponse)
async def schedule_workflow_for_deletion(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowListResponse:
    from datetime import datetime, timezone

    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    if workflow.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can schedule this workflow for deletion",
        )

    workflow.scheduled_for_deletion = datetime.now(timezone.utc)
    workflow.folder_id = None
    await db.flush()
    await db.refresh(workflow)

    return WorkflowListResponse(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        folder_id=workflow.folder_id,
        first_node_type=get_first_node_type(workflow),
        scheduled_for_deletion=workflow.scheduled_for_deletion,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


@router.delete("/{workflow_id}/schedule-deletion", response_model=WorkflowListResponse)
async def unschedule_workflow_for_deletion(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowListResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    if workflow.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can unschedule this workflow for deletion",
        )

    workflow.scheduled_for_deletion = None
    await db.flush()
    await db.refresh(workflow)

    return WorkflowListResponse(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        folder_id=workflow.folder_id,
        first_node_type=get_first_node_type(workflow),
        scheduled_for_deletion=workflow.scheduled_for_deletion,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


@router.get("/{workflow_id}/versions", response_model=list[WorkflowVersionResponse])
async def list_workflow_versions(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> list[WorkflowVersionResponse]:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    result = await db.execute(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version_number.desc())
        .limit(limit)
        .offset(offset)
    )
    versions = result.scalars().all()

    return [WorkflowVersionResponse.model_validate(version) for version in versions]


@router.get("/{workflow_id}/versions/{version_id}", response_model=WorkflowVersionResponse)
async def get_workflow_version(
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowVersionResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    result = await db.execute(
        select(WorkflowVersion).where(
            WorkflowVersion.id == version_id, WorkflowVersion.workflow_id == workflow_id
        )
    )
    version = result.scalar_one_or_none()

    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found",
        )

    return WorkflowVersionResponse.model_validate(version)


@router.get(
    "/{workflow_id}/versions/{version_id}/diff",
    response_model=WorkflowVersionDiffResponse,
)
async def get_workflow_version_diff(
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    compare_to: uuid.UUID | None = None,
) -> WorkflowVersionDiffResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    result = await db.execute(
        select(WorkflowVersion).where(
            WorkflowVersion.id == version_id, WorkflowVersion.workflow_id == workflow_id
        )
    )
    version = result.scalar_one_or_none()

    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found",
        )

    if compare_to:
        compare_result = await db.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.id == compare_to,
                WorkflowVersion.workflow_id == workflow_id,
            )
        )
        compare_version = compare_result.scalar_one_or_none()
        if compare_version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Compare version not found",
            )
        old_nodes = compare_version.nodes
        old_edges = compare_version.edges
        old_config = {
            "auth_type": compare_version.auth_type,
            "auth_header_key": compare_version.auth_header_key,
            "auth_header_value": compare_version.auth_header_value,
            "webhook_body_mode": compare_version.webhook_body_mode,
            "cache_ttl_seconds": compare_version.cache_ttl_seconds,
            "rate_limit_requests": compare_version.rate_limit_requests,
            "rate_limit_window_seconds": compare_version.rate_limit_window_seconds,
        }
        compared_to_version_id = str(compare_version.id)
        compared_to_version_number = compare_version.version_number
        new_nodes = version.nodes
        new_edges = version.edges
        new_config = {
            "auth_type": version.auth_type,
            "auth_header_key": version.auth_header_key,
            "auth_header_value": version.auth_header_value,
            "webhook_body_mode": version.webhook_body_mode,
            "cache_ttl_seconds": version.cache_ttl_seconds,
            "rate_limit_requests": version.rate_limit_requests,
            "rate_limit_window_seconds": version.rate_limit_window_seconds,
        }
    else:
        old_nodes = version.nodes
        old_edges = version.edges
        old_config = {
            "auth_type": version.auth_type,
            "auth_header_key": version.auth_header_key,
            "auth_header_value": version.auth_header_value,
            "webhook_body_mode": version.webhook_body_mode,
            "cache_ttl_seconds": version.cache_ttl_seconds,
            "rate_limit_requests": version.rate_limit_requests,
            "rate_limit_window_seconds": version.rate_limit_window_seconds,
        }
        compared_to_version_id = None
        compared_to_version_number = None
        new_nodes = workflow.nodes
        new_edges = workflow.edges
        new_config = {
            "auth_type": workflow.auth_type,
            "auth_header_key": workflow.auth_header_key,
            "auth_header_value": workflow.auth_header_value,
            "webhook_body_mode": workflow.webhook_body_mode,
            "cache_ttl_seconds": workflow.cache_ttl_seconds,
            "rate_limit_requests": workflow.rate_limit_requests,
            "rate_limit_window_seconds": workflow.rate_limit_window_seconds,
        }

    diff = calculate_workflow_diff(
        old_nodes=old_nodes,
        old_edges=old_edges,
        old_config=old_config,
        new_nodes=new_nodes,
        new_edges=new_edges,
        new_config=new_config,
        version_id=str(version.id),
        version_number=version.version_number,
        compared_to_version_id=compared_to_version_id,
        compared_to_version_number=compared_to_version_number,
    )

    return diff


@router.post("/{workflow_id}/versions/{version_id}/revert", response_model=WorkflowResponse)
async def revert_workflow_to_version(
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    revert_data: RevertVersionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    if workflow.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can revert this workflow",
        )

    result = await db.execute(
        select(WorkflowVersion).where(
            WorkflowVersion.id == version_id, WorkflowVersion.workflow_id == workflow_id
        )
    )
    version = result.scalar_one_or_none()

    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found",
        )

    if not revert_data.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Revert confirmation required",
        )

    workflow.name = version.name
    workflow.description = version.description
    workflow.nodes = _sanitize_invalid_unicode(version.nodes)
    workflow.edges = _sanitize_invalid_unicode(version.edges)
    workflow.auth_type = version.auth_type
    workflow.auth_header_key = version.auth_header_key
    workflow.auth_header_value = version.auth_header_value
    workflow.webhook_body_mode = version.webhook_body_mode
    workflow.cache_ttl_seconds = version.cache_ttl_seconds
    workflow.rate_limit_requests = version.rate_limit_requests
    workflow.rate_limit_window_seconds = version.rate_limit_window_seconds

    await db.flush()
    await db.refresh(workflow)

    return _build_workflow_response(workflow)


@router.delete("/{workflow_id}/versions", status_code=status.HTTP_204_NO_CONTENT)
async def clear_workflow_versions(
    workflow_id: uuid.UUID,
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
            detail="Only the owner can clear version history",
        )

    result = await db.execute(
        select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id)
    )
    versions = result.scalars().all()

    for version in versions:
        await db.delete(version)

    await db.commit()


@router.get("/{workflow_id}/shares", response_model=list[WorkflowShareResponse])
async def list_workflow_shares(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowShareResponse]:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    result = await db.execute(
        select(WorkflowShare, User)
        .join(User, User.id == WorkflowShare.user_id)
        .where(WorkflowShare.workflow_id == workflow_id)
        .order_by(User.email.asc())
    )
    shares = []
    for share, user in result.all():
        shares.append(
            WorkflowShareResponse(
                id=share.id,
                user_id=user.id,
                email=user.email,
                name=user.name,
                mcp_enabled=share.mcp_enabled,
                folder_id=share.folder_id,
                shared_at=share.created_at,
            )
        )
    return shares


@router.post("/{workflow_id}/shares", response_model=WorkflowShareResponse)
async def create_workflow_share(
    workflow_id: uuid.UUID,
    share_data: WorkflowShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowShareResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    result = await db.execute(select(User).where(User.email == share_data.email))
    target_user = result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if target_user.id == workflow.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot share with owner",
        )

    share_result = await db.execute(
        select(WorkflowShare).where(
            WorkflowShare.workflow_id == workflow.id,
            WorkflowShare.user_id == target_user.id,
        )
    )
    share = share_result.scalar_one_or_none()
    if share is None:
        share = WorkflowShare(workflow_id=workflow.id, user_id=target_user.id)
        db.add(share)
        await db.flush()
        await db.refresh(share)

    return WorkflowShareResponse(
        id=share.id,
        user_id=target_user.id,
        email=target_user.email,
        name=target_user.name,
        shared_at=share.created_at,
    )


@router.delete("/{workflow_id}/shares/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_workflow_share(
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

    result = await db.execute(
        select(WorkflowShare).where(
            WorkflowShare.workflow_id == workflow_id, WorkflowShare.user_id == user_id
        )
    )
    share = result.scalar_one_or_none()
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share not found",
        )

    await db.delete(share)
    await db.commit()


@router.get("/{workflow_id}/team-shares", response_model=list[TeamShareResponse])
async def list_workflow_team_shares(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TeamShareResponse]:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )
    if workflow.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner can list team shares",
        )
    result = await db.execute(
        select(WorkflowTeamShare, Team)
        .join(Team, Team.id == WorkflowTeamShare.team_id)
        .where(WorkflowTeamShare.workflow_id == workflow_id)
        .order_by(Team.name.asc())
    )
    return [
        TeamShareResponse(
            id=share.id,
            team_id=team.id,
            team_name=team.name,
            shared_at=share.created_at,
        )
        for share, team in result.all()
    ]


@router.post("/{workflow_id}/team-shares", response_model=TeamShareResponse)
async def create_workflow_team_share(
    workflow_id: uuid.UUID,
    payload: TeamShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamShareResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )
    if workflow.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner can add team shares",
        )
    team_result = await db.execute(
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(Team.id == payload.team_id, TeamMember.user_id == current_user.id)
    )
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found or you are not a member",
        )
    existing = await db.execute(
        select(WorkflowTeamShare).where(
            WorkflowTeamShare.workflow_id == workflow_id,
            WorkflowTeamShare.team_id == payload.team_id,
        )
    )
    share = existing.scalar_one_or_none()
    if share:
        return TeamShareResponse(
            id=share.id,
            team_id=team.id,
            team_name=team.name,
            shared_at=share.created_at,
        )
    share = WorkflowTeamShare(workflow_id=workflow_id, team_id=payload.team_id)
    db.add(share)
    await db.flush()
    await db.refresh(share)
    await db.commit()
    return TeamShareResponse(
        id=share.id,
        team_id=team.id,
        team_name=team.name,
        shared_at=share.created_at,
    )


@router.delete("/{workflow_id}/team-shares/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_workflow_team_share(
    workflow_id: uuid.UUID,
    team_id: uuid.UUID,
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
            detail="Only owner can remove team shares",
        )
    result = await db.execute(
        select(WorkflowTeamShare).where(
            WorkflowTeamShare.workflow_id == workflow_id,
            WorkflowTeamShare.team_id == team_id,
        )
    )
    share = result.scalar_one_or_none()
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team share not found",
        )
    await db.delete(share)
    await db.commit()


async def get_credentials_context(
    db: AsyncSession, user_id: uuid.UUID, include_shared: bool = True
) -> dict[str, str]:
    from app.db.models import CredentialShare

    owned_result = await db.execute(select(Credential).where(Credential.owner_id == user_id))
    owned_credentials = owned_result.scalars().all()

    shared_credentials = []
    if include_shared:
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


async def validate_workflow_auth(
    workflow: Workflow,
    request: Request,
    current_user: User | None,
    db: AsyncSession,
) -> None:
    if workflow.auth_type == WorkflowAuthType.anonymous:
        return

    if workflow.auth_type == WorkflowAuthType.jwt:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="JWT authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not await user_has_workflow_access(db, workflow, current_user.id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found",
            )
        return

    if workflow.auth_type == WorkflowAuthType.header_auth:
        if current_user is not None and await user_has_workflow_access(
            db, workflow, current_user.id
        ):
            return

        if not workflow.auth_header_key or not workflow.auth_header_value:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

        header_value = request.headers.get(workflow.auth_header_key)
        if header_value != workflow.auth_header_value:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing authentication header",
            )
        return


async def collect_referenced_workflows(
    db: AsyncSession,
    nodes: list[dict],
    collected: dict[str, dict] | None = None,
) -> dict[str, dict]:
    if collected is None:
        collected = {}

    for node in nodes:
        if node.get("type") == "execute":
            target_id = node.get("data", {}).get("executeWorkflowId", "")
            if target_id and target_id not in collected:
                try:
                    result = await db.execute(
                        select(Workflow).where(Workflow.id == uuid.UUID(target_id))
                    )
                    target_workflow = result.scalar_one_or_none()
                    if target_workflow and target_workflow.nodes:
                        input_fields = extract_input_fields_from_workflow(target_workflow)
                        collected[target_id] = {
                            "nodes": target_workflow.nodes,
                            "edges": target_workflow.edges,
                            "name": target_workflow.name or "",
                            "input_fields": [f.model_dump(by_alias=True) for f in input_fields],
                        }
                        await collect_referenced_workflows(db, target_workflow.nodes, collected)
                except Exception:
                    pass

        if node.get("type") == "agent":
            for target_id in node.get("data", {}).get("subWorkflowIds") or []:
                if target_id and target_id not in collected:
                    try:
                        result = await db.execute(
                            select(Workflow).where(Workflow.id == uuid.UUID(target_id))
                        )
                        target_workflow = result.scalar_one_or_none()
                        if target_workflow and target_workflow.nodes:
                            input_fields = extract_input_fields_from_workflow(target_workflow)
                            collected[target_id] = {
                                "nodes": target_workflow.nodes,
                                "edges": target_workflow.edges,
                                "name": target_workflow.name or "",
                                "input_fields": [f.model_dump(by_alias=True) for f in input_fields],
                            }
                            await collect_referenced_workflows(db, target_workflow.nodes, collected)
                    except Exception:
                        pass

    return collected


@router.get("/grist/columns")
async def get_grist_columns(
    doc_id: str,
    table_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.services.grist_pool import get_grist_client

    result = await db.execute(
        select(Credential)
        .where(Credential.type == CredentialType.grist)
        .where(Credential.owner_id == current_user.id)
        .limit(1)
    )
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(status_code=404, detail="Grist credential not found")

    try:
        config = decrypt_config(credential.encrypted_config)
        server_url = config.get("server_url", "").rstrip("/")
        api_key = config.get("api_key", "")

        if not server_url or not api_key:
            raise HTTPException(status_code=400, detail="Invalid Grist configuration")

        client = get_grist_client(server_url, api_key)
        response = client.get(f"/api/docs/{doc_id}/tables/{table_id}/columns")
        response.raise_for_status()

        data = response.json()
        columns = data.get("columns", [])

        formatted_columns = [
            {
                "id": str(col.get("id", "")),
                "name": col.get("fields", {}).get("label", ""),
                "type": col.get("fields", {}).get("type", col.get("type", "Text")),
            }
            for col in columns
        ]

        return JSONResponse({"columns": formatted_columns})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def parse_execute_body(request: Request) -> tuple[object, bool, str | None, bool]:
    raw_body: object = {}
    test_run = _coerce_bool(request.query_params.get("test_run"))
    trigger_source = str(request.query_params.get("trigger_source") or "").strip() or None
    simple_response = _coerce_bool(request.headers.get("x-simple-response", "true"), default=True)
    if not trigger_source:
        trigger_source = str(request.headers.get("x-trigger-source") or "").strip() or None
    try:
        body_bytes = await request.body()
        if body_bytes:
            raw_body = json.loads(body_bytes.decode("utf-8"))
            if isinstance(raw_body, dict):
                if "inputs" in raw_body:
                    test_run = _coerce_bool(raw_body.get("test_run", test_run))
                    body_trigger_source = str(raw_body.get("trigger_source") or "").strip()
                    if body_trigger_source:
                        trigger_source = body_trigger_source
                    raw_body = raw_body.get("inputs", {})
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return raw_body, test_run, trigger_source or "API", simple_response


@router.post("/{workflow_id}/execute", response_model=WorkflowExecuteResponse)
async def execute_workflow_endpoint(
    workflow_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks = None,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> WorkflowExecuteResponse:
    raw_body, test_run, trigger_source, simple_response = await parse_execute_body(request)

    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    await validate_workflow_auth(workflow, request, current_user, db)

    enriched_inputs = {
        "headers": _sanitize_headers(dict(request.headers)),
        "query": dict(request.query_params),
        "body": raw_body,
    }

    client_ip = get_client_ip(request)
    workflow_id_str = str(workflow.id)

    if not test_run:
        if (
            workflow.rate_limit_requests
            and workflow.rate_limit_window_seconds
            and workflow.rate_limit_requests > 0
            and workflow.rate_limit_window_seconds > 0
        ):
            is_allowed, remaining, retry_after = rate_limiter.is_allowed(
                workflow_id_str,
                client_ip,
                workflow.rate_limit_requests,
                workflow.rate_limit_window_seconds,
            )
            if not is_allowed:
                history_entry = ExecutionHistory(
                    workflow_id=workflow.id,
                    inputs=enriched_inputs,
                    outputs={"error": "Rate limit exceeded"},
                    node_results=[],
                    status="rate_limited",
                    execution_time_ms=0,
                    trigger_source=trigger_source,
                )
                db.add(history_entry)
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status="rate_limited",
                    execution_time_ms=0.0,
                )
                await db.commit()

                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={
                        "X-RateLimit-Limit": str(workflow.rate_limit_requests),
                        "X-RateLimit-Remaining": str(remaining),
                        "X-RateLimit-Reset": str(workflow.rate_limit_window_seconds),
                        "Retry-After": str(retry_after),
                    },
                )

        if workflow.cache_ttl_seconds and workflow.cache_ttl_seconds > 0:
            cache_hit, cached_response = response_cache.get(
                workflow_id_str, raw_body, dict(request.query_params)
            )
            if cache_hit:
                history_entry = ExecutionHistory(
                    workflow_id=workflow.id,
                    inputs=enriched_inputs,
                    outputs=cached_response["outputs"],
                    node_results=[],
                    status="cached",
                    execution_time_ms=0,
                    trigger_source=trigger_source,
                )
                db.add(history_entry)
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status="cached",
                    execution_time_ms=0.0,
                )
                await db.flush()

                if simple_response:
                    return JSONResponse(content=cached_response["outputs"])
                return WorkflowExecuteResponse(
                    workflow_id=workflow.id,
                    status="cached",
                    outputs=cached_response["outputs"],
                    execution_time_ms=0,
                    execution_history_id=history_entry.id,
                )

    if not workflow.nodes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workflow has no nodes",
        )

    workflow_cache = await collect_referenced_workflows(db, workflow.nodes)

    credentials_owner_id = current_user.id if current_user else workflow.owner_id
    credentials_context = await get_credentials_context(db, credentials_owner_id)
    trace_user_id = current_user.id if current_user else workflow.owner_id
    global_variables_context = await get_global_variables_context(db, credentials_owner_id)

    execution_id = uuid.uuid4()
    cancel_event = register_execution(workflow_id=workflow.id, execution_id=execution_id)
    try:
        execution_result = await asyncio.to_thread(
            execute_workflow,
            workflow_id=workflow.id,
            nodes=workflow.nodes,
            edges=workflow.edges,
            inputs=enriched_inputs,
            workflow_cache=workflow_cache,
            test_run=test_run,
            credentials_context=credentials_context,
            global_variables_context=global_variables_context,
            trace_user_id=trace_user_id,
            cancel_event=cancel_event,
        )
    except WorkflowCancelledError:
        if not test_run:
            history_entry = ExecutionHistory(
                workflow_id=workflow.id,
                inputs=enriched_inputs,
                outputs={},
                node_results=[],
                status="cancelled",
                execution_time_ms=0,
                trigger_source=trigger_source,
            )
            db.add(history_entry)
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                workflow_name_snapshot=workflow.name,
                status="cancelled",
                execution_time_ms=0.0,
            )
            # Commit before raising so get_db's rollback-on-exception doesn't discard the entry.
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Execution was cancelled",
        )
    finally:
        clear_active_execution(execution_id)

    if execution_result.status == "pending":
        history_entry, _ = await persist_pending_hitl_execution(
            db=db,
            workflow=workflow,
            enriched_inputs=enriched_inputs,
            execution_result=execution_result,
            trigger_source=trigger_source,
            credentials_owner_id=credentials_owner_id,
            trace_user_id=trace_user_id,
            public_base_url=build_public_base_url(request),
        )
        await upsert_workflow_analytics_snapshot(
            db,
            workflow_id=workflow.id,
            owner_id=workflow.owner_id,
            workflow_name_snapshot=workflow.name,
            status=execution_result.status,
            execution_time_ms=execution_result.execution_time_ms,
        )
        await db.flush()
        if simple_response:
            return JSONResponse(content=execution_result.outputs)
        return WorkflowExecuteResponse(
            workflow_id=execution_result.workflow_id,
            status=execution_result.status,
            outputs=execution_result.outputs,
            node_results=execution_result.node_results,
            execution_time_ms=execution_result.execution_time_ms,
            execution_history_id=history_entry.id,
        )

    if (
        workflow.cache_ttl_seconds
        and workflow.cache_ttl_seconds > 0
        and execution_result.status == "success"
    ):
        response_cache.set(
            workflow_id_str,
            raw_body,
            dict(request.query_params),
            {"outputs": execution_result.outputs},
            workflow.cache_ttl_seconds,
        )

    history_entry: ExecutionHistory | None = None
    if not test_run:
        history_entry = ExecutionHistory(
            workflow_id=workflow.id,
            inputs=enriched_inputs,
            outputs=execution_result.outputs,
            node_results=execution_result.node_results,
            status=execution_result.status,
            execution_time_ms=execution_result.execution_time_ms,
            trigger_source=trigger_source,
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
        await db.flush()
        if execution_result.allow_downstream_pending:
            if background_tasks is None:
                background_tasks = BackgroundTasks()
            background_tasks.add_task(
                _finalize_allow_downstream_history,
                history_entry_id=history_entry.id,
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                owner_id=workflow.owner_id,
                credentials_owner_id=credentials_owner_id,
                workflow_nodes=copy.deepcopy(workflow.nodes),
                workflow_cache=copy.deepcopy(workflow_cache),
                execution_result=execution_result,
            )
            if simple_response:
                await db.commit()
                return JSONResponse(
                    content=execution_result.outputs,
                    background=background_tasks,
                )
            await db.commit()
            return WorkflowExecuteResponse(
                workflow_id=execution_result.workflow_id,
                status=execution_result.status,
                outputs=execution_result.outputs,
                node_results=execution_result.node_results,
                execution_time_ms=execution_result.execution_time_ms,
                execution_history_id=history_entry.id,
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
        credentials_owner_id,
        workflow.nodes,
        workflow_cache,
        execution_result.node_results,
        execution_result.sub_workflow_executions,
    )
    await db.flush()

    if execution_result.status == "error":
        custom_status_code = None
        for node_result in execution_result.node_results:
            if (
                node_result.get("node_type") == "throwError"
                and node_result.get("status") == "error"
                and node_result.get("output", {}).get("httpStatusCode")
            ):
                custom_status_code = node_result["output"]["httpStatusCode"]
                break

        if custom_status_code:
            if simple_response:
                return JSONResponse(
                    status_code=custom_status_code, content=execution_result.outputs
                )
            payload: dict[str, object] = {
                "workflow_id": str(execution_result.workflow_id),
                "status": execution_result.status,
                "outputs": execution_result.outputs,
                "node_results": execution_result.node_results,
                "execution_time_ms": execution_result.execution_time_ms,
            }
            if history_entry is not None:
                payload["execution_history_id"] = str(history_entry.id)
            return JSONResponse(
                status_code=custom_status_code,
                content=payload,
            )

    if simple_response:
        return JSONResponse(content=execution_result.outputs)
    return WorkflowExecuteResponse(
        workflow_id=execution_result.workflow_id,
        status=execution_result.status,
        outputs=execution_result.outputs,
        node_results=execution_result.node_results,
        execution_time_ms=execution_result.execution_time_ms,
        execution_history_id=history_entry.id if history_entry is not None else None,
    )


@router.get(
    "/{workflow_id}/history/{entry_id}",
    response_model=ExecutionHistoryResponse,
)
async def get_workflow_execution_history_entry(
    workflow_id: uuid.UUID,
    entry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExecutionHistoryResponse:
    """Get full detail of a single workflow execution history entry."""
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )
    result = await db.execute(
        select(ExecutionHistory).where(
            ExecutionHistory.id == entry_id,
            ExecutionHistory.workflow_id == workflow_id,
        )
    )
    history = result.scalar_one_or_none()
    if history is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution history entry not found",
        )
    return ExecutionHistoryResponse.model_validate(history)


@router.get("/{workflow_id}/history/{entry_id}/stream")
async def stream_workflow_execution_history_entry(
    workflow_id: uuid.UUID,
    entry_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream changes for a single workflow execution history entry."""
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    initial_result = await db.execute(
        select(ExecutionHistory).where(
            ExecutionHistory.id == entry_id,
            ExecutionHistory.workflow_id == workflow_id,
        )
    )
    initial_history = initial_result.scalar_one_or_none()
    if initial_history is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution history entry not found",
        )

    async def event_generator():
        last_payload = ""
        heartbeat_tick = 0

        while True:
            if await request.is_disconnected():
                break

            async with async_session_maker() as stream_db:
                result = await stream_db.execute(
                    select(ExecutionHistory).where(
                        ExecutionHistory.id == entry_id,
                        ExecutionHistory.workflow_id == workflow_id,
                    )
                )
                history = result.scalar_one_or_none()

            if history is None:
                error_event = {
                    "type": "error",
                    "message": "Execution history entry not found",
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                break

            entry_payload = ExecutionHistoryResponse.model_validate(history).model_dump(mode="json")
            serialized_payload = json.dumps(entry_payload, sort_keys=True)
            if serialized_payload != last_payload:
                update_event = {"type": "history_update", "entry": entry_payload}
                yield f"data: {json.dumps(update_event)}\n\n"
                last_payload = serialized_payload
                heartbeat_tick = 0

                if history.status != "pending":
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break
            else:
                heartbeat_tick += 1
                if heartbeat_tick >= 15:
                    heartbeat_tick = 0
                    yield ": keepalive\n\n"

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{workflow_id}/history", response_model=HistoryListResponse)
async def get_execution_history(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    trigger_source: str | None = Query(default=None),
) -> HistoryListResponse:
    """List workflow execution history (lightweight, paginated)."""
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )
    total_query = (
        select(func.count())
        .select_from(ExecutionHistory)
        .where(ExecutionHistory.workflow_id == workflow_id)
    )
    if trigger_source:
        total_query = total_query.where(ExecutionHistory.trigger_source == trigger_source)
    if search:
        pattern = f"%{search}%"
        total_query = total_query.where(
            or_(
                ExecutionHistory.status.ilike(pattern),
                ExecutionHistory.trigger_source.ilike(pattern),
                cast(ExecutionHistory.inputs, String).ilike(pattern),
                cast(ExecutionHistory.outputs, String).ilike(pattern),
                cast(ExecutionHistory.node_results, String).ilike(pattern),
            )
        )
    total_result = await db.execute(total_query)
    total = total_result.scalar() or 0
    history_query = select(ExecutionHistory).where(ExecutionHistory.workflow_id == workflow_id)
    if trigger_source:
        history_query = history_query.where(ExecutionHistory.trigger_source == trigger_source)
    if search:
        pattern = f"%{search}%"
        history_query = history_query.where(
            or_(
                ExecutionHistory.status.ilike(pattern),
                ExecutionHistory.trigger_source.ilike(pattern),
                cast(ExecutionHistory.inputs, String).ilike(pattern),
                cast(ExecutionHistory.outputs, String).ilike(pattern),
                cast(ExecutionHistory.node_results, String).ilike(pattern),
            )
        )
    history_result = await db.execute(
        history_query.order_by(ExecutionHistory.started_at.desc()).limit(limit).offset(offset)
    )
    history = history_result.scalars().all()
    items = [
        ExecutionHistoryListResponse(
            id=h.id,
            workflow_id=h.workflow_id,
            workflow_name=workflow.name,
            run_type="workflow",
            started_at=h.started_at,
            status=h.status,
            execution_time_ms=h.execution_time_ms,
            trigger_source=h.trigger_source,
        )
        for h in history
    ]
    return HistoryListResponse(total=total, items=items)


@router.delete("/{workflow_id}/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_execution_history(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    await db.execute(
        ExecutionHistory.__table__.delete().where(ExecutionHistory.workflow_id == workflow_id)
    )


@router.post("/{workflow_id}/execute/stream")
async def execute_workflow_stream(
    workflow_id: uuid.UUID,
    request: Request,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    raw_body, test_run, trigger_source, simple_response = await parse_execute_body(request)

    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    await validate_workflow_auth(workflow, request, current_user, db)

    if not workflow.sse_enabled and trigger_source not in _INTERNAL_STREAM_TRIGGER_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSE streaming is disabled for this workflow",
        )

    enriched_inputs = {
        "headers": _sanitize_headers(dict(request.headers)),
        "query": dict(request.query_params),
        "body": raw_body,
    }

    client_ip = get_client_ip(request)
    workflow_id_str = str(workflow.id)

    if not test_run:
        if (
            workflow.rate_limit_requests
            and workflow.rate_limit_window_seconds
            and workflow.rate_limit_requests > 0
            and workflow.rate_limit_window_seconds > 0
        ):
            is_allowed, remaining, retry_after = rate_limiter.is_allowed(
                workflow_id_str,
                client_ip,
                workflow.rate_limit_requests,
                workflow.rate_limit_window_seconds,
            )
            if not is_allowed:
                history_entry = ExecutionHistory(
                    workflow_id=workflow.id,
                    inputs=enriched_inputs,
                    outputs={"error": "Rate limit exceeded"},
                    node_results=[],
                    status="rate_limited",
                    execution_time_ms=0,
                )
                db.add(history_entry)
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status="rate_limited",
                    execution_time_ms=0.0,
                )
                await db.commit()

                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={
                        "X-RateLimit-Limit": str(workflow.rate_limit_requests),
                        "X-RateLimit-Remaining": str(remaining),
                        "X-RateLimit-Reset": str(workflow.rate_limit_window_seconds),
                        "Retry-After": str(retry_after),
                    },
                )

        if workflow.cache_ttl_seconds and workflow.cache_ttl_seconds > 0:
            cache_hit, cached_response = response_cache.get(
                workflow_id_str, raw_body, dict(request.query_params)
            )
            if cache_hit:
                history_entry = ExecutionHistory(
                    workflow_id=workflow.id,
                    inputs=enriched_inputs,
                    outputs=cached_response["outputs"],
                    node_results=[],
                    status="cached",
                    execution_time_ms=0,
                    trigger_source=trigger_source,
                )
                db.add(history_entry)
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status="cached",
                    execution_time_ms=0.0,
                )
                await db.flush()

                async def cached_event_generator():
                    event_data = (
                        {"outputs": cached_response["outputs"]}
                        if simple_response
                        else {
                            "type": "execution_complete",
                            "status": "cached",
                            "outputs": cached_response["outputs"],
                            "execution_time_ms": 0,
                        }
                    )
                    yield f"data: {json.dumps(event_data)}\n\n"

                return StreamingResponse(
                    cached_event_generator(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache, no-transform",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )

    if not workflow.nodes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workflow has no nodes",
        )

    workflow_cache = await collect_referenced_workflows(db, workflow.nodes)

    credentials_owner_id = current_user.id if current_user else workflow.owner_id
    credentials_context = await get_credentials_context(db, credentials_owner_id)
    trace_user_id = current_user.id if current_user else workflow.owner_id
    global_variables_context = await get_global_variables_context(db, credentials_owner_id)
    public_base_url = build_public_base_url(request)

    import asyncio
    import queue
    from concurrent.futures import ThreadPoolExecutor

    execution_id = uuid.uuid4()
    cancel_event = register_execution(workflow_id=workflow.id, execution_id=execution_id)
    event_queue: queue.Queue = queue.Queue()
    final_result: dict = {}
    executor_holder: dict = {}
    was_cancelled: bool = False

    def run_executor():
        nonlocal final_result, was_cancelled
        try:
            for event in execute_workflow_streaming(
                workflow_id=workflow.id,
                nodes=workflow.nodes,
                edges=workflow.edges,
                inputs=enriched_inputs,
                workflow_cache=workflow_cache,
                test_run=test_run,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=trace_user_id,
                cancel_event=cancel_event,
                executor_holder=executor_holder,
                sse_node_config=workflow.sse_node_config or {},
                public_base_url=public_base_url,
            ):
                event_queue.put(event)
                if event.get("type") == "execution_complete":
                    final_result = event
            # Drain executeDoNotWait background sub-workflows AFTER execution_complete
            # has been put on the queue (client already got the response).
            wf_exec = executor_holder.get("executor")
            if wf_exec is not None:
                wf_exec.drain_bg_futures()
                extra = _serialize_sub_workflow_executions(wf_exec.sub_workflow_executions)
                if extra and final_result:
                    existing = final_result.get("sub_workflow_executions") or []
                    seen = {s.get("workflow_id") for s in existing}
                    final_result["sub_workflow_executions"] = existing + [
                        s for s in extra if s.get("workflow_id") not in seen
                    ]
        except WorkflowCancelledError:
            was_cancelled = True
            return
        finally:
            event_queue.put(None)
            clear_active_execution(execution_id)

    async def event_generator():
        nonlocal final_result, was_cancelled
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
                            trigger_source=trigger_source,
                            credentials_owner_id=credentials_owner_id,
                            trace_user_id=trace_user_id,
                            public_base_url=public_base_url,
                        )
                        await upsert_workflow_analytics_snapshot(
                            db,
                            workflow_id=workflow.id,
                            owner_id=workflow.owner_id,
                            workflow_name_snapshot=workflow.name,
                            status="pending",
                            execution_time_ms=pending_result.execution_time_ms,
                        )
                        event["outputs"] = pending_result.outputs
                        event["node_results"] = pending_result.node_results
                        event["execution_history_id"] = str(history_entry.id)
                        final_result = event
                    sanitized_event = {
                        key: value for key, value in event.items() if not key.startswith("_")
                    }
                    if simple_response and sanitized_event.get("type") == "execution_complete":
                        sanitized_event = {"outputs": sanitized_event.get("outputs", {})}
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
                                    trigger_source=trigger_source,
                                    credentials_owner_id=credentials_owner_id,
                                    trace_user_id=trace_user_id,
                                    public_base_url=public_base_url,
                                )
                                await upsert_workflow_analytics_snapshot(
                                    db,
                                    workflow_id=workflow.id,
                                    owner_id=workflow.owner_id,
                                    workflow_name_snapshot=workflow.name,
                                    status="pending",
                                    execution_time_ms=pending_result.execution_time_ms,
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
                            if (
                                simple_response
                                and sanitized_event.get("type") == "execution_complete"
                            ):
                                sanitized_event = {"outputs": sanitized_event.get("outputs", {})}
                            yield f"data: {json.dumps(sanitized_event)}\n\n"
                        break
                    await asyncio.sleep(0.001)
                except Exception:
                    cancel_event.set()
                    break

            if was_cancelled:
                cancelled_entry = ExecutionHistory(
                    workflow_id=workflow.id,
                    inputs=enriched_inputs,
                    outputs={},
                    node_results=[],
                    status="cancelled",
                    execution_time_ms=0,
                    trigger_source=trigger_source,
                )
                db.add(cancelled_entry)
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status="cancelled",
                    execution_time_ms=0.0,
                )
                await db.flush()
            elif final_result and final_result.get("status") != "pending":
                if (
                    workflow.cache_ttl_seconds
                    and workflow.cache_ttl_seconds > 0
                    and final_result.get("status") == "success"
                ):
                    response_cache.set(
                        workflow_id_str,
                        raw_body,
                        dict(request.query_params),
                        {"outputs": final_result.get("outputs", {})},
                        workflow.cache_ttl_seconds,
                    )

                if final_result.get("status") == "success":
                    _persist_playwright_save_steps(
                        workflow, final_result.get("node_results", []), db
                    )

                await _persist_global_variables_from_execution(
                    db,
                    credentials_owner_id,
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
                    trigger_source=trigger_source,
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


@router.post("/{workflow_id}/executions/{execution_id}/cancel")
async def cancel_workflow_execution(
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    cancelled = cancel_active_execution(workflow_id=workflow_id, execution_id=execution_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found or already finished",
        )

    return {"status": "cancel_requested"}
