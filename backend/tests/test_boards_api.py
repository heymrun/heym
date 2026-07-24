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
            [(c.name, c.color) for c in sorted(columns, key=lambda c: c.position)],
            [
                ("Backlog", "#8b5cf6"),
                ("Planning", "#22d3ee"),
                ("Development", "#f59e0b"),
                ("Done", "#10d9a0"),
            ],
        )
        db.commit.assert_awaited()


class TestBoardCredentialValidation(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_accessible_credential(self):
        db = AsyncMock()
        user = _User()
        credential_id = uuid.uuid4()

        with patch(
            "app.api.boards.get_accessible_credential",
            AsyncMock(return_value=MagicMock()),
        ) as get_credential:
            await boards_api._validate_accessible_credential(db, credential_id, user)

        get_credential.assert_awaited_once_with(db, credential_id, user.id)

    async def test_rejects_inaccessible_credential(self):
        db = AsyncMock()
        user = _User()
        credential_id = uuid.uuid4()

        with patch(
            "app.api.boards.get_accessible_credential",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await boards_api._validate_accessible_credential(db, credential_id, user)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "Credential not found")


class TestBoardOwnership(unittest.IsolatedAsyncioTestCase):
    async def test_get_board_404_for_missing_or_foreign_board(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result_with(scalar=None))
        with self.assertRaises(HTTPException) as ctx:
            await boards_api.get_board_state(board_id=uuid.uuid4(), db=db, current_user=_User())
        self.assertEqual(ctx.exception.status_code, 404)


class TestBoardActiveExecutionStatus(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _card(*, run_status: str = "failed") -> SimpleNamespace:
        now = datetime.datetime.now(datetime.timezone.utc)
        return SimpleNamespace(
            id=uuid.uuid4(),
            board_id=uuid.uuid4(),
            column_id=uuid.uuid4(),
            title="Recover deployment",
            content="",
            position=0,
            run_status=run_status,
            card_metadata={},
            created_at=now,
            updated_at=now,
        )

    async def test_board_state_prefers_active_workflow_over_stored_failure(self) -> None:
        user = _User()
        card = self._card()
        board = SimpleNamespace(
            id=card.board_id,
            name="Recovery board",
            description=None,
            mapper_model=None,
            mapper_credential_id=None,
        )
        column = SimpleNamespace(
            id=card.column_id,
            board_id=board.id,
            name="Development",
            position=0,
            color=None,
            ai_instructions=None,
        )
        execution_id = uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalars_list=[column]),
                _result_with(scalars_list=[card]),
            ]
        )

        with (
            patch.object(
                boards_api,
                "_get_board_for_user",
                AsyncMock(return_value=(board, "owner")),
            ),
            patch.object(
                boards_api,
                "_active_board_execution_ids",
                AsyncMock(return_value={card.id: {execution_id}}),
            ),
            patch.object(boards_api, "_column_workflow_responses", AsyncMock(return_value={})),
            patch.object(boards_api, "_mapper_credential_name", AsyncMock(return_value=None)),
        ):
            response = await boards_api.get_board_state(board_id=board.id, db=db, current_user=user)

        self.assertEqual(response.cards[0].run_status, "running")
        self.assertTrue(response.has_active_runs)

    async def test_card_detail_marks_only_linked_active_run_as_running(self) -> None:
        user = _User()
        card = self._card()
        board = SimpleNamespace(id=card.board_id)
        execution_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)
        run = SimpleNamespace(
            id=uuid.uuid4(),
            card_id=card.id,
            column_id=card.column_id,
            workflow_id=uuid.uuid4(),
            workflow_name="Deploy",
            chain_position=0,
            chain_length=1,
            status="failed",
            execution_history_id=None,
            active_execution_id=execution_id,
            output={},
            error="Server restarted during execution",
            started_at=now,
            finished_at=now,
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalars_list=[]),
                _result_with(scalars_list=[run]),
            ]
        )

        with (
            patch.object(
                boards_api,
                "_get_board_for_user",
                AsyncMock(return_value=(board, "owner")),
            ),
            patch.object(boards_api, "_get_board_card", AsyncMock(return_value=card)),
            patch.object(
                boards_api,
                "_active_board_execution_ids",
                AsyncMock(return_value={card.id: {execution_id}}),
            ),
        ):
            response = await boards_api.get_card_detail(
                board_id=board.id,
                card_id=card.id,
                db=db,
                current_user=user,
            )

        self.assertEqual(response.card.run_status, "running")
        self.assertEqual(response.runs[0].status, "running")
        self.assertEqual(response.runs[0].error, "Server restarted during execution")


