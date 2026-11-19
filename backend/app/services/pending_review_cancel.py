"""Cancel executions that are parked on a human review instead of running on a worker.

A run waiting on a HITL review or a Codex follow-up question owns no worker: its
process has already returned, so there is no in-memory cancellation handle and no
``ActiveWorkflowExecution`` row to flag. The only durable state is the pending review
request and a ``pending`` ``ExecutionHistory`` row, so cancelling means closing both.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CodexFollowupRequest, ExecutionHistory, HITLRequest
from app.services.run_history_encryption import unseal_in_place

CANCELLED_STATUS = "cancelled"
CANCELLED_OUTPUT: dict[str, str] = {"error": "Execution was cancelled"}


def _cancel_pending_node_results(node_results: Any) -> list[Any]:
    """Return a copy of ``node_results`` with parked (pending) nodes marked cancelled."""
    if not isinstance(node_results, list):
        return []
    updated: list[Any] = []
    for item in node_results:
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "pending":
            item = {**copy.deepcopy(item), "status": CANCELLED_STATUS}
        updated.append(item)
    return updated


async def cancel_pending_review_execution(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
) -> bool:
    """Cancel an execution that is waiting on a pending HITL or Codex review.

    The review request is closed with a conditional ``UPDATE ... WHERE status='pending'``
    so a reviewer deciding at the same moment and this cancel cannot both win. Returns
    True when a pending review was closed, False when the execution has none (it is
    running, already resolved, or unknown) and the caller should try other cancel paths.
    """
    now = datetime.now(timezone.utc)

    hitl_result = await db.execute(
        update(HITLRequest)
        .where(
            HITLRequest.workflow_id == workflow_id,
            HITLRequest.execution_history_id == execution_id,
            HITLRequest.status == "pending",
        )
        .values(status=CANCELLED_STATUS, resolved_at=now)
    )
    codex_result = await db.execute(
        update(CodexFollowupRequest)
        .where(
            CodexFollowupRequest.workflow_id == workflow_id,
            CodexFollowupRequest.execution_history_id == execution_id,
            CodexFollowupRequest.status == "pending",
        )
        .values(status=CANCELLED_STATUS)
    )
    if (hitl_result.rowcount or 0) + (codex_result.rowcount or 0) == 0:
        return False

    history = (
        await db.execute(
            select(ExecutionHistory)
            .where(
                ExecutionHistory.id == execution_id,
                ExecutionHistory.workflow_id == workflow_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if history is not None and history.status == "pending":
        await unseal_in_place(db, history)
        history.status = CANCELLED_STATUS
        history.outputs = dict(CANCELLED_OUTPUT)
        history.node_results = _cancel_pending_node_results(history.node_results)

    await db.commit()

    # A board card chain parked on this review would otherwise wait forever.
    from app.services.board_run_service import resume_card_chain

    await resume_card_chain(execution_id)
    return True
