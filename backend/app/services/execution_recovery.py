"""Leader-gated recovery of workflow executions interrupted by a restart."""

import asyncio
import contextlib
import logging
import uuid
from typing import Literal

from app.services.distributed_lock import lock_service
from app.services.execution_cancellation import (
    RECOVERY_STALE_AFTER_SECONDS,  # noqa: F401  (re-exported for callers/tests)
    ClaimedOrphan,
    claim_orphaned_executions,
)

logger = logging.getLogger(__name__)

# Retry once: the original run is attempt 0; the first recovery makes it 1.
MAX_RECOVERY_ATTEMPTS = 1
_RECOVERY_GRACE_SECONDS = 5.0
_RECOVERY_POLL_SECONDS = 15.0

RecoveryAction = Literal["rerun", "skipped", "failed"]


def decide_recovery_action(
    *, attempt: int, auto_recover: bool, workflow_exists: bool
) -> RecoveryAction:
    """Decide what to do with a claimed orphan. `attempt` is post-claim-increment."""
    if not workflow_exists:
        return "failed"
    if attempt > MAX_RECOVERY_ATTEMPTS:
        return "failed"
    if not auto_recover:
        return "skipped"
    return "rerun"


class ExecutionRecoveryService:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._recovery_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Execution recovery service started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        recovery_tasks = list(self._recovery_tasks)
        if recovery_tasks:
            logger.info("Waiting for %d recovery task(s) to finish", len(recovery_tasks))
            await asyncio.gather(*recovery_tasks, return_exceptions=True)
        logger.info("Execution recovery service stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(_RECOVERY_GRACE_SECONDS)
        while self._running:
            try:
                if lock_service.is_leader:
                    await self._sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Execution recovery sweep failed")
            await asyncio.sleep(_RECOVERY_POLL_SECONDS)

    async def _sweep_once(self) -> None:
        orphans = await claim_orphaned_executions()
        for orphan in orphans:
            task = asyncio.create_task(self._recover_one(orphan))
            self._recovery_tasks.add(task)
            task.add_done_callback(self._recovery_task_done)

    def _recovery_task_done(self, task: asyncio.Task[None]) -> None:
        """Retain recovery tasks through completion and consume unexpected failures."""
        self._recovery_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Execution recovery task failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    async def _recover_one(self, orphan: ClaimedOrphan) -> None:
        from app.services.workflow_executor import WorkflowCancelledError, WorkflowTimeoutError

        workflow = await self._load_workflow(orphan.workflow_id)
        action = decide_recovery_action(
            attempt=orphan.attempt,
            auto_recover=bool(getattr(workflow, "auto_recover_runs", True)),
            workflow_exists=workflow is not None,
        )
        if action == "rerun":
            try:
                await self._rerun(orphan, workflow)
            except asyncio.CancelledError:
                raise
            except WorkflowTimeoutError:
                logger.warning("Recovery re-run timed out for execution %s", orphan.execution_id)
                from app.services.execution_cancellation import unregister_local_execution

                unregister_local_execution(orphan.execution_id)
                await self._finalize(orphan=orphan, workflow=workflow, status="failed")
            except WorkflowCancelledError:
                logger.info("Recovery re-run was cancelled for execution %s", orphan.execution_id)
                from app.services.execution_cancellation import unregister_local_execution

                unregister_local_execution(orphan.execution_id)
                await self._finalize(orphan=orphan, workflow=workflow, status="cancelled")
            except Exception:
                logger.exception("Recovery re-run failed for execution %s", orphan.execution_id)
                from app.services.execution_cancellation import unregister_local_execution

                unregister_local_execution(orphan.execution_id)
                await self._finalize(orphan=orphan, workflow=workflow, status="failed")
            return
        await self._finalize(orphan=orphan, workflow=workflow, status=action)

    async def _load_workflow(self, workflow_id: uuid.UUID):
        from sqlalchemy import select

        from app.db.models import Workflow
        from app.db.session import async_session_maker

        async with async_session_maker() as session:
            result = await session.execute(
                select(Workflow).where(
                    Workflow.id == workflow_id,
                    Workflow.scheduled_for_deletion.is_(None),
                )
            )
            return result.scalar_one_or_none()

    async def _finalize(self, *, orphan: ClaimedOrphan, workflow, status: str) -> None:
        """Write a terminal ExecutionHistory entry and drop the active row."""
        from sqlalchemy import delete
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.api.analytics import upsert_workflow_analytics_snapshot
        from app.db.models import ActiveWorkflowExecution, ExecutionHistory
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import clear_execution

        async with async_session_maker() as session:
            await session.execute(
                pg_insert(ExecutionHistory)
                .values(
                    id=orphan.execution_id,
                    workflow_id=orphan.workflow_id,
                    inputs=orphan.inputs,
                    outputs={},
                    node_results=[],
                    status=status,
                    execution_time_ms=0.0,
                    trigger_source=orphan.trigger_source,
                    recovered=True,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "outputs": {},
                        "node_results": [],
                        "status": status,
                        "execution_time_ms": 0.0,
                        "recovered": True,
                    },
                )
            )
            await session.execute(
                delete(ActiveWorkflowExecution).where(
                    ActiveWorkflowExecution.execution_id == orphan.execution_id
                )
            )
            if workflow is not None:
                await upsert_workflow_analytics_snapshot(
                    session,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status="error" if status == "failed" else status,
                    execution_time_ms=0.0,
                )
            await session.commit()
        clear_execution(orphan.execution_id)
        logger.info(
            "Recovery finalized execution %s as %s (workflow %s)",
            orphan.execution_id,
            status,
            orphan.workflow_id,
        )

    async def _rerun(self, orphan: ClaimedOrphan, workflow) -> None:
        """Re-run the workflow from scratch with the original inputs."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.api.analytics import upsert_workflow_analytics_snapshot
        from app.api.workflows import (
            _persist_global_variables_from_execution,
            collect_referenced_workflows,
            get_credentials_context,
        )
        from app.db.models import ExecutionHistory
        from app.db.session import async_session_maker
        from app.services.codex_followup_service import (
            is_codex_pending_execution,
            persist_pending_codex_followup_execution,
        )
        from app.services.execution_cancellation import (
            clear_execution,
            register_execution,
        )
        from app.services.global_variables_service import get_global_variables_context
        from app.services.hitl_service import (
            build_default_public_base_url,
            persist_pending_hitl_execution,
        )
        from app.services.workflow_executor import _to_json_compatible, execute_workflow

        actor_user_id = orphan.actor_user_id or workflow.owner_id
        async with async_session_maker() as session:
            workflow_cache = await collect_referenced_workflows(
                session, workflow.nodes, actor_user_id=actor_user_id
            )
            credentials_context = await get_credentials_context(session, actor_user_id)
            global_variables_context = await get_global_variables_context(session, actor_user_id)

        # Re-register the SAME execution_id so the claimed attempt count is preserved.
        cancel_event = register_execution(
            workflow_id=workflow.id,
            execution_id=orphan.execution_id,
            inputs=orphan.inputs,
            trigger_source=orphan.trigger_source,
            actor_user_id=actor_user_id,
            recoverable=True,
        )
        execution_task = asyncio.create_task(
            asyncio.to_thread(
                execute_workflow,
                workflow_id=workflow.id,
                nodes=workflow.nodes,
                edges=workflow.edges,
                inputs=orphan.inputs,
                workflow_cache=workflow_cache,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=actor_user_id,
                actor_user_id=actor_user_id,
                cancel_event=cancel_event,
                timeout_seconds=getattr(workflow, "workflow_timeout_seconds", None),
                workflow_name=workflow.name,
                workflow_description=getattr(workflow, "description", None) or "",
                execution_id=str(orphan.execution_id),
                public_base_url=build_default_public_base_url(),
            )
        )
        try:
            result = await asyncio.shield(execution_task)
        except asyncio.CancelledError:
            cancel_event.set()
            logger.warning(
                "Waiting for cancelled recovery execution %s worker thread to stop",
                orphan.execution_id,
            )
            result = await execution_task

        if getattr(result, "allow_downstream_pending", False):
            result.join_allow_downstream()

        async with async_session_maker() as session:
            if result.status == "pending":
                history_entry = await session.get(ExecutionHistory, orphan.execution_id)
                persist_pending = (
                    persist_pending_codex_followup_execution
                    if is_codex_pending_execution(result)
                    else persist_pending_hitl_execution
                )
                history_entry, _ = await persist_pending(
                    db=session,
                    workflow=workflow,
                    enriched_inputs=orphan.inputs,
                    execution_result=result,
                    trigger_source=orphan.trigger_source,
                    credentials_owner_id=actor_user_id,
                    trace_user_id=actor_user_id,
                    public_base_url=build_default_public_base_url(),
                    history_entry=history_entry,
                    history_entry_id=orphan.execution_id,
                )
                history_entry.recovered = True
                await upsert_workflow_analytics_snapshot(
                    session,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                )
                await session.commit()
                clear_execution(orphan.execution_id)
                if orphan.trigger_source == "board":
                    from app.services.board_run_service import sync_recovered_board_run

                    await sync_recovered_board_run(orphan.execution_id)
                logger.info("Recovered execution %s is pending human input", orphan.execution_id)
                return

            await session.execute(
                pg_insert(ExecutionHistory)
                .values(
                    id=orphan.execution_id,
                    workflow_id=workflow.id,
                    inputs=orphan.inputs,
                    outputs=_to_json_compatible(result.outputs),
                    node_results=_to_json_compatible(result.node_results),
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                    trigger_source=orphan.trigger_source,
                    recovered=True,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "inputs": orphan.inputs,
                        "outputs": _to_json_compatible(result.outputs),
                        "node_results": _to_json_compatible(result.node_results),
                        "status": result.status,
                        "execution_time_ms": result.execution_time_ms,
                        "trigger_source": orphan.trigger_source,
                        "recovered": True,
                    },
                )
            )
            await upsert_workflow_analytics_snapshot(
                session,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                workflow_name_snapshot=workflow.name,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
            )
            for sub_execution in result.sub_workflow_executions:
                session.add(
                    ExecutionHistory(
                        workflow_id=uuid.UUID(sub_execution.workflow_id),
                        inputs=_to_json_compatible(sub_execution.inputs),
                        outputs=_to_json_compatible(sub_execution.outputs),
                        node_results=_to_json_compatible(sub_execution.node_results),
                        status=sub_execution.status,
                        execution_time_ms=sub_execution.execution_time_ms,
                        trigger_source=sub_execution.trigger_source,
                        recovered=True,
                    )
                )
                await upsert_workflow_analytics_snapshot(
                    session,
                    workflow_id=uuid.UUID(sub_execution.workflow_id),
                    owner_id=None,
                    workflow_name_snapshot=sub_execution.workflow_name or "Sub-workflow",
                    status=sub_execution.status,
                    execution_time_ms=sub_execution.execution_time_ms,
                )
            await _persist_global_variables_from_execution(
                session,
                workflow.owner_id,
                workflow.nodes,
                workflow_cache,
                _to_json_compatible(result.node_results),
                result.sub_workflow_executions,
            )
            await session.commit()
        clear_execution(orphan.execution_id)
        if orphan.trigger_source == "board":
            from app.services.board_run_service import sync_recovered_board_run

            await sync_recovered_board_run(orphan.execution_id)
        logger.info(
            "Recovery re-ran execution %s -> %s (workflow %s)",
            orphan.execution_id,
            result.status,
            workflow.id,
        )


execution_recovery_service = ExecutionRecoveryService()