class TestColumnEndpoints(unittest.IsolatedAsyncioTestCase):
    def _board(self, user):
        board = MagicMock()
        board.id = uuid.uuid4()
        board.owner_id = user.id
        return board

    async def test_set_chain_rejects_inaccessible_workflows(self):
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
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=column),
                _result_with(scalars_list=[]),
            ]
        )

        async def _accessible_workflow(_db, workflow_id, _user_id):
            if workflow_id == wanted[0]:
                return owned_workflow
            return None

        with patch(
            "app.api.boards.get_accessible_workflow",
            AsyncMock(side_effect=_accessible_workflow),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await boards_api.update_column(
                    board_id=board.id,
                    column_id=column.id,
                    request=ColumnUpdateRequest(workflow_ids=wanted),
                    db=db,
                    current_user=user,
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "One or more workflows were not found")

    async def test_set_chain_accepts_shared_workflows(self):
        user = _User()
        board = self._board(user)
        column = MagicMock()
        column.id = uuid.uuid4()
        column.board_id = board.id
        column.name = "Dev"
        column.color = "#fff"
        column.position = 0
        column.ai_instructions = None
        wanted = [uuid.uuid4()]
        shared_workflow = MagicMock()
        shared_workflow.id = wanted[0]

        db = AsyncMock()
        db.add = MagicMock()
        _wire_db_inserts(db)
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=column),
                _result_with(scalars_list=[]),
                _result_with(scalars_list=[]),
            ]
        )

        with patch(
            "app.api.boards.get_accessible_workflow",
            AsyncMock(return_value=shared_workflow),
        ):
            response = await boards_api.update_column(
                board_id=board.id,
                column_id=column.id,
                request=ColumnUpdateRequest(workflow_ids=wanted),
                db=db,
                current_user=user,
            )

        self.assertEqual(response.id, column.id)
        db.commit.assert_awaited()

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

    async def test_empty_column_deletes_all_cards_and_commits(self):
        user = _User()
        board = self._board(user)
        column = MagicMock()
        column.id = uuid.uuid4()
        column.board_id = board.id

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=column),
                _result_with(),
            ]
        )

        await boards_api.empty_column(
            board_id=board.id, column_id=column.id, db=db, current_user=user
        )

        delete_statement = db.execute.await_args_list[2].args[0]
        self.assertEqual(delete_statement.table.name, "board_cards")
        self.assertIn("board_cards.column_id", str(delete_statement.whereclause))
        db.commit.assert_awaited_once()


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
        column = MagicMock()
        column.id = uuid.uuid4()
        column.board_id = board.id
        card.column_id = column.id

        db = AsyncMock()
        db.add = MagicMock()
        _wire_db_inserts(db)
        # 1: board, 2: card, 3: column (for the planning-gate answer hook)
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=card),
                _result_with(scalar=column),
            ]
        )

        with patch.object(
            boards_api.board_run_service, "answer_card_comment", AsyncMock(return_value=False)
        ) as answer:
            await boards_api.create_card_comment(
                board_id=board.id,
                card_id=card.id,
                request=CommentCreateRequest(content="Use the Q3 tone guide"),
                db=db,
                current_user=user,
            )

        # Answering a card re-runs the gate column's chain (no-op past the gate).
        answer.assert_awaited_once()
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
                # Ordered column ids for the positional planning gate.
                _result_with(scalars_list=[from_column.id]),
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

    async def test_follow_up_run_allows_auto_advance_past_the_gate(self):
        user, board, from_column, to_column, card = self._setup()
        development = MagicMock()
        development.id = uuid.uuid4()
        development.board_id = board.id
        development.name = "Development"
        development.position = 2
        card.column_id = development.id
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=card),
                _result_with(scalar=development),
                _result_with(scalars_list=[from_column.id, to_column.id, development.id]),
            ]
        )

        with patch.object(
            boards_api.board_run_service, "enqueue_card_chain", AsyncMock(return_value=True)
        ) as enqueue:
            await boards_api.run_card_chain(
                board_id=board.id, card_id=card.id, db=db, current_user=user
            )

        self.assertTrue(enqueue.await_args.kwargs["allow_advance"])

    async def test_follow_up_run_on_gate_column_never_auto_advances(self):
        """Second column (sorted index 1) waits for a comment — even without skip flag."""
        user, board, from_column, to_column, card = self._setup()
        card.column_id = to_column.id
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=card),
                _result_with(scalar=to_column),
                _result_with(scalars_list=[from_column.id, to_column.id]),
            ]
        )

        with patch.object(
            boards_api.board_run_service, "enqueue_card_chain", AsyncMock(return_value=True)
        ) as enqueue:
            await boards_api.run_card_chain(
                board_id=board.id, card_id=card.id, db=db, current_user=user
            )

        self.assertFalse(enqueue.await_args.kwargs["allow_advance"])

    async def test_follow_up_run_can_skip_auto_advance(self):
        user, board, from_column, to_column, card = self._setup()
        development = MagicMock()
        development.id = uuid.uuid4()
        development.board_id = board.id
        development.name = "Development"
        development.position = 2
        card.column_id = development.id
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=card),
                _result_with(scalar=development),
                _result_with(scalars_list=[from_column.id, to_column.id, development.id]),
            ]
        )

        with patch.object(
            boards_api.board_run_service, "enqueue_card_chain", AsyncMock(return_value=True)
        ) as enqueue:
            await boards_api.run_card_chain(
                board_id=board.id,
                card_id=card.id,
                skip_auto_advance=True,
                db=db,
                current_user=user,
            )

        self.assertFalse(enqueue.await_args.kwargs["allow_advance"])


