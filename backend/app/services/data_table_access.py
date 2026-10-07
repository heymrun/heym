"""Who can reach a data table, and how far.

A user reaches a table by owning it, by a direct share, or through a team the table is
shared with; the strongest grant wins. Heym's data table routes and Heym Work both read
access through this module, so the two never disagree.
"""

import uuid

from sqlalchemy import Select, case, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataTable, DataTableShare, DataTableTeamShare, TeamMember

PERMISSION_OWNER = "owner"
PERMISSION_WRITE = "write"
PERMISSION_READ = "read"
_RANK = {PERMISSION_READ: 1, PERMISSION_WRITE: 2, PERMISSION_OWNER: 3}


def strongest_share_permission(permissions: list[str]) -> str | None:
    """Collapse share grants into one permission: any ``write`` wins over ``read``."""
    if not permissions:
        return None
    return PERMISSION_WRITE if PERMISSION_WRITE in permissions else PERMISSION_READ


async def get_data_table_with_permission(
    db: AsyncSession, table_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[DataTable, str] | None:
    """The table and the user's strongest permission on it, or None when unreachable."""
    owned = (
        await db.execute(
            select(DataTable).where(DataTable.id == table_id, DataTable.owner_id == user_id)
        )
    ).scalar_one_or_none()
    if owned is not None:
        return owned, PERMISSION_OWNER

    user_permissions = (
        (
            await db.execute(
                select(DataTableShare.permission).where(
                    DataTableShare.table_id == table_id, DataTableShare.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    team_permissions = (
        (
            await db.execute(
                select(DataTableTeamShare.permission)
                .join(TeamMember, TeamMember.team_id == DataTableTeamShare.team_id)
                .where(DataTableTeamShare.table_id == table_id, TeamMember.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    permission = strongest_share_permission([*user_permissions, *team_permissions])
    if permission is None:
        return None
    table = (
        await db.execute(select(DataTable).where(DataTable.id == table_id))
    ).scalar_one_or_none()
    if table is None:
        return None
    return table, permission


def data_table_access_rows(user_id: uuid.UUID) -> Select:
    """One ``(table_id, permission)`` row per table ``user_id`` reaches, strongest grant first.

    Join it to explicit table columns: ``select(DataTable.id, DataTable.name, rows.c.permission)
    .join(rows, rows.c.table_id == DataTable.id)`` with ``rows = data_table_access_rows(u).subquery()``.
    """
    team_ids = select(TeamMember.team_id).where(TeamMember.user_id == user_id)
    grants = union_all(
        select(DataTable.id.label("table_id"), literal(PERMISSION_OWNER).label("permission")).where(
            DataTable.owner_id == user_id
        ),
        select(
            DataTableShare.table_id.label("table_id"), DataTableShare.permission.label("permission")
        ).where(DataTableShare.user_id == user_id),
        select(
            DataTableTeamShare.table_id.label("table_id"),
            DataTableTeamShare.permission.label("permission"),
        ).where(DataTableTeamShare.team_id.in_(team_ids)),
    ).subquery()
    rank = case(
        {permission: value for permission, value in _RANK.items()},
        value=grants.c.permission,
        else_=0,
    )
    best = func.max(rank)
    return select(
        grants.c.table_id,
        case(
            (best == _RANK[PERMISSION_OWNER], PERMISSION_OWNER),
            (best == _RANK[PERMISSION_WRITE], PERMISSION_WRITE),
            else_=PERMISSION_READ,
        ).label("permission"),
    ).group_by(grants.c.table_id)
