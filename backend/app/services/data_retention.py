"""Daily deletion of execution history and LLM traces older than HEYM_DATA_RETENTION_DAYS.

Runs on the scheduler leader once a day under a cleanup claim. Rows go in batches so one
pass never holds a long lock on a busy table. A run that is still waiting on a review or a
Codex follow-up is kept whatever its age: deleting it would cascade the pending request
away. The weekly TOAST reclaim in `execution_history_maintenance.py` returns the freed
space to the operating system afterwards.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db.models import CodexFollowupRequest, ExecutionHistory, HITLRequest, LLMTrace
from app.db.session import async_session_maker

logger = logging.getLogger("data_retention")

BATCH_SIZE = 1000
# A ceiling per pass, so a first run on a large install spreads over a few days.
MAX_BATCHES = 200


@dataclass
class RetentionResult:
    executions_deleted: int = 0
    traces_deleted: int = 0


def retention_cutoff(now: datetime | None = None) -> datetime | None:
    """The oldest timestamp kept, or None when retention is off."""
    days = settings.data_retention_days
    if days <= 0:
        return None
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


def _expired_executions(cutoff: datetime):  # noqa: ANN202 - a SQLAlchemy select
    pending_review = exists().where(
        HITLRequest.execution_history_id == ExecutionHistory.id,
        HITLRequest.status == "pending",
    )
    pending_followup = exists().where(
        CodexFollowupRequest.execution_history_id == ExecutionHistory.id,
        CodexFollowupRequest.status == "pending",
    )
    return (
        select(ExecutionHistory.id)
        .where(ExecutionHistory.started_at < cutoff, ~pending_review, ~pending_followup)
        .limit(BATCH_SIZE)
    )


async def _delete_batch(db: AsyncSession, statement) -> int:  # noqa: ANN001
    result = await db.execute(statement)
    await db.commit()
    return result.rowcount or 0


async def apply_retention(
    *, now: datetime | None = None, sessions: async_sessionmaker = async_session_maker
) -> RetentionResult:
    """Delete what is older than the retention window. A no-op when it is 0."""
    result = RetentionResult()
    cutoff = retention_cutoff(now)
    if cutoff is None:
        return result
    async with sessions() as db:
        for _ in range(MAX_BATCHES):
            deleted = await _delete_batch(
                db,
                delete(ExecutionHistory).where(
                    ExecutionHistory.id.in_(_expired_executions(cutoff).scalar_subquery())
                ),
            )
            result.executions_deleted += deleted
            if deleted < BATCH_SIZE:
                break
        for _ in range(MAX_BATCHES):
            expired_traces = (
                select(LLMTrace.id).where(LLMTrace.created_at < cutoff).limit(BATCH_SIZE)
            )
            deleted = await _delete_batch(
                db, delete(LLMTrace).where(LLMTrace.id.in_(expired_traces.scalar_subquery()))
            )
            result.traces_deleted += deleted
            if deleted < BATCH_SIZE:
                break
    if result.executions_deleted or result.traces_deleted:
        logger.info(
            "Data retention (%d days): %d executions and %d LLM traces deleted",
            settings.data_retention_days,
            result.executions_deleted,
            result.traces_deleted,
        )
    return result
