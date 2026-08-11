"""Retention for alert_events.

One row per firing, on accounts with many alerts, grows without bound. This runs
once a day from the scheduler, following the same shape as the existing portal
session and cron slot claim cleanups.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AlertEvent

logger = logging.getLogger("alert_cleanup")

ALERT_EVENT_RETENTION_DAYS = 90


async def cleanup_old_alert_events(db: AsyncSession, *, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=ALERT_EVENT_RETENTION_DAYS)
    result = await db.execute(delete(AlertEvent).where(AlertEvent.triggered_at < cutoff))
    await db.commit()
    deleted = int(result.rowcount or 0)
    if deleted:
        logger.info(
            "Deleted %s alert events older than %s days", deleted, ALERT_EVENT_RETENTION_DAYS
        )
    return deleted
