import asyncio
import copy
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import DashboardWidget, ExecutionHistory, User, Workflow
from app.db.session import async_session_maker
from app.models.dashboard_schemas import WidgetDataResponse
from app.services.dashboard_widget_policy import dashboard_widget_blocked_nodes_error
from app.services.highlight.highlight_builder import build_highlight_payload
from app.services.workflow_executor import _to_json_compatible, execute_workflow

logger = logging.getLogger(__name__)

_CHART_PAYLOAD_TYPES = frozenset(
    (
        "pie",
        "bar",
        "line",
        "area",
        "table",
        "numeric",
        "gauge",
        "scatter",
        "proportion",
        "barGauge",
        "text",
    )
)


async def _record_widget_execution(
    db: AsyncSession, workflow: Workflow, result
) -> ExecutionHistory | None:
    """Record an execution-history row + analytics snapshot for a widget run.

    Mirrors the workflow execute endpoint so a widget that actually runs (cache miss)
    increases the history of both the widget and its underlying workflow.
    """
    from app.api.analytics import upsert_workflow_analytics_snapshot

    try:
        history_entry = ExecutionHistory(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            inputs={},
            outputs=result.outputs,
            node_results=result.node_results,
            status=result.status,
            execution_time_ms=result.execution_time_ms,
            trigger_source="dashboard",
        )
        db.add(history_entry)
        await upsert_workflow_analytics_snapshot(
            db,
            workflow_id=workflow.id,
            owner_id=workflow.owner_id,
            workflow_name_snapshot=workflow.name,
            status=result.status,
            execution_time_ms=result.execution_time_ms,
        )
        return history_entry
    except Exception:  # history is best-effort; never break widget rendering
        logger.debug("Failed to record widget execution history", exc_info=True)
        return None


def _version_token(workflow: Workflow) -> str:
    return workflow.updated_at.isoformat() if workflow.updated_at else ""


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _highlight_rows(result: Any) -> list[dict]:
    """Normalize a run's node_results to plain dicts for the highlight builder."""
    rows = getattr(result, "node_results", []) or []
    normalized: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            normalized.append(row)
        else:
            normalized.append(
                {
                    "node_id": _field(row, "node_id"),
                    "node_label": _field(row, "node_label"),
                    "node_type": _field(row, "node_type"),
                    "output": _field(row, "output"),
                    "metadata": _field(row, "metadata"),
                }
            )
    return normalized


def _is_chart_payload(value: Any) -> bool:
    return isinstance(value, dict) and value.get("type") in _CHART_PAYLOAD_TYPES


def _unwrap_chart_payload(value: Any) -> dict | None:
    if _is_chart_payload(value):
        return value
    if not isinstance(value, dict):
        return None

    nested_payloads = [nested for nested in value.values() if _is_chart_payload(nested)]
    return nested_payloads[0] if len(nested_payloads) == 1 else None


def _extract_chart_payload(result: Any) -> dict | None:
    final_payload = _unwrap_chart_payload(getattr(result, "outputs", None))
    for nr in getattr(result, "node_results", []) or []:
        node_type = _field(nr, "node_type")
        if node_type == "chartOutput":
            return _unwrap_chart_payload(_field(nr, "output")) or final_payload
    return final_payload


async def _load_widget_execution_context(
    db: AsyncSession, workflow: Workflow, user: User
) -> tuple[dict[str, dict], dict[str, str], dict[str, object]]:
    from app.api.workflows import collect_referenced_workflows, get_credentials_context
    from app.services.global_variables_service import get_global_variables_context

    workflow_cache = await collect_referenced_workflows(
        db, workflow.nodes or [], actor_user_id=user.id
    )
    credentials_context = await get_credentials_context(db, user.id)
    global_variables_context = await get_global_variables_context(db, user.id)
    return workflow_cache, credentials_context, global_variables_context


async def _persist_widget_global_variables(
    db: AsyncSession,
    owner_id: uuid.UUID,
    workflow_nodes: list[dict],
    workflow_cache: dict[str, dict],
    result: Any,
) -> None:
    from app.api.workflows import _persist_global_variables_from_execution

    sub_workflow_executions = getattr(result, "sub_workflow_executions", None)
    if not isinstance(sub_workflow_executions, list):
        sub_workflow_executions = []

    await _persist_global_variables_from_execution(
        db,
        owner_id,
        workflow_nodes,
        workflow_cache,
        getattr(result, "node_results", []) or [],
        sub_workflow_executions,
    )


