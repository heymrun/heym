"""The one seam where a background run either executes here or is enqueued.

Callers that today call execute_workflow() call dispatch_workflow() instead.
Streaming callers (execute_workflow_streaming) are untouched: their SSE events
go to the caller's own HTTP response and cannot cross an instance boundary.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.db.models import Workflow, WorkflowRunQueue
from app.services.cluster import identity, run_queue
from app.services.cluster.node_placement import Placement, workflow_placement
from app.services.cluster.run_history import (
    OffloadedRun,
    from_summary,
    offloaded_error,
    persist_pending_run_history,
    persist_run_history,
    summarize,
)
from app.services.cluster.run_result_bus import DEFAULT_WAIT_SECONDS, run_result_bus
from app.services.execution_cancellation import complete_execution, register_execution
from app.services.workflow_executor import execute_workflow

logger = logging.getLogger("cluster")

_RESULT_POLL_SECONDS = 10.0


def should_run_in_process(
    *, cluster_enabled: bool, placement: str, is_main: bool, test_run: bool = False
) -> bool:
    """Whether to execute here rather than enqueue.

    With no cluster, nothing is ever enqueued and a single-instance install
    behaves exactly as before, with no added latency. With a cluster, only a
    MAIN_ONLY run already on main skips the queue - an ANYWHERE run on main goes
    through it, or main would never hand work to anyone.

    A test run never leaves this instance: it is an interactive editor action
    whose latency the user is watching, and queueing it would buy nothing.
    """
    if not cluster_enabled or test_run:
        return True
    return placement == Placement.MAIN_ONLY.value and is_main


def resolve_placement(nodes: list[dict], workflow_cache: dict[str, dict] | None) -> str:
    """Placement for this graph, resolving sub-workflows from the executor's cache."""
    cache = workflow_cache or {}

    def resolve(workflow_id: str) -> list[dict] | None:
        entry = cache.get(workflow_id)
        return entry.get("nodes") if entry else None

    return workflow_placement(nodes, resolve_workflow=resolve).value


def _timeout_error(execution_id: uuid.UUID) -> OffloadedRun:
    return offloaded_error(
        f"Run {execution_id} did not report a result in time. It may still be "
        "executing on another instance; check the execution history."
    )


async def wait_for_result(
    execution_id: uuid.UUID, *, timeout_seconds: float | None = None
) -> OffloadedRun:
    """Block until the executing instance reports this run, or give up.

    Giving up matters: an instance that dies mid-run never notifies, and a
    request that waits forever is worse than one that says so. Orphan recovery
    still re-runs the execution afterwards.
    """
    deadline = asyncio.get_running_loop().time() + (timeout_seconds or DEFAULT_WAIT_SECONDS)
    event = run_result_bus.register(execution_id)
    try:
        while True:
            status, result, error = await run_queue.read_terminal_result(execution_id)
            if run_queue.is_terminal(status):
                if error or result is None:
                    return offloaded_error(error or "Run finished without a result")
                return from_summary(result)

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return _timeout_error(execution_id)
            try:
                await asyncio.wait_for(event.wait(), timeout=min(_RESULT_POLL_SECONDS, remaining))
            except asyncio.TimeoutError:
                pass
            event.clear()
    finally:
        run_result_bus.release(execution_id)


async def dispatch_workflow(
    *,
    workflow_id: uuid.UUID,
    nodes: list[dict],
    edges: list[dict],
    inputs: dict,
    workflow_cache: dict[str, dict] | None = None,
    trigger_source: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    credentials_owner_id: uuid.UUID | None = None,
    test_run: bool = False,
    timeout_seconds: float | None = None,
    wait_for_completion: bool = True,
    run_in_thread: bool = False,
    execution_id: uuid.UUID | None = None,
    **executor_kwargs: Any,
) -> Any:
    """Run here, or enqueue and wait for whichever instance takes it.

    Returns the run result. With `wait_for_completion=False` an offloaded run
    returns None immediately, for callers that ignore the result.
    """
    placement = resolve_placement(nodes, workflow_cache)
    if should_run_in_process(
        cluster_enabled=settings.cluster_enabled,
        placement=placement,
        is_main=identity.is_main(),
        test_run=test_run,
    ):
        # Charge the counter even here: forced main work must spend main's quota.
        if settings.cluster_enabled:
            await run_queue.choose_target(placement)
        call_kwargs = dict(
            workflow_id=workflow_id,
            nodes=nodes,
            edges=edges,
            inputs=inputs,
            workflow_cache=workflow_cache,
            test_run=test_run,
            actor_user_id=actor_user_id,
            timeout_seconds=timeout_seconds,
            execution_id=str(execution_id) if execution_id else "",
            **executor_kwargs,
        )
        # Each call site keeps the blocking behaviour it already had: cron
        # deliberately runs off the event loop, the webhook triggers do not.
        if run_in_thread:
            return await asyncio.to_thread(execute_workflow, **call_kwargs)
        return execute_workflow(**call_kwargs)

    run_id = execution_id or uuid.uuid4()
    # Register before enqueueing so a run that finishes first still wakes us.
    if wait_for_completion:
        run_result_bus.register(run_id)
    queued = run_queue.QueuedRun(
        workflow_id=workflow_id,
        execution_id=run_id,
        placement=placement,
        inputs=inputs,
        trigger_source=trigger_source,
        actor_user_id=actor_user_id,
        credentials_owner_id=credentials_owner_id,
        test_run=test_run,
        timeout_seconds=timeout_seconds,
        return_on_chart_output=bool(executor_kwargs.get("return_on_chart_output", False)),
    )
    target = await run_queue.enqueue(queued)
    if target:
        await run_queue.notify_queue(target)
    logger.info(
        "Dispatched workflow %s as %s to %s", workflow_id, placement, target or "waiting_for_main"
    )
    if not wait_for_completion:
        run_result_bus.release(run_id)
        return None
    return await wait_for_result(run_id, timeout_seconds=timeout_seconds)


