import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ExecutionCancellationHandle:
    workflow_id: uuid.UUID
    execution_id: uuid.UUID
    event: threading.Event
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_ACTIVE_EXECUTIONS: dict[uuid.UUID, ExecutionCancellationHandle] = {}
_LOCK = threading.Lock()


def register_execution(
    *,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    event: threading.Event | None = None,
) -> threading.Event:
    if event is None:
        event = threading.Event()
    handle = ExecutionCancellationHandle(
        workflow_id=workflow_id,
        execution_id=execution_id,
        event=event,
    )
    with _LOCK:
        _ACTIVE_EXECUTIONS[execution_id] = handle
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


def list_active_executions() -> list[ExecutionCancellationHandle]:
    """Return a snapshot of all currently active executions."""
    with _LOCK:
        return list(_ACTIVE_EXECUTIONS.values())
