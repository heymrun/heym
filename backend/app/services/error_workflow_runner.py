"""Run an external "error workflow" when a top-level run fails.

A workflow may designate another workflow (``error_workflow_id``) to run when it
fails. This is suppressed when the canvas already has a local ``errorHandler``
node (the "Global Error Catcher"), which handles errors in-workflow.

The error workflow is executed directly via ``execute_workflow`` (not through the
HTTP execute path), so it never re-enters this hook — no recursion guard beyond
that is required.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.workflows import collect_referenced_workflows, get_credentials_context
from app.db.models import ExecutionHistory, Workflow
from app.services.global_variables_service import get_global_variables_context
from app.services.workflow_executor import execute_workflow

logger = logging.getLogger(__name__)


def _has_local_error_handler(nodes: list[dict[str, Any]] | None) -> bool:
    return any(isinstance(n, dict) and n.get("type") == "errorHandler" for n in (nodes or []))


def should_run_error_workflow(workflow: Any, status: str) -> bool:
    """True when the failed run should trigger the configured error workflow."""
    if status != "error":
        return False
    if getattr(workflow, "error_workflow_id", None) is None:
        return False
    if _has_local_error_handler(getattr(workflow, "nodes", None)):
        return False
    return True


def build_error_context(
    workflow: Any, node_results: list[dict[str, Any]], run_id: str | None
) -> dict[str, Any]:
    """Build the payload passed to the error workflow as input ``body``."""
    failed = next(
        (r for r in (node_results or []) if isinstance(r, dict) and r.get("status") == "error"),
        None,
    )
    return {
        "workflow_id": str(getattr(workflow, "id", "")),
        "workflow_name": getattr(workflow, "name", ""),
        "run_id": str(run_id) if run_id is not None else None,
        "error": (failed or {}).get("error"),
        "errorNode": (failed or {}).get("node_label"),
        "errorNodeType": (failed or {}).get("node_type"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _load_workflow(db: AsyncSession, workflow_id: uuid.UUID) -> Workflow | None:
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    return result.scalar_one_or_none()


async def maybe_run_error_workflow(
    db: AsyncSession,
    workflow: Any,
    *,
    status: str,
    node_results: list[dict[str, Any]],
    run_id: str | None,
    actor_user_id: uuid.UUID,
) -> bool:
    """Run the configured error workflow if the guard passes. Never raises."""
    try:
        if not should_run_error_workflow(workflow, status):
            return False

        target = await _load_workflow(db, workflow.error_workflow_id)
        if target is None:
            return False

        error_context = build_error_context(workflow, node_results, run_id)
        enriched_inputs = {"headers": {}, "query": {}, "body": error_context}

        workflow_cache = await collect_referenced_workflows(
            db, target.nodes, actor_user_id=actor_user_id
        )
        credentials_context = await get_credentials_context(db, actor_user_id)
        global_variables_context = await get_global_variables_context(db, actor_user_id)

        result = await asyncio.to_thread(
            execute_workflow,
            workflow_id=target.id,
            nodes=target.nodes,
            edges=target.edges,
            inputs=enriched_inputs,
            workflow_cache=workflow_cache,
            test_run=False,
            credentials_context=credentials_context,
            global_variables_context=global_variables_context,
            trace_user_id=actor_user_id,
            actor_user_id=actor_user_id,
        )

        history = ExecutionHistory(
            workflow_id=target.id,
            inputs=enriched_inputs,
            outputs=result.outputs,
            node_results=result.node_results,
            status=result.status,
            execution_time_ms=result.execution_time_ms,
            trigger_source="ERROR_WORKFLOW",
        )
        db.add(history)
        await db.flush()
        return True
    except Exception:  # noqa: BLE001 — error workflow must never mask the original failure
        logger.exception("Error workflow execution failed for %s", getattr(workflow, "id", "?"))
        return False
