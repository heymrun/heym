"""Per-workflow run history for the dashboard chat (and therefore `heym_chat` over MCP).

The `get_workflow_run_history` chat tool works in two steps so the model never has
to read a pile of run payloads just to answer "how many times did this run?":

1. With only a `workflow_id` it returns metadata: total runs, a per-status
   breakdown, first/last run time, average duration, and a page of lightweight run
   rows (id, status, start time, duration, trigger).
2. With an `execution_id` taken from that list it returns the detail of that one
   run: inputs, outputs, and a compacted per-node trace.

All filtering happens in SQL, scoped to one workflow the caller can reach. Nothing
is fetched and then searched in Python.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExecutionHistory
from app.services.workflow_access import get_accessible_workflow

DEFAULT_RUN_LIMIT = 20
MAX_RUN_LIMIT = 50

_TIME_RANGE_HOURS: dict[str, int | None] = {
    "1h": 1,
    "3h": 3,
    "6h": 6,
    "24h": 24,
    "7d": 168,
    "30d": 720,
    "all": None,
}

# The chat layer replaces any tool result over ~96k characters with a short summary,
# so the detail view stays well below that: 40 nodes * ~1.2k + inputs/outputs.
_MAX_DETAIL_NODES = 40
_MAX_INPUTS_CHARS = 4000
_MAX_OUTPUTS_CHARS = 6000
_MAX_NODE_OUTPUT_CHARS = 1200
_MAX_ERROR_CHARS = 1000


def _iso(value: datetime | None) -> str | None:
    """Return an ISO-8601 string in UTC, treating naive datetimes as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _compact(value: Any, max_chars: int) -> Any:
    """Return `value` unchanged when small, else a bounded JSON preview of it."""
    try:
        dumped = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        dumped = str(value)
    if len(dumped) <= max_chars:
        return value
    return {"truncated": True, "original_length": len(dumped), "preview": dumped[:max_chars]}


