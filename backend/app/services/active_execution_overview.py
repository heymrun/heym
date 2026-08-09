"""Shared reader for currently-active workflow executions.

Both the dashboard badge endpoint (`GET /api/workflows/executions/active`) and the
dashboard chat / MCP `get_active_executions` tool read from here so the badge and the
assistant can never disagree about what is running.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workflow, WorkflowShare
from app.models.schemas import ActiveExecutionItem
from app.services.execution_cancellation import (
    get_active_execution_progress,
    list_active_executions,
    list_pending_review_executions_for_user,
    list_persisted_active_executions_for_user,
)

logger = logging.getLogger(__name__)

# Node statuses that mean the node already produced a result, so it is not the node
# the run is currently sitting on.
_FINISHED_NODE_STATUSES = frozenset({"success", "error", "skipped", "cancelled"})


async def collect_active_executions_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[ActiveExecutionItem]:
    """Return running and pending-review executions visible to the user.

    Stitches together three independent reads. Any one of them can fail on its own, and
    a partial list is far more useful to callers than a 500: degrade section by section
    instead of failing the whole request.
    """

    async def _read(section: str, coroutine: Any) -> Any:
        try:
            return await coroutine
        except SQLAlchemyError:
            logger.warning("Active executions: %s lookup failed; skipping", section, exc_info=True)
            await db.rollback()
            return None

    persisted = (
        await _read("persisted registry", list_persisted_active_executions_for_user(db, user_id))
        or []
    )
    items_by_execution_id = {
        record.execution_id: ActiveExecutionItem(
            execution_id=str(record.execution_id),
            workflow_id=str(record.workflow_id),
            workflow_name=record.workflow_name,
            started_at=record.started_at,
            inputs=record.inputs,
            running_node_ids=record.running_node_ids,
            node_results=record.node_results,
            status="running",
        )
        for record in persisted
    }

    local_handles = [
        handle
        for handle in list_active_executions()
        if handle.execution_id not in items_by_execution_id and not handle.event.is_set()
    ]
    if local_handles:
        workflow_ids = list({h.workflow_id for h in local_handles})
        result = await _read(
            "local handle workflows",
            db.execute(
                select(Workflow).where(
                    Workflow.id.in_(workflow_ids),
                    or_(
                        Workflow.owner_id == user_id,
                        Workflow.id.in_(
                            select(WorkflowShare.workflow_id).where(
                                WorkflowShare.user_id == user_id
                            )
                        ),
                    ),
                )
            ),
        )
        accessible: dict[uuid.UUID, str] = (
            {w.id: w.name for w in result.scalars().all()} if result is not None else {}
        )
        for handle in local_handles:
            if handle.workflow_id not in accessible:
                continue
            progress = get_active_execution_progress(
                handle.execution_id,
                workflow_id=handle.workflow_id,
            )
            if progress is None:
                continue
            running_node_ids, node_results = progress
            items_by_execution_id[handle.execution_id] = ActiveExecutionItem(
                execution_id=str(handle.execution_id),
                workflow_id=str(handle.workflow_id),
                workflow_name=accessible[handle.workflow_id],
                started_at=handle.started_at,
                inputs=dict(handle.inputs),
                running_node_ids=running_node_ids,
                node_results=node_results,
                status="running",
            )

    pending_reviews = (
        await _read("pending reviews", list_pending_review_executions_for_user(db, user_id)) or []
    )
    for record in pending_reviews:
        if record.execution_id in items_by_execution_id:
            continue
        items_by_execution_id[record.execution_id] = ActiveExecutionItem(
            execution_id=str(record.execution_id),
            workflow_id=str(record.workflow_id),
            workflow_name=record.workflow_name,
            started_at=record.started_at,
            inputs=record.inputs,
            running_node_ids=[],
            node_results=record.node_results,
            status="pending",
            pending_kind=record.pending_kind,
        )

    return sorted(
        items_by_execution_id.values(),
        key=lambda item: item.started_at,
        reverse=True,
    )


def format_duration(total_seconds: float) -> str:
    """Render an elapsed duration the way the chat assistant should read it aloud."""
    seconds = max(0, int(total_seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _node_label_index(nodes: Any) -> dict[str, dict[str, str]]:
    """Map node id -> label/type from a workflow's stored node list."""
    index: dict[str, dict[str, str]] = {}
    if not isinstance(nodes, list):
        return index
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        label = str(data.get("label") or "").strip()
        node_type = str(node.get("type") or data.get("type") or "").strip()
        index[node_id] = {"label": label or node_id, "type": node_type}
    return index


