"""Which Slack event deliveries have already been handled, across every worker.

Slack redelivers an event it believes timed out (``X-Slack-Retry-Num``). Production runs
several uvicorn workers and a retry arrives on a new connection, so the record of
handled ``event_id``s lives in Postgres, not in a process. ``cron_cleanup_claims`` is a
generic once-only claim (job name + key) whose rows the scheduler drops after 7 days.
"""

import hashlib
import logging
import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import CronCleanupClaim
from app.db.session import async_session_maker

logger = logging.getLogger(__name__)

_CLAIM_KEY = "slack"


async def claim_slack_event(event_id: object, scope: str) -> bool:
    """False for an event_id this scope (a credential or a node URL) has already handled.

    Fails open: if the claim cannot be written, the event is handled rather than lost.
    """
    key = str(event_id or "")
    if not key:
        return True
    digest = hashlib.sha256(f"{scope}:{key}".encode()).hexdigest()[:48]
    stmt = (
        pg_insert(CronCleanupClaim)
        .values(id=uuid.uuid4(), job_name=f"slack-event:{digest}", slot_date=_CLAIM_KEY)
        .on_conflict_do_nothing(constraint="uq_cron_cleanup_claim")
        .returning(CronCleanupClaim.id)
    )
    try:
        async with async_session_maker() as db:
            claimed = (await db.execute(stmt)).first() is not None
            await db.commit()
            return claimed
    except Exception:
        logger.exception("Could not record Slack event %s; handling it anyway", key)
        return True
