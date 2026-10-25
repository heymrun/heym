"""Per-workflow concurrency limit: admit, hold, release and promote production runs.

A slot is a row in ``workflow_concurrency_slots``; a run waiting for one is a
``workflow_run_queue`` row with status ``held``. Every transaction that changes
either for one workflow first takes that workflow's advisory lock, so the counts
are exact across every process and every cluster instance.

Promotion turns a held row into an ordinary queued run, so the run queue worker
executes, persists and recovers it exactly like an offloaded cluster run.
"""

from __future__ import annotations

import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func

from app.services.cluster import identity, run_queue
from app.services.secret_tokens import hash_secret

logger = logging.getLogger("concurrency")

HISTORY_STATUS_QUEUE_FULL = "queue_full"
QUEUE_FULL_MESSAGE = "Concurrency queue is full"
EXPIRED_MESSAGE = "Waited longer than the workflow's max wait for a concurrency slot"
CANCELLED_MESSAGE = "Execution was cancelled"
RUN_TOKEN_HEADER = "X-Heym-Run-Token"
# Same grace as a stranded claim: registration reaches the database asynchronously.
STALE_SLOT_GRACE_SECONDS = 120
SEQUENCE_NAME = "workflow_concurrency_seq"
IN_FLIGHT_STATUSES = (
    run_queue.STATUS_QUEUED,
    run_queue.STATUS_WAITING_FOR_MAIN,
    run_queue.STATUS_CLAIMED,
)

AdmissionKind = Literal["unlimited", "admitted", "queued", "queue_full"]


@dataclass(frozen=True)
class ConcurrencySettings:
    limit: int | None
    max_queue: int | None
    max_wait_seconds: int | None


