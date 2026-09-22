"""The single definition of which workflows a user can reach.

Both the async API layer and the synchronous node handlers need this answer, so
it is expressed as a SQLAlchemy clause rather than an executed query - the caller
supplies the session and the engine.
"""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import (
    TeamMember,
    Workflow,
    WorkflowExecutionToken,
    WorkflowShare,
    WorkflowTeamShare,
)


def workflow_access_clause(user_id: UUID) -> ColumnElement[bool]:
    """Return the WHERE clause matching every workflow ``user_id`` can reach.

    A user reaches a workflow by owning it, by holding a direct share, or by
    belonging to a team the workflow is shared with.
    """
    return or_(
        Workflow.owner_id == user_id,
        Workflow.id.in_(select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == user_id)),
        Workflow.id.in_(
            select(WorkflowTeamShare.workflow_id).where(
                WorkflowTeamShare.team_id.in_(
                    select(TeamMember.team_id).where(TeamMember.user_id == user_id)
                )
            )
        ),
    )


async def get_accessible_workflow(
    db: AsyncSession,
    workflow_id: UUID,
    user_id: UUID,
) -> Workflow | None:
    """Return a workflow the user owns or that has been shared with them."""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            workflow_access_clause(user_id),
        )
    )
    return result.scalar_one_or_none()


async def user_has_workflow_access(db: AsyncSession, workflow: Workflow, user_id: UUID) -> bool:
    """Return whether ``user_id`` can reach ``workflow``.

    Goes through ``workflow_access_clause``'s ``IN`` subqueries rather than joining
    ``WorkflowTeamShare`` to ``TeamMember`` directly. A direct join produces one row per
    team a user shares the workflow through, so a user reachable via two teams made a
    two-argument JOIN return two rows and ``scalar_one_or_none()`` raise
    ``MultipleResultsFound``. The subquery form only ever matches the single ``workflow.id``
    row, however many paths grant access to it.
    """
    if workflow.owner_id == user_id:
        return True
    result = await db.execute(
        select(Workflow.id).where(Workflow.id == workflow.id, workflow_access_clause(user_id))
    )
    return result.scalar_one_or_none() is not None


async def revoke_execution_tokens_without_access(db: AsyncSession, workflow: Workflow) -> None:
    """Revoke execution tokens whose minter can no longer access ``workflow``.

    Call after a share, team share, team membership, or team itself has been removed and
    the change flushed. ``validate_workflow_auth`` rechecks access on every use regardless,
    so this is defense in depth: it keeps the stored token state honest and lets the
    workflow owner see revoked tokens as revoked rather than merely unusable.
    """
    result = await db.execute(
        select(WorkflowExecutionToken).where(
            WorkflowExecutionToken.workflow_id == workflow.id,
            WorkflowExecutionToken.revoked.is_(False),
        )
    )
    for token in result.scalars().all():
        if not await user_has_workflow_access(db, workflow, token.user_id):
            token.revoked = True
