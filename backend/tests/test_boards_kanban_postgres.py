"""Board API behavior for team kanban use, on a real PostgreSQL."""

import unittest
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.api import boards as boards_api
from app.db.models import BoardCard
from app.models.board_schemas import (
    BoardCreateRequest,
    BoardUpdateRequest,
    CardCreateRequest,
    CardMoveRequest,
)
from tests.board_pg_support import cleanup, connect_or_skip, make_board, make_user


class KanbanPgCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = await connect_or_skip(self)
        self.owner = await make_user(self.engine, "owner")
        self.users = [self.owner]
        self.teams = []

    async def asyncTearDown(self) -> None:
        await cleanup(self.engine, self.users, self.teams)

    def session(self) -> AsyncSession:
        return AsyncSession(self.engine, expire_on_commit=False)

    async def card_in(self, board_id: uuid.UUID, column_id: uuid.UUID, title: str) -> uuid.UUID:
        async with self.session() as db:
            card = await boards_api.create_card(
                board_id=board_id,
                request=CardCreateRequest(title=title, column_id=column_id),
                db=db,
                current_user=self.owner,
            )
            return card.id


class AutoAdvanceTests(KanbanPgCase):
    async def test_new_boards_advance_and_the_setting_round_trips(self) -> None:
        async with self.session() as db:
            created = await boards_api.create_board(
                request=BoardCreateRequest(name="Team", auto_advance=False),
                db=db,
                current_user=self.owner,
            )
            self.assertFalse(created.auto_advance)
            updated = await boards_api.update_board(
                board_id=created.id,
                request=BoardUpdateRequest(auto_advance=True),
                db=db,
                current_user=self.owner,
            )
            self.assertTrue(updated.auto_advance)
            state = await boards_api.get_board_state(
                board_id=created.id, db=db, current_user=self.owner
            )
            self.assertTrue(state.auto_advance)

    async def test_without_auto_advance_a_card_stays_in_an_empty_column(self) -> None:
        board, columns = await make_board(self.engine, self.owner, auto_advance=False)
        card_id = await self.card_in(board.id, columns[0].id, "Contract review")
        async with self.session() as db:
            await boards_api.move_card(
                board_id=board.id,
                card_id=card_id,
                request=CardMoveRequest(to_column_id=columns[2].id),
                db=db,
                current_user=self.owner,
            )
        async with self.session() as db:
            card = await db.get(BoardCard, card_id)
            self.assertEqual(card.column_id, columns[2].id)
            self.assertEqual(card.run_status, "idle")

    async def test_with_auto_advance_a_card_passes_empty_columns(self) -> None:
        board, columns = await make_board(self.engine, self.owner, auto_advance=True)
        card_id = await self.card_in(board.id, columns[0].id, "Contract review")
        async with self.session() as db:
            await boards_api.move_card(
                board_id=board.id,
                card_id=card_id,
                request=CardMoveRequest(to_column_id=columns[2].id),
                db=db,
                current_user=self.owner,
            )
        async with self.session() as db:
            card = await db.get(BoardCard, card_id)
            self.assertEqual(card.column_id, columns[3].id)
