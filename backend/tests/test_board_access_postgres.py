"""Board access on a real PostgreSQL: owner, direct shares, team shares, none."""

import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Board
from app.services import board_access
from tests.board_pg_support import (
    cleanup,
    connect_or_skip,
    make_board,
    make_user,
    share_board,
    share_board_with_team,
)


class BoardAccessPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = await connect_or_skip(self)
        self.owner = await make_user(self.engine, "owner")
        self.writer = await make_user(self.engine, "writer")
        self.reader = await make_user(self.engine, "reader")
        self.outsider = await make_user(self.engine, "outsider")
        self.board, _ = await make_board(self.engine, self.owner)
        await share_board(self.engine, self.board, self.writer, "read")
        self.team = await share_board_with_team(
            self.engine, self.board, self.owner, [self.writer, self.reader], "write"
        )
        await share_board(self.engine, self.board, self.reader, "read")
        self.teams = [self.team]

    async def asyncTearDown(self) -> None:
        await cleanup(
            self.engine, [self.owner, self.writer, self.reader, self.outsider], self.teams
        )

    async def _ids_for(self, user_id) -> set:
        async with AsyncSession(self.engine) as db:
            rows = await db.execute(
                select(Board.id).where(Board.id.in_(board_access.accessible_board_ids(user_id)))
            )
            return set(rows.scalars().all())

    async def test_owner_gets_owner(self) -> None:
        async with AsyncSession(self.engine) as db:
            board = await db.get(Board, self.board.id)
            self.assertEqual(await board_access.board_permission(db, board, self.owner.id), "owner")

    async def test_most_permissive_share_wins(self) -> None:
        async with AsyncSession(self.engine) as db:
            board = await db.get(Board, self.board.id)
            # Direct read plus team write gives write.
            self.assertEqual(
                await board_access.board_permission(db, board, self.writer.id), "write"
            )

    async def test_outsider_has_no_access(self) -> None:
        async with AsyncSession(self.engine) as db:
            board = await db.get(Board, self.board.id)
            self.assertIsNone(await board_access.board_permission(db, board, self.outsider.id))

    async def test_accessible_board_ids(self) -> None:
        self.assertIn(self.board.id, await self._ids_for(self.reader.id))
        self.assertIn(self.board.id, await self._ids_for(self.owner.id))
        self.assertNotIn(self.board.id, await self._ids_for(self.outsider.id))

    async def test_board_permissions_for_many_boards(self) -> None:
        async with AsyncSession(self.engine) as db:
            board = await db.get(Board, self.board.id)
            self.assertEqual(
                await board_access.board_permissions(db, [board], self.reader.id),
                {self.board.id: "write"},
            )
            self.assertEqual(
                await board_access.board_permissions(db, [board], self.outsider.id), {}
            )

    async def test_members_are_owner_and_every_shared_user_once(self) -> None:
        async with AsyncSession(self.engine) as db:
            board = await db.get(Board, self.board.id)
            members = await board_access.board_members(db, board)
            ids = await board_access.board_member_ids(db, board)
        by_id = {m.user_id: m for m in members}
        self.assertEqual(len(members), 3)
        self.assertEqual(set(by_id), {self.owner.id, self.writer.id, self.reader.id})
        self.assertEqual(ids, set(by_id))
        self.assertEqual(members[0].user_id, self.owner.id)
        self.assertEqual(by_id[self.owner.id].permission, "owner")
        self.assertEqual(by_id[self.reader.id].permission, "write")
        self.assertEqual(by_id[self.writer.id].name, "writer")
