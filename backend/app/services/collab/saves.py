"""Tell a workflow's canvas room that the workflow was saved.

The notification is queued on the saving request's own session, so Postgres delivers it when
that transaction commits and never for a save that rolled back. ``now()`` inside the
transaction is the instant the update wrote to ``updated_at``, so peers adopt the revision
without reading it back. It is formatted like the API's ``updated_at`` (UTC, ``Z``).
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.collab.wire import CHANNEL

_SAVED_NOTIFY = text(
    "SELECT pg_notify(:channel, :prefix || json_build_object("
    "'to', NULL, 'skip', NULL, 'data', json_build_object("
    "'t', 'saved', "
    "'updatedAt', to_char(now() AT TIME ZONE 'UTC', "
    '\'YYYY-MM-DD"T"HH24\\:MI\\:SS.US"Z"\'), '
    "'sid', CAST(:sid AS text), "
    "'hash', CAST(:hash AS text), "
    "'byUserId', CAST(:by AS text)"
    "))::text)"
)


async def queue_collab_saved(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    actor_id: uuid.UUID,
    *,
    session: str | None,
    state_hash: str | None,
) -> None:
    """Queue the ``saved`` message for ``workflow_id``'s room in the current transaction.

    ``session`` and ``state_hash`` come from the editor's save headers. Both are None for a
    save made outside a canvas (MCP, Chat build, Edit History restore); peers treat that as an
    external save.
    """
    await db.execute(
        _SAVED_NOTIFY,
        {
            "channel": CHANNEL,
            "prefix": f"{workflow_id}|{uuid.uuid4().hex}|0/1|",
            "sid": session,
            "hash": state_hash,
            "by": str(actor_id),
        },
    )
