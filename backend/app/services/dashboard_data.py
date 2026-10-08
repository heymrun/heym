import asyncio
import copy
import logging
import uuid
from concurrent.futures import CancelledError
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import DashboardWidget, DashboardWidgetRecordCache, ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.models.dashboard_schemas import WidgetDataResponse
from app.services.cluster.dispatch import dispatch_workflow
from app.services.dashboard_widget_policy import dashboard_widget_blocked_nodes_error
from app.services.highlight.highlight_builder import build_highlight_payload
from app.services.page_params import page_inputs
from app.services.workflow_executor import (
    WorkflowCancelledError,
    WorkflowTimeoutError,
    _to_json_compatible,
)

logger = logging.getLogger(__name__)

# Detail-page records cached per widget; the oldest beyond this are dropped on write.
RECORD_CACHE_LIMIT = 50

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
        "hitl",
    )
)


def _is_hitl_chart_workflow(nodes: list[dict[str, Any]] | None) -> bool:
    """True when the widget's terminal chart is the pending-review inbox."""
    for node in nodes or []:
        if not isinstance(node, dict) or node.get("type") != "chartOutput":
            continue
        data = node.get("data")
        if isinstance(data, dict) and data.get("chartType") == "hitl":
            return True
    return False


async def _record_widget_execution(
    db: AsyncSession, workflow: Workflow, result, inputs: dict[str, Any]
) -> ExecutionHistory | None:
    """Record an execution-history row + analytics snapshot for a widget run.

    Mirrors the workflow execute endpoint so a widget that actually runs (cache miss)
    increases the history of both the widget and its underlying workflow.
    """
    from app.api.analytics import upsert_workflow_analytics_snapshot
    from app.services.hitl_service import build_default_public_base_url
    from app.services.pending_execution import (
        needs_local_pending_persist,
        persist_pending_execution,
    )

    try:
        if needs_local_pending_persist(result):
            paused_entry, _ = await persist_pending_execution(
                db=db,
                workflow=workflow,
                enriched_inputs=inputs,
                execution_result=result,
                trigger_source="dashboard",
                credentials_owner_id=workflow.owner_id,
                trace_user_id=workflow.owner_id,
                public_base_url=build_default_public_base_url(),
            )
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                workflow_name_snapshot=workflow.name,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
                started_at=getattr(paused_entry, "started_at", None),
            )
            return paused_entry

        history_entry = ExecutionHistory(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            inputs=inputs,
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


async def _load_record_cache(
    db: AsyncSession, widget_id: uuid.UUID, record: str
) -> DashboardWidgetRecordCache | None:
    result = await db.execute(
        select(DashboardWidgetRecordCache).where(
            DashboardWidgetRecordCache.widget_id == widget_id,
            DashboardWidgetRecordCache.record == record,
        )
    )
    return result.scalar_one_or_none()


async def store_record_cache(
    db: AsyncSession,
    widget_id: uuid.UUID,
    record: str,
    payload: dict | None,
    cached_at: datetime,
    version: str,
) -> None:
    """Upsert one record's chart, then keep only the newest records for the widget.

    Two viewers opening the same record at once both write; the upsert lets the
    later one win instead of failing on the unique constraint.
    """
    statement = pg_insert(DashboardWidgetRecordCache).values(
        id=uuid.uuid4(),
        widget_id=widget_id,
        record=record,
        payload=payload,
        cached_at=cached_at,
        cached_workflow_version=version,
    )
    await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_dashboard_widget_record_cache",
            set_={
                "payload": statement.excluded.payload,
                "cached_at": statement.excluded.cached_at,
                "cached_workflow_version": statement.excluded.cached_workflow_version,
            },
        )
    )
    newest = (
        select(DashboardWidgetRecordCache.id)
        .where(DashboardWidgetRecordCache.widget_id == widget_id)
        .order_by(DashboardWidgetRecordCache.cached_at.desc())
        .limit(RECORD_CACHE_LIMIT)
    )
    await db.execute(
        delete(DashboardWidgetRecordCache).where(
            DashboardWidgetRecordCache.widget_id == widget_id,
            DashboardWidgetRecordCache.id.not_in(newest),
        )
    )


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
    db: AsyncSession, workflow: Workflow, run_as_user_id: uuid.UUID
) -> tuple[dict[str, dict], dict[str, str], dict[str, object]]:
    from app.api.workflows import collect_referenced_workflows, get_credentials_context
    from app.services.global_variables_service import get_global_variables_context

    workflow_cache = await collect_referenced_workflows(
        db, workflow.nodes or [], actor_user_id=run_as_user_id
    )
    credentials_context = await get_credentials_context(db, run_as_user_id)
    global_variables_context = await get_global_variables_context(db, run_as_user_id)
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
        try:
            await asyncio.to_thread(result.join_allow_downstream)
        except WorkflowTimeoutError as exc:
            logger.warning("Dashboard widget run allowDownstream timed out: %s", exc)
            result.status = "error"
            if hasattr(result, "outputs") and isinstance(result.outputs, dict):
                result.outputs.setdefault("error", str(exc) or "Workflow execution timed out")
        except (WorkflowCancelledError, CancelledError, asyncio.CancelledError):
            logger.info("Dashboard widget run allowDownstream cancelled")
            result.status = "cancelled"
        except Exception as exc:
            logger.exception("Dashboard widget run allowDownstream failed unexpectedly")
            result.status = "error"
            if hasattr(result, "outputs") and isinstance(result.outputs, dict):
                result.outputs.setdefault("error", str(exc))
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
    db: AsyncSession,
    widget: DashboardWidget,
    run_as_user_id: uuid.UUID,
    force: bool = False,
    record: str | None = None,
) -> WidgetDataResponse:
    """Serve the widget's cached chart, or run its workflow as ``run_as_user_id``.

    Callers pass the dashboard owner, whoever is viewing: the cache is shared by
    every viewer, so the run behind it must not depend on who asked. ``record`` is a
    detail page's ``?record=`` value, already checked against the dashboard's record
    format; the workflow reads it as ``$page.record`` and its chart is cached per record.
    """
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

    # Pending reviews belong to whoever is signed in, and the widget cache is shared
    # with every dashboard viewer. Return only the chart marker. The inbox is loaded
    # separately and never written into cached_payload.
    if _is_hitl_chart_workflow(workflow.nodes):
        return WidgetDataResponse(
            widget_id=widget.id,
            payload={"type": "hitl"},
            cached=False,
            computed_at=datetime.now(timezone.utc),
        )

    version = _version_token(workflow)
    now = datetime.now(timezone.utc)
    cache = widget if record is None else await _load_record_cache(db, widget.id, record)
    cached_payload = None
    cached_at = None
    if cache is not None:
        cached_payload = cache.cached_payload if record is None else cache.payload
        cached_at = cache.cached_at
    fresh = (
        not force
        and cache is not None
        and cached_payload is not None
        and cached_at is not None
        and cache.cached_workflow_version == version
        and (now - cached_at).total_seconds() < widget.cache_ttl_seconds
    )
    if fresh:
        return WidgetDataResponse(
            widget_id=widget.id,
            payload=cached_payload,
            cached=True,
            computed_at=cached_at,
        )

    nodes = workflow.nodes or []
    edges = workflow.edges or []
    inputs = page_inputs(record)

    try:
        (
            workflow_cache,
            credentials_context,
            global_variables_context,
        ) = await _load_widget_execution_context(db, workflow, run_as_user_id)
        result = await dispatch_workflow(
            workflow_id=workflow.id,
            nodes=nodes,
            edges=edges,
            inputs=inputs,
            workflow_cache=workflow_cache,
            test_run=False,
            trigger_source="dashboard",
            credentials_owner_id=run_as_user_id,
            run_in_thread=True,
            credentials_context=credentials_context,
            global_variables_context=global_variables_context,
            trace_user_id=run_as_user_id,
            actor_user_id=run_as_user_id,
            return_on_chart_output=True,
        )
    except Exception as exc:  # surface execution errors to the widget, never 500 the dashboard
        return WidgetDataResponse(
            widget_id=widget.id, payload=None, cached=False, computed_at=None, error=str(exc)
        )

    payload = _extract_chart_payload(result)
    history_entry = (
        None
        if getattr(result, "history_written", False) is True
        else await _record_widget_execution(db, workflow, result, inputs)
    )

    background_finalize = bool(getattr(result, "allow_downstream_pending", False))
    if not background_finalize and result.status != "pending":
        await _persist_widget_global_variables(db, run_as_user_id, nodes, workflow_cache, result)

    if record is None:
        widget.cached_payload = payload
        widget.cached_at = now
        widget.cached_workflow_version = version
    else:
        await store_record_cache(db, widget.id, record, payload, now, version)
    await db.commit()

    if background_finalize:
        asyncio.create_task(
            _finalize_widget_allow_downstream(
                history_entry_id=history_entry.id if history_entry is not None else None,
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                owner_id=run_as_user_id,
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


async def run_widget_workflow(
    db: AsyncSession,
    workflow: Workflow,
    run_as_user_id: uuid.UUID,
    inputs: dict[str, Any],
) -> tuple[Any, ExecutionHistory | None]:
    """Run an ordinary workflow from a run widget, as the dashboard owner, and record the run.

    ``inputs`` are the execute endpoint's shape (``headers``, ``query``, ``body``); a start
    node reads the run widget's field values from ``body``.
    """
    nodes = workflow.nodes or []
    (
        workflow_cache,
        credentials_context,
        global_variables_context,
    ) = await _load_widget_execution_context(db, workflow, run_as_user_id)
    result = await dispatch_workflow(
        workflow_id=workflow.id,
        nodes=nodes,
        edges=workflow.edges or [],
        inputs=inputs,
        workflow_cache=workflow_cache,
        test_run=False,
        trigger_source="dashboard",
        credentials_owner_id=run_as_user_id,
        run_in_thread=True,
        credentials_context=credentials_context,
        global_variables_context=global_variables_context,
        trace_user_id=run_as_user_id,
        actor_user_id=run_as_user_id,
    )
    history_entry = (
        None
        if getattr(result, "history_written", False) is True
        else await _record_widget_execution(db, workflow, result, inputs)
    )
    background_finalize = bool(getattr(result, "allow_downstream_pending", False))
    if not background_finalize and result.status != "pending":
        await _persist_widget_global_variables(db, run_as_user_id, nodes, workflow_cache, result)
    await db.commit()
    if background_finalize:
        asyncio.create_task(
            _finalize_widget_allow_downstream(
                history_entry_id=history_entry.id if history_entry is not None else None,
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                owner_id=run_as_user_id,
                workflow_nodes=copy.deepcopy(nodes),
                workflow_cache=copy.deepcopy(workflow_cache),
                result=result,
            )
        )
    return result, history_entry
