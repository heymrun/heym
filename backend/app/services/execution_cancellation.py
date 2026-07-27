import asyncio
import contextlib
import logging
import os
import queue
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker

ACTIVE_EXECUTION_STALE_AFTER_SECONDS = 300
# Heartbeats stop the moment the owning worker dies; wait this long before
# treating a run as orphaned so a brief pause is not misread as a crash.
RECOVERY_STALE_AFTER_SECONDS = 60
_REGISTRY_POLL_SECONDS = 0.5
_REGISTRY_CLEANUP_SECONDS = 30.0

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


@dataclass
class ExecutionCancellationHandle:
    workflow_id: uuid.UUID
    execution_id: uuid.UUID
    event: threading.Event
    started_at: datetime = field(default_factory=_utcnow)
    inputs: dict = field(default_factory=dict)
    trigger_source: str | None = None
    actor_user_id: uuid.UUID | None = None
    recoverable: bool = True
    running_node_ids: set[str] = field(default_factory=set)
    node_results: list[dict[str, Any]] = field(default_factory=list)
    progress_version: int = 0
    synced_progress_version: int = 0


@dataclass(frozen=True)
class ActiveExecutionRecord:
    """Persisted active execution visible across API workers."""

    execution_id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    started_at: datetime
    inputs: dict = field(default_factory=dict)
    running_node_ids: list[str] = field(default_factory=list)
    node_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ClaimedOrphan:
    """An orphaned execution this worker has atomically claimed for recovery."""

    execution_id: uuid.UUID
    workflow_id: uuid.UUID
    inputs: dict
    trigger_source: str | None
    actor_user_id: uuid.UUID | None
    attempt: int


@dataclass(frozen=True)
class _RegistryCommand:
    action: Literal["start", "finish"]
    execution_id: uuid.UUID
    workflow_id: uuid.UUID | None = None
    started_at: datetime | None = None
    inputs: dict | None = None
    trigger_source: str | None = None
    actor_user_id: uuid.UUID | None = None
    recoverable: bool = True


_ACTIVE_EXECUTIONS: dict[uuid.UUID, ExecutionCancellationHandle] = {}
_LOCK = threading.Lock()


def register_execution(
    *,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    event: threading.Event | None = None,
    started_at: datetime | None = None,
    inputs: dict | None = None,
    trigger_source: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    recoverable: bool = True,
) -> threading.Event:
    if event is None:
        event = threading.Event()
    started_at = started_at or _utcnow()
    handle = ExecutionCancellationHandle(
        workflow_id=workflow_id,
        execution_id=execution_id,
        event=event,
        started_at=started_at,
        inputs=inputs or {},
        trigger_source=trigger_source,
        actor_user_id=actor_user_id,
        recoverable=recoverable,
    )
    with _LOCK:
        _ACTIVE_EXECUTIONS[execution_id] = handle
    active_execution_registry.record_started(handle)
    return event


def cancel_execution(*, workflow_id: uuid.UUID, execution_id: uuid.UUID) -> bool:
    with _LOCK:
        handle = _ACTIVE_EXECUTIONS.get(execution_id)
    if handle is None or handle.workflow_id != workflow_id:
        return False
    handle.event.set()
    return True


def clear_execution(execution_id: uuid.UUID) -> None:
    with _LOCK:
        _ACTIVE_EXECUTIONS.pop(execution_id, None)
    active_execution_registry.record_finished(execution_id)


def list_active_executions() -> list[ExecutionCancellationHandle]:
    """Return a snapshot of all currently active executions."""
    with _LOCK:
        return list(_ACTIVE_EXECUTIONS.values())


def get_active_execution_progress(
    execution_id: uuid.UUID,
    *,
    workflow_id: uuid.UUID,
) -> tuple[list[str], list[dict[str, Any]]] | None:
    """Return a thread-safe copy of one local execution's live node progress."""
    with _LOCK:
        handle = _ACTIVE_EXECUTIONS.get(execution_id)
        if handle is None or handle.workflow_id != workflow_id or handle.event.is_set():
            return None
        return sorted(handle.running_node_ids), list(handle.node_results)


