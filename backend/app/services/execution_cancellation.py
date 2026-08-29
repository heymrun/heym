import asyncio
import contextlib
import copy
import json
import logging
import math
import os
import queue
import socket
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterator
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
# The registry loop retries every 0.5s, so an unhealthy database would otherwise
# emit two tracebacks a second. Report the first failure per scope immediately and
# then at most once a minute, with the suppressed count.
_REGISTRY_FAILURE_LOG_INTERVAL_SECONDS = 60.0
# Start/finish commands are replayed until the database accepts them; cap the
# backlog so a permanently unreachable database cannot grow it without bound.
_MAX_PENDING_REGISTRY_COMMANDS = 2000
# Replays happen every _REGISTRY_POLL_SECONDS, so this is ~60s of retrying: long
# enough to ride out a database restart, short enough that a command which can
# never be written (corrupt row, missing workflow) is dropped instead of spinning
# forever and holding back the finish that follows it.
_MAX_REGISTRY_COMMAND_ATTEMPTS = 120
# Live SSE events kept per execution so a canvas that attaches mid-run replays the
# same stream the runner emitted (agent tool progress, sub-agent node lifecycle).
# Bounded by both count and total bytes: the oldest events are dropped first.
MAX_PROGRESS_EVENTS = 2000
MAX_PROGRESS_EVENT_BYTES = 8 * 1024 * 1024
# A single oversized payload (large node output) is buffered without its payload
# fields; the full value still reaches the canvas with the final history entry.
MAX_PROGRESS_EVENT_PAYLOAD_BYTES = 256 * 1024
# Canvas test runs deliberately do not create persistent ExecutionHistory rows. Keep their final
# SSE payload briefly so another tab already observing the run can still receive its result.
TERMINAL_EXECUTION_RESULT_TTL_SECONDS = 60.0
MAX_TERMINAL_EXECUTION_RESULTS = 500
# Events the observer synthesizes itself, plus executor-internal plumbing that is
# not JSON serializable.
_UNBUFFERED_EVENT_TYPES = frozenset({"execution_started", "execution_complete"})

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
    running_node_started_at_ms: dict[str, float] = field(default_factory=dict)
    node_results: list[dict[str, Any]] = field(default_factory=list)
    progress_version: int = 0
    synced_progress_version: int = 0
    publishes_progress_events: bool = False
    progress_events: deque[tuple[int, str]] = field(default_factory=deque)
    progress_event_bytes: int = 0
    next_progress_event_seq: int = 0
    dropped_progress_events: int = 0


@dataclass(frozen=True)
class ActiveExecutionStreamSnapshot:
    """Atomic view of one execution's live progress, taken under the registry lock."""

    publishes_progress_events: bool
    running_node_ids: list[str]
    running_node_started_at_ms: dict[str, float]
    node_results: list[dict[str, Any]]
    events: list[str]
    next_event_seq: int
    dropped_event_count: int


@dataclass(frozen=True)
class CompletedExecutionResult:
    """Short-lived terminal result for a non-persisted execution."""

    workflow_id: uuid.UUID
    result: dict[str, Any]
    completed_at: float


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
_COMPLETED_EXECUTIONS: dict[uuid.UUID, CompletedExecutionResult] = {}
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
        _COMPLETED_EXECUTIONS.pop(execution_id, None)
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
        _COMPLETED_EXECUTIONS.pop(execution_id, None)
    active_execution_registry.record_finished(execution_id)


def complete_execution(
    execution_id: uuid.UUID,
    *,
    workflow_id: uuid.UUID,
    result: dict[str, Any],
) -> None:
    """Finish a non-persisted run while retaining its final SSE payload briefly."""

    now = time.monotonic()
    with _LOCK:
        _ACTIVE_EXECUTIONS.pop(execution_id, None)
        _purge_expired_completed_executions(now)
        _COMPLETED_EXECUTIONS[execution_id] = CompletedExecutionResult(
            workflow_id=workflow_id,
            result=copy.deepcopy(result),
            completed_at=now,
        )
        while len(_COMPLETED_EXECUTIONS) > MAX_TERMINAL_EXECUTION_RESULTS:
            oldest_execution_id = next(iter(_COMPLETED_EXECUTIONS))
            _COMPLETED_EXECUTIONS.pop(oldest_execution_id, None)
    active_execution_registry.record_finished(execution_id)


