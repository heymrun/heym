"""Who started each run on a history page, and whether the viewer may delete it."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExecutionHistory, User, Workflow


@dataclass(frozen=True)
class RunMeta:
    """The starter of one workflow run and whether the viewer owns its workflow."""

    user_id: uuid.UUID | None
    user_name: str | None
    can_delete: bool


async def workflow_run_meta(
    db: AsyncSession, history_ids: Sequence[uuid.UUID], viewer_id: uuid.UUID
) -> dict[uuid.UUID, RunMeta]:
    """Read the starter and delete permission of the given workflow runs in one query."""
    if not history_ids:
        return {}
    rows = await db.execute(
        select(
            ExecutionHistory.id,
            ExecutionHistory.executed_by_user_id,
            User.name,
            Workflow.owner_id,
        )
        .join(Workflow, ExecutionHistory.workflow_id == Workflow.id)
        .outerjoin(User, User.id == ExecutionHistory.executed_by_user_id)
        .where(ExecutionHistory.id.in_(history_ids))
    )
    return {
        row.id: RunMeta(
            user_id=row.executed_by_user_id,
            user_name=row.name,
            can_delete=row.owner_id == viewer_id,
        )
        for row in rows.all()
    }