class TestBoardAccess(unittest.IsolatedAsyncioTestCase):
    """Boards reach their owner, the users they are shared with, and those users' teams."""

    def _board(self, owner_id):
        board = MagicMock()
        board.id = uuid.uuid4()
        board.owner_id = owner_id
        return board

    async def test_owner_always_has_owner_permission(self):
        user = _User()
        board = self._board(user.id)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_result_with(scalar=board)])

        found, permission = await boards_api._get_board_for_user(db, board.id, user, write=True)

        self.assertIs(found, board)
        self.assertEqual(permission, "owner")
        # The owner short-circuits: no share lookups at all.
        self.assertEqual(db.execute.await_count, 1)

    async def test_direct_share_grants_write(self):
        user = _User()
        board = self._board(uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalars_list=["write"]),
                _result_with(scalars_list=[]),
            ]
        )

        _, permission = await boards_api._get_board_for_user(db, board.id, user, write=True)

        self.assertEqual(permission, "write")

    async def test_team_share_grants_read_and_blocks_writes(self):
        user = _User()
        board = self._board(uuid.uuid4())

        def _db():
            db = AsyncMock()
            db.execute = AsyncMock(
                side_effect=[
                    _result_with(scalar=board),
                    _result_with(scalars_list=[]),
                    _result_with(scalars_list=["read"]),
                ]
            )
            return db

        _, permission = await boards_api._get_board_for_user(_db(), board.id, user, write=False)
        self.assertEqual(permission, "read")

        with self.assertRaises(HTTPException) as ctx:
            await boards_api._get_board_for_user(_db(), board.id, user, write=True)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_unshared_board_is_not_found(self):
        user = _User()
        board = self._board(uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalars_list=[]),
                _result_with(scalars_list=[]),
            ]
        )

        with self.assertRaises(HTTPException) as ctx:
            await boards_api._get_board_for_user(db, board.id, user, write=False)
        self.assertEqual(ctx.exception.status_code, 404)


