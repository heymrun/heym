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
            asyncio.create_task(self._recover_one(orphan))

    async def _recover_one(self, orphan: ClaimedOrphan) -> None:
        workflow = await self._load_workflow(orphan.workflow_id)
        action = decide_recovery_action(
            attempt=orphan.attempt,
            auto_recover=bool(getattr(workflow, "auto_recover_runs", True)),
            workflow_exists=workflow is not None,
        )
        if action == "rerun":
            await self._rerun(orphan, workflow)
            return
        await self._finalize(orphan=orphan, workflow=workflow, status=action)

    async def _load_workflow(self, workflow_id: uuid.UUID):
        from sqlalchemy import select

        from app.db.models import Workflow
        from app.db.session import async_session_maker

        async with async_session_maker() as session:
            result = await session.execute(select(Workflow).where(Workflow.id == workflow_id))
            return result.scalar_one_or_none()

    async def _finalize(self, *, orphan: ClaimedOrphan, workflow, status: str) -> None:
        """Write a terminal ExecutionHistory entry and drop the active row."""
        from sqlalchemy import delete

        from app.db.models import ActiveWorkflowExecution, ExecutionHistory
        from app.db.session import async_session_maker

        async with async_session_maker() as session:
            session.add(
                ExecutionHistory(
                    workflow_id=orphan.workflow_id,
                    inputs=orphan.inputs,
                    outputs={},
                    node_results=[],
                    status=status,
                    execution_time_ms=0.0,
                    trigger_source=orphan.trigger_source,
                    recovered=True,
                )
            )
            await session.execute(
                delete(ActiveWorkflowExecution).where(
                    ActiveWorkflowExecution.execution_id == orphan.execution_id
                )
            )
            await session.commit()
        logger.info(
            "Recovery finalized execution %s as %s (workflow %s)",
            orphan.execution_id,
            status,
            orphan.workflow_id,
        )

    async def _rerun(self, orphan: ClaimedOrphan, workflow) -> None:
        """Re-run the workflow from scratch with the original inputs."""
        from app.api.analytics import upsert_workflow_analytics_snapshot
        from app.api.workflows import (
            _persist_global_variables_from_execution,
            collect_referenced_workflows,
            get_credentials_context,
        )
        from app.db.models import ExecutionHistory
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import (
            clear_execution,
            register_execution,
        )
        from app.services.global_variables_service import get_global_variables_context
        from app.services.workflow_executor import execute_workflow

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
        try:
            result = await asyncio.to_thread(
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
            )
        finally:
            clear_execution(orphan.execution_id)

        async with async_session_maker() as session:
            session.add(
                ExecutionHistory(
                    workflow_id=workflow.id,
                    inputs=orphan.inputs,
                    outputs=result.outputs,
                    node_results=result.node_results,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                    trigger_source=orphan.trigger_source,
                    recovered=True,
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
            await _persist_global_variables_from_execution(
                session,
                workflow.owner_id,
                workflow.nodes,
                workflow_cache,
                result.node_results,
                result.sub_workflow_executions,
            )
            await session.commit()
        logger.info(
            "Recovery re-ran execution %s -> %s (workflow %s)",
            orphan.execution_id,
            result.status,
            workflow.id,
        )


execution_recovery_service = ExecutionRecoveryService()
