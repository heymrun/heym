"""Who can reach a dashboard, and how far.

A user reaches a dashboard by owning it, by a direct share, or through a team the
dashboard is shared with; the most permissive grant wins. A ``write`` grant also
reaches the dashboard's widget workflows, which ``workflow_access_clause`` pulls in
through :func:`writable_shared_widget_workflow_ids`.
"""

import uuid

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Dashboard, DashboardShare, DashboardTeamShare, DashboardWidget, TeamMember

PERMISSION_OWNER = "owner"
PERMISSION_WRITE = "write"
PERMISSION_READ = "read"
SHARE_PERMISSIONS = (PERMISSION_READ, PERMISSION_WRITE)


def _team_ids(user_id: uuid.UUID) -> Select:
    return select(TeamMember.team_id).where(TeamMember.user_id == user_id)


def _grants(user_id: uuid.UUID) -> Select:
    """Every (dashboard_id, permission) grant ``user_id`` holds, direct or through a team."""
    direct = select(DashboardShare.dashboard_id, DashboardShare.permission).where(
        DashboardShare.user_id == user_id
    )
    via_team = select(DashboardTeamShare.dashboard_id, DashboardTeamShare.permission).where(
        DashboardTeamShare.team_id.in_(_team_ids(user_id))
    )
    return direct.union_all(via_team)


def writable_shared_widget_workflow_ids(user_id: uuid.UUID) -> Select:
    """Workflow ids of widgets on dashboards shared with ``user_id`` for writing.

    Expressed as IN-subqueries rather than joins so a user who reaches the same
    dashboard through several teams still matches each workflow row once.
    """
    return select(DashboardWidget.workflow_id).where(
        or_(
            DashboardWidget.dashboard_id.in_(
                select(DashboardShare.dashboard_id).where(
                    DashboardShare.user_id == user_id,
                    DashboardShare.permission == PERMISSION_WRITE,
                )
            ),
            DashboardWidget.dashboard_id.in_(
                select(DashboardTeamShare.dashboard_id).where(
                    DashboardTeamShare.permission == PERMISSION_WRITE,
                    DashboardTeamShare.team_id.in_(_team_ids(user_id)),
                )
            ),
        )
    )


def team_writable_widget_workflow_ids(team_id: uuid.UUID) -> Select:
    """Workflow ids of widgets on dashboards a team can write, for revoking tokens on team changes."""
    return select(DashboardWidget.workflow_id).where(
        DashboardWidget.dashboard_id.in_(
            select(DashboardTeamShare.dashboard_id).where(
                DashboardTeamShare.team_id == team_id,
                DashboardTeamShare.permission == PERMISSION_WRITE,
            )
        )
    )


def strongest_permission(permissions: list[str]) -> str | None:
    """Collapse share grants into one permission: any ``write`` wins over ``read``."""
    if not permissions:
        return None
    return PERMISSION_WRITE if PERMISSION_WRITE in permissions else PERMISSION_READ


async def shared_dashboard_permissions(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[uuid.UUID, str]:
    """Map every dashboard shared with ``user_id`` to the caller's strongest grant."""
    grants: dict[uuid.UUID, list[str]] = {}
    for dashboard_id, permission in (await db.execute(_grants(user_id))).all():
        grants.setdefault(dashboard_id, []).append(permission)
    return {
        dashboard_id: permission
        for dashboard_id, permissions in grants.items()
        if (permission := strongest_permission(permissions)) is not None
    }


async def dashboard_permission(
    db: AsyncSession, dashboard: Dashboard, user_id: uuid.UUID
) -> str | None:
    """The caller's access to ``dashboard``: owner, write, read, or None when not shared."""
    if dashboard.owner_id == user_id:
        return PERMISSION_OWNER
    grants = _grants(user_id).subquery()
    result = await db.execute(
        select(grants.c.permission).where(grants.c.dashboard_id == dashboard.id)
    )
    return strongest_permission(list(result.scalars().all()))
