"""Who can reach a kanban board, and how far.

A user reaches a board by owning it, by a direct share, or through a team the board is
shared with; the most permissive grant wins. The board routes, the chat board tools and
Heym Work all read board access here, so this module imports no settings.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Board, BoardShare, BoardTeamShare, TeamMember, User
from app.services.dashboard_access import (
    PERMISSION_OWNER,
    PERMISSION_READ,
    PERMISSION_WRITE,
    strongest_permission,
)

__all__ = [
    "PERMISSION_OWNER",
    "PERMISSION_READ",
    "PERMISSION_WRITE",
    "BoardMember",
    "accessible_board_ids",
    "board_member_ids",
    "board_members",
    "board_permission",
    "board_permissions",
]


@dataclass(frozen=True)
class BoardMember:
    """Someone who can open a board, with the access that applies to them."""

    user_id: uuid.UUID
    name: str | None
    email: str
    permission: str


def _team_ids(user_id: uuid.UUID) -> Select:
    return select(TeamMember.team_id).where(TeamMember.user_id == user_id)


def _grants(user_id: uuid.UUID) -> Select:
    """Every (board_id, permission) grant ``user_id`` holds, direct or through a team."""
    direct = select(BoardShare.board_id, BoardShare.permission).where(BoardShare.user_id == user_id)
    via_team = select(BoardTeamShare.board_id, BoardTeamShare.permission).where(
        BoardTeamShare.team_id.in_(_team_ids(user_id))
    )
    return direct.union_all(via_team)


def accessible_board_ids(user_id: uuid.UUID) -> Select:
    """A select of every board id ``user_id`` owns or reaches through a share."""
    grants = _grants(user_id).subquery()
    return select(Board.id).where(
        or_(Board.owner_id == user_id, Board.id.in_(select(grants.c.board_id)))
    )


async def board_permission(db: AsyncSession, board: Board, user_id: uuid.UUID) -> str | None:
    """The caller's access to ``board``: owner, write, read, or None when it is not shared."""
    if board.owner_id == user_id:
        return PERMISSION_OWNER
    grants = _grants(user_id).subquery()
    result = await db.execute(select(grants.c.permission).where(grants.c.board_id == board.id))
    return strongest_permission(list(result.scalars().all()))


async def board_permissions(
    db: AsyncSession, boards: Sequence[Board], user_id: uuid.UUID
) -> dict[uuid.UUID, str]:
    """The caller's access to each board in ``boards`` they can open, in one query."""
    out = {board.id: PERMISSION_OWNER for board in boards if board.owner_id == user_id}
    others = [board.id for board in boards if board.id not in out]
    if not others:
        return out
    grants = _grants(user_id).subquery()
    rows = await db.execute(
        select(grants.c.board_id, grants.c.permission).where(grants.c.board_id.in_(others))
    )
    collected: dict[uuid.UUID, list[str]] = {}
    for board_id, permission in rows.all():
        collected.setdefault(board_id, []).append(permission)
    for board_id, permissions in collected.items():
        strongest = strongest_permission(permissions)
        if strongest is not None:
            out[board_id] = strongest
    return out


async def board_members(db: AsyncSession, board: Board) -> list[BoardMember]:
    """The owner and every user the board is shared with, directly or through a team, once.

    The owner comes first, then everyone else by name.
    """
    direct = select(BoardShare.user_id, BoardShare.permission).where(
        BoardShare.board_id == board.id
    )
    via_team = (
        select(TeamMember.user_id, BoardTeamShare.permission)
        .join(BoardTeamShare, BoardTeamShare.team_id == TeamMember.team_id)
        .where(BoardTeamShare.board_id == board.id)
    )
    grants = direct.union_all(via_team).subquery()
    rows = await db.execute(
        select(User.id, User.name, User.email, grants.c.permission).join(
            grants, grants.c.user_id == User.id
        )
    )
    collected: dict[uuid.UUID, tuple[str | None, str, list[str]]] = {}
    for user_id, name, email, permission in rows.all():
        entry = collected.setdefault(user_id, (name, email, []))
        entry[2].append(permission)
    owner = (
        await db.execute(select(User.id, User.name, User.email).where(User.id == board.owner_id))
    ).one_or_none()
    members: list[BoardMember] = []
    for user_id, (name, email, permissions) in collected.items():
        if user_id == board.owner_id:
            continue
        members.append(
            BoardMember(user_id, name, email, strongest_permission(permissions) or PERMISSION_READ)
        )
    members.sort(key=lambda m: (m.name or m.email).casefold())
    if owner is not None:
        members.insert(0, BoardMember(owner.id, owner.name, owner.email, PERMISSION_OWNER))
    return members


async def board_member_ids(db: AsyncSession, board: Board) -> set[uuid.UUID]:
    """The ids of everyone who can open ``board``."""
    return {member.user_id for member in await board_members(db, board)}
