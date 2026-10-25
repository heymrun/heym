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
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import and_, delete, exists, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.config import settings
from app.db.models import (
    ActiveWorkflowExecution,
    ExecutionHistory,
    Workflow,
    WorkflowConcurrencySlot,
    WorkflowRunQueue,
)
from app.db.session import async_session_maker
from app.services.cluster import identity, run_queue
from app.services.cluster.attribution import attribution_fields
from app.services.secret_tokens import hash_secret
from app.services.workflow_access import workflow_access_clause

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


async def _lock(db: AsyncSession, workflow_id: uuid.UUID) -> None:
    """Serialize every slot and held-row change for one workflow, cluster-wide."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"heym.concurrency:{workflow_id}"},
    )


async def _settings(db: AsyncSession, workflow_id: uuid.UUID) -> ConcurrencySettings | None:
    row = (
        await db.execute(
            select(
                Workflow.concurrency_limit,
                Workflow.concurrency_max_queue,
                Workflow.concurrency_max_wait_seconds,
            ).where(Workflow.id == workflow_id)
        )
    ).first()
    if row is None:
        return None
    return ConcurrencySettings(limit=row[0], max_queue=row[1], max_wait_seconds=row[2])


async def _running(db: AsyncSession, workflow_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(WorkflowConcurrencySlot)
                .where(WorkflowConcurrencySlot.workflow_id == workflow_id)
            )
        ).scalar_one()
    )


async def _waiting(db: AsyncSession, workflow_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(WorkflowRunQueue)
                .where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.status == run_queue.STATUS_HELD,
                )
            )
        ).scalar_one()
    )


async def admit(run: HeldRun) -> Admission:
    """Decide whether a production run starts now, waits for a slot, or is turned away."""
    now = datetime.now(timezone.utc)
    async with async_session_maker() as db:
        await _lock(db, run.workflow_id)
        cfg = await _settings(db, run.workflow_id)
        if cfg is None or cfg.limit is None:
            await db.commit()
            return Admission(kind="unlimited", execution_id=run.execution_id)
        has_slot = await db.get(WorkflowConcurrencySlot, run.execution_id) is not None
        running = await _running(db, run.workflow_id)
        waiting = await _waiting(db, run.workflow_id)
        kind = decide_admission(cfg, running=running, waiting=waiting, has_slot=has_slot)
        if kind == "admitted":
            if not has_slot:
                db.add(
                    WorkflowConcurrencySlot(
                        execution_id=run.execution_id,
                        workflow_id=run.workflow_id,
                        acquired_at=now,
                    )
                )
            await db.commit()
            return Admission(kind="admitted", execution_id=run.execution_id)
        if kind == "queue_full":
            await db.commit()
            return Admission(
                kind="queue_full",
                execution_id=run.execution_id,
                queue=QueueInfo(position=0, size=waiting, running=running, limit=cfg.limit),
            )
        token = secrets.token_urlsafe(32) if run.mint_status_token else None
        try:
            await db.execute(
                WorkflowRunQueue.__table__.insert().values(
                    **held_values(run, cfg=cfg, now=now, token=token)
                )
            )
        except StatementError as error:
            # Inputs can hold request data; keep them out of the exception text.
            error.hide_parameters = True
            raise
        await db.commit()
    return Admission(
        kind="queued",
        execution_id=run.execution_id,
        queue=QueueInfo(position=waiting + 1, size=waiting + 1, running=running, limit=cfg.limit),
        status_token=token,
    )


async def _promotion_target(placement: str) -> str | None:
    if settings.cluster_enabled:
        return await run_queue.choose_target(placement)
    return identity.instance_id()


async def _close_held_locked(
    db: AsyncSession, row: WorkflowRunQueue, *, status: str, message: str, now: datetime
) -> None:
    """Retire a held run that will never execute, with a history row that says why."""
    row.status = status
    row.finished_at = now
    row.result = terminal_summary(
        execution_id=row.execution_id, workflow_id=row.workflow_id, status=status, message=message
    )
    await db.execute(
        pg_insert(ExecutionHistory)
        .values(
            id=row.execution_id,
            workflow_id=row.workflow_id,
            inputs=row.inputs,
            outputs={"error": message},
            node_results=[],
            status=status,
            execution_time_ms=0.0,
            trigger_source=row.trigger_source,
            **attribution_fields(),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    workflow = await db.get(Workflow, row.workflow_id)
    if workflow is not None:
        await upsert_workflow_analytics_snapshot(
            db,
            workflow_id=row.workflow_id,
            owner_id=workflow.owner_id,
            workflow_name_snapshot=workflow.name,
            status=status,
            execution_time_ms=0.0,
        )
    await db.flush()
    # Wakes any dispatcher waiting on this run; delivered when the transaction commits.
    await db.execute(
        text("SELECT pg_notify('heym_run_done', :payload)"), {"payload": str(row.execution_id)}
    )


async def _promote_locked(db: AsyncSession, workflow_id: uuid.UUID) -> int:
    """Hand free slots to the oldest held runs. Caller holds the workflow lock."""
    cfg = await _settings(db, workflow_id)
    if cfg is None:
        return 0
    now = datetime.now(timezone.utc)
    promoted = 0
    while True:
        if cfg.limit is not None and await _running(db, workflow_id) >= cfg.limit:
            return promoted
        head = (
            await db.execute(
                select(WorkflowRunQueue)
                .where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.status == run_queue.STATUS_HELD,
                )
                .order_by(WorkflowRunQueue.concurrency_seq)
                .limit(1)
            )
        ).scalar_one_or_none()
        if head is None:
            return promoted
        if head.expires_at is not None and head.expires_at <= now:
            await _close_held_locked(
                db, head, status=run_queue.STATUS_EXPIRED, message=EXPIRED_MESSAGE, now=now
            )
            continue
        if cfg.limit is not None:
            db.add(
                WorkflowConcurrencySlot(
                    execution_id=head.execution_id, workflow_id=workflow_id, acquired_at=now
                )
            )
        target = await _promotion_target(head.placement)
        head.target_instance_id = target
        head.status = run_queue.next_status(target_instance_id=target)
        head.not_after = now + timedelta(seconds=settings.cron_misfire_grace_seconds)
        await db.flush()
        if target:
            await db.execute(
                text("SELECT pg_notify('heym_run_queue', :payload)"), {"payload": target}
            )
        promoted += 1


async def release(execution_id: uuid.UUID) -> None:
    """Free this run's slot, if it holds one, and start whoever is next."""
    async with async_session_maker() as db:
        workflow_id = (
            await db.execute(
                select(WorkflowConcurrencySlot.workflow_id).where(
                    WorkflowConcurrencySlot.execution_id == execution_id
                )
            )
        ).scalar_one_or_none()
        if workflow_id is None:
            return
        await _lock(db, workflow_id)
        await db.execute(
            delete(WorkflowConcurrencySlot).where(
                WorkflowConcurrencySlot.execution_id == execution_id
            )
        )
        await _promote_locked(db, workflow_id)
        await db.commit()


