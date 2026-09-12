"""Board runs may only be settled by something other than their own chain when dead.

Startup reconciliation runs once per uvicorn worker (8 per container) and once per
instance in a cluster, so it can fire while another process is part-way through a
chain. Failing a live run both lies about it and releases the enqueue guard, which
lets a second chain start on the same card.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import board_run_service
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
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(rows)
    result.all.return_value = list(rows)
    return result


class _SequencedSession:
    """Serves db.execute results in call order."""

    def __init__(self, results):
        self._results = list(results)
        self.commit = AsyncMock()
        self.executed = 0

    async def execute(self, *_args, **_kwargs):
        result = self._results[self.executed]
        self.executed += 1
        return result

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


class ReconcileOrphanedBoardRunsTests(unittest.IsolatedAsyncioTestCase):
    async def _reconcile(self, runs, live_execution_ids, cards):
        session = _SequencedSession(
            [
                _result(runs),
                _result(live_execution_ids),
                _result(cards),
            ]
        )
        with patch.object(board_run_service, "async_session_maker", lambda: session):
            await board_run_service.reconcile_orphaned_board_runs()
        return session

    async def test_live_run_is_left_alone(self) -> None:
        execution_id = uuid.uuid4()
        card_id = uuid.uuid4()
        run = _run(active_execution_id=execution_id, card_id=card_id)
        card = SimpleNamespace(id=card_id, run_status="running")

        await self._reconcile([run], [execution_id], [card])

        self.assertEqual(run.status, "running")
        self.assertIsNone(run.finished_at)
        self.assertEqual(card.run_status, "running")

    async def test_dead_run_and_its_card_are_failed(self) -> None:
        card_id = uuid.uuid4()
        run = _run(active_execution_id=uuid.uuid4(), card_id=card_id)
        card = SimpleNamespace(id=card_id, run_status="running")

        await self._reconcile([run], [], [card])

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error, "Server restarted during execution")
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(card.run_status, "failed")

    async def test_young_run_is_left_alone(self) -> None:
        card_id = uuid.uuid4()
        run = _run(active_execution_id=uuid.uuid4(), age_seconds=FRESH_AGE, card_id=card_id)
        card = SimpleNamespace(id=card_id, run_status="running")

        await self._reconcile([run], [], [card])

        self.assertEqual(run.status, "running")
        self.assertEqual(card.run_status, "running")

    async def test_card_stays_running_while_any_of_its_runs_is_live(self) -> None:
        card_id = uuid.uuid4()
        live_execution_id = uuid.uuid4()
        dead = _run(active_execution_id=uuid.uuid4(), card_id=card_id)
        live = _run(active_execution_id=live_execution_id, card_id=card_id)
        card = SimpleNamespace(id=card_id, run_status="running")

        await self._reconcile([dead, live], [live_execution_id], [card])

        self.assertEqual(dead.status, "failed")
        self.assertEqual(live.status, "running")
        self.assertEqual(card.run_status, "running")


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
        return enqueued, spawn

    async def test_live_run_blocks_a_new_chain(self) -> None:
        execution_id = uuid.uuid4()
        enqueued, spawn = await self._enqueue(
            [_run(active_execution_id=execution_id)], [execution_id]
        )
        self.assertFalse(enqueued)
        spawn.assert_not_called()

    async def test_pending_run_blocks_a_new_chain(self) -> None:
        enqueued, spawn = await self._enqueue(
            [_run(status="pending", active_execution_id=None)], []
        )
        self.assertFalse(enqueued)
        spawn.assert_not_called()

    async def test_young_run_blocks_a_new_chain(self) -> None:
        enqueued, spawn = await self._enqueue(
            [_run(active_execution_id=uuid.uuid4(), age_seconds=FRESH_AGE)], []
        )
        self.assertFalse(enqueued)
        spawn.assert_not_called()

    async def test_dead_run_does_not_block_a_new_chain(self) -> None:
        # A run abandoned by recovery's _finalize keeps active_execution_id but its
        # active row is gone, so it must not lock the card out forever.
        enqueued, spawn = await self._enqueue([_run(active_execution_id=uuid.uuid4())], [])
        self.assertTrue(enqueued)
        spawn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
