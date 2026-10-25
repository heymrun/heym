"""Lifecycle checks shared by interactive and scheduled workflow deletion."""

import copy
from typing import Any
from uuid import UUID

from sqlalchemy import select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import CompoundSelect

from app.db.models import (
    ActiveWorkflowExecution,
    CodexFollowupRequest,
    HITLRequest,
    WorkflowRunQueue,
)
from app.services.cluster.run_queue import (
    STATUS_CLAIMED,
    STATUS_HELD,
    STATUS_QUEUED,
    STATUS_WAITING_FOR_MAIN,
)
from app.services.execution_cancellation import list_active_executions
from app.services.workflow_status import TRIGGER_NODE_TYPES


def _unfinished_execution_query(workflow_id: UUID) -> CompoundSelect:
    return union_all(
        select(ActiveWorkflowExecution.execution_id).where(
            ActiveWorkflowExecution.workflow_id == workflow_id
        ),
        select(WorkflowRunQueue.execution_id).where(
            WorkflowRunQueue.workflow_id == workflow_id,
            # A held run is waiting for a concurrency slot; deleting would cascade it away.
            WorkflowRunQueue.status.in_(
                [STATUS_HELD, STATUS_QUEUED, STATUS_WAITING_FOR_MAIN, STATUS_CLAIMED]
            ),
        ),
        select(HITLRequest.execution_history_id).where(
            HITLRequest.workflow_id == workflow_id,
            HITLRequest.status == "pending",
            HITLRequest.execution_history_id.is_not(None),
        ),
        select(CodexFollowupRequest.execution_history_id).where(
            CodexFollowupRequest.workflow_id == workflow_id,
            CodexFollowupRequest.status == "pending",
            CodexFollowupRequest.execution_history_id.is_not(None),
        ),
    )


def set_automatic_triggers_paused(
    nodes: list[dict[str, Any]], *, paused: bool
) -> list[dict[str, Any]]:
    """Pause/resume triggers without enabling ones already off before an admin pause.

    Remember affected triggers in their stored node data so Resume survives reloads
    and works from another administrator's session. Older paused graphs without this
    marker can still be resumed by enabling their automatic triggers.
    """
    updated = copy.deepcopy(nodes)
    triggers = [node for node in updated if node.get("type") in TRIGGER_NODE_TYPES]
    has_pause_marker = any(node.get("data", {}).get("_adminPaused") is True for node in triggers)
    resume_unmarked = not has_pause_marker and all(
        node.get("data", {}).get("active") is False for node in triggers
    )
    for node in triggers:
        data = node.setdefault("data", {})
        if paused:
            if data.get("active") is not False:
                data["_adminPaused"] = True
                data["active"] = False
        elif resume_unmarked or data.get("_adminPaused") is True:
            data["active"] = True
            data.pop("_adminPaused", None)
    return updated


async def has_unfinished_workflow_executions(db: AsyncSession, workflow_id: UUID) -> bool:
    """Keep the workflow until workers finish, queued runs settle, and reviews close.

    A cancellation request is not completion: even a flagged worker still needs its
    workflow row to persist the final history. Unlike the dashboard overview this
    check fails closed when the registry cannot be read.
    """
    if any(handle.workflow_id == workflow_id for handle in list_active_executions()):
        return True
    result = await db.execute(_unfinished_execution_query(workflow_id).limit(1))
    return result.first() is not None