async def promote(workflow_id: uuid.UUID) -> int:
    """Start held runs that now fit under the limit, for example after a settings save."""
    async with async_session_maker() as db:
        await _lock(db, workflow_id)
        promoted = await _promote_locked(db, workflow_id)
        await db.commit()
    return promoted


@dataclass(frozen=True)
class HeldRunRecord:
    execution_id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    enqueued_at: datetime
    inputs: dict
    position: int
    size: int


async def cancel_held(workflow_id: uuid.UUID, execution_id: uuid.UUID) -> bool:
    """Cancel a run that is still waiting. False when it is not held (or not this workflow's)."""
    async with async_session_maker() as db:
        await _lock(db, workflow_id)
        row = (
            await db.execute(
                select(WorkflowRunQueue).where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.execution_id == execution_id,
                    WorkflowRunQueue.status == run_queue.STATUS_HELD,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            await db.commit()
            return False
        await _close_held_locked(
            db,
            row,
            status=run_queue.STATUS_CANCELLED,
            message=CANCELLED_MESSAGE,
            now=datetime.now(timezone.utc),
        )
        await db.commit()
        return True


async def record_queue_full(
    *, workflow_id: uuid.UUID, execution_id: uuid.UUID, inputs: dict, trigger_source: str | None
) -> None:
    """A history row for a run the full queue turned away, like rate limiting writes."""
    async with async_session_maker() as db:
        workflow = await db.get(Workflow, workflow_id)
        if workflow is None:
            return
        db.add(
            ExecutionHistory(
                id=execution_id,
                workflow_id=workflow_id,
                inputs=inputs,
                outputs={"error": QUEUE_FULL_MESSAGE},
                node_results=[],
                status=HISTORY_STATUS_QUEUE_FULL,
                execution_time_ms=0.0,
                trigger_source=trigger_source,
            )
        )
        await upsert_workflow_analytics_snapshot(
            db,
            workflow_id=workflow_id,
            owner_id=workflow.owner_id,
            workflow_name_snapshot=workflow.name,
            status=HISTORY_STATUS_QUEUE_FULL,
            execution_time_ms=0.0,
        )
        await db.commit()


def _stale_slot_clause(cutoff: datetime) -> Any:
    """A slot that nothing is executing: no active run and no queued, claimable row."""
    return and_(
        WorkflowConcurrencySlot.acquired_at < cutoff,
        ~exists().where(
            ActiveWorkflowExecution.execution_id == WorkflowConcurrencySlot.execution_id
        ),
        ~exists().where(
            WorkflowRunQueue.execution_id == WorkflowConcurrencySlot.execution_id,
            WorkflowRunQueue.status.in_(IN_FLIGHT_STATUSES),
        ),
    )


async def _maintain_workflow(workflow_id: uuid.UUID, *, now: datetime, cutoff: datetime) -> None:
    async with async_session_maker() as db:
        await _lock(db, workflow_id)
        reclaimed = (
            (
                await db.execute(
                    delete(WorkflowConcurrencySlot)
                    .where(
                        WorkflowConcurrencySlot.workflow_id == workflow_id,
                        _stale_slot_clause(cutoff),
                    )
                    .returning(WorkflowConcurrencySlot.execution_id)
                )
            )
            .scalars()
            .all()
        )
        for execution_id in reclaimed:
            logger.warning(
                "Reclaimed the concurrency slot of run %s: nothing is running it", execution_id
            )
        overdue = (
            (
                await db.execute(
                    select(WorkflowRunQueue).where(
                        WorkflowRunQueue.workflow_id == workflow_id,
                        WorkflowRunQueue.status == run_queue.STATUS_HELD,
                        WorkflowRunQueue.expires_at.is_not(None),
                        WorkflowRunQueue.expires_at <= now,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in overdue:
            await _close_held_locked(
                db, row, status=run_queue.STATUS_EXPIRED, message=EXPIRED_MESSAGE, now=now
            )
        await _promote_locked(db, workflow_id)
        await db.commit()


async def maintain() -> None:
    """Leader pass: retire overdue held runs, reclaim dead slots, start whoever fits."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=STALE_SLOT_GRACE_SECONDS)
    async with async_session_maker() as db:
        held = select(WorkflowRunQueue.workflow_id).where(
            WorkflowRunQueue.status == run_queue.STATUS_HELD
        )
        stale = select(WorkflowConcurrencySlot.workflow_id).where(_stale_slot_clause(cutoff))
        workflow_ids = set((await db.execute(held.union(stale))).scalars().all())
    for workflow_id in workflow_ids:
        try:
            await _maintain_workflow(workflow_id, now=now, cutoff=cutoff)
        except Exception:
            logger.exception("Concurrency maintenance failed for workflow %s", workflow_id)


async def _queue_info(db: AsyncSession, workflow_id: uuid.UUID, concurrency_seq: int) -> QueueInfo:
    cfg = await _settings(db, workflow_id)
    position = int(
        (
            await db.execute(
                select(func.count())
                .select_from(WorkflowRunQueue)
                .where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.status == run_queue.STATUS_HELD,
                    WorkflowRunQueue.concurrency_seq <= concurrency_seq,
                )
            )
        ).scalar_one()
    )
    return QueueInfo(
        position=position,
        size=await _waiting(db, workflow_id),
        running=await _running(db, workflow_id),
        limit=cfg.limit if cfg else None,
    )


async def build_status_body(
    workflow_id: uuid.UUID, execution_id: uuid.UUID
) -> dict[str, Any] | None:
    """The status URL's body: the queue row when there is one, else the history row."""
    base: dict[str, Any] = {
        "execution_id": str(execution_id),
        "workflow_id": str(workflow_id),
        "queue": None,
    }
    async with async_session_maker() as db:
        row = (
            await db.execute(
                select(WorkflowRunQueue).where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.execution_id == execution_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            body = {
                **base,
                **status_view(row_status=row.status, result=row.result, error=row.error),
            }
            if row.status == run_queue.STATUS_HELD and row.concurrency_seq is not None:
                info = await _queue_info(db, workflow_id, row.concurrency_seq)
                body["queue"] = info.as_dict()
            return body
        history = (
            await db.execute(
                select(
                    ExecutionHistory.status,
                    ExecutionHistory.outputs,
                    ExecutionHistory.execution_time_ms,
                ).where(
                    ExecutionHistory.id == execution_id,
                    ExecutionHistory.workflow_id == workflow_id,
                )
            )
        ).first()
    if history is None:
        return None
    return {
        **base,
        **history_view(status=history[0], outputs=history[1], execution_time_ms=history[2]),
    }


async def status_token_hash_for(workflow_id: uuid.UUID, execution_id: uuid.UUID) -> str | None:
    async with async_session_maker() as db:
        return (
            await db.execute(
                select(WorkflowRunQueue.status_token_hash).where(
                    WorkflowRunQueue.workflow_id == workflow_id,
                    WorkflowRunQueue.execution_id == execution_id,
                )
            )
        ).scalar_one_or_none()


async def list_held_runs_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[HeldRunRecord]:
    """Held runs of every workflow the user can reach, in queue order, with positions."""
    rows = (
        await db.execute(
            select(
                WorkflowRunQueue.execution_id,
                WorkflowRunQueue.workflow_id,
                Workflow.name,
                WorkflowRunQueue.enqueued_at,
                WorkflowRunQueue.inputs,
            )
            .join(Workflow, Workflow.id == WorkflowRunQueue.workflow_id)
            .where(
                WorkflowRunQueue.status == run_queue.STATUS_HELD,
                workflow_access_clause(user_id),
            )
            .order_by(WorkflowRunQueue.workflow_id, WorkflowRunQueue.concurrency_seq)
        )
    ).all()
    sizes: dict[uuid.UUID, int] = {}
    for row in rows:
        sizes[row[1]] = sizes.get(row[1], 0) + 1
    seen: dict[uuid.UUID, int] = {}
    records: list[HeldRunRecord] = []
    for execution_id, workflow_id, name, enqueued_at, inputs in rows:
        seen[workflow_id] = seen.get(workflow_id, 0) + 1
        records.append(
            HeldRunRecord(
                execution_id=execution_id,
                workflow_id=workflow_id,
                workflow_name=name,
                enqueued_at=enqueued_at,
                inputs=inputs or {},
                position=seen[workflow_id],
                size=sizes[workflow_id],
            )
        )
    return records


def holds_slot(row: Any) -> bool:
    """Whether a claimed queue row must give a slot back when it finishes."""
    options = getattr(row, "run_options", None) or {}
    return getattr(row, "concurrency_seq", None) is not None or bool(
        options.get("holds_concurrency_slot")
    )


def is_concurrency_row(row: Any) -> bool:
    """A row that waited for a slot: its caller may be gone, so the worker finishes it."""
    return getattr(row, "concurrency_seq", None) is not None
