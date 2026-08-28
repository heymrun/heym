"""Persist an offloaded run's history on the instance that executed it.

Trigger call sites normally write ExecutionHistory themselves after
execute_workflow returns. When the run is offloaded, the caller never sees an
ExecutionResult - the objects inside it (NodeResult, SubWorkflowExecution, and
the Future fields for executeDoNotWait) do not survive a JSON round trip - so
the claiming instance writes history where the run actually happened, stamped
with its own label.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.db.models import ExecutionHistory
from app.db.session import async_session_maker
from app.services.cluster.attribution import attribution_fields


def summarize(result: Any, execution_id: uuid.UUID) -> dict[str, Any]:
    """The part of an ExecutionResult that can cross an instance boundary.

    Node results and sub-workflow executions stay in the history row; the
    waiting caller gets what it needs to reply and nothing it cannot decode.
    """
    return {
        "execution_id": str(execution_id),
        "status": result.status,
        "outputs": result.outputs,
        "execution_time_ms": result.execution_time_ms,
        "history_written": True,
    }


async def persist_run_history(
    *,
    execution_id: uuid.UUID,
    workflow_id: uuid.UUID,
    owner_id: uuid.UUID,
    workflow_name: str,
    inputs: dict,
    trigger_source: str | None,
    result: Any,
) -> None:
    """Write the run, its analytics bucket, and any sub-workflow runs."""
    async with async_session_maker() as db:
        db.add(
            ExecutionHistory(
                id=execution_id,
                workflow_id=workflow_id,
                inputs=inputs,
                outputs=result.outputs,
                node_results=result.node_results,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
                trigger_source=trigger_source,
                **attribution_fields(),
            )
        )
        await upsert_workflow_analytics_snapshot(
            db,
            workflow_id=workflow_id,
            owner_id=owner_id,
            workflow_name_snapshot=workflow_name,
            status=result.status,
            execution_time_ms=result.execution_time_ms,
        )
        for sub_exec in result.sub_workflow_executions:
            db.add(
                ExecutionHistory(
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    inputs=sub_exec.inputs,
                    outputs=sub_exec.outputs,
                    node_results=sub_exec.node_results,
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                    trigger_source=sub_exec.trigger_source,
                    **attribution_fields(),
                )
            )
        await db.commit()


@dataclass
class OffloadedRun:
    """An offloaded run's result, shaped like ExecutionResult where it matters.

    Trigger call sites read `.status`, `.outputs` and `.execution_time_ms` and
    then write history. `history_written` tells them the executing instance
    already did, so the same call site serves both paths with one guard.
    """

    status: str
    outputs: dict
    execution_time_ms: float = 0.0
    error: str | None = None
    node_results: list = field(default_factory=list)
    sub_workflow_executions: list = field(default_factory=list)
    history_written: bool = True
    # The executing instance already joined any allow-downstream work locally.
    allow_downstream_pending: bool = False

    def join_allow_downstream(self) -> None:
        return None


def from_summary(summary: dict[str, Any]) -> OffloadedRun:
    return OffloadedRun(
        status=str(summary.get("status") or "error"),
        outputs=summary.get("outputs") or {},
        execution_time_ms=float(summary.get("execution_time_ms") or 0.0),
        error=summary.get("error"),
    )


def offloaded_error(message: str) -> OffloadedRun:
    """A failure the caller must surface without a history row of its own."""
    return OffloadedRun(status="error", outputs={}, error=message)