class RunQueueWorker:
    """Claims queued rows for this instance and executes them.

    All 8 uvicorn processes run one of these. FOR UPDATE SKIP LOCKED resolves
    the race between them, and the percentage stays meaningful because it is
    applied per instance at enqueue time, not per process at claim time.
    """

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._bus: Any = None

    async def start(self) -> None:
        if not settings.cluster_enabled or self._task is not None:
            return
        from app.services.cluster.run_queue_bus import QueueWakeBus

        bus = QueueWakeBus(identity.instance_id())
        await bus.start()
        self._bus = bus
        self._running = True
        self._task = asyncio.create_task(self._run_loop(bus))
        logger.info("Run queue worker started (instance=%s)", identity.instance_id())

    async def stop(self) -> None:
        self._running = False
        if self._bus is not None:
            await self._bus.stop()
            self._bus = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self, bus: Any) -> None:
        while self._running:
            try:
                await bus.wait_for_work()
                while self._running:
                    row = await run_queue.claim_next(identity.instance_id())
                    if row is None:
                        break
                    asyncio.create_task(self._execute_claimed(row))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Run queue worker loop failed")
                await asyncio.sleep(1)

    async def _execute_claimed(self, row: WorkflowRunQueue) -> None:
        """Load the graph here rather than carrying it through the queue."""
        cancel_event = None
        # Imports included: anything raising outside this try strands the row.
        try:
            # Local: app.api.workflows imports dispatch_workflow.
            from app.api.workflows import (
                _persist_global_variables_from_execution,
                collect_referenced_workflows,
                get_credentials_context,
            )
            from app.db.session import async_session_maker
            from app.services.global_variables_service import get_global_variables_context
            from app.services.hitl_service import build_default_public_base_url

            # Without this the run is invisible to the cancel bus and to recovery.
            cancel_event = register_execution(
                workflow_id=row.workflow_id,
                execution_id=row.execution_id,
                inputs=row.inputs,
                trigger_source=row.trigger_source,
                actor_user_id=row.actor_user_id,
            )

            async with async_session_maker() as db:
                workflow = (
                    await db.execute(select(Workflow).where(Workflow.id == row.workflow_id))
                ).scalar_one_or_none()
                if workflow is None:
                    await run_queue.complete(
                        row.execution_id, result=None, error="Workflow no longer exists"
                    )
                    await run_queue.notify_done(row.execution_id)
                    return
                credentials_context = await get_credentials_context(db, row.credentials_owner_id)
                global_variables_context = await get_global_variables_context(
                    db, row.credentials_owner_id
                )
                workflow_cache = await collect_referenced_workflows(
                    db, workflow.nodes, actor_user_id=row.credentials_owner_id
                )
                nodes = list(workflow.nodes or [])
                edges = list(workflow.edges or [])
                owner_id = workflow.owner_id
                workflow_name = workflow.name

            result = await asyncio.to_thread(
                execute_workflow,
                workflow_id=row.workflow_id,
                nodes=nodes,
                edges=edges,
                inputs=row.inputs,
                workflow_cache=workflow_cache,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                public_base_url=build_default_public_base_url(),
                test_run=row.test_run,
                trace_user_id=owner_id,
                actor_user_id=row.actor_user_id,
                cancel_event=cancel_event,
                timeout_seconds=row.timeout_seconds,
                return_on_chart_output=row.return_on_chart_output,
                execution_id=str(row.execution_id),
            )
            # History is written here, on the instance that ran it, stamped with
            # this instance's label. The caller only ever sees the summary.
            if result.status == "pending":
                await persist_pending_run_history(
                    execution_id=row.execution_id,
                    workflow_id=row.workflow_id,
                    owner_id=owner_id,
                    workflow_name=workflow_name,
                    inputs=row.inputs,
                    trigger_source=row.trigger_source,
                    credentials_owner_id=row.credentials_owner_id,
                    result=result,
                )
            else:
                await persist_run_history(
                    execution_id=row.execution_id,
                    workflow_id=row.workflow_id,
                    owner_id=owner_id,
                    workflow_name=workflow_name,
                    inputs=row.inputs,
                    trigger_source=row.trigger_source,
                    result=result,
                )
                if row.credentials_owner_id is not None:
                    async with async_session_maker() as db:
                        await _persist_global_variables_from_execution(
                            db,
                            row.credentials_owner_id,
                            nodes,
                            workflow_cache,
                            result.node_results,
                            result.sub_workflow_executions,
                        )
                        await db.commit()
            await run_queue.complete(
                row.execution_id, result=summarize(result, row.execution_id), error=None
            )
        except Exception as exc:
            logger.exception("Claimed run failed")
            await run_queue.complete(row.execution_id, result=None, error=str(exc))
        finally:
            # Never let cleanup failure block notify_done; the caller is waiting.
            with contextlib.suppress(Exception):
                complete_execution(row.execution_id, workflow_id=row.workflow_id, result={})
            await run_queue.notify_done(row.execution_id)


run_queue_worker = RunQueueWorker()
