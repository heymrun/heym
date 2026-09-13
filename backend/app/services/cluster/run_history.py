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

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.db.models import ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.services.cluster import identity
from app.services.cluster.attribution import attribution_fields


def failed_node_summary(node_results: Any) -> dict[str, Any] | None:
    """The first failing node, reduced to the fields an error context reads.

    A whole NodeResult carries outputs that need not survive JSON, so only these
    four strings travel; everything else stays in the history row.
    """
    for item in node_results or []:
        if isinstance(item, dict) and item.get("status") == "error":
            return {
                "status": "error",
                "error": item.get("error"),
                "node_label": item.get("node_label"),
                "node_type": item.get("node_type"),
            }
    return None


def failure_node_results(result: Any) -> list[dict[str, Any]]:
    """Node results for an error workflow's context, either side of the queue."""
    results = getattr(result, "node_results", None) or []
    if results:
        return list(results)
    failed = getattr(result, "failed_node", None)
    return [failed] if failed else []


def summarize(result: Any, execution_id: uuid.UUID) -> dict[str, Any]:
    """The part of an ExecutionResult that can cross an instance boundary.

    Node results and sub-workflow executions stay in the history row; the
    waiting caller gets what it needs to reply and nothing it cannot decode.
    """
    return {
        "execution_id": str(execution_id),
        "workflow_id": str(getattr(result, "workflow_id", "") or ""),
        "status": result.status,
        "outputs": result.outputs,
        "execution_time_ms": result.execution_time_ms,
        "history_written": True,
        # The configured error workflow runs on the dispatching instance, which
        # never sees node_results, so the failing node travels with the summary.
        "failed_node": failed_node_summary(getattr(result, "node_results", None)),
        # Named so the caller's log can say where to look for the run.
        "instance": identity.instance_name(),
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
    """Write the run, its analytics bucket, and any sub-workflow runs.

    The run's own row is written last-writer-wins: the queue may already have
    given up on this execution and recorded it as failed, and the instance that
    actually ran it holds the real answer.
    """
    async with async_session_maker() as db:
        values = {
            "id": execution_id,
            "workflow_id": workflow_id,
            "inputs": inputs,
            "outputs": result.outputs,
            "node_results": result.node_results,
            "status": result.status,
            "execution_time_ms": result.execution_time_ms,
            "trigger_source": trigger_source,
            **attribution_fields(),
        }
        await db.execute(
            pg_insert(ExecutionHistory)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={k: v for k, v in values.items() if k != "id"},
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


async def persist_pending_run_history(
    *,
    execution_id: uuid.UUID,
    workflow_id: uuid.UUID,
    owner_id: uuid.UUID,
    workflow_name: str,
    inputs: dict,
    trigger_source: str | None,
    credentials_owner_id: uuid.UUID | None,
    result: Any,
) -> None:
    """Mint a paused run's review request where the run actually paused.

    A pause is not a finished run: without the request row there is no public
    token, no link, no notification branch and no way to resume, and the run
    sits at pending forever.
    """
    from app.services.hitl_service import build_default_public_base_url
    from app.services.pending_execution import persist_pending_execution

    async with async_session_maker() as db:
        workflow = await db.get(Workflow, workflow_id)
        if workflow is None:
            return
        history_entry, _ = await persist_pending_execution(
            db=db,
            workflow=workflow,
            enriched_inputs=inputs,
            execution_result=result,
            trigger_source=trigger_source,
            credentials_owner_id=credentials_owner_id or owner_id,
            trace_user_id=owner_id,
            public_base_url=build_default_public_base_url(),
            history_entry_id=execution_id,
        )
        for name, value in attribution_fields().items():
            setattr(history_entry, name, value)
        await upsert_workflow_analytics_snapshot(
            db,
            workflow_id=workflow_id,
            owner_id=owner_id,
            workflow_name_snapshot=workflow_name,
            status=result.status,
            execution_time_ms=result.execution_time_ms,
        )
        await db.commit()


@dataclass
class OffloadedRun:
    """An offloaded run's result, shaped like ExecutionResult where it matters.

    Trigger call sites read `.status`, `.outputs` and `.execution_time_ms` and
    then write history. `history_written` tells them the executing instance
    already did, so the same call site serves both paths with one guard.

    `reported` separates the two ways this object carries status "error": a run
    that executed somewhere and failed (reported, history written there), and a
    run the queue retired before any instance produced a result (not reported,
    nothing written anywhere). Only the caller can tell them apart, and it can
    only tell them apart if we say so.
    """

    status: str
    outputs: dict
    workflow_id: str = ""
    execution_time_ms: float = 0.0
    error: str | None = None
    node_results: list = field(default_factory=list)
    sub_workflow_executions: list = field(default_factory=list)
    history_written: bool = True
    reported: bool = True
    instance: str = ""
    # The failing node, for the error workflow the dispatching instance runs.
    failed_node: dict | None = None
    # The executing instance already joined any allow-downstream work locally.
    allow_downstream_pending: bool = False

    def join_allow_downstream(self) -> None:
        return None


def from_summary(summary: dict[str, Any]) -> OffloadedRun:
    return OffloadedRun(
        status=str(summary.get("status") or "error"),
        outputs=summary.get("outputs") or {},
        workflow_id=str(summary.get("workflow_id") or ""),
        execution_time_ms=float(summary.get("execution_time_ms") or 0.0),
        error=summary.get("error"),
        instance=str(summary.get("instance") or ""),
        failed_node=summary.get("failed_node"),
    )


def offloaded_error(message: str, *, reported: bool = False) -> OffloadedRun:
    """A failure the caller must surface, carrying its reason in the outputs.

    `reported=True` means an instance may still be executing this run - a wait
    that timed out - so its history row is not ours to write.
    """
    return OffloadedRun(
        status="error",
        outputs={"error": message},
        error=message,
        reported=reported,
    )


async def record_failed_dispatch(
    *,
    execution_id: uuid.UUID,
    workflow_id: uuid.UUID,
    inputs: dict,
    trigger_source: str | None,
    message: str,
) -> bool:
    """Write the run that no instance ever reported, and say whether we did.

    The queue retired it - never claimed inside the grace window, claimed by an
    instance that stopped, or a claim that raised - so no ExecutionHistory row
    exists anywhere and the run is simply missing from the user's history. The
    insert is conditional because a run that reports late still owns this id.
    """
    async with async_session_maker() as db:
        workflow = await db.get(Workflow, workflow_id)
        if workflow is None:
            return False
        inserted = (
            await db.execute(
                pg_insert(ExecutionHistory)
                .values(
                    id=execution_id,
                    workflow_id=workflow_id,
                    inputs=inputs,
                    outputs={"error": message},
                    node_results=[],
                    status="error",
                    execution_time_ms=0.0,
                    trigger_source=trigger_source,
                    # The dispatcher recorded this, no one executed it.
                    **attribution_fields(),
                )
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(ExecutionHistory.id)
            )
        ).scalar_one_or_none()
        if inserted is None:
            await db.rollback()
            return False
        await upsert_workflow_analytics_snapshot(
            db,
            workflow_id=workflow_id,
            owner_id=workflow.owner_id,
            workflow_name_snapshot=workflow.name,
            status="error",
            execution_time_ms=0.0,
        )
        await db.commit()
        return True
