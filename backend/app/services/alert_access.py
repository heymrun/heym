"""Alert access resolution.

Structurally mirrors ``credential_access.py``: owner, then direct share, then
team membership. Read access comes from any of the three; mutation requires
ownership, which is what ``get_owned_alert`` is for.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert, AlertShare, AlertTeamShare, TeamMember


async def get_owned_alert(db: AsyncSession, alert_id: UUID, user_id: UUID) -> Alert | None:
    """Only the owner. Use for update, delete, enable/disable, and re-share."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id, Alert.owner_id == user_id))
    return result.scalar_one_or_none()


async def get_accessible_alert(db: AsyncSession, alert_id: UUID, user_id: UUID) -> Alert | None:
    """Owner, direct share, or team share. Use for reads."""
    owned = await get_owned_alert(db, alert_id, user_id)
    if owned is not None:
        return owned

    shared_result = await db.execute(
        select(Alert)
        .join(AlertShare, AlertShare.alert_id == Alert.id)
        .where(Alert.id == alert_id, AlertShare.user_id == user_id)
    )
    shared = shared_result.scalar_one_or_none()
    if shared is not None:
        return shared

    team_result = await db.execute(
        select(Alert)
        .join(AlertTeamShare, AlertTeamShare.alert_id == Alert.id)
        .join(TeamMember, TeamMember.team_id == AlertTeamShare.team_id)
        .where(Alert.id == alert_id, TeamMember.user_id == user_id)
    )
    return team_result.scalar_one_or_none()


def accessible_alert_ids_subquery(user_id: UUID):
    """Reusable subquery of alert ids the user can read: owned, shared, or team-shared."""
    owned = select(Alert.id).where(Alert.owner_id == user_id)
    shared = select(AlertShare.alert_id).where(AlertShare.user_id == user_id)
    team_shared = (
        select(AlertTeamShare.alert_id)
        .join(TeamMember, TeamMember.team_id == AlertTeamShare.team_id)
        .where(TeamMember.user_id == user_id)
    )
    return owned.union(shared, team_shared).subquery()


def accessible_alerts_filter(user_id: UUID):
    """WHERE clause for listing alerts the user can read."""
    return Alert.id.in_(select(accessible_alert_ids_subquery(user_id).c[0]))