async def _finalize_widget_allow_downstream(
    *,
    history_entry_id: uuid.UUID | None,
    workflow_id: uuid.UUID,
    workflow_name: str,
    owner_id: uuid.UUID,
    workflow_nodes: list[dict],
    workflow_cache: dict[str, dict],
    result: Any,
) -> None:
    try:
        await asyncio.to_thread(result.join_allow_downstream)
        async with async_session_maker() as bg_db:
            if history_entry_id is not None:
                history_result = await bg_db.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_entry_id)
                )
                history_entry = history_result.scalar_one_or_none()
                if history_entry is not None:
                    history_entry.outputs = _to_json_compatible(result.outputs)
                    history_entry.node_results = _to_json_compatible(result.node_results)
                    history_entry.status = result.status
                    history_entry.execution_time_ms = result.execution_time_ms
                    flag_modified(history_entry, "outputs")
                    flag_modified(history_entry, "node_results")

            await _persist_widget_global_variables(
                bg_db, owner_id, workflow_nodes, workflow_cache, result
            )

            from app.api.analytics import upsert_workflow_analytics_snapshot

            await upsert_workflow_analytics_snapshot(
                bg_db,
                workflow_id=workflow_id,
                owner_id=owner_id,
                workflow_name_snapshot=workflow_name,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
            )
            await bg_db.commit()
    except Exception:
        logger.debug("Failed to finalize dashboard widget background branch", exc_info=True)


async def compute_widget_data(
    db: AsyncSession, widget: DashboardWidget, user: User, force: bool = False
) -> WidgetDataResponse:
    wf_result = await db.execute(select(Workflow).where(Workflow.id == widget.workflow_id))
    workflow = wf_result.scalar_one_or_none()
    if workflow is None:
        return WidgetDataResponse(
            widget_id=widget.id,
            payload=None,
            cached=False,
            computed_at=None,
            error="Widget workflow not found",
        )

    blocked_error = dashboard_widget_blocked_nodes_error(workflow.nodes)
    if blocked_error is not None:
        return WidgetDataResponse(
            widget_id=widget.id,
            payload=None,
            cached=False,
            computed_at=None,
            error=blocked_error,
        )

    version = _version_token(workflow)
    now = datetime.now(timezone.utc)
    fresh = (
        not force
        and widget.cached_payload is not None
        and widget.cached_at is not None
        and widget.cached_workflow_version == version
        and (now - widget.cached_at).total_seconds() < widget.cache_ttl_seconds
    )
    if fresh:
        return WidgetDataResponse(
            widget_id=widget.id,
            payload=widget.cached_payload,
            cached=True,
            computed_at=widget.cached_at,
        )

    nodes = workflow.nodes or []
    edges = workflow.edges or []

    try:
        (
            workflow_cache,
            credentials_context,
            global_variables_context,
        ) = await _load_widget_execution_context(db, workflow, user)
        result = await asyncio.to_thread(
            execute_workflow,
            workflow_id=workflow.id,
            nodes=nodes,
            edges=edges,
            inputs={},
            workflow_cache=workflow_cache,
            test_run=False,
            credentials_context=credentials_context,
            global_variables_context=global_variables_context,
            trace_user_id=user.id,
            actor_user_id=user.id,
            return_on_chart_output=True,
        )
    except Exception as exc:  # surface execution errors to the widget, never 500 the dashboard
        return WidgetDataResponse(
            widget_id=widget.id, payload=None, cached=False, computed_at=None, error=str(exc)
        )

    payload = _extract_chart_payload(result)
    history_entry = await _record_widget_execution(db, workflow, result)

    background_finalize = bool(getattr(result, "allow_downstream_pending", False))
    if not background_finalize:
        await _persist_widget_global_variables(db, user.id, nodes, workflow_cache, result)

    widget.cached_payload = payload
    widget.cached_at = now
    widget.cached_workflow_version = version
    await db.commit()

    if background_finalize:
        asyncio.create_task(
            _finalize_widget_allow_downstream(
                history_entry_id=history_entry.id if history_entry is not None else None,
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                owner_id=user.id,
                workflow_nodes=copy.deepcopy(nodes),
                workflow_cache=copy.deepcopy(workflow_cache),
                result=result,
            )
        )

    return WidgetDataResponse(
        widget_id=widget.id,
        payload=payload,
        cached=False,
        computed_at=now,
        error=None if payload is not None else "Workflow produced no chartOutput",
        highlight=build_highlight_payload(_highlight_rows(result), nodes, None),
    )
