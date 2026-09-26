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
    cleanup_completed_active_executions,
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
        from app.services.board_run_service import reconcile_orphaned_board_runs

        await asyncio.sleep(_RECOVERY_GRACE_SECONDS)
        while self._running:
            try:
                if lock_service.is_leader:
                    await self._sweep_once()
                    # Startup alone is too early: a run whose heartbeat was still fresh
                    # when this process booted is only settleable once it goes stale.
                    await reconcile_orphaned_board_runs()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Execution recovery sweep failed")
            await asyncio.sleep(_RECOVERY_POLL_SECONDS)

    async def _sweep_once(self) -> None:
        await cleanup_completed_active_executions()
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
        from datetime import datetime, timezone

        from sqlalchemy import delete, select, update
        from sqlalchemy.exc import IntegrityError

        from app.db.models import ActiveWorkflowExecution, ExecutionHistory, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_FAILED, STATUS_SKIPPED_LATE

        has_history = False
        async with async_session_maker() as session:
            # Atomic lock acquisition in global lock order:
            # 1. ActiveWorkflowExecution
            # 2. WorkflowRunQueue
            active_row = (
                await session.execute(
                    select(ActiveWorkflowExecution)
                    .where(ActiveWorkflowExecution.execution_id == orphan.execution_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()

            queue_row = (
                await session.execute(
                    select(WorkflowRunQueue)
                    .where(WorkflowRunQueue.execution_id == orphan.execution_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()

            if orphan.claim_owner is not None:
                if (
                    active_row is None
                    or active_row.worker_id != orphan.claim_owner
                    or (
                        queue_row is not None and queue_row.claimed_by_process != orphan.claim_owner
                    )
                ):
                    logger.warning(
                        "Recovery finalize: execution %s ownership lost (expected owner %s, active worker %s, queue claim %s); discarding finalize.",
                        orphan.execution_id,
                        orphan.claim_owner,
                        getattr(active_row, "worker_id", None),
                        getattr(queue_row, "claimed_by_process", None),
                    )
                    return

            # A paused run already published history under this id, and its finish write
            # can be dropped by the registry, leaving a claimable active row. Inserting
            # again would collide on the primary key and overwrite real inputs.
            existing = await session.get(ExecutionHistory, orphan.execution_id)
            has_history = existing is not None
            # A deleted workflow leaves nothing for the history row's foreign key to
            # point at, so the insert could only raise. Dropping the active row is
            # enough; board reconciliation settles the run once the execution is gone.
            if workflow is not None and existing is None:
                try:
                    # The workflow can still go away between _load_workflow and here, so
                    # the insert gets its own savepoint rather than losing the delete.
                    async with session.begin_nested():
                        session.add(
                            ExecutionHistory(
                                # Callers already hold this id: the streaming endpoint,
                                # the by-id lookup and the board run are keyed by it.
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
                        )
                    has_history = True
                except IntegrityError:
                    logger.info(
                        "Recovery skipped history for execution %s: workflow %s is gone",
                        orphan.execution_id,
                        orphan.workflow_id,
                    )
            if orphan.claim_owner is not None:
                await session.execute(
                    delete(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == orphan.execution_id,
                        ActiveWorkflowExecution.worker_id == orphan.claim_owner,
                    )
                )
                await session.execute(
                    update(WorkflowRunQueue)
                    .where(
                        WorkflowRunQueue.execution_id == orphan.execution_id,
                        WorkflowRunQueue.claimed_by_process == orphan.claim_owner,
                    )
                    .values(
                        status=STATUS_FAILED if status == "failed" else STATUS_SKIPPED_LATE,
                        finished_at=datetime.now(timezone.utc),
                        error=f"Execution {status} by recovery",
                    )
                )
            else:
                await session.execute(
                    delete(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == orphan.execution_id
                    )
                )
                await session.execute(
                    update(WorkflowRunQueue)
                    .where(WorkflowRunQueue.execution_id == orphan.execution_id)
                    .values(
                        status=STATUS_FAILED if status == "failed" else STATUS_SKIPPED_LATE,
                        finished_at=datetime.now(timezone.utc),
                        error=f"Execution {status} by recovery",
                    )
                )
            await session.commit()
        # Whether the row is new or was already there, the board may still be waiting
        # for it: a previous pass can commit history and be interrupted before it syncs.
        # Only the helper can tell applied from unapplied, so let it decide.
        if has_history and orphan.trigger_source == "board":
            from app.services.board_run_service import sync_recovered_board_run

            await sync_recovered_board_run(orphan.execution_id)
        logger.info(
            "Recovery finalized execution %s as %s (workflow %s)",
            orphan.execution_id,
            status,
            orphan.workflow_id,
        )

    async def _rerun(self, orphan: ClaimedOrphan, workflow) -> None:
        """Re-run the workflow from scratch with the original inputs."""
        from datetime import datetime, timezone

        from sqlalchemy import delete, select, update

        from app.api.analytics import upsert_workflow_analytics_snapshot
        from app.api.workflows import (
            _persist_global_variables_from_execution,
            collect_referenced_workflows,
            get_credentials_context,
        )
        from app.db.models import ActiveWorkflowExecution, ExecutionHistory, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_history import summarize
        from app.services.cluster.run_queue import STATUS_DONE, STATUS_FAILED
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

        # Re-register the SAME execution_id with recovery claim ownership.
        cancel_event = register_execution(
            workflow_id=workflow.id,
            execution_id=orphan.execution_id,
            inputs=orphan.inputs,
            trigger_source=orphan.trigger_source,
            actor_user_id=actor_user_id,
            recoverable=True,
            claim_owner=orphan.claim_owner,
            registration_token=orphan.registration_token,
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
                execution_id=str(orphan.execution_id),
            )

            committed = False
            async with async_session_maker() as session:
                # Atomic lock acquisition in global lock order:
                # 1. ActiveWorkflowExecution
                # 2. WorkflowRunQueue
                active_row = (
                    await session.execute(
                        select(ActiveWorkflowExecution)
                        .where(ActiveWorkflowExecution.execution_id == orphan.execution_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()

                queue_row = (
                    await session.execute(
                        select(WorkflowRunQueue)
                        .where(WorkflowRunQueue.execution_id == orphan.execution_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()

                if orphan.claim_owner is not None:
                    if (
                        active_row is None
                        or active_row.worker_id != orphan.claim_owner
                        or (
                            queue_row is not None
                            and queue_row.claimed_by_process != orphan.claim_owner
                        )
                    ):
                        logger.warning(
                            "Recovery rerun: execution %s ownership lost (expected owner %s, active worker %s, queue claim %s); discarding completion.",
                            orphan.execution_id,
                            orphan.claim_owner,
                            getattr(active_row, "worker_id", None),
                            getattr(queue_row, "claimed_by_process", None),
                        )
                        return

                session.add(
                    ExecutionHistory(
                        id=orphan.execution_id,
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

                if orphan.claim_owner is not None:
                    await session.execute(
                        delete(ActiveWorkflowExecution).where(
                            ActiveWorkflowExecution.execution_id == orphan.execution_id,
                            ActiveWorkflowExecution.worker_id == orphan.claim_owner,
                        )
                    )
                    await session.execute(
                        update(WorkflowRunQueue)
                        .where(
                            WorkflowRunQueue.execution_id == orphan.execution_id,
                            WorkflowRunQueue.claimed_by_process == orphan.claim_owner,
                        )
                        .values(
                            status=STATUS_DONE if result.status == "success" else STATUS_FAILED,
                            finished_at=datetime.now(timezone.utc),
                            result=summarize(result, orphan.execution_id),
                            error=None,
                        )
                    )
                else:
                    await session.execute(
                        delete(ActiveWorkflowExecution).where(
                            ActiveWorkflowExecution.execution_id == orphan.execution_id
                        )
                    )
                    await session.execute(
                        update(WorkflowRunQueue)
                        .where(WorkflowRunQueue.execution_id == orphan.execution_id)
                        .values(
                            status=STATUS_DONE if result.status == "success" else STATUS_FAILED,
                            finished_at=datetime.now(timezone.utc),
                            result=summarize(result, orphan.execution_id),
                            error=None,
                        )
                    )
                await session.commit()
                committed = True
            if committed and orphan.trigger_source == "board":
                from app.services.board_run_service import sync_recovered_board_run

                await sync_recovered_board_run(orphan.execution_id)
            if committed:
                logger.info(
                    "Recovery re-ran execution %s -> %s (workflow %s)",
                    orphan.execution_id,
                    result.status,
                    workflow.id,
                )
        finally:
            clear_execution(
                orphan.execution_id,
                handle=getattr(cancel_event, "_execution_handle", None),
            )


execution_recovery_service = ExecutionRecoveryService()
