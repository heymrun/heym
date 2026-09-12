"""Recovery's terminal path has to publish the id its callers are already holding.

``_finalize`` is the branch taken when a run is not re-run: auto recovery is off, the
attempt budget is spent, or the workflow is gone. Everywhere else the terminal history
row carries the execution id that was handed out at dispatch, and a board run is keyed
by that same id, so dropping it strands the streaming endpoint, the by-id lookup and
the board reconciliation helper.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


class _RecordingSession:
    """Captures what _finalize adds and deletes."""

    def __init__(self, existing_history=None):
        self.added = []
        self.statements = []
        self.commit = AsyncMock()
        self._existing_history = existing_history

    def add(self, obj):
        self.added.append(obj)

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
    async def _finalize(self, orphan, *, workflow, status, existing_history=None):
        session = _RecordingSession(existing_history=existing_history)
        sync = AsyncMock()
        with (
            patch("app.db.session.async_session_maker", lambda: session),
            patch.object(board_run_service, "sync_recovered_board_run", sync),
        ):
            await ExecutionRecoveryService()._finalize(
                orphan=orphan, workflow=workflow, status=status
            )
        return session, sync

    async def test_history_keeps_the_original_execution_id(self) -> None:
        orphan = _orphan()
        workflow = SimpleNamespace(id=orphan.workflow_id, owner_id=uuid.uuid4())

        session, _ = await self._finalize(orphan, workflow=workflow, status="skipped")

        (history,) = session.history_rows()
        self.assertEqual(history.id, orphan.execution_id)
        self.assertEqual(history.status, "skipped")
        self.assertTrue(history.recovered)
        self.assertIn("active_workflow_executions", session.deleted_tables())

    async def test_board_trigger_is_reconciled(self) -> None:
        orphan = _orphan(trigger_source="board")
        workflow = SimpleNamespace(id=orphan.workflow_id, owner_id=uuid.uuid4())

        _, sync = await self._finalize(orphan, workflow=workflow, status="skipped")

        sync.assert_awaited_once_with(orphan.execution_id)

    async def test_non_board_trigger_is_not_reconciled(self) -> None:
        orphan = _orphan(trigger_source="manual")
        workflow = SimpleNamespace(id=orphan.workflow_id, owner_id=uuid.uuid4())

        _, sync = await self._finalize(orphan, workflow=workflow, status="failed")

        sync.assert_not_awaited()

    async def test_deleted_workflow_writes_no_history(self) -> None:
        # The foreign key needs the workflow to exist, so the insert could only raise.
        # Dropping the active row is enough: board reconciliation settles the run once
        # the execution is gone.
        orphan = _orphan()

        session, sync = await self._finalize(orphan, workflow=None, status="failed")

        self.assertEqual(session.history_rows(), [])
        self.assertIn("active_workflow_executions", session.deleted_tables())
        sync.assert_not_awaited()

    async def test_existing_history_is_not_written_twice(self) -> None:
        # A paused run published history under this id already. Its real inputs must
        # survive, and the primary key must not collide.
        orphan = _orphan()
        workflow = SimpleNamespace(id=orphan.workflow_id, owner_id=uuid.uuid4())
        paused = SimpleNamespace(id=orphan.execution_id, status="pending")

        session, _ = await self._finalize(
            orphan, workflow=workflow, status="failed", existing_history=paused
        )

        self.assertEqual(session.history_rows(), [])
        self.assertIn("active_workflow_executions", session.deleted_tables())


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


class SkippedBoardRunTests(unittest.IsolatedAsyncioTestCase):
    """A run the operator chose not to resume is not a failure."""

    @staticmethod
    def _env(history_status):
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
            status="running",
            execution_history_id=None,
            active_execution_id=execution_id,
            output={},
            error=None,
            finished_at=None,
        )
        history = SimpleNamespace(
            id=execution_id, status=history_status, inputs={}, outputs={}, node_results=[]
        )
        workflow = SimpleNamespace(id=run.workflow_id, name="Plan")
        session = _GetSession(
            {
                (BoardCardRun.__name__, execution_id): run,
                (ExecutionHistory.__name__, execution_id): history,
                (BoardCard.__name__, card.id): card,
                (BoardColumn.__name__, column.id): column,
                (Board.__name__, board.id): board,
                (Workflow.__name__, run.workflow_id): workflow,
            }
        )
        return execution_id, run, card, session

    async def test_skipped_leaves_the_card_runnable(self) -> None:
        execution_id, run, card, session = self._env("skipped")
        with (
            patch.object(board_run_service, "_column_links", AsyncMock(return_value=[])),
            patch.object(board_run_service, "_abort_remaining", AsyncMock()) as abort,
        ):
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
        abort.assert_awaited_once()

    async def test_failed_still_fails_the_card(self) -> None:
        execution_id, run, card, session = self._env("failed")
        with (
            patch.object(board_run_service, "_column_links", AsyncMock(return_value=[])),
            patch.object(board_run_service, "_abort_remaining", AsyncMock()),
        ):
            await board_run_service.sync_recovered_board_run(
                execution_id, session_factory=lambda: session
            )

        self.assertEqual(run.status, "failed")
        self.assertEqual(card.run_status, "failed")


if __name__ == "__main__":
    unittest.main()
