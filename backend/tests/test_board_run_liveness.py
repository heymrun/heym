"""Board runs may only be settled by something other than their own chain when dead.

Startup reconciliation runs once per uvicorn worker (8 per container) and once per
instance in a cluster, so it can fire while another process is part-way through a
chain. Failing a live run both lies about it and releases the enqueue guard, which
lets a second chain start on the same card.
"""

import asyncio
import contextlib
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.sql.dml import Update

from app.services import board_run_service, execution_recovery
from app.services.execution_cancellation import RECOVERY_STALE_AFTER_SECONDS

# Ages are relative to real time because reconciliation and the enqueue guard each
# read the clock themselves.
SETTLED_AGE = RECOVERY_STALE_AFTER_SECONDS + 60
FRESH_AGE = 1


def _run(*, status="running", active_execution_id=None, age_seconds=SETTLED_AGE, card_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        card_id=card_id or uuid.uuid4(),
        status=status,
        active_execution_id=active_execution_id,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
        error=None,
        finished_at=None,
    )


def _result(rows):
    rows = list(rows)
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    result.all.return_value = rows
    result.first.return_value = rows[0] if rows else None
    return result


class _SequencedSession:
    """Serves db.execute results in call order and records the statements."""

    def __init__(self, results):
        self._results = list(results)
        self.commit = AsyncMock()
        self.executed = 0
        self.statements = []

    async def execute(self, statement=None, *_args, **_kwargs):
        self.statements.append(statement)
        # Queued results stand in for reads only, so adding a write does not shift them.
        if isinstance(statement, Update):
            return _result([])
        result = self._results[self.executed] if self.executed < len(self._results) else _result([])
        self.executed += 1
        return result

    def writes(self, table):
        """Recorded UPDATE statements against ``table``."""
        return [
            s
            for s in self.statements
            if isinstance(s, Update) and s.table.name == table  # type: ignore[attr-defined]
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class BoardRunIsDeadTests(unittest.TestCase):
    def test_live_execution_is_not_dead(self) -> None:
        execution_id = uuid.uuid4()
        run = _run(active_execution_id=execution_id)
        self.assertFalse(board_run_service.board_run_is_dead(run, {execution_id}))

    def test_pending_run_is_never_dead(self) -> None:
        # A pending run is parked on a human answer and clears active_execution_id,
        # so a liveness-only rule would wrongly release the card.
        run = _run(status="pending", active_execution_id=None)
        self.assertFalse(board_run_service.board_run_is_dead(run, set()))

    def test_young_run_is_not_dead(self) -> None:
        # register_execution queues the active row write, so a just-started run has
        # no row yet and must not be read as finished.
        run = _run(active_execution_id=uuid.uuid4(), age_seconds=FRESH_AGE)
        self.assertFalse(board_run_service.board_run_is_dead(run, set()))

    def test_old_run_without_a_live_execution_is_dead(self) -> None:
        run = _run(active_execution_id=uuid.uuid4(), age_seconds=SETTLED_AGE)
        self.assertTrue(board_run_service.board_run_is_dead(run, set()))

    def test_young_run_without_an_execution_id_is_not_dead(self) -> None:
        run = _run(active_execution_id=None, age_seconds=FRESH_AGE)
        self.assertFalse(board_run_service.board_run_is_dead(run, set()))

    def test_old_run_without_an_execution_id_is_dead(self) -> None:
        # Every path that nulls active_execution_id also leaves a terminal or pending
        # status, so a committed running row with no id has no live execution behind
        # it and must be settled rather than blocking the card forever.
        run = _run(active_execution_id=None, age_seconds=SETTLED_AGE)
        self.assertTrue(board_run_service.board_run_is_dead(run, set()))


class ReconcileOrphanedBoardRunsTests(unittest.IsolatedAsyncioTestCase):
    async def _reconcile(self, runs, live_execution_ids, _cards=()):
        session = _SequencedSession([_result(runs), _result(live_execution_ids)])
        with patch.object(board_run_service, "async_session_maker", lambda: session):
            await board_run_service.reconcile_orphaned_board_runs()
        return session

    async def test_live_run_is_left_alone(self) -> None:
        execution_id = uuid.uuid4()
        run = _run(active_execution_id=execution_id)

        session = await self._reconcile([run], [execution_id], [])

        self.assertEqual(session.writes("board_card_runs"), [])
        self.assertEqual(session.writes("board_cards"), [])

    async def test_dead_run_and_its_card_are_failed(self) -> None:
        run = _run(active_execution_id=uuid.uuid4())

        session = await self._reconcile([run], [], [])

        (run_write,) = session.writes("board_card_runs")
        self.assertEqual(run_write.compile().params["status"], "failed")
        self.assertEqual(run_write.compile().params["error"], "Server restarted during execution")
        (card_write,) = session.writes("board_cards")
        self.assertEqual(card_write.compile().params["run_status"], "failed")

    async def test_young_run_is_left_alone(self) -> None:
        run = _run(active_execution_id=uuid.uuid4(), age_seconds=FRESH_AGE)

        session = await self._reconcile([run], [], [])

        self.assertEqual(session.writes("board_card_runs"), [])
        self.assertEqual(session.writes("board_cards"), [])

    async def test_card_stays_running_while_any_of_its_runs_is_live(self) -> None:
        card_id = uuid.uuid4()
        live_execution_id = uuid.uuid4()
        dead = _run(active_execution_id=uuid.uuid4(), card_id=card_id)
        live = _run(active_execution_id=live_execution_id, card_id=card_id)

        session = await self._reconcile([dead, live], [live_execution_id], [])

        self.assertEqual(len(session.writes("board_card_runs")), 1)
        self.assertEqual(session.writes("board_cards"), [])

    async def test_settle_is_guarded_on_the_run_still_being_running(self) -> None:
        # The judgement is made from a snapshot; the chain drops its active row before
        # committing its own result, so an unguarded write lands on top of a success.
        run = _run(active_execution_id=uuid.uuid4())

        session = await self._reconcile([run], [], [])

        (run_write,) = session.writes("board_card_runs")
        self.assertIn("board_card_runs.status", str(run_write.whereclause))
        (card_write,) = session.writes("board_cards")
        self.assertIn("board_cards.run_status", str(card_write.whereclause))


class EnqueueCardChainGuardTests(unittest.IsolatedAsyncioTestCase):
    async def _enqueue(self, runs, live_execution_ids):
        card = SimpleNamespace(id=uuid.uuid4(), board_id=uuid.uuid4(), run_status="idle")
        column = SimpleNamespace(id=uuid.uuid4())
        board = SimpleNamespace(id=card.board_id)
        session = _SequencedSession([_result(runs), _result(live_execution_ids)])
        links = [{"workflow_id": uuid.uuid4(), "workflow_name": "Plan", "position": 0}]
        spawn = MagicMock()
        with (
            patch.object(board_run_service, "_column_links", AsyncMock(return_value=links)),
            patch.object(board_run_service, "_spawn_chain", spawn),
        ):
            enqueued = await board_run_service.enqueue_card_chain(
                session, card=card, column=column, board=board, move=None, rerun=True
            )
        return enqueued, spawn, session

    async def test_live_run_blocks_a_new_chain(self) -> None:
        execution_id = uuid.uuid4()
        enqueued, spawn, _ = await self._enqueue(
            [_run(active_execution_id=execution_id)], [execution_id]
        )
        self.assertFalse(enqueued)
        spawn.assert_not_called()

    async def test_pending_run_blocks_a_new_chain(self) -> None:
        enqueued, spawn, _ = await self._enqueue(
            [_run(status="pending", active_execution_id=None)], []
        )
        self.assertFalse(enqueued)
        spawn.assert_not_called()

    async def test_young_run_blocks_a_new_chain(self) -> None:
        enqueued, spawn, _ = await self._enqueue(
            [_run(active_execution_id=uuid.uuid4(), age_seconds=FRESH_AGE)], []
        )
        self.assertFalse(enqueued)
        spawn.assert_not_called()

    async def test_dead_run_does_not_block_a_new_chain(self) -> None:
        # A run abandoned by recovery's _finalize keeps active_execution_id but its
        # active row is gone, so it must not lock the card out forever.
        enqueued, spawn, _ = await self._enqueue([_run(active_execution_id=uuid.uuid4())], [])
        self.assertTrue(enqueued)
        spawn.assert_called_once()

    async def test_skipped_dead_run_is_settled_not_left_running(self) -> None:
        # Starting a new chain over a stale row is not enough: the row keeps blocking
        # every other reader of the status column, such as the comment gate.
        dead = _run(active_execution_id=uuid.uuid4())
        enqueued, _, session = await self._enqueue([dead], [])
        self.assertTrue(enqueued)
        (run_write,) = session.writes("board_card_runs")
        self.assertEqual(run_write.compile().params["error"], "Execution is no longer running")
        self.assertIn("board_card_runs.status", str(run_write.whereclause))

    async def test_dead_run_is_left_untouched_while_a_sibling_is_live(self) -> None:
        live_execution_id = uuid.uuid4()
        dead = _run(active_execution_id=uuid.uuid4())
        live = _run(active_execution_id=live_execution_id)
        enqueued, spawn, session = await self._enqueue([dead, live], [live_execution_id])
        self.assertFalse(enqueued)
        spawn.assert_not_called()
        self.assertEqual(session.writes("board_card_runs"), [])


class AnswerCardCommentGuardTests(unittest.IsolatedAsyncioTestCase):
    """The comment gate reads the same status column, so it needs the same rule."""

    async def _blocking(self, runs, live_execution_ids):
        session = _SequencedSession([_result(runs), _result(live_execution_ids)])
        blocking = await board_run_service.blocking_card_runs(session, uuid.uuid4())
        return blocking, session

    async def test_live_run_still_blocks_the_answer(self) -> None:
        execution_id = uuid.uuid4()
        blocking, session = await self._blocking(
            [_run(active_execution_id=execution_id)], [execution_id]
        )
        self.assertEqual(len(blocking), 1)

    async def test_pending_run_still_blocks_the_answer(self) -> None:
        blocking, session = await self._blocking(
            [_run(status="pending", active_execution_id=None)], []
        )
        self.assertEqual(len(blocking), 1)

    async def test_dead_run_is_settled_and_stops_blocking_the_answer(self) -> None:
        dead = _run(active_execution_id=uuid.uuid4())
        blocking, session = await self._blocking([dead], [])
        self.assertEqual(blocking, [])
        (run_write,) = session.writes("board_card_runs")
        self.assertIn("board_card_runs.status", str(run_write.whereclause))
        # The card has to settle with the run: reconciliation only revisits cards that
        # still have a running run, so a card left behind here is stuck for good.
        (card_write,) = session.writes("board_cards")
        self.assertEqual(card_write.compile().params["run_status"], "failed")


class AnswerCardCommentEndToEndTests(unittest.IsolatedAsyncioTestCase):
    """Through the real answer_card_comment, not just the shared helper."""

    @staticmethod
    def _env():
        card = SimpleNamespace(id=uuid.uuid4(), run_status="success")
        column = SimpleNamespace(id=uuid.uuid4())
        board = SimpleNamespace(id=uuid.uuid4())
        columns = _result([uuid.uuid4(), column.id, uuid.uuid4()])
        return card, column, board, columns

    async def test_live_run_blocks_the_answer(self) -> None:
        card, column, board, columns = self._env()
        execution_id = uuid.uuid4()
        run = _run(active_execution_id=execution_id, card_id=card.id)
        session = _SequencedSession([columns, _result([run]), _result([execution_id])])

        with patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance:
            result = await board_run_service.answer_card_comment(
                session, card=card, column=column, board=board
            )

        self.assertFalse(result)
        advance.assert_not_awaited()
        self.assertEqual(run.status, "running")

    async def test_abandoned_run_no_longer_blocks_the_answer(self) -> None:
        # The regression the review caught: a stale row left behind by a skipped
        # recovery used to reject the human answer for good.
        card, column, board, columns = self._env()
        dead = _run(active_execution_id=uuid.uuid4(), card_id=card.id)
        session = _SequencedSession(
            [columns, _result([dead]), _result([]), _result([uuid.uuid4()])]
        )

        with patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance:
            result = await board_run_service.answer_card_comment(
                session, card=card, column=column, board=board
            )

        self.assertTrue(result)
        advance.assert_awaited_once()
        self.assertEqual(len(session.writes("board_card_runs")), 1)
        self.assertEqual(card.run_status, "running")

    async def test_unanswered_gate_still_settles_run_and_card_together(self) -> None:
        # The second regression the review caught: the helper settled the run, then
        # answer_card_comment bailed out because no previous run had succeeded, leaving
        # the card running with no running run for reconciliation to ever find again.
        card, column, board, columns = self._env()
        dead = _run(active_execution_id=uuid.uuid4(), card_id=card.id)
        session = _SequencedSession([columns, _result([dead]), _result([])])

        with patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance:
            result = await board_run_service.answer_card_comment(
                session, card=card, column=column, board=board
            )

        self.assertFalse(result)
        advance.assert_not_awaited()
        self.assertEqual(len(session.writes("board_card_runs")), 1)
        (card_write,) = session.writes("board_cards")
        self.assertEqual(card_write.compile().params["run_status"], "failed")


class RecoveryLoopReconcilesBoardRunsTests(unittest.IsolatedAsyncioTestCase):
    """Startup-only reconciliation cannot settle a run that was still fresh at boot."""

    async def _run_one_pass(self, *, leader: bool) -> AsyncMock:
        reconcile = AsyncMock()
        service = execution_recovery.ExecutionRecoveryService()
        with (
            patch.object(board_run_service, "reconcile_orphaned_board_runs", reconcile),
            patch.object(execution_recovery, "_RECOVERY_GRACE_SECONDS", 0),
            patch.object(execution_recovery, "_RECOVERY_POLL_SECONDS", 0.01),
            patch.object(execution_recovery.lock_service, "_is_leader", leader),
            patch.object(service, "_sweep_once", AsyncMock()),
        ):
            service._running = True
            task = asyncio.create_task(service._run_loop())
            await asyncio.sleep(0.05)
            service._running = False
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        return reconcile

    async def test_leader_reconciles_on_every_sweep(self) -> None:
        reconcile = await self._run_one_pass(leader=True)
        reconcile.assert_awaited()

    async def test_follower_does_not_reconcile(self) -> None:
        reconcile = await self._run_one_pass(leader=False)
        reconcile.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