def get_active_execution_inputs(
    execution_id: uuid.UUID,
    *,
    workflow_id: uuid.UUID,
) -> dict | None:
    """Return a thread-safe copy of one local execution's original inputs."""
    with _LOCK:
        handle = _ACTIVE_EXECUTIONS.get(execution_id)
        if handle is None or handle.workflow_id != workflow_id or handle.event.is_set():
            return None
        return dict(handle.inputs)


def record_execution_node_started(execution_id: str, node_id: str) -> None:
    """Record a node start in the cross-worker live execution snapshot."""
    try:
        parsed_execution_id = uuid.UUID(str(execution_id))
    except (TypeError, ValueError):
        return

    with _LOCK:
        handle = _ACTIVE_EXECUTIONS.get(parsed_execution_id)
        if handle is None:
            return
        normalized_node_id = str(node_id)
        if normalized_node_id not in handle.running_node_ids:
            handle.running_node_ids.add(normalized_node_id)
            handle.progress_version += 1


def record_execution_node_completed(
    execution_id: str,
    node_id: str,
    node_result: dict[str, Any],
) -> None:
    """Record a completed node so observers can stream the same log as the runner."""
    try:
        parsed_execution_id = uuid.UUID(str(execution_id))
    except (TypeError, ValueError):
        return

    with _LOCK:
        handle = _ACTIVE_EXECUTIONS.get(parsed_execution_id)
        if handle is None:
            return
        handle.running_node_ids.discard(str(node_id))
        handle.node_results.append(node_result)
        handle.progress_version += 1


