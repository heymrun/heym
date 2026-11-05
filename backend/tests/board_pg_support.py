"""Real-PostgreSQL fixtures for board tests: users, a board with default columns, cleanup."""

import uuid

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.models import Board, BoardColumn, BoardShare, BoardTeamShare, Team, TeamMember, User
from app.db.session import engine as app_engine

DEFAULT_COLUMNS = ("Backlog", "Planning", "Development", "Done")


async def connect_or_skip(test) -> AsyncEngine:
    """An engine on settings.database_url; skips the test when PostgreSQL is unreachable."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        test.skipTest("PostgreSQL database is not reachable")
    return engine


async def make_user(engine: AsyncEngine, name: str) -> User:
    """A committed user named ``name`` with a unique email."""
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user = User(email=f"{name}-{uuid.uuid4()}@example.com", hashed_password="x", name=name)
        db.add(user)
        await db.commit()
        return user


async def make_board(
    engine: AsyncEngine, owner: User, name: str = "Legal", *, auto_advance: bool = True
) -> tuple[Board, list[BoardColumn]]:
    """A board owned by ``owner`` with the four default columns."""
    async with AsyncSession(engine, expire_on_commit=False) as db:
        board = Board(owner_id=owner.id, name=name)
        # Set as an attribute so the helper also loads before the column exists.
        board.auto_advance = auto_advance
        db.add(board)
        await db.flush()
        columns = [
            BoardColumn(board_id=board.id, name=column_name, position=index)
            for index, column_name in enumerate(DEFAULT_COLUMNS)
        ]
        db.add_all(columns)
        await db.commit()
        return board, columns


async def share_board(engine: AsyncEngine, board: Board, user: User, permission: str) -> None:
    """Share ``board`` with ``user`` directly."""
    async with AsyncSession(engine) as db:
        db.add(BoardShare(board_id=board.id, user_id=user.id, permission=permission))
        await db.commit()


async def share_board_with_team(
    engine: AsyncEngine, board: Board, owner: User, members: list[User], permission: str
) -> Team:
    """A new team holding ``members``, with ``board`` shared to it."""
    async with AsyncSession(engine, expire_on_commit=False) as db:
        team = Team(name=f"team-{uuid.uuid4()}", creator_id=owner.id)
        db.add(team)
        await db.flush()
        db.add_all(
            [TeamMember(team_id=team.id, user_id=m.id, added_by_id=owner.id) for m in members]
        )
        db.add(BoardTeamShare(board_id=board.id, team_id=team.id, permission=permission))
        await db.commit()
        return team


async def cleanup(engine: AsyncEngine, users: list[User], teams: list[Team] = ()) -> None:
    """Delete boards owned by ``users``, then ``teams``, then the users, and dispose."""
    async with AsyncSession(engine) as db:
        ids = [u.id for u in users]
        await db.execute(delete(Board).where(Board.owner_id.in_(ids)))
        for team in teams:
            await db.execute(delete(Team).where(Team.id == team.id))
        await db.execute(delete(User).where(User.id.in_(ids)))
        await db.commit()
    await engine.dispose()
    # Code under test opens its own sessions (auto-advance); their pooled connections
    # belong to this test's event loop and would fail, silently, in the next one.
    await app_engine.dispose()
