"""Cross-worker bookkeeping for cron slots that have already been run.

The scheduler's in-memory state is per uvicorn worker, so it cannot answer
"did anyone already run this slot?" on its own. These helpers keep that answer
in Postgres, where every worker (and every restart) sees the same truth.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CronCleanupClaim, CronSlotClaim
from app.db.session import async_session_maker

logger = logging.getLogger("cron_scheduler")

CLAIM_RETENTION_DAYS = 7


async def claim_cron_slot(
    *,
    workflow_id: uuid.UUID,
    node_id: str,
    slot_at: datetime,
    worker_id: str | None = None,
) -> bool | None:
    """Claim one cron slot for this worker.

    Returns True only for the worker that inserted the row; everyone else - a
    concurrent worker, or the same worker after a restart - gets False and must
    skip the run. Returns None on a database error: nothing is executed, and a
    claim row usually does not exist, so the caller may retry the slot on its
    next pass. If the failure hit the commit itself, the row may exist and the
    retry then gets False, which skips the run.
    """
    stmt = (
        pg_insert(CronSlotClaim)
        .values(
            id=uuid.uuid4(),
            workflow_id=workflow_id,
            node_id=node_id,
            slot_at=slot_at,
            claimed_by=worker_id,
        )
        .on_conflict_do_nothing(constraint="uq_cron_slot_claim")
        .returning(CronSlotClaim.id)
    )
    try:
        async with async_session_maker() as db:
            result = await db.execute(stmt)
            claimed = result.first() is not None
            await db.commit()
            return claimed
    except Exception as e:
        logger.warning(
            "Failed to claim cron slot for workflow %s node %s at %s: %s",
            workflow_id,
            node_id,
            slot_at,
            e,
        )
        return None


async def cleanup_cron_slot_claims(
    db: AsyncSession, *, retention_days: int = CLAIM_RETENTION_DAYS
) -> int:
    """Drop claims older than the retention window; they can never match again."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await db.execute(delete(CronSlotClaim).where(CronSlotClaim.slot_at < cutoff))
    return result.rowcount or 0


def iso_week_slot(moment: datetime) -> str:
    """Cleanup slot key for a weekly job: ISO year and week, e.g. ``2026-W40``.

    Eight characters, so it fits ``cron_cleanup_claims.slot_date`` beside the
    daily ``YYYYMMDD`` keys. A weekly claim outlives its week before the
    retention cleanup removes it, so the same key can never be claimed twice.
    """
    iso_year, iso_week, _ = moment.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


async def claim_cleanup_slot(
    *,
    job_name: str,
    slot_date: str,
    worker_id: str | None = None,
) -> bool:
    """Claim one cleanup slot (a daily date or an ISO week) for this worker.

    Returns True only for the worker that inserted the row; everyone else - a
    concurrent worker, or the same worker after a leader handoff - gets False
    and must skip the run. Fails closed: on a database error nothing is executed.
    """
    stmt = (
        pg_insert(CronCleanupClaim)
        .values(
            id=uuid.uuid4(),
            job_name=job_name,
            slot_date=slot_date,
            claimed_by=worker_id,
        )
        .on_conflict_do_nothing(constraint="uq_cron_cleanup_claim")
        .returning(CronCleanupClaim.id)
    )
    try:
        async with async_session_maker() as db:
            result = await db.execute(stmt)
            claimed = result.first() is not None
            await db.commit()
            return claimed
    except Exception as e:
        logger.warning("Failed to claim cleanup slot for job %s at %s: %s", job_name, slot_date, e)
        return False


async def cleanup_old_cleanup_slot_claims(
    db: AsyncSession, *, retention_days: int = CLAIM_RETENTION_DAYS
) -> int:
    """Drop daily cleanup claims older than the retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await db.execute(delete(CronCleanupClaim).where(CronCleanupClaim.created_at < cutoff))
    return result.rowcount or 0