class ActiveExecutionRegistry:
    """Persist local active execution state into Postgres for multi-worker visibility."""

    def __init__(self) -> None:
        self._commands: queue.Queue[_RegistryCommand] = queue.Queue()
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wakeup: asyncio.Event | None = None
        self._running = False
        self._next_cleanup_at = 0.0

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._wakeup = asyncio.Event()
        self._next_cleanup_at = time.monotonic()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Active execution registry started (worker_id=%s)", _WORKER_ID)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._loop = None
        self._wakeup = None
        with contextlib.suppress(Exception):
            await self._drain_commands()
        logger.info("Active execution registry stopped")

    def record_started(self, handle: ExecutionCancellationHandle) -> None:
        if not self._running:
            return
        self._commands.put(
            _RegistryCommand(
                action="start",
                execution_id=handle.execution_id,
                workflow_id=handle.workflow_id,
                started_at=handle.started_at,
                inputs=handle.inputs,
                trigger_source=handle.trigger_source,
                actor_user_id=handle.actor_user_id,
                recoverable=handle.recoverable,
            )
        )
        self._wake()

    def record_finished(self, execution_id: uuid.UUID) -> None:
        if not self._running:
            return
        self._commands.put(_RegistryCommand(action="finish", execution_id=execution_id))
        self._wake()

    def _wake(self) -> None:
        if self._loop is None or self._wakeup is None:
            return
        self._loop.call_soon_threadsafe(self._wakeup.set)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._drain_commands()
                await self._sync_local_handles()
                # Stale recoverable rows are now owned by the recovery service
                # (execution_recovery), which re-runs / skips / fails them instead
                # of silently deleting, so this loop no longer blind-deletes.
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Active execution registry sync failed")
            if self._wakeup is None:
                await asyncio.sleep(_REGISTRY_POLL_SECONDS)
                continue
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wakeup.wait(), timeout=_REGISTRY_POLL_SECONDS)
            self._wakeup.clear()

    async def _drain_commands(self) -> None:
        commands: list[_RegistryCommand] = []
        while True:
            try:
                commands.append(self._commands.get_nowait())
            except queue.Empty:
                break
        if not commands:
            return

        from sqlalchemy import delete
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.db.models import ActiveWorkflowExecution
        from app.db.session import async_session_maker

        now = _utcnow()
        async with async_session_maker() as session:
            for command in commands:
                if command.action == "finish":
                    await session.execute(
                        delete(ActiveWorkflowExecution).where(
                            ActiveWorkflowExecution.execution_id == command.execution_id
                        )
                    )
                    continue

                if command.workflow_id is None:
                    continue
                started_at = command.started_at or now
                stmt = (
                    pg_insert(ActiveWorkflowExecution)
                    .values(
                        execution_id=command.execution_id,
                        workflow_id=command.workflow_id,
                        worker_id=_WORKER_ID,
                        started_at=started_at,
                        heartbeat_at=now,
                        cancel_requested_at=None,
                        inputs=command.inputs or {},
                        trigger_source=command.trigger_source,
                        actor_user_id=command.actor_user_id,
                        attempt=0,
                        recoverable=command.recoverable,
                        running_node_ids=[],
                        node_results=[],
                    )
                    .on_conflict_do_update(
                        index_elements=["execution_id"],
                        # set_ intentionally omits `attempt` and `recoverable` so a
                        # recovery re-run (re-registering the same execution_id)
                        # preserves the claimed attempt count and recoverable flag.
                        set_={
                            "workflow_id": command.workflow_id,
                            "worker_id": _WORKER_ID,
                            "started_at": started_at,
                            "heartbeat_at": now,
                            "cancel_requested_at": None,
                            "inputs": command.inputs or {},
                            "trigger_source": command.trigger_source,
                            "actor_user_id": command.actor_user_id,
                            "running_node_ids": [],
                            "node_results": [],
                        },
                    )
                )
                await session.execute(stmt)
            await session.commit()

    async def _sync_local_handles(self) -> None:
        handles = list_active_executions()
        if not handles:
            return

        from sqlalchemy import select, update

        from app.db.models import ActiveWorkflowExecution
        from app.db.session import async_session_maker

        handles_by_id = {handle.execution_id: handle for handle in handles}
        execution_ids = list(handles_by_id)
        progress_snapshots: dict[
            uuid.UUID,
            tuple[ExecutionCancellationHandle, list[str], list[dict[str, Any]], int, bool],
        ] = {}
        with _LOCK:
            for execution_id, listed_handle in handles_by_id.items():
                current_handle = _ACTIVE_EXECUTIONS.get(execution_id)
                if current_handle is not listed_handle:
                    continue
                progress_changed = (
                    current_handle.progress_version != current_handle.synced_progress_version
                )
                progress_snapshots[execution_id] = (
                    current_handle,
                    sorted(current_handle.running_node_ids) if progress_changed else [],
                    list(current_handle.node_results) if progress_changed else [],
                    current_handle.progress_version,
                    progress_changed,
                )
        now = _utcnow()
        async with async_session_maker() as session:
            cancel_result = await session.execute(
                select(ActiveWorkflowExecution.execution_id).where(
                    ActiveWorkflowExecution.execution_id.in_(execution_ids),
                    ActiveWorkflowExecution.cancel_requested_at.is_not(None),
                )
            )
            cancelled_ids = list(cancel_result.scalars().all())
            for execution_id, snapshot in progress_snapshots.items():
                _handle, running_node_ids, node_results, _version, progress_changed = snapshot
                update_values: dict[str, Any] = {
                    "heartbeat_at": now,
                    "worker_id": _WORKER_ID,
                }
                if progress_changed:
                    update_values.update(
                        running_node_ids=running_node_ids,
                        node_results=node_results,
                    )
                await session.execute(
                    update(ActiveWorkflowExecution)
                    .where(ActiveWorkflowExecution.execution_id == execution_id)
                    .values(**update_values)
                )
            await session.commit()

        with _LOCK:
            for execution_id, snapshot in progress_snapshots.items():
                snapshotted_handle, _running, _results, version, progress_changed = snapshot
                if not progress_changed:
                    continue
                current_handle = _ACTIVE_EXECUTIONS.get(execution_id)
                if current_handle is snapshotted_handle:
                    current_handle.synced_progress_version = max(
                        current_handle.synced_progress_version,
                        version,
                    )

        for execution_id in cancelled_ids:
            handle = handles_by_id.get(execution_id)
            if handle is not None:
                handle.event.set()