def get_completed_execution_result(
    execution_id: uuid.UUID,
    *,
    workflow_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Return a terminal payload while its short cross-tab handoff window is open."""

    with _LOCK:
        _purge_expired_completed_executions(time.monotonic())
        completed = _COMPLETED_EXECUTIONS.get(execution_id)
        if completed is None or completed.workflow_id != workflow_id:
            return None
        return copy.deepcopy(completed.result)


def _purge_expired_completed_executions(now: float) -> None:
    expired_ids = [
        execution_id
        for execution_id, completed in _COMPLETED_EXECUTIONS.items()
        if now - completed.completed_at >= TERMINAL_EXECUTION_RESULT_TTL_SECONDS
    ]
    for execution_id in expired_ids:
        _COMPLETED_EXECUTIONS.pop(execution_id, None)


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


def record_execution_node_started(
    execution_id: str,
    node_id: str,
    *,
    started_at_ms: float | None = None,
) -> None:
    """Record a node start in the cross-worker live execution snapshot."""
    try:
        parsed_execution_id = uuid.UUID(str(execution_id))
    except (TypeError, ValueError):
        return

    if (
        isinstance(started_at_ms, bool)
        or not isinstance(started_at_ms, (int, float))
        or not math.isfinite(started_at_ms)
    ):
        started_at_ms = time.time() * 1000

    with _LOCK:
        handle = _ACTIVE_EXECUTIONS.get(parsed_execution_id)
        if handle is None:
            return
        normalized_node_id = str(node_id)
        if normalized_node_id not in handle.running_node_ids:
            handle.running_node_ids.add(normalized_node_id)
            handle.running_node_started_at_ms[normalized_node_id] = float(started_at_ms)
            handle.progress_version += 1
        elif normalized_node_id not in handle.running_node_started_at_ms:
            handle.running_node_started_at_ms[normalized_node_id] = float(started_at_ms)
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
        handle.running_node_started_at_ms.pop(str(node_id), None)
        handle.node_results.append(node_result)
        handle.progress_version += 1


def mark_execution_publishes_progress_events(execution_id: str) -> None:
    """Flag a run as emitting live SSE events so observers stream them instead of polling."""
    handle = _handle_for_execution_id(execution_id)
    if handle is None:
        return
    with _LOCK:
        handle.publishes_progress_events = True


def _serialize_progress_event(event: dict[str, Any]) -> str | None:
    try:
        payload = json.dumps(event)
    except (TypeError, ValueError):
        return None
    if len(payload) <= MAX_PROGRESS_EVENT_PAYLOAD_BYTES:
        return payload
    # Keep the node lifecycle (type/id/label/status) and drop the bulky payload
    # fields so one large output cannot dominate the buffer.
    trimmed: dict[str, Any] = {
        key: value
        for key, value in event.items()
        if value is None or isinstance(value, (str, int, float, bool))
    }
    trimmed["_truncated"] = True
    try:
        return json.dumps(trimmed)
    except (TypeError, ValueError):
        return None


def record_execution_progress_event(execution_id: str, event: dict[str, Any]) -> None:
    """Buffer one live SSE event so other tabs can replay the runner's stream."""
    event_type = event.get("type")
    if not isinstance(event_type, str) or event_type.startswith("_"):
        return
    if event_type in _UNBUFFERED_EVENT_TYPES:
        return
    handle = _handle_for_execution_id(execution_id)
    if handle is None:
        return
    payload = _serialize_progress_event(event)
    if payload is None:
        logger.debug("Skipping non-serializable live event %s", event_type)
        return

    with _LOCK:
        events = handle.progress_events
        events.append((handle.next_progress_event_seq, payload))
        handle.next_progress_event_seq += 1
        handle.progress_event_bytes += len(payload)
        while events and (
            len(events) > MAX_PROGRESS_EVENTS
            or handle.progress_event_bytes > MAX_PROGRESS_EVENT_BYTES
        ):
            _seq, dropped_payload = events.popleft()
            handle.progress_event_bytes -= len(dropped_payload)
            handle.dropped_progress_events += 1


def buffer_live_execution_events(
    events: Iterator[dict[str, Any]],
    execution_id: str,
) -> Iterator[dict[str, Any]]:
    """Pass a runner's SSE events through while recording them for late observers."""
    mark_execution_publishes_progress_events(execution_id)
    for event in events:
        record_execution_progress_event(execution_id, event)
        yield event


def get_active_execution_stream_snapshot(
    execution_id: uuid.UUID,
    *,
    workflow_id: uuid.UUID,
) -> ActiveExecutionStreamSnapshot | None:
    """Return node progress and the buffered live events in one consistent read."""
    with _LOCK:
        handle = _ACTIVE_EXECUTIONS.get(execution_id)
        if handle is None or handle.workflow_id != workflow_id or handle.event.is_set():
            return None
        return ActiveExecutionStreamSnapshot(
            publishes_progress_events=handle.publishes_progress_events,
            running_node_ids=sorted(handle.running_node_ids),
            running_node_started_at_ms=dict(handle.running_node_started_at_ms),
            node_results=list(handle.node_results),
            events=[payload for _seq, payload in handle.progress_events],
            next_event_seq=handle.next_progress_event_seq,
            dropped_event_count=handle.dropped_progress_events,
        )


def get_active_execution_events(
    execution_id: uuid.UUID,
    *,
    workflow_id: uuid.UUID,
    after_seq: int,
) -> tuple[list[str], int] | None:
    """Return live events newer than ``after_seq`` plus the next cursor value."""
    with _LOCK:
        handle = _ACTIVE_EXECUTIONS.get(execution_id)
        if handle is None or handle.workflow_id != workflow_id or handle.event.is_set():
            return None
        payloads = [payload for seq, payload in handle.progress_events if seq >= after_seq]
        return payloads, handle.next_progress_event_seq


def _handle_for_execution_id(execution_id: str) -> ExecutionCancellationHandle | None:
    try:
        parsed_execution_id = uuid.UUID(str(execution_id))
    except (TypeError, ValueError):
        return None
    with _LOCK:
        return _ACTIVE_EXECUTIONS.get(parsed_execution_id)


class _ThrottledFailureLog:
    """Report the first failure per scope, then at most once a minute with a count.

    The registry and the orphan sweep both retry on short timers, so an unhealthy
    row would otherwise emit a traceback every tick. ``scope`` must come from a
    fixed vocabulary (never an execution id) so the bookkeeping stays bounded.
    """

    def __init__(self, interval_seconds: float = _REGISTRY_FAILURE_LOG_INTERVAL_SECONDS) -> None:
        self._interval_seconds = interval_seconds
        self._counts: dict[str, int] = {}
        self._logged_at: dict[str, float] = {}

    def failure(self, scope: str, exc: BaseException, detail: str = "") -> None:
        now = time.monotonic()
        self._counts[scope] = self._counts.get(scope, 0) + 1
        last_logged_at = self._logged_at.get(scope)
        if last_logged_at is not None and now - last_logged_at < self._interval_seconds:
            return
        self._logged_at[scope] = now
        occurrences = self._counts[scope]
        self._counts[scope] = 0
        logger.error(
            "Active execution registry %s failed%s (%d occurrence(s) since last report)",
            scope,
            f" [{detail}]" if detail else "",
            occurrences,
            exc_info=exc,
        )

    def success(self, scope: str) -> None:
        """Announce recovery once, so a healed database is visible in the log."""
        if self._logged_at.pop(scope, None) is None:
            self._counts.pop(scope, None)
            return
        suppressed = self._counts.pop(scope, 0)
        logger.info(
            "Active execution registry %s recovered (%d suppressed failure(s))",
            scope,
            suppressed,
        )

    def suppressed_count(self, scope: str) -> int:
        return self._counts.get(scope, 0)

    def reset(self) -> None:
        self._counts.clear()
        self._logged_at.clear()


# The orphan sweep runs from execution_recovery on its own 15s timer, outside any
# registry instance, so it keeps its own throttle state.
_claim_failures = _ThrottledFailureLog()


def _build_active_execution_upsert(
    *,
    execution_id: uuid.UUID,
    workflow_id: uuid.UUID,
    started_at: datetime,
    heartbeat_at: datetime,
    inputs: dict,
    trigger_source: str | None,
    actor_user_id: uuid.UUID | None,
    recoverable: bool,
    running_node_ids: list[str],
    running_node_started_at_ms: dict[str, float],
    node_results: list[dict[str, Any]],
) -> Any:
    """Insert-or-refresh one active execution row.

    ``set_`` intentionally omits ``attempt`` and ``recoverable`` so a recovery
    re-run (re-registering the same execution_id) preserves the claimed attempt
    count and recoverable flag.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.db.models import ActiveWorkflowExecution

    shared_values: dict[str, Any] = {
        "workflow_id": workflow_id,
        "worker_id": _WORKER_ID,
        "started_at": started_at,
        "heartbeat_at": heartbeat_at,
        "cancel_requested_at": None,
        "inputs": inputs,
        "trigger_source": trigger_source,
        "actor_user_id": actor_user_id,
        "running_node_ids": running_node_ids,
        "running_node_started_at_ms": running_node_started_at_ms,
        "node_results": node_results,
    }
    return (
        pg_insert(ActiveWorkflowExecution)
        .values(
            execution_id=execution_id,
            attempt=0,
            recoverable=recoverable,
            **shared_values,
        )
        .on_conflict_do_update(index_elements=["execution_id"], set_=shared_values)
    )


class ActiveExecutionRegistry:
    """Persist local active execution state into Postgres for multi-worker visibility."""

    def __init__(self) -> None:
        self._commands: queue.Queue[_RegistryCommand] = queue.Queue()
        self._pending: list[_RegistryCommand] = []
        self._command_attempts: dict[tuple[str, uuid.UUID], int] = {}
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wakeup: asyncio.Event | None = None
        self._running = False
        self._next_cleanup_at = 0.0
        self._failures = _ThrottledFailureLog()

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
        self._failures.reset()
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
            except Exception as exc:
                self._failures.failure("sync loop", exc)
            if self._wakeup is None:
                await asyncio.sleep(_REGISTRY_POLL_SECONDS)
                continue
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wakeup.wait(), timeout=_REGISTRY_POLL_SECONDS)
            self._wakeup.clear()

    async def _apply_command(self, session: Any, command: _RegistryCommand, now: datetime) -> None:
        from sqlalchemy import delete

        from app.db.models import ActiveWorkflowExecution

        if command.action == "finish":
            await session.execute(
                delete(ActiveWorkflowExecution).where(
                    ActiveWorkflowExecution.execution_id == command.execution_id
                )
            )
            return
        if command.workflow_id is None:
            return
        await session.execute(
            _build_active_execution_upsert(
                execution_id=command.execution_id,
                workflow_id=command.workflow_id,
                started_at=command.started_at or now,
                heartbeat_at=now,
                inputs=command.inputs or {},
                trigger_source=command.trigger_source,
                actor_user_id=command.actor_user_id,
                recoverable=command.recoverable,
                running_node_ids=[],
                running_node_started_at_ms={},
                node_results=[],
            )
        )

    async def _drain_commands(self) -> None:
        while True:
            try:
                self._pending.append(self._commands.get_nowait())
            except queue.Empty:
                break
        if not self._pending:
            return
        if len(self._pending) > _MAX_PENDING_REGISTRY_COMMANDS:
            overflow = len(self._pending) - _MAX_PENDING_REGISTRY_COMMANDS
            self._pending = self._pending[overflow:]
            logger.warning(
                "Dropped %d buffered active execution registry command(s); database backlog too long",
                overflow,
            )

        from app.db.session import async_session_maker

        # A command that cannot be written must not be lost: it is kept and replayed
        # on the next tick, otherwise a single transient database error permanently
        # hides a running execution (lost "start") or leaves a phantom row (lost
        # "finish") until the stale-row sweep.
        commands, self._pending = self._pending, []
        deferred: list[_RegistryCommand] = []
        deferred_execution_ids: set[uuid.UUID] = set()
        now = _utcnow()
        try:
            async with async_session_maker() as session:
                for command in commands:
                    # Ordering matters per execution: once one command is deferred,
                    # every later command for the same execution must wait with it.
                    if command.execution_id in deferred_execution_ids:
                        deferred.append(command)
                        continue
                    try:
                        async with session.begin_nested():
                            await self._apply_command(session, command, now)
                    except Exception as exc:
                        key = (command.action, command.execution_id)
                        attempts = self._command_attempts.get(key, 0) + 1
                        self._failures.failure(
                            "command flush",
                            exc,
                            f"{command.action} {command.execution_id} attempt {attempts}",
                        )
                        if attempts >= _MAX_REGISTRY_COMMAND_ATTEMPTS:
                            # Give up on this one rather than replaying it forever and
                            # blocking every later command for the same execution.
                            self._command_attempts.pop(key, None)
                            logger.error(
                                "Dropping active execution registry %s for %s after %d "
                                "failed attempts; the row may be stale until the sweep "
                                "clears it",
                                command.action,
                                command.execution_id,
                                attempts,
                            )
                            continue
                        self._command_attempts[key] = attempts
                        deferred.append(command)
                        deferred_execution_ids.add(command.execution_id)
                    else:
                        self._command_attempts.pop((command.action, command.execution_id), None)
                await session.commit()
        except Exception:
            self._pending = commands + self._pending
            raise
        self._pending = deferred + self._pending
        if not deferred:
            self._failures.success("command flush")

    async def _reinsert_missing_row(
        self,
        session: Any,
        execution_id: uuid.UUID,
        handle: ExecutionCancellationHandle,
        now: datetime,
    ) -> int | None:
        """Recreate a registry row that vanished while its execution is still running.

        The stale-row sweep, a manual cleanup, or a repaired table all delete rows out
        from under live runs. Without this the heartbeat UPDATE would silently match
        nothing forever and the execution would stay invisible to every other worker.
        Returns the progress version now persisted, or ``None`` if the run has ended.
        """
        with _LOCK:
            if _ACTIVE_EXECUTIONS.get(execution_id) is not handle:
                return None
            running_node_ids = sorted(handle.running_node_ids)
            running_node_started_at_ms = dict(handle.running_node_started_at_ms)
            node_results = list(handle.node_results)
            version = handle.progress_version
        await session.execute(
            _build_active_execution_upsert(
                execution_id=execution_id,
                workflow_id=handle.workflow_id,
                started_at=handle.started_at,
                heartbeat_at=now,
                inputs=dict(handle.inputs),
                trigger_source=handle.trigger_source,
                actor_user_id=handle.actor_user_id,
                recoverable=handle.recoverable,
                running_node_ids=running_node_ids,
                running_node_started_at_ms=running_node_started_at_ms,
                node_results=node_results,
            )
        )
        logger.info("Recreated missing active execution registry row for %s", execution_id)
        return version

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
            tuple[
                ExecutionCancellationHandle,
                list[str],
                dict[str, float],
                list[dict[str, Any]],
                int,
                bool,
            ],
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
                    dict(current_handle.running_node_started_at_ms) if progress_changed else {},
                    list(current_handle.node_results) if progress_changed else [],
                    current_handle.progress_version,
                    progress_changed,
                )
        now = _utcnow()
        cancelled_ids: list[uuid.UUID] = []
        # (execution_id, handle, synced_version) for the rows this tick actually wrote.
        synced: list[tuple[uuid.UUID, ExecutionCancellationHandle, int]] = []
        heartbeat_failures = 0
        async with async_session_maker() as session:
            try:
                async with session.begin_nested():
                    cancel_result = await session.execute(
                        select(ActiveWorkflowExecution.execution_id).where(
                            ActiveWorkflowExecution.execution_id.in_(execution_ids),
                            ActiveWorkflowExecution.cancel_requested_at.is_not(None),
                        )
                    )
                    cancelled_ids = list(cancel_result.scalars().all())
            except Exception as exc:
                self._failures.failure("cancel poll", exc)
            else:
                self._failures.success("cancel poll")

            for execution_id, snapshot in progress_snapshots.items():
                (
                    handle,
                    running_node_ids,
                    running_node_started_at_ms,
                    node_results,
                    version,
                    progress_changed,
                ) = snapshot
                update_values: dict[str, Any] = {
                    "heartbeat_at": now,
                    "worker_id": _WORKER_ID,
                }
                if progress_changed:
                    update_values.update(
                        running_node_ids=running_node_ids,
                        running_node_started_at_ms=running_node_started_at_ms,
                        node_results=node_results,
                    )
                # Each row gets its own savepoint: a single unwritable row (a corrupt
                # page, a lock timeout) must not abort the heartbeats of every other
                # execution on this worker, which would make them all look orphaned.
                try:
                    async with session.begin_nested():
                        result = await session.execute(
                            update(ActiveWorkflowExecution)
                            .where(ActiveWorkflowExecution.execution_id == execution_id)
                            .values(**update_values)
                        )
                        if (result.rowcount or 0) == 0:
                            version = await self._reinsert_missing_row(
                                session, execution_id, handle, now
                            )
                            if version is None:
                                continue
                except Exception as exc:
                    heartbeat_failures += 1
                    self._failures.failure("heartbeat sync", exc, str(execution_id))
                    continue
                synced.append((execution_id, handle, version))
            try:
                await session.commit()
            except Exception as exc:
                self._failures.failure("heartbeat sync", exc, "commit")
                return
        if heartbeat_failures == 0:
            self._failures.success("heartbeat sync")

        with _LOCK:
            for execution_id, snapshotted_handle, version in synced:
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
    """Mark a running execution as cancelled and broadcast the stop to every worker.

    The row update is only the durable record (it drives the dashboard filter and
    the registry's fallback poll). Delivery is the broadcast, so the update runs in
    its own savepoint: an unwritable registry row must not swallow the cancel.

    Returns False only when the row is provably absent, since that is the one case
    where the caller can honestly report "not found". A failed update leaves the
    state unknown, and the broadcast has gone out regardless.
    """
    from sqlalchemy import update

    from app.db.models import ActiveWorkflowExecution
    from app.services.execution_cancel_bus import publish_execution_cancel

    marked_rows: int | None = None
    try:
        async with db.begin_nested():
            result = await db.execute(
                update(ActiveWorkflowExecution)
                .where(
                    ActiveWorkflowExecution.workflow_id == workflow_id,
                    ActiveWorkflowExecution.execution_id == execution_id,
                )
                .values(cancel_requested_at=_utcnow())
            )
            marked_rows = result.rowcount or 0
    except Exception:
        logger.warning(
            "Could not record cancel for execution %s; broadcasting anyway",
            execution_id,
            exc_info=True,
        )

    await publish_execution_cancel(db, workflow_id=workflow_id, execution_id=execution_id)
    await db.commit()
    return marked_rows is None or marked_rows > 0


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
                # Never hand a cancelled run to recovery on shutdown.
                ActiveWorkflowExecution.cancel_requested_at.is_(None),
            )
            .values(heartbeat_at=epoch)
        )
        await session.commit()
    return result.rowcount or 0


async def claim_orphaned_executions(*, now: datetime | None = None) -> list["ClaimedOrphan"]:
    """Atomically claim recoverable rows whose heartbeat is stale; return the winners.

    Every claim runs in its own savepoint. Without that, one unreadable or locked row
    aborts the shared transaction and no orphan anywhere in the deployment can be
    recovered for as long as the row stays broken.
    """
    from sqlalchemy import select, update

    from app.db.models import ActiveWorkflowExecution

    now = now or _utcnow()
    cutoff = now - timedelta(seconds=RECOVERY_STALE_AFTER_SECONDS)
    claimed: list[ClaimedOrphan] = []
    skipped = 0
    async with async_session_maker() as session:
        try:
            async with session.begin_nested():
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
                            # A cancelled run is not an orphan. Its row only survives
                            # because the finish DELETE could not be written, and
                            # re-running work the user explicitly stopped is worse
                            # than leaving the row for the stale sweep to clear.
                            ActiveWorkflowExecution.cancel_requested_at.is_(None),
                        )
                    )
                ).all()
        except Exception as exc:
            # Nothing can be enumerated, so nothing can be recovered this tick. This
            # is the signature of an unreadable active_workflow_executions row: it
            # matches the stale predicate forever and blinds every later sweep too.
            _claim_failures.failure("orphan candidate scan", exc)
            return []
        _claim_failures.success("orphan candidate scan")

        for row in candidates:
            try:
                async with session.begin_nested():
                    result = await session.execute(
                        update(ActiveWorkflowExecution)
                        .where(
                            ActiveWorkflowExecution.execution_id == row.execution_id,
                            ActiveWorkflowExecution.heartbeat_at < cutoff,
                        )
                        .values(worker_id=_WORKER_ID, heartbeat_at=now, attempt=row.attempt + 1)
                    )
            except Exception as exc:
                skipped += 1
                _claim_failures.failure("orphan claim", exc, str(row.execution_id))
                continue
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
    if skipped == 0:
        _claim_failures.success("orphan claim")
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
