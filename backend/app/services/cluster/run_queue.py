"""Enqueue, claim, and retire background runs through Postgres.

The queue row never holds a resolved credentials context. It carries
credentials_owner_id and the executing instance calls
get_credentials_context() itself, which it can do because every instance in a
cluster shares one ENCRYPTION_KEY.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text, update

from app.config import settings
from app.db.models import ClusterDispatchState, WorkflowRunQueue
from app.db.session import async_session_maker
from app.services.cluster import registry
from app.services.cluster.weights import pick_instance, rescale_counters

logger = logging.getLogger("cluster")

STATUS_QUEUED = "queued"
STATUS_WAITING_FOR_MAIN = "waiting_for_main"
STATUS_CLAIMED = "claimed"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED_LATE = "skipped_late"


@dataclass(frozen=True)
class QueuedRun:
    workflow_id: uuid.UUID
    execution_id: uuid.UUID
    placement: str
    inputs: dict
    trigger_source: str | None
    actor_user_id: uuid.UUID | None
    credentials_owner_id: uuid.UUID | None
    test_run: bool
    timeout_seconds: float | None


def next_status(*, target_instance_id: str | None) -> str:
    """A run with no reachable target waits instead of failing."""
    return STATUS_QUEUED if target_instance_id else STATUS_WAITING_FOR_MAIN


def is_expired(*, not_after: datetime, now: datetime) -> bool:
    return now > not_after


def build_queue_values(
    run: QueuedRun, *, target_instance_id: str | None, grace_seconds: int
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "id": uuid.uuid4(),
        "workflow_id": run.workflow_id,
        "execution_id": run.execution_id,
        "placement": run.placement,
        "target_instance_id": target_instance_id,
        "status": next_status(target_instance_id=target_instance_id),
        "inputs": run.inputs,
        "trigger_source": run.trigger_source,
        "actor_user_id": run.actor_user_id,
        "credentials_owner_id": run.credentials_owner_id,
        "test_run": run.test_run,
        "timeout_seconds": run.timeout_seconds,
        "enqueued_at": now,
        "not_after": now + timedelta(seconds=grace_seconds),
    }


async def choose_target(placement: str) -> str | None:
    """Pick the instance for this run and charge it, in one locked transaction.

    A MAIN_ONLY run is not selected - its target is always main - but it still
    increments main's counter, so the forced work spends main's quota.
    """
    async with async_session_maker() as db:
        state = (
            await db.execute(
                select(ClusterDispatchState)
                .where(ClusterDispatchState.id == "singleton")
                .with_for_update()
            )
        ).scalar_one_or_none()
        if state is None:
            return None

        instances = await registry.list_instances()
        now = datetime.now(timezone.utc)
        counters = rescale_counters(dict(state.counters or {}))

        if placement == "main_only":
            main = registry.find_main(instances)
            target = main.id if main and registry.is_live(main, now=now) else None
        else:
            pool = registry.candidate_instances(instances, now=now)
            target = pick_instance({i.id: i.weight for i in pool}, counters=counters)

        if target is not None:
            counters[target] = counters.get(target, 0) + 1
            state.counters = counters
        await db.commit()
        return target


async def enqueue(run: QueuedRun) -> str | None:
    """Write the queue row and return the instance it was assigned to."""
    target = await choose_target(run.placement)
    values = build_queue_values(
        run, target_instance_id=target, grace_seconds=settings.cron_misfire_grace_seconds
    )
    async with async_session_maker() as db:
        await db.execute(WorkflowRunQueue.__table__.insert().values(**values))
        await db.commit()
    return target


async def claim_next(instance_id: str) -> WorkflowRunQueue | None:
    """Take one queued row for this instance. Concurrent claimers skip each other."""
    async with async_session_maker() as db:
        row = (
            await db.execute(
                select(WorkflowRunQueue)
                .where(
                    WorkflowRunQueue.target_instance_id == instance_id,
                    WorkflowRunQueue.status == STATUS_QUEUED,
                )
                .order_by(WorkflowRunQueue.enqueued_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row.status = STATUS_CLAIMED
        row.claimed_at = datetime.now(timezone.utc)
        row.claimed_by_process = f"{instance_id}-{os.getpid()}"
        await db.commit()
        db.expunge(row)
        return row


async def complete(execution_id: uuid.UUID, *, result: dict | None, error: str | None) -> None:
    async with async_session_maker() as db:
        await db.execute(
            update(WorkflowRunQueue)
            .where(WorkflowRunQueue.execution_id == execution_id)
            .values(
                status=STATUS_FAILED if error else STATUS_DONE,
                result=result,
                error=error,
                finished_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def expire_late_rows() -> int:
    """Retire rows past their grace window instead of replaying a backlog.

    Without this, a main instance returning after a long outage would run every
    queued MAIN_ONLY job at once - the mirror image of the cron duplicate-fire
    incident that cron_misfire_grace_seconds already guards against.
    """
    async with async_session_maker() as db:
        result = await db.execute(
            update(WorkflowRunQueue)
            .where(
                WorkflowRunQueue.status.in_([STATUS_QUEUED, STATUS_WAITING_FOR_MAIN]),
                WorkflowRunQueue.not_after < datetime.now(timezone.utc),
            )
            .values(
                status=STATUS_SKIPPED_LATE,
                error="Skipped: not claimed inside the misfire grace window",
                finished_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        return result.rowcount or 0


async def release_waiting_for_main(main_instance_id: str) -> int:
    """Hand waiting rows to main once it is live again."""
    async with async_session_maker() as db:
        result = await db.execute(
            update(WorkflowRunQueue)
            .where(
                WorkflowRunQueue.status == STATUS_WAITING_FOR_MAIN,
                WorkflowRunQueue.not_after >= datetime.now(timezone.utc),
            )
            .values(status=STATUS_QUEUED, target_instance_id=main_instance_id)
        )
        await db.commit()
        return result.rowcount or 0


async def notify_queue(target_instance_id: str) -> None:
    async with async_session_maker() as db:
        await db.execute(
            text("SELECT pg_notify('heym_run_queue', :payload)"),
            {"payload": target_instance_id},
        )
        await db.commit()


async def read_terminal_result(execution_id: uuid.UUID) -> tuple[str, dict | None, str | None]:
    """Status, result and error for one queued run, or ("missing", None, None)."""
    async with async_session_maker() as db:
        row = (
            await db.execute(
                select(
                    WorkflowRunQueue.status,
                    WorkflowRunQueue.result,
                    WorkflowRunQueue.error,
                ).where(WorkflowRunQueue.execution_id == execution_id)
            )
        ).first()
    if row is None:
        return "missing", None, None
    return row[0], row[1], row[2]


def is_terminal(status: str) -> bool:
    return status in {STATUS_DONE, STATUS_FAILED, STATUS_SKIPPED_LATE}


async def notify_done(execution_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        await db.execute(
            text("SELECT pg_notify('heym_run_done', :payload)"),
            {"payload": str(execution_id)},
        )
        await db.commit()