async def request_persisted_execution_cancel(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
) -> bool:
    """Mark a running execution as cancelled so its owning worker can stop it."""
    from sqlalchemy import update

    from app.db.models import ActiveWorkflowExecution

    result = await db.execute(
        update(ActiveWorkflowExecution)
        .where(
            ActiveWorkflowExecution.workflow_id == workflow_id,
            ActiveWorkflowExecution.execution_id == execution_id,
        )
        .values(cancel_requested_at=_utcnow())
    )
    await db.commit()
    return bool(result.rowcount or 0)


async def cleanup_stale_persisted_executions() -> int:
    """Remove active rows whose worker has stopped heartbeating."""
    from sqlalchemy import delete

    from app.db.models import ActiveWorkflowExecution
    from app.db.session import async_session_maker

    cutoff = _utcnow() - timedelta(seconds=ACTIVE_EXECUTION_STALE_AFTER_SECONDS)
    async with async_session_maker() as session:
        result = await session.execute(
            delete(ActiveWorkflowExecution).where(ActiveWorkflowExecution.heartbeat_at < cutoff)
        )
        await session.commit()
    return result.rowcount or 0


async def mark_own_executions_orphaned() -> int:
    """Backdate this worker's recoverable rows so the next leader recovers them now."""
    from sqlalchemy import update

    from app.db.models import ActiveWorkflowExecution

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    async with async_session_maker() as session:
        result = await session.execute(
            update(ActiveWorkflowExecution)
            .where(
                ActiveWorkflowExecution.worker_id == _WORKER_ID,
                ActiveWorkflowExecution.recoverable.is_(True),
            )
            .values(heartbeat_at=epoch)
        )
        await session.commit()
    return result.rowcount or 0


async def claim_orphaned_executions(*, now: datetime | None = None) -> list["ClaimedOrphan"]:
    """Atomically claim recoverable rows whose heartbeat is stale; return the winners."""
    from sqlalchemy import select, update

    from app.db.models import ActiveWorkflowExecution

    now = now or _utcnow()
    cutoff = now - timedelta(seconds=RECOVERY_STALE_AFTER_SECONDS)
    claimed: list[ClaimedOrphan] = []
    async with async_session_maker() as session:
        candidates = (
            await session.execute(
                select(
                    ActiveWorkflowExecution.execution_id,
                    ActiveWorkflowExecution.workflow_id,
                    ActiveWorkflowExecution.inputs,
                    ActiveWorkflowExecution.trigger_source,
                    ActiveWorkflowExecution.actor_user_id,
                    ActiveWorkflowExecution.attempt,
                ).where(
                    ActiveWorkflowExecution.recoverable.is_(True),
                    ActiveWorkflowExecution.heartbeat_at < cutoff,
                )
            )
        ).all()
        for row in candidates:
            result = await session.execute(
                update(ActiveWorkflowExecution)
                .where(
                    ActiveWorkflowExecution.execution_id == row.execution_id,
                    ActiveWorkflowExecution.heartbeat_at < cutoff,
                )
                .values(worker_id=_WORKER_ID, heartbeat_at=now, attempt=row.attempt + 1)
            )
            if (result.rowcount or 0) == 1:
                claimed.append(
                    ClaimedOrphan(
                        execution_id=row.execution_id,
                        workflow_id=row.workflow_id,
                        inputs=row.inputs or {},
                        trigger_source=row.trigger_source,
                        actor_user_id=row.actor_user_id,
                        attempt=row.attempt + 1,
                    )
                )
        await session.commit()
    return claimed


