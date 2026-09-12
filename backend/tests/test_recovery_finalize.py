"""Recovery's terminal path has to publish the id its callers are already holding.

``_finalize`` is the branch taken when a run is not re-run: auto recovery is off, the
attempt budget is spent, or the workflow is gone. Everywhere else the terminal history
row carries the execution id handed out at dispatch, and a board run is keyed by that
same id, so dropping it strands the streaming endpoint, the by-id lookup and the board
reconciliation helper.

It also has to stay a no-op for a result the board already has. Re-applying one runs
the tail of a finished chain a second time.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Board,
    BoardCard,
    BoardCardRun,
    BoardColumn,
    ExecutionHistory,
    Workflow,
)
from app.services import board_run_service
from app.services.execution_cancellation import ClaimedOrphan
from app.services.execution_recovery import ExecutionRecoveryService


def _orphan(*, trigger_source="manual", workflow_id=None, attempt=1):
    return ClaimedOrphan(
        execution_id=uuid.uuid4(),
        workflow_id=workflow_id or uuid.uuid4(),
        inputs={"seed": 1},
        trigger_source=trigger_source,
        actor_user_id=uuid.uuid4(),
        attempt=attempt,
    )


class _Savepoint:
    def __init__(self, fails):
        self._fails = fails

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        if self._fails:
            raise IntegrityError("INSERT", {}, Exception("execution_history_workflow_id_fkey"))
        return False


class _RecordingSession:
    """Captures what _finalize adds and deletes."""

    def __init__(self, existing_history=None, insert_fails=False):
        self.added = []
        self.statements = []
        self.commit = AsyncMock()
        self._existing_history = existing_history
        self._insert_fails = insert_fails

    def add(self, obj):
        self.added.append(obj)

    def begin_nested(self):
        return _Savepoint(self._insert_fails)

    async def get(self, _model, _pk):
        return self._existing_history

    async def execute(self, statement=None, *_args, **_kwargs):
        self.statements.append(statement)
        return MagicMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def history_rows(self):
        return [o for o in self.added if isinstance(o, ExecutionHistory)]

    def deleted_tables(self):
        return [getattr(getattr(s, "table", None), "name", None) for s in self.statements]


class FinalizeTests(unittest.IsolatedAsyncioTestCase):
    async def _finalize(
        self, orphan, *, workflow, status, existing_history=None, insert_fails=False
    ):
        session = _RecordingSession(existing_history=existing_history, insert_fails=insert_fails)
        sync = AsyncMock()
        with (
            patch("app.db.session.async_session_maker", lambda: session),
            patch.object(board_run_service, "sync_recovered_board_run", sync),
        ):
            await ExecutionRecoveryService()._finalize(
                orphan=orphan, workflow=workflow, status=status
            )
        return session, sync

    @staticmethod
    def _workflow(orphan):
        return SimpleNamespace(id=orphan.workflow_id, owner_id=uuid.uuid4())

    async def test_history_keeps_the_original_execution_id(self) -> None:
        orphan = _orphan()

        session, _ = await self._finalize(orphan, workflow=self._workflow(orphan), status="skipped")

        (history,) = session.history_rows()
        self.assertEqual(history.id, orphan.execution_id)
        self.assertEqual(history.status, "skipped")
        self.assertTrue(history.recovered)
        self.assertIn("active_workflow_executions", session.deleted_tables())

    async def test_board_trigger_is_reconciled(self) -> None:
        orphan = _orphan(trigger_source="board")

        _, sync = await self._finalize(orphan, workflow=self._workflow(orphan), status="skipped")

        sync.assert_awaited_once_with(orphan.execution_id)

    async def test_non_board_trigger_is_not_reconciled(self) -> None:
        orphan = _orphan(trigger_source="manual")

        _, sync = await self._finalize(orphan, workflow=self._workflow(orphan), status="failed")

        sync.assert_not_awaited()

    async def test_deleted_workflow_writes_no_history(self) -> None:
        orphan = _orphan(trigger_source="board")

        session, sync = await self._finalize(orphan, workflow=None, status="failed")

        self.assertEqual(session.history_rows(), [])
        self.assertIn("active_workflow_executions", session.deleted_tables())
        sync.assert_not_awaited()

    async def test_workflow_deleted_after_it_was_loaded_does_not_raise(self) -> None:
        # _load_workflow returned an object, then the row went away, so the insert hits
        # the foreign key. The savepoint keeps that from losing the active row delete.
        orphan = _orphan(trigger_source="board")

        session, sync = await self._finalize(
            orphan, workflow=self._workflow(orphan), status="failed", insert_fails=True
        )

        self.assertIn("active_workflow_executions", session.deleted_tables())
        sync.assert_not_awaited()

    async def test_existing_history_is_not_written_again_but_still_reaches_the_board(
        self,
    ) -> None:
        # A paused run published history under this id already, so its real inputs must
        # survive and the primary key must not collide. The board still has to be
        # offered it: an earlier pass can commit history and die before syncing, and
        # only the helper can tell an applied result from an unapplied one.
        orphan = _orphan(trigger_source="board")
        paused = SimpleNamespace(id=orphan.execution_id, status="pending")

        session, sync = await self._finalize(
            orphan, workflow=self._workflow(orphan), status="failed", existing_history=paused
        )

        self.assertEqual(session.history_rows(), [])
        self.assertIn("active_workflow_executions", session.deleted_tables())
        sync.assert_awaited_once_with(orphan.execution_id)


class _GetSession:
    """Serves db.get by (model, pk) and records adds."""

    def __init__(self, objects):
        self.objects = objects
        self.added = []
        self.commit = AsyncMock()

    def add(self, obj):
        self.added.append(obj)

    async def get(self, model, pk):
        return self.objects.get((model.__name__, pk))

    async def execute(self, *_args, **_kwargs):
        return MagicMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def added_runs(self):
        return [o for o in self.added if isinstance(o, BoardCardRun)]


def _board_env(history_status, *, run_status="running", execution_history_id=None):
    execution_id = uuid.uuid4()
    board = SimpleNamespace(id=uuid.uuid4(), name="Board", owner_id=uuid.uuid4())
    card = SimpleNamespace(id=uuid.uuid4(), board_id=board.id, run_status="running")
    column = SimpleNamespace(id=uuid.uuid4(), ai_instructions=None)
    run = SimpleNamespace(
        id=execution_id,
        card_id=card.id,
        column_id=column.id,
        workflow_id=uuid.uuid4(),
        workflow_name="Plan",
        chain_position=0,
        chain_length=2,
        status=run_status,
        execution_history_id=execution_history_id,
        active_execution_id=execution_id,
        output={},
        error=None,
        finished_at=None,
    )
    history = SimpleNamespace(
        id=execution_id, status=history_status, inputs={}, outputs={}, node_results=[]
    )
    session = _GetSession(
        {
            (BoardCardRun.__name__, execution_id): run,
            (ExecutionHistory.__name__, execution_id): history,
            (BoardCard.__name__, card.id): card,
            (BoardColumn.__name__, column.id): column,
            (Board.__name__, board.id): board,
            (Workflow.__name__, run.workflow_id): SimpleNamespace(id=run.workflow_id, name="Plan"),
        }
    )
    return execution_id, run, card, session


_LINKS = [
    {"workflow_id": uuid.uuid4(), "workflow_name": "Plan", "position": 0},
    {"workflow_id": uuid.uuid4(), "workflow_name": "Build", "position": 1},
]


class SkippedBoardRunTests(unittest.IsolatedAsyncioTestCase):
    """A run the operator chose not to resume is not a failure."""

    async def test_skipped_leaves_the_card_runnable_and_skips_the_rest(self) -> None:
        execution_id, run, card, session = _board_env("skipped")

        # Real _abort_remaining over a real remaining link, so the tail is covered too.
        with patch.object(board_run_service, "_column_links", AsyncMock(return_value=_LINKS)):
            await board_run_service.sync_recovered_board_run(
                execution_id, session_factory=lambda: session
            )

        self.assertEqual(run.status, "skipped")
        self.assertIsNone(run.error)
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(run.execution_history_id, execution_id)
        self.assertIsNone(run.active_execution_id)
        # idle, not failed: nothing went wrong, and the card stays re-runnable.
        self.assertEqual(card.run_status, "idle")
        (tail,) = session.added_runs()
        self.assertEqual(tail.status, "skipped")
        self.assertEqual(tail.chain_position, 1)

    async def test_failed_still_fails_the_card(self) -> None:
        execution_id, run, card, session = _board_env("failed")

        with patch.object(board_run_service, "_column_links", AsyncMock(return_value=_LINKS)):
            await board_run_service.sync_recovered_board_run(
                execution_id, session_factory=lambda: session
            )

        self.assertEqual(run.status, "failed")
        self.assertEqual(card.run_status, "failed")


class AlreadyAppliedResultTests(unittest.IsolatedAsyncioTestCase):
    """A result the chain published itself must not be replayed onto the board."""

    async def test_run_with_a_history_link_is_left_alone(self) -> None:
        # The regression: the chain finished both links, its active row lingered, and
        # recovery replayed the success so the tail ran a second time.
        history_id = uuid.uuid4()
        execution_id, run, card, session = _board_env(
            "success", run_status="success", execution_history_id=history_id
        )
        spawn = MagicMock()

        with (
            patch.object(board_run_service, "_column_links", AsyncMock(return_value=_LINKS)),
            patch.object(board_run_service, "_spawn_chain", spawn),
            patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance,
        ):
            await board_run_service.sync_recovered_board_run(
                execution_id, session_factory=lambda: session
            )

        spawn.assert_not_called()
        advance.assert_not_awaited()
        self.assertEqual(session.added_runs(), [])
        self.assertEqual(run.status, "success")
        self.assertEqual(run.execution_history_id, history_id)
        self.assertEqual(card.run_status, "running")

    async def test_a_run_reconciliation_settled_is_still_corrected(self) -> None:
        # Reconciliation leaves execution_history_id null, so its guess stays correctable.
        execution_id, run, card, session = _board_env(
            "skipped", run_status="failed", execution_history_id=None
        )
        run.error = "Server restarted during execution"

        with patch.object(board_run_service, "_column_links", AsyncMock(return_value=_LINKS)):
            await board_run_service.sync_recovered_board_run(
                execution_id, session_factory=lambda: session
            )

        self.assertEqual(run.status, "skipped")
        self.assertIsNone(run.error)
        self.assertEqual(card.run_status, "idle")


class FinalizeDrivesTheRealSyncTests(unittest.IsolatedAsyncioTestCase):
    """End to end through _finalize into the real helper, nothing mocked between them."""

    async def test_skipped_board_run_is_settled_through_finalize(self) -> None:
        execution_id, run, card, board_session = _board_env("skipped")
        orphan = ClaimedOrphan(
            execution_id=execution_id,
            workflow_id=uuid.uuid4(),
            inputs={},
            trigger_source="board",
            actor_user_id=uuid.uuid4(),
            attempt=1,
        )
        recovery_session = _RecordingSession()
        workflow = SimpleNamespace(id=orphan.workflow_id, owner_id=uuid.uuid4())

        # The helper binds its session factory as a default argument, so the only way to
        # run the real body against a stub is to pass one in.
        real_sync = board_run_service.sync_recovered_board_run

        async def sync_with_stub_session(execution_id):
            await real_sync(execution_id, session_factory=lambda: board_session)

        with (
            patch("app.db.session.async_session_maker", lambda: recovery_session),
            patch.object(board_run_service, "sync_recovered_board_run", sync_with_stub_session),
            patch.object(board_run_service, "_column_links", AsyncMock(return_value=_LINKS)),
        ):
            await ExecutionRecoveryService()._finalize(
                orphan=orphan, workflow=workflow, status="skipped"
            )

        (history,) = recovery_session.history_rows()
        self.assertEqual(history.id, execution_id)
        self.assertEqual(run.status, "skipped")
        self.assertEqual(card.run_status, "idle")

    async def test_history_committed_by_an_interrupted_pass_still_reaches_the_board(
        self,
    ) -> None:
        # The registry lost the finish write and an earlier recovery pass was cut off
        # between committing history and syncing, so the row exists while the board run
        # has no link to it. The chain has to be picked up, not left for reconciliation
        # to fail.
        execution_id, run, card, board_session = _board_env("skipped")
        self.assertIsNone(run.execution_history_id)
        orphan = ClaimedOrphan(
            execution_id=execution_id,
            workflow_id=uuid.uuid4(),
            inputs={},
            trigger_source="board",
            actor_user_id=uuid.uuid4(),
            attempt=1,
        )
        recovery_session = _RecordingSession(
            existing_history=SimpleNamespace(id=execution_id, status="skipped")
        )
        real_sync = board_run_service.sync_recovered_board_run

        async def sync_with_stub_session(eid):
            await real_sync(eid, session_factory=lambda: board_session)

        with (
            patch("app.db.session.async_session_maker", lambda: recovery_session),
            patch.object(board_run_service, "sync_recovered_board_run", sync_with_stub_session),
            patch.object(board_run_service, "_column_links", AsyncMock(return_value=_LINKS)),
        ):
            await ExecutionRecoveryService()._finalize(
                orphan=orphan, workflow=SimpleNamespace(id=orphan.workflow_id), status="skipped"
            )

        self.assertEqual(recovery_session.history_rows(), [])
        self.assertEqual(run.status, "skipped")
        self.assertEqual(run.execution_history_id, execution_id)
        self.assertEqual(card.run_status, "idle")


if __name__ == "__main__":
    unittest.main()
