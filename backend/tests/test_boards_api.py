import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app.api import boards as boards_api
from app.models.board_schemas import (
    BoardCreateRequest,
    ColumnUpdateRequest,
)


class _User:
    def __init__(self):
        self.id = uuid.uuid4()


def _result_with(*, scalar=None, scalars_list=None, scalar_one=None):
    """Build a MagicMock imitating a SQLAlchemy Result."""
    res = MagicMock()
    res.scalar_one_or_none.return_value = scalar
    res.scalar.return_value = scalar_one
    scalars = MagicMock()
    scalars.all.return_value = scalars_list if scalars_list is not None else []
    res.scalars.return_value = scalars
    return res


def _wire_db_inserts(db):
    """Assign PKs and column defaults on flush/refresh like PostgreSQL would.

    ORM python-side defaults (run_status, card_metadata, timestamps) only apply
    at flush time against a real engine, so the fakes fill them in here to keep
    the endpoint response models valid.
    """

    def _apply_defaults(obj):
        now = datetime.datetime.now(datetime.timezone.utc)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        if hasattr(obj, "run_status") and obj.run_status is None:
            obj.run_status = "idle"
        if hasattr(obj, "card_metadata") and obj.card_metadata is None:
            obj.card_metadata = {}
        if hasattr(obj, "data") and obj.data is None:
            obj.data = {}

    async def fake_flush():
        for call in db.add.call_args_list:
            _apply_defaults(call.args[0])

    async def fake_refresh(obj):
        _apply_defaults(obj)

    db.flush = AsyncMock(side_effect=fake_flush)
    db.refresh = AsyncMock(side_effect=fake_refresh)


class TestCreateBoard(unittest.IsolatedAsyncioTestCase):
    async def test_create_board_seeds_default_columns(self):
        db = AsyncMock()
        db.add = MagicMock()
        _wire_db_inserts(db)
        user = _User()

        await boards_api.create_board(
            request=BoardCreateRequest(name="My Board"), db=db, current_user=user
        )

        added = [call.args[0] for call in db.add.call_args_list]
        boards = [obj for obj in added if type(obj).__name__ == "Board"]
        columns = [obj for obj in added if type(obj).__name__ == "BoardColumn"]
        self.assertEqual(len(boards), 1)
        self.assertEqual(boards[0].name, "My Board")
        self.assertEqual(
            [c.name for c in sorted(columns, key=lambda c: c.position)],
            ["Backlog", "Planning", "To Do", "Waiting", "Development", "Done"],
        )
        db.commit.assert_awaited()


class TestBoardOwnership(unittest.IsolatedAsyncioTestCase):
    async def test_get_board_404_for_missing_or_foreign_board(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result_with(scalar=None))
        with self.assertRaises(HTTPException) as ctx:
            await boards_api.get_board_state(board_id=uuid.uuid4(), db=db, current_user=_User())
        self.assertEqual(ctx.exception.status_code, 404)


class TestColumnEndpoints(unittest.IsolatedAsyncioTestCase):
    def _board(self, user):
        board = MagicMock()
        board.id = uuid.uuid4()
        board.owner_id = user.id
        return board

    async def test_set_chain_rejects_unowned_workflows(self):
        user = _User()
        board = self._board(user)
        column = MagicMock()
        column.id = uuid.uuid4()
        column.board_id = board.id
        wanted = [uuid.uuid4(), uuid.uuid4()]
        owned_workflow = MagicMock()
        owned_workflow.id = wanted[0]

        db = AsyncMock()
        db.add = MagicMock()
        # 1: board lookup, 2: column lookup, 3: owned workflows lookup (only one found)
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=column),
                _result_with(scalars_list=[owned_workflow]),
            ]
        )

        with self.assertRaises(HTTPException) as ctx:
            await boards_api.update_column(
                board_id=board.id,
                column_id=column.id,
                request=ColumnUpdateRequest(workflow_ids=wanted),
                db=db,
                current_user=user,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_delete_column_with_cards_conflicts(self):
        user = _User()
        board = self._board(user)
        column = MagicMock()
        column.id = uuid.uuid4()
        column.board_id = board.id

        db = AsyncMock()
        # 1: board, 2: column, 3: card count
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=column),
                _result_with(scalar_one=3),
            ]
        )

        with self.assertRaises(HTTPException) as ctx:
            await boards_api.delete_column(
                board_id=board.id, column_id=column.id, db=db, current_user=user
            )
        self.assertEqual(ctx.exception.status_code, 409)
