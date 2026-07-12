import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app.api import boards as boards_api
from app.models.board_schemas import (
    BoardCreateRequest,
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