async def list_persisted_active_executions_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[ActiveExecutionRecord]:
    """Return active execution rows for workflows accessible to the user."""
    from sqlalchemy import or_, select

    from app.db.models import ActiveWorkflowExecution, Workflow, WorkflowShare

    cutoff = _utcnow() - timedelta(seconds=ACTIVE_EXECUTION_STALE_AFTER_SECONDS)
    result = await db.execute(
        select(
            ActiveWorkflowExecution.execution_id,
            ActiveWorkflowExecution.workflow_id,
            ActiveWorkflowExecution.started_at,
            Workflow.name,
            ActiveWorkflowExecution.inputs,
            ActiveWorkflowExecution.running_node_ids,
            ActiveWorkflowExecution.node_results,
        )
        .join(Workflow, Workflow.id == ActiveWorkflowExecution.workflow_id)
        .where(
            ActiveWorkflowExecution.heartbeat_at >= cutoff,
            ActiveWorkflowExecution.cancel_requested_at.is_(None),
            or_(
                Workflow.owner_id == user_id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == user_id)
                ),
            ),
        )
        .order_by(ActiveWorkflowExecution.started_at.desc())
    )

    return [
        ActiveExecutionRecord(
            execution_id=row.execution_id,
            workflow_id=row.workflow_id,
            workflow_name=row.name,
            started_at=row.started_at,
            inputs=dict(row.inputs or {}),
            running_node_ids=list(row.running_node_ids or []),
            node_results=list(row.node_results or []),
        )
        for row in result.all()
    ]


@dataclass(frozen=True)
class PendingReviewExecutionRecord:
    """Execution waiting on HITL or Codex human input."""

    execution_id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    started_at: datetime
    inputs: dict = field(default_factory=dict)
    node_results: list[dict[str, Any]] = field(default_factory=list)
    pending_kind: Literal["hitl", "codex"] = "hitl"


async def list_pending_review_executions_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[PendingReviewExecutionRecord]:
    """Return non-expired pending HITL/Codex review executions for accessible workflows."""
    from sqlalchemy import literal, or_, select, union_all

    from app.db.models import (
        CodexFollowupRequest,
        ExecutionHistory,
        HITLRequest,
        Workflow,
        WorkflowShare,
    )

    now = _utcnow()
    accessible_workflow = or_(
        Workflow.owner_id == user_id,
        Workflow.id.in_(select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == user_id)),
    )

    hitl_stmt = (
        select(
            HITLRequest.execution_history_id.label("execution_id"),
            HITLRequest.workflow_id.label("workflow_id"),
            HITLRequest.workflow_name.label("workflow_name"),
            ExecutionHistory.started_at.label("started_at"),
            ExecutionHistory.inputs.label("inputs"),
            ExecutionHistory.node_results.label("node_results"),
            literal("hitl").label("pending_kind"),
        )
        .join(ExecutionHistory, ExecutionHistory.id == HITLRequest.execution_history_id)
        .join(Workflow, Workflow.id == HITLRequest.workflow_id)
        .where(
            HITLRequest.status == "pending",
            HITLRequest.expires_at >= now,
            accessible_workflow,
        )
    )
    codex_stmt = (
        select(
            CodexFollowupRequest.execution_history_id.label("execution_id"),
            CodexFollowupRequest.workflow_id.label("workflow_id"),
            CodexFollowupRequest.workflow_name.label("workflow_name"),
            ExecutionHistory.started_at.label("started_at"),
            ExecutionHistory.inputs.label("inputs"),
            ExecutionHistory.node_results.label("node_results"),
            literal("codex").label("pending_kind"),
        )
        .join(
            ExecutionHistory,
            ExecutionHistory.id == CodexFollowupRequest.execution_history_id,
        )
        .join(Workflow, Workflow.id == CodexFollowupRequest.workflow_id)
        .where(
            CodexFollowupRequest.status == "pending",
            CodexFollowupRequest.expires_at >= now,
            accessible_workflow,
        )
    )

    result = await db.execute(union_all(hitl_stmt, codex_stmt))

    records: list[PendingReviewExecutionRecord] = []
    seen: set[uuid.UUID] = set()
    for row in result.all():
        execution_id = row.execution_id
        if execution_id in seen:
            continue
        seen.add(execution_id)
        kind: Literal["hitl", "codex"] = "codex" if row.pending_kind == "codex" else "hitl"
        records.append(
            PendingReviewExecutionRecord(
                execution_id=execution_id,
                workflow_id=row.workflow_id,
                workflow_name=row.workflow_name,
                started_at=row.started_at,
                inputs=dict(row.inputs or {}),
                node_results=list(row.node_results or []),
                pending_kind=kind,
            )
        )
    records.sort(key=lambda item: item.started_at, reverse=True)
    return records


active_execution_registry = ActiveExecutionRegistry()
