import datetime
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import boards as boards_api
from app.models.board_schemas import (
    BoardCreateRequest,
    CardCreateRequest,
    CardMoveRequest,
    ColumnUpdateRequest,
    CommentCreateRequest,
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


class TestCardEndpoints(unittest.IsolatedAsyncioTestCase):
    async def test_create_card_defaults_to_first_column_bottom(self):
        user = _User()
        board = MagicMock()
        board.id = uuid.uuid4()
        board.owner_id = user.id
        first_column = MagicMock()
        first_column.id = uuid.uuid4()
        first_column.board_id = board.id

        db = AsyncMock()
        db.add = MagicMock()
        _wire_db_inserts(db)
        # 1: board, 2: first column by position, 3: card count in column
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=first_column),
                _result_with(scalar_one=2),
            ]
        )

        response = await boards_api.create_card(
            board_id=board.id,
            request=CardCreateRequest(title="Ship the launch email"),
            db=db,
            current_user=user,
        )

        self.assertEqual(response.column_id, first_column.id)
        self.assertEqual(response.position, 2)
        self.assertEqual(response.run_status, "idle")

    async def test_comment_creates_user_activity(self):
        user = _User()
        board = MagicMock()
        board.id = uuid.uuid4()
        board.owner_id = user.id
        card = MagicMock()
        card.id = uuid.uuid4()
        card.board_id = board.id

        db = AsyncMock()
        db.add = MagicMock()
        _wire_db_inserts(db)
        db.execute = AsyncMock(side_effect=[_result_with(scalar=board), _result_with(scalar=card)])

        await boards_api.create_card_comment(
            board_id=board.id,
            card_id=card.id,
            request=CommentCreateRequest(content="Use the Q3 tone guide"),
            db=db,
            current_user=user,
        )

        added = [call.args[0] for call in db.add.call_args_list]
        activities = [obj for obj in added if type(obj).__name__ == "BoardCardActivity"]
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities[0].kind, "comment")
        self.assertEqual(activities[0].author_type, "user")
        self.assertEqual(activities[0].author_user_id, user.id)


class TestMoveAndRun(unittest.IsolatedAsyncioTestCase):
    def _setup(self):
        user = _User()
        board = MagicMock()
        board.id = uuid.uuid4()
        board.owner_id = user.id
        from_column = MagicMock()
        from_column.id = uuid.uuid4()
        from_column.board_id = board.id
        from_column.name = "Backlog"
        from_column.position = 0
        to_column = MagicMock()
        to_column.id = uuid.uuid4()
        to_column.board_id = board.id
        to_column.name = "Planning"
        to_column.position = 1
        now = datetime.datetime.now(datetime.timezone.utc)
        # Real field values (not MagicMock) so `_card_response` validates cleanly.
        card = SimpleNamespace(
            id=uuid.uuid4(),
            board_id=board.id,
            column_id=from_column.id,
            title="Write launch email",
            content="",
            position=0,
            run_status="idle",
            card_metadata={},
            created_at=now,
            updated_at=now,
        )
        return user, board, from_column, to_column, card

    async def test_move_to_new_column_enqueues_chain(self):
        user, board, from_column, to_column, card = self._setup()
        db = AsyncMock()
        db.add = MagicMock()
        _wire_db_inserts(db)
        # 1: board, 2: card, 3: target column, 4: source column,
        # 5+: reindex queries (return empty lists)
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=card),
                _result_with(scalar=to_column),
                _result_with(scalar=from_column),
                _result_with(scalars_list=[]),
                _result_with(scalars_list=[]),
            ]
        )

        with patch.object(
            boards_api.board_run_service, "enqueue_card_chain", AsyncMock(return_value=True)
        ) as enqueue:
            await boards_api.move_card(
                board_id=board.id,
                card_id=card.id,
                request=CardMoveRequest(to_column_id=to_column.id, position=0),
                db=db,
                current_user=user,
            )

        enqueue.assert_awaited_once()
        kwargs = enqueue.await_args.kwargs
        self.assertEqual(kwargs["move"]["from_column"], "Backlog")
        self.assertEqual(kwargs["move"]["to_column"], "Planning")
        self.assertFalse(kwargs["rerun"])
        self.assertTrue(kwargs["allow_advance"])  # forward move may cascade
        added = [call.args[0] for call in db.add.call_args_list]
        events = [o for o in added if type(o).__name__ == "BoardCardActivity"]
        self.assertTrue(any(a.kind == "event" for a in events))

    async def test_backward_move_does_not_allow_advance(self):
        user, board, from_column, to_column, card = self._setup()
        # Card currently in "Planning" (pos 1), moving back to "Backlog" (pos 0).
        card.column_id = to_column.id
        db = AsyncMock()
        db.add = MagicMock()
        _wire_db_inserts(db)
        # 1: board, 2: card, 3: target (Backlog), 4: source (Planning), 5+: reindex
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=card),
                _result_with(scalar=from_column),
                _result_with(scalar=to_column),
                _result_with(scalars_list=[]),
                _result_with(scalars_list=[]),
            ]
        )
        with patch.object(
            boards_api.board_run_service, "enqueue_card_chain", AsyncMock(return_value=True)
        ) as enqueue:
            await boards_api.move_card(
                board_id=board.id,
                card_id=card.id,
                request=CardMoveRequest(to_column_id=from_column.id, position=0),
                db=db,
                current_user=user,
            )
        enqueue.assert_awaited_once()
        self.assertFalse(enqueue.await_args.kwargs["allow_advance"])

    async def test_same_column_reorder_does_not_enqueue(self):
        user, board, from_column, _, card = self._setup()
        db = AsyncMock()
        db.add = MagicMock()
        _wire_db_inserts(db)
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=card),
                _result_with(scalar=from_column),
                _result_with(scalars_list=[]),
            ]
        )

        with patch.object(
            boards_api.board_run_service, "enqueue_card_chain", AsyncMock(return_value=True)
        ) as enqueue:
            await boards_api.move_card(
                board_id=board.id,
                card_id=card.id,
                request=CardMoveRequest(to_column_id=from_column.id, position=1),
                db=db,
                current_user=user,
            )

        enqueue.assert_not_awaited()

    async def test_follow_up_run_conflicts_when_not_enqueued(self):
        user, board, from_column, _, card = self._setup()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=card),
                _result_with(scalar=from_column),
            ]
        )

        with patch.object(
            boards_api.board_run_service, "enqueue_card_chain", AsyncMock(return_value=False)
        ):
            with self.assertRaises(HTTPException) as ctx:
                await boards_api.run_card_chain(
                    board_id=board.id, card_id=card.id, db=db, current_user=user
                )
        self.assertEqual(ctx.exception.status_code, 409)