class TestCardAttachments(unittest.IsolatedAsyncioTestCase):
    def _card(self, board, attachments=None):
        card = MagicMock()
        card.id = uuid.uuid4()
        card.board_id = board.id
        card.card_metadata = {"attachments": list(attachments)} if attachments else {}
        return card

    async def test_upload_appends_the_attachment_and_logs_it(self):
        user = _User()
        board = MagicMock()
        board.id = uuid.uuid4()
        board.owner_id = user.id
        card = self._card(board)

        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(side_effect=[_result_with(scalar=board), _result_with(scalar=card)])
        stored = SimpleNamespace(
            id=uuid.uuid4(), filename="brief.pdf", mime_type="application/pdf", size_bytes=12
        )
        upload = SimpleNamespace(filename="brief.pdf", content_type="application/pdf")

        with (
            patch.object(boards_api, "read_upload_file_limited", AsyncMock(return_value=b"pdf")),
            patch.object(boards_api, "store_file", AsyncMock(return_value=stored)),
            patch.object(
                boards_api,
                "create_access_token",
                AsyncMock(return_value=SimpleNamespace(token="tok")),
            ),
            patch.object(boards_api, "build_public_base_url", MagicMock(return_value="http://x")),
        ):
            response = await boards_api.add_card_attachment(
                board_id=board.id,
                card_id=card.id,
                request=MagicMock(),
                file=upload,
                db=db,
                current_user=user,
            )

        self.assertEqual(response.name, "brief.pdf")
        self.assertEqual(response.url, "http://x/api/files/dl/tok")
        # The workflow payload reads attachments off the card metadata.
        self.assertEqual(card.card_metadata["attachments"][0]["file_id"], str(stored.id))
        activities = [
            call.args[0]
            for call in db.add.call_args_list
            if type(call.args[0]).__name__ == "BoardCardActivity"
        ]
        self.assertEqual(len(activities), 1)

    async def test_delete_removes_the_entry_and_the_file(self):
        user = _User()
        board = MagicMock()
        board.id = uuid.uuid4()
        board.owner_id = user.id
        file_id = uuid.uuid4()
        card = self._card(board, [{"file_id": str(file_id), "name": "brief.pdf"}])

        stored = SimpleNamespace(id=file_id, owner_id=board.owner_id)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_result_with(scalar=board), _result_with(scalar=card)])
        db.get = AsyncMock(return_value=stored)

        with patch.object(boards_api, "delete_file", AsyncMock()) as delete:
            await boards_api.delete_card_attachment(
                board_id=board.id,
                card_id=card.id,
                file_id=file_id,
                db=db,
                current_user=user,
            )

        self.assertEqual(card.card_metadata["attachments"], [])
        delete.assert_awaited_once()

    async def test_delete_unknown_attachment_is_404(self):
        user = _User()
        board = MagicMock()
        board.id = uuid.uuid4()
        board.owner_id = user.id
        card = self._card(board)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_result_with(scalar=board), _result_with(scalar=card)])

        with self.assertRaises(HTTPException) as ctx:
            await boards_api.delete_card_attachment(
                board_id=board.id,
                card_id=card.id,
                file_id=uuid.uuid4(),
                db=db,
                current_user=user,
            )
        self.assertEqual(ctx.exception.status_code, 404)


class TestDeleteCardActivity(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_an_activity_from_the_timeline(self):
        user = _User()
        board = MagicMock()
        board.id = uuid.uuid4()
        board.owner_id = user.id
        card = MagicMock()
        card.id = uuid.uuid4()
        card.board_id = board.id
        activity = MagicMock()
        activity.id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=card),
                _result_with(scalar=activity),
            ]
        )

        await boards_api.delete_card_activity(
            board_id=board.id,
            card_id=card.id,
            activity_id=activity.id,
            db=db,
            current_user=user,
        )

        db.delete.assert_awaited_once_with(activity)

    async def test_unknown_activity_is_404(self):
        user = _User()
        board = MagicMock()
        board.id = uuid.uuid4()
        board.owner_id = user.id
        card = MagicMock()
        card.id = uuid.uuid4()
        card.board_id = board.id

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result_with(scalar=board),
                _result_with(scalar=card),
                _result_with(scalar=None),
            ]
        )

        with self.assertRaises(HTTPException) as ctx:
            await boards_api.delete_card_activity(
                board_id=board.id,
                card_id=card.id,
                activity_id=uuid.uuid4(),
                db=db,
                current_user=user,
            )
        self.assertEqual(ctx.exception.status_code, 404)


class TestReorderColumns(unittest.IsolatedAsyncioTestCase):
    """Column positions drive the planning gate, so they stay a dense 0..n-1 sequence."""

    async def test_moving_a_column_renumbers_the_board(self):
        board = MagicMock()
        board.id = uuid.uuid4()
        columns = []
        for position, name in enumerate(["Backlog", "Planning", "Development", "Done"]):
            column = MagicMock()
            column.id = uuid.uuid4()
            column.name = name
            column.position = position
            columns.append(column)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result_with(scalars_list=columns))

        # Done (last) becomes the second column.
        await boards_api._reorder_columns(db, board, columns[3], 1)

        order = sorted(columns, key=lambda c: c.position)
        self.assertEqual([c.name for c in order], ["Backlog", "Done", "Planning", "Development"])
        self.assertEqual([c.position for c in order], [0, 1, 2, 3])

    async def test_target_beyond_the_end_moves_the_column_last(self):
        board = MagicMock()
        board.id = uuid.uuid4()
        columns = []
        for position, name in enumerate(["A", "B", "C"]):
            column = MagicMock()
            column.id = uuid.uuid4()
            column.name = name
            column.position = position
            columns.append(column)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result_with(scalars_list=columns))

        await boards_api._reorder_columns(db, board, columns[0], 99)

        order = sorted(columns, key=lambda c: c.position)
        self.assertEqual([c.name for c in order], ["B", "C", "A"])
