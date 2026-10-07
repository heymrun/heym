"""Who can reach a Drive file.

A user reaches a file by owning it or through a team the file is shared with. Team shares
let members read and download; deleting, sharing and changing a file stay with the owner.
Heym's Drive routes and Heym Work both read access through this module.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, case, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FileTeamShare, GeneratedFile, Team, TeamMember, User

GRANT_OWNER = "owner"
GRANT_SHARED = "shared"


@dataclass(frozen=True)
class AccessibleFile:
    """A file the user reaches, with who shared it when the user is not the owner."""

    file: GeneratedFile
    is_shared: bool
    shared_by: str | None
    shared_by_team: str | None


async def get_accessible_file(
    db: AsyncSession, file_id: uuid.UUID, user_id: uuid.UUID
) -> AccessibleFile | None:
    """The file if the user owns it or a team of theirs holds a share, else None."""
    owned = (
        await db.execute(
            select(GeneratedFile).where(
                GeneratedFile.id == file_id,
                GeneratedFile.owner_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if owned is not None:
        return AccessibleFile(owned, False, None, None)

    shared = (
        await db.execute(
            select(GeneratedFile, User.email, Team.name)
            .join(FileTeamShare, FileTeamShare.file_id == GeneratedFile.id)
            .join(TeamMember, TeamMember.team_id == FileTeamShare.team_id)
            .join(Team, Team.id == FileTeamShare.team_id)
            .join(User, User.id == GeneratedFile.owner_id)
            .where(GeneratedFile.id == file_id, TeamMember.user_id == user_id)
            .order_by(Team.name.asc())
        )
    ).first()
    if shared is None:
        return None
    row, owner_email, team_name = shared
    return AccessibleFile(row, True, owner_email, team_name)


def drive_file_access_rows(user_id: uuid.UUID) -> Select:
    """One ``(file_id, grant)`` row per file ``user_id`` reaches; owner beats shared."""
    team_ids = select(TeamMember.team_id).where(TeamMember.user_id == user_id)
    grants = union_all(
        select(GeneratedFile.id.label("file_id"), literal(GRANT_OWNER).label("grant")).where(
            GeneratedFile.owner_id == user_id
        ),
        select(FileTeamShare.file_id.label("file_id"), literal(GRANT_SHARED).label("grant")).where(
            FileTeamShare.team_id.in_(team_ids)
        ),
    ).subquery()
    is_owner = func.max(case((grants.c.grant == GRANT_OWNER, 1), else_=0))
    return select(
        grants.c.file_id,
        case((is_owner == 1, GRANT_OWNER), else_=GRANT_SHARED).label("grant"),
    ).group_by(grants.c.file_id)