def _current_nodes(
    item: ActiveExecutionItem,
    labels: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """Nodes the run is executing right now, newest activity first."""
    current: list[dict[str, str]] = []
    seen: set[str] = set()

    for node_id in item.running_node_ids:
        key = str(node_id)
        if key in seen:
            continue
        seen.add(key)
        info = labels.get(key, {})
        current.append(
            {
                "node_id": key,
                "node_label": info.get("label") or key,
                "node_type": info.get("type") or "",
            }
        )

    # The persisted registry only carries running_node_ids while a worker owns the run.
    # A node_result left in a non-terminal state (for example a paused HITL node) is the
    # node the run is waiting on, so surface it too.
    for node_result in item.node_results:
        if not isinstance(node_result, dict):
            continue
        status = str(node_result.get("status") or "").strip().lower()
        if status in _FINISHED_NODE_STATUSES:
            continue
        key = str(node_result.get("node_id") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        info = labels.get(key, {})
        current.append(
            {
                "node_id": key,
                "node_label": str(node_result.get("node_label") or "") or info.get("label") or key,
                "node_type": str(node_result.get("node_type") or "") or info.get("type") or "",
            }
        )

    return current


def _last_completed_node(
    item: ActiveExecutionItem,
    labels: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    for node_result in reversed(item.node_results):
        if not isinstance(node_result, dict):
            continue
        status = str(node_result.get("status") or "").strip().lower()
        if status not in _FINISHED_NODE_STATUSES:
            continue
        key = str(node_result.get("node_id") or "").strip()
        info = labels.get(key, {})
        return {
            "node_id": key,
            "node_label": str(node_result.get("node_label") or "") or info.get("label") or key,
            "node_type": str(node_result.get("node_type") or "") or info.get("type") or "",
            "status": status,
        }
    return None


async def build_active_execution_overview(
    db: AsyncSession,
    user_id: uuid.UUID,
    public_base_url: str = "",
) -> dict[str, Any]:
    """Summarize what is running right now for the dashboard chat / MCP assistant."""
    items = await collect_active_executions_for_user(db, user_id)
    if not items:
        return {"count": 0, "running_count": 0, "pending_count": 0, "executions": []}

    workflow_ids = {uuid.UUID(item.workflow_id) for item in items}
    labels_by_workflow: dict[str, dict[str, dict[str, str]]] = {}
    try:
        result = await db.execute(
            select(Workflow.id, Workflow.nodes).where(Workflow.id.in_(workflow_ids))
        )
        labels_by_workflow = {str(row.id): _node_label_index(row.nodes) for row in result.all()}
    except SQLAlchemyError:
        logger.warning("Active executions: node label lookup failed; skipping", exc_info=True)
        await db.rollback()

    base = (public_base_url or "").rstrip("/")
    now = datetime.now(timezone.utc)
    executions: list[dict[str, Any]] = []
    for item in items:
        labels = labels_by_workflow.get(item.workflow_id, {})
        started_at = item.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        running_seconds = max(0.0, (now - started_at).total_seconds())
        path = f"/workflows/{item.workflow_id}/{item.execution_id}"
        executions.append(
            {
                "execution_id": item.execution_id,
                "workflow_id": item.workflow_id,
                "workflow_name": item.workflow_name,
                "status": item.status,
                "pending_kind": item.pending_kind,
                "started_at": started_at.isoformat(),
                "running_for_seconds": round(running_seconds, 1),
                "running_for": format_duration(running_seconds),
                "current_nodes": _current_nodes(item, labels),
                "last_completed_node": _last_completed_node(item, labels),
                "completed_node_count": len(item.node_results),
                "url": f"{base}{path}" if base else path,
                "workflow_url": f"{base}/workflows/{item.workflow_id}"
                if base
                else f"/workflows/{item.workflow_id}",
            }
        )

    return {
        "count": len(executions),
        "running_count": sum(1 for e in executions if e["status"] == "running"),
        "pending_count": sum(1 for e in executions if e["status"] == "pending"),
        "executions": executions,
    }