def _clip(text: str | None, max_chars: int) -> str | None:
    if text is None:
        return None
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def _clamp_limit(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return DEFAULT_RUN_LIMIT
    return max(1, min(raw, MAX_RUN_LIMIT))


def _clamp_offset(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return 0
    return raw


def _parse_uuid(raw: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def _node_row(node_result: Any) -> dict[str, Any]:
    if not isinstance(node_result, dict):
        return {"output": _compact(node_result, _MAX_NODE_OUTPUT_CHARS)}
    return {
        "node_id": node_result.get("node_id"),
        "node_label": node_result.get("node_label"),
        "node_type": node_result.get("node_type"),
        "status": node_result.get("status"),
        "execution_time_ms": node_result.get("execution_time_ms"),
        "error": _clip(node_result.get("error"), _MAX_ERROR_CHARS),
        "output": _compact(node_result.get("output"), _MAX_NODE_OUTPUT_CHARS),
    }


async def _load_run_detail(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    workflow_name: str,
    execution_id: uuid.UUID,
) -> dict[str, Any]:
    result = await db.execute(
        select(ExecutionHistory).where(
            ExecutionHistory.id == execution_id,
            ExecutionHistory.workflow_id == workflow_id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "Execution not found for this workflow"}

    node_results = run.node_results if isinstance(run.node_results, list) else []
    nodes = [_node_row(item) for item in node_results[:_MAX_DETAIL_NODES]]
    return {
        "workflow_id": str(workflow_id),
        "workflow_name": workflow_name,
        "execution_id": str(run.id),
        "status": run.status,
        "started_at": _iso(run.started_at),
        "execution_time_ms": run.execution_time_ms or 0,
        "trigger_source": run.trigger_source or "",
        "recovered": bool(run.recovered),
        "inputs": _compact(run.inputs or {}, _MAX_INPUTS_CHARS),
        "outputs": _compact(run.outputs or {}, _MAX_OUTPUTS_CHARS),
        "node_count": len(node_results),
        "nodes": nodes,
        "nodes_truncated": len(node_results) > _MAX_DETAIL_NODES,
    }


async def _load_run_metadata(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    workflow_name: str,
    time_range: str,
    status_filter: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    hours = _TIME_RANGE_HOURS[time_range]
    scope = [ExecutionHistory.workflow_id == workflow_id]
    if hours is not None:
        scope.append(
            ExecutionHistory.started_at >= datetime.now(timezone.utc) - timedelta(hours=hours)
        )

    stats_rows = (
        await db.execute(
            select(
                ExecutionHistory.status,
                func.count(),
                func.min(ExecutionHistory.started_at),
                func.max(ExecutionHistory.started_at),
                func.sum(ExecutionHistory.execution_time_ms),
            )
            .where(*scope)
            .group_by(ExecutionHistory.status)
        )
    ).all()

    status_counts: dict[str, int] = {}
    first_run: datetime | None = None
    last_run: datetime | None = None
    total_runs = 0
    total_time_ms = 0.0
    for row_status, count, first_at, last_at, time_sum in stats_rows:
        status_counts[row_status] = int(count)
        total_runs += int(count)
        total_time_ms += float(time_sum or 0.0)
        if first_at is not None and (first_run is None or first_at < first_run):
            first_run = first_at
        if last_at is not None and (last_run is None or last_at > last_run):
            last_run = last_at

    runs_query = select(ExecutionHistory).where(*scope)
    if status_filter:
        runs_query = runs_query.where(ExecutionHistory.status == status_filter)
    run_rows = (
        (
            await db.execute(
                runs_query.order_by(ExecutionHistory.started_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )

    matching_runs = status_counts.get(status_filter, 0) if status_filter else total_runs
    latest = (
        await db.execute(
            select(ExecutionHistory.id, ExecutionHistory.status, ExecutionHistory.started_at)
            .where(*scope)
            .order_by(ExecutionHistory.started_at.desc())
            .limit(1)
        )
    ).first()

    return {
        "workflow_id": str(workflow_id),
        "workflow_name": workflow_name,
        "time_range": time_range,
        "total_runs": total_runs,
        "status_counts": status_counts,
        "first_run_at": _iso(first_run),
        "last_run_at": _iso(last_run),
        "last_run": (
            {
                "execution_id": str(latest[0]),
                "status": latest[1],
                "started_at": _iso(latest[2]),
            }
            if latest is not None
            else None
        ),
        "avg_execution_time_ms": round(total_time_ms / total_runs, 2) if total_runs else 0,
        "status_filter": status_filter,
        "matching_runs": matching_runs,
        "offset": offset,
        "returned": len(run_rows),
        "has_more": offset + len(run_rows) < matching_runs,
        "runs": [
            {
                "execution_id": str(run.id),
                "status": run.status,
                "started_at": _iso(run.started_at),
                "execution_time_ms": run.execution_time_ms or 0,
                "trigger_source": run.trigger_source or "",
            }
            for run in run_rows
        ],
        "hint": "Pass execution_id from runs to get inputs, outputs and the per-node trace.",
    }


async def get_workflow_run_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Return run history metadata for one workflow, or the detail of a single run.

    Without `execution_id`: metadata plus a page of run rows. With `execution_id`:
    that run's inputs, outputs and per-node trace. Errors come back as `{"error": ...}`
    so the chat loop can show them like any other tool failure.
    """
    workflow_id = _parse_uuid(args.get("workflow_id"))
    if workflow_id is None:
        return {"error": "Invalid workflow_id"}

    workflow = await get_accessible_workflow(db, workflow_id, user_id)
    if workflow is None:
        return {"error": "Workflow not found or no access"}

    raw_execution_id = args.get("execution_id")
    if raw_execution_id not in (None, ""):
        execution_id = _parse_uuid(raw_execution_id)
        if execution_id is None:
            return {"error": "Invalid execution_id"}
        return await _load_run_detail(
            db,
            workflow_id=workflow_id,
            workflow_name=workflow.name,
            execution_id=execution_id,
        )

    time_range = str(args.get("time_range") or "all").strip().lower()
    if time_range not in _TIME_RANGE_HOURS:
        return {"error": "time_range must be one of 1h, 3h, 6h, 24h, 7d, 30d, all"}

    raw_status = args.get("status")
    status_filter = str(raw_status).strip().lower() if raw_status else None

    return await _load_run_metadata(
        db,
        workflow_id=workflow_id,
        workflow_name=workflow.name,
        time_range=time_range,
        status_filter=status_filter or None,
        limit=_clamp_limit(args.get("limit")),
        offset=_clamp_offset(args.get("offset")),
    )
