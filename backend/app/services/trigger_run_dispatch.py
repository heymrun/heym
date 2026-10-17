"""Start a workflow run for a background trigger and persist what it produced.

Shared by the IMAP trigger and the Google Drive and Google Sheets triggers. A failure
before ``dispatch_workflow`` starts raises TriggerDispatchNotStartedError, which is safe
to retry because nothing has run yet. Once dispatch has started, errors propagate as they
are and must not be retried: the run may already have had side effects.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.workflows import (
    _persist_global_variables_from_execution,
    collect_referenced_workflows,
    get_credentials_context,
)
from app.db.models import ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.services.cluster.dispatch import dispatch_workflow, log_offloaded_run
from app.services.global_variables_service import get_global_variables_context
from app.services.hitl_service import build_default_public_base_url
from app.services.pending_execution import (
    needs_local_pending_persist,
    persist_pending_execution,
)


class TriggerDispatchNotStartedError(Exception):
    """Preparing the run failed before dispatch_workflow was invoked; safe to retry."""


async def run_trigger_workflow(
    *,
    workflow_id: uuid.UUID,
    inputs: dict[str, Any],
    trigger_source: str,
    trigger_label: str,
    log: logging.Logger,
) -> None:
    """Run the workflow with ``inputs`` as a ``trigger_source`` run and write its history."""
    async with async_session_maker() as db:
        try:
            workflow_result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
            fresh_workflow = workflow_result.scalar_one_or_none()
            if not fresh_workflow:
                log.warning(
                    "Workflow %s disappeared before %s execution", workflow_id, trigger_label
                )
                return

            workflow_cache = await collect_referenced_workflows(
                db, fresh_workflow.nodes, actor_user_id=fresh_workflow.owner_id
            )
            credentials_context = await get_credentials_context(db, fresh_workflow.owner_id)
            global_variables_context = await get_global_variables_context(
                db, fresh_workflow.owner_id
            )

            from app.services.execution_cancellation import (
                clear_execution,
                register_execution,
            )

            execution_id = uuid.uuid4()
            cancel_event = register_execution(
                workflow_id=fresh_workflow.id,
                execution_id=execution_id,
                inputs=inputs,
                trigger_source=trigger_source,
                actor_user_id=fresh_workflow.owner_id,
            )
        except Exception as exc:
            raise TriggerDispatchNotStartedError(str(exc)) from exc

        try:
            result = await dispatch_workflow(
                workflow_id=fresh_workflow.id,
                nodes=fresh_workflow.nodes,
                edges=fresh_workflow.edges,
                inputs=inputs,
                workflow_cache=workflow_cache,
                trigger_source=trigger_source,
                credentials_owner_id=fresh_workflow.owner_id,
                execution_id=execution_id,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=fresh_workflow.owner_id,
                actor_user_id=fresh_workflow.owner_id,
                cancel_event=cancel_event,
            )
        finally:
            clear_execution(execution_id, handle=getattr(cancel_event, "_execution_handle", None))

        # An offloaded run's history is written where it ran, or by the
        # dispatcher itself when the queue retired it before it ran.
        if getattr(result, "history_written", False):
            log_offloaded_run(
                log, workflow_id=fresh_workflow.id, trigger=trigger_label, result=result
            )
            return

        if needs_local_pending_persist(result):
            history_entry, _ = await persist_pending_execution(
                db=db,
                workflow=fresh_workflow,
                enriched_inputs=inputs,
                execution_result=result,
                trigger_source=trigger_source,
                credentials_owner_id=fresh_workflow.owner_id,
                trace_user_id=fresh_workflow.owner_id,
                public_base_url=build_default_public_base_url(),
                history_entry_id=execution_id,
            )
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=fresh_workflow.id,
                owner_id=fresh_workflow.owner_id,
                workflow_name_snapshot=fresh_workflow.name,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
                started_at=getattr(history_entry, "started_at", None),
            )
            await db.commit()
            log.info("Workflow %s paused for human review via %s", fresh_workflow.id, trigger_label)
            return

        history_entry = ExecutionHistory(
            id=execution_id,
            workflow_id=fresh_workflow.id,
            inputs=inputs,
            outputs=result.outputs,
            node_results=result.node_results,
            status=result.status,
            execution_time_ms=result.execution_time_ms,
            trigger_source=trigger_source,
        )
        db.add(history_entry)
        await upsert_workflow_analytics_snapshot(
            db,
            workflow_id=fresh_workflow.id,
            owner_id=fresh_workflow.owner_id,
            workflow_name_snapshot=fresh_workflow.name,
            status=result.status,
            execution_time_ms=result.execution_time_ms,
        )

        for sub_exec in result.sub_workflow_executions:
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
            fresh_workflow.owner_id,
            fresh_workflow.nodes,
            workflow_cache,
            result.node_results,
            result.sub_workflow_executions,
        )

        await db.commit()
