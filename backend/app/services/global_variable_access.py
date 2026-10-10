"""Who can reach a global variable.

A user reaches a variable by owning it, by a direct share, or through a team the variable
is shared with, and anyone who reaches it can read and change its value. Sharing and
deleting stay with the owner. Heym's variable routes and Heym Work both read access
through this module.
"""

import uuid

from sqlalchemy import ColumnElement, Select, case, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GlobalVariable, GlobalVariableShare, GlobalVariableTeamShare, TeamMember

GRANT_OWNER = "owner"
GRANT_SHARED = "shared"


def team_shared_variable_clause(user_id: uuid.UUID) -> ColumnElement[bool]:
    """WHERE clause for variables shared with any team the user belongs to.

    IN subqueries rather than a join to ``TeamMember``, so a user who is in two teams that
    both hold the share still matches a single row.
    """
    return GlobalVariable.id.in_(
        select(GlobalVariableTeamShare.global_variable_id).where(
            GlobalVariableTeamShare.team_id.in_(
                select(TeamMember.team_id).where(TeamMember.user_id == user_id)
            )
        )
    )


async def get_global_variable_with_grant(
    db: AsyncSession, variable_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[GlobalVariable, str] | None:
    """The variable and how the user reaches it (``owner`` or ``shared``), or None."""
    owned = (
        await db.execute(
            select(GlobalVariable).where(
                GlobalVariable.id == variable_id,
                GlobalVariable.owner_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if owned is not None:
        return owned, GRANT_OWNER

    shared = (
        await db.execute(
            select(GlobalVariable)
            .join(GlobalVariableShare, GlobalVariableShare.global_variable_id == GlobalVariable.id)
            .where(
                GlobalVariable.id == variable_id,
                GlobalVariableShare.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if shared is None:
        shared = (
            await db.execute(
                select(GlobalVariable).where(
                    GlobalVariable.id == variable_id,
                    team_shared_variable_clause(user_id),
                )
            )
        ).scalar_one_or_none()
    if shared is None:
        return None
    return shared, GRANT_SHARED


def global_variable_access_rows(user_id: uuid.UUID) -> Select:
    """One ``(global_variable_id, grant)`` row per variable ``user_id`` reaches; owner wins."""
    team_ids = select(TeamMember.team_id).where(TeamMember.user_id == user_id)
    grants = union_all(
        select(
            GlobalVariable.id.label("global_variable_id"), literal(GRANT_OWNER).label("grant")
        ).where(GlobalVariable.owner_id == user_id),
        select(
            GlobalVariableShare.global_variable_id.label("global_variable_id"),
            literal(GRANT_SHARED).label("grant"),
        ).where(GlobalVariableShare.user_id == user_id),
        select(
            GlobalVariableTeamShare.global_variable_id.label("global_variable_id"),
            literal(GRANT_SHARED).label("grant"),
        ).where(GlobalVariableTeamShare.team_id.in_(team_ids)),
    ).subquery()
    is_owner = func.max(case((grants.c.grant == GRANT_OWNER, 1), else_=0))
    return select(
        grants.c.global_variable_id,
        case((is_owner == 1, GRANT_OWNER), else_=GRANT_SHARED).label("grant"),
    ).group_by(grants.c.global_variable_id)