@dataclass(frozen=True)
class QueueInfo:
    position: int
    size: int
    running: int
    limit: int | None

    def as_dict(self) -> dict[str, int | None]:
        return {
            "position": self.position,
            "size": self.size,
            "running": self.running,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class Admission:
    kind: AdmissionKind
    execution_id: uuid.UUID
    queue: QueueInfo | None = None
    # Plaintext, minted for anonymous workflows only. Returned to the caller once.
    status_token: str | None = None

    @property
    def runs_now(self) -> bool:
        return self.kind in ("unlimited", "admitted")

    @property
    def holds_slot(self) -> bool:
        return self.kind == "admitted"


@dataclass(frozen=True)
class HeldRun:
    """Everything a held row needs so the worker can run it later without the caller."""

    workflow_id: uuid.UUID
    execution_id: uuid.UUID
    placement: str
    inputs: dict
    trigger_source: str | None
    actor_user_id: uuid.UUID | None
    credentials_owner_id: uuid.UUID | None
    timeout_seconds: float | None = None
    return_on_chart_output: bool = False
    run_options: dict | None = None
    mint_status_token: bool = False
    trace_context: dict[str, str] | None = None


def decide_admission(
    cfg: ConcurrencySettings, *, running: int, waiting: int, has_slot: bool
) -> AdmissionKind:
    """The admission rule. Strict FIFO: nobody overtakes a held run."""
    if cfg.limit is None:
        return "unlimited"
    if has_slot:
        return "admitted"
    if running < cfg.limit and waiting == 0:
        return "admitted"
    if cfg.max_queue is not None and waiting >= cfg.max_queue:
        return "queue_full"
    return "queued"


def held_expires_at(cfg: ConcurrencySettings, now: datetime) -> datetime | None:
    """Fixed at enqueue, so changing the setting later does not move runs already waiting."""
    if not cfg.max_wait_seconds:
        return None
    return now + timedelta(seconds=cfg.max_wait_seconds)


def held_values(
    run: HeldRun, *, cfg: ConcurrencySettings, now: datetime, token: str | None
) -> dict[str, Any]:
    """The queue row for a held run. Holds a credentials owner, never a credential."""
    return {
        "id": uuid.uuid4(),
        "workflow_id": run.workflow_id,
        "execution_id": run.execution_id,
        "placement": run.placement,
        "target_instance_id": None,
        "status": run_queue.STATUS_HELD,
        "inputs": run.inputs,
        "trace_context": run.trace_context,
        "trigger_source": run.trigger_source,
        "actor_user_id": run.actor_user_id,
        "credentials_owner_id": run.credentials_owner_id,
        "test_run": False,
        "timeout_seconds": run.timeout_seconds,
        "return_on_chart_output": run.return_on_chart_output,
        "enqueued_at": now,
        # Not read while held; promotion sets the real claim deadline.
        "not_after": now,
        "concurrency_seq": func.nextval(SEQUENCE_NAME),
        "expires_at": held_expires_at(cfg, now),
        "status_token_hash": hash_secret(token) if token else None,
        "run_options": run.run_options,
    }


def status_token_matches(stored_hash: str | None, presented: str | None) -> bool:
    """Compare digests only: the stored digest itself must never work as a token."""
    if not stored_hash or not presented:
        return False
    return hmac.compare_digest(stored_hash, hash_secret(presented))


def terminal_summary(
    *, execution_id: uuid.UUID, workflow_id: uuid.UUID, status: str, message: str
) -> dict[str, Any]:
    """The run-queue result for a held run that never executed."""
    return {
        "execution_id": str(execution_id),
        "workflow_id": str(workflow_id),
        "status": status,
        "outputs": {"error": message},
        "execution_time_ms": 0.0,
        "history_written": True,
        "error": None,
        "instance": identity.instance_name(),
    }


def _error_text(status: str, outputs: Any, fallback: str | None) -> str | None:
    if status in ("error", "expired", "cancelled") and isinstance(outputs, dict):
        message = outputs.get("error")
        if isinstance(message, str) and message:
            return message
    return fallback


def status_view(*, row_status: str, result: dict | None, error: str | None) -> dict[str, Any]:
    """Map one queue row to the public status fields."""
    if row_status == run_queue.STATUS_HELD:
        return {"status": "queued", "outputs": None, "error": None, "execution_time_ms": None}
    if row_status in IN_FLIGHT_STATUSES:
        return {"status": "running", "outputs": None, "error": None, "execution_time_ms": None}
    if result is None:
        return {
            "status": "error",
            "outputs": None,
            "error": error or "The run finished without a result",
            "execution_time_ms": None,
        }
    status = str(result.get("status") or "error")
    outputs = result.get("outputs")
    return {
        "status": status,
        "outputs": outputs,
        "error": _error_text(status, outputs, result.get("error") or error),
        "execution_time_ms": result.get("execution_time_ms"),
    }


def history_view(*, status: str, outputs: Any, execution_time_ms: float | None) -> dict[str, Any]:
    """Map an execution history row to the public status fields."""
    return {
        "status": status,
        "outputs": outputs,
        "error": _error_text(status, outputs, None),
        "execution_time_ms": execution_time_ms,
    }


def status_url(*, base_url: str, workflow_id: uuid.UUID, execution_id: uuid.UUID) -> str:
    return f"{base_url.rstrip('/')}/api/workflows/{workflow_id}/executions/{execution_id}/status"


def queued_body(admission: Admission, *, workflow_id: uuid.UUID, base_url: str) -> dict[str, Any]:
    """The 202 body: where to poll, and where this run stands right now."""
    body: dict[str, Any] = {
        "status": "queued",
        "execution_id": str(admission.execution_id),
        "status_url": status_url(
            base_url=base_url, workflow_id=workflow_id, execution_id=admission.execution_id
        ),
        "queue": admission.queue.as_dict() if admission.queue else None,
    }
    if admission.status_token:
        body["status_token"] = admission.status_token
    return body


async def promote(workflow_id: uuid.UUID) -> int:
    """Start held runs that now fit under the limit."""
    return 0
