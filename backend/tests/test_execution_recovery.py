import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.execution_recovery import MAX_RECOVERY_ATTEMPTS, decide_recovery_action


class DecideRecoveryActionTests(unittest.TestCase):
    def test_rerun_when_enabled_and_within_attempts(self) -> None:
        action = decide_recovery_action(attempt=1, auto_recover=True, workflow_exists=True)
        self.assertEqual(action, "rerun")

    def test_skipped_when_toggle_off(self) -> None:
        action = decide_recovery_action(attempt=1, auto_recover=False, workflow_exists=True)
        self.assertEqual(action, "skipped")

    def test_failed_when_attempts_exhausted(self) -> None:
        action = decide_recovery_action(
            attempt=MAX_RECOVERY_ATTEMPTS + 1, auto_recover=True, workflow_exists=True
        )
        self.assertEqual(action, "failed")

    def test_failed_when_workflow_missing(self) -> None:
        action = decide_recovery_action(attempt=1, auto_recover=True, workflow_exists=False)
        self.assertEqual(action, "failed")

    def test_missing_workflow_beats_skip(self) -> None:
        action = decide_recovery_action(attempt=1, auto_recover=False, workflow_exists=False)
        self.assertEqual(action, "failed")


class MarkOwnExecutionsOrphanedTests(unittest.IsolatedAsyncioTestCase):
    async def test_backdates_only_own_recoverable_rows(self) -> None:
        from app.services.execution_cancellation import mark_own_executions_orphaned

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(rowcount=2))
        session.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch("app.services.execution_cancellation.async_session_maker", return_value=cm):
            count = await mark_own_executions_orphaned()
        self.assertEqual(count, 2)
        session.execute.assert_awaited_once()
        session.commit.assert_awaited_once()


class ClaimOrphanedExecutionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_claims_only_rows_won_atomically(self) -> None:
        from app.services.execution_cancellation import claim_orphaned_executions

        ex_won = uuid.uuid4()
        ex_lost = uuid.uuid4()
        wf = uuid.uuid4()
        now = datetime.now(timezone.utc)
        candidate = MagicMock(
            execution_id=ex_won,
            workflow_id=wf,
            inputs={"x": 1},
            trigger_source="schedule",
            actor_user_id=None,
            attempt=0,
        )
        candidate_lost = MagicMock(
            execution_id=ex_lost,
            workflow_id=wf,
            inputs={},
            trigger_source=None,
            actor_user_id=None,
            attempt=0,
        )
        select_result = MagicMock()
        select_result.all.return_value = [candidate, candidate_lost]
        # First claim wins (rowcount=1), second loses (rowcount=0).
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                select_result,
                MagicMock(rowcount=1),
                MagicMock(rowcount=0),
            ]
        )
        session.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch("app.services.execution_cancellation.async_session_maker", return_value=cm):
            claimed = await claim_orphaned_executions(now=now)
        self.assertEqual([c.execution_id for c in claimed], [ex_won])
        self.assertEqual(claimed[0].attempt, 1)


def _orphan(attempt: int = 1):
    from app.services.execution_cancellation import ClaimedOrphan

    return ClaimedOrphan(
        execution_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        inputs={"k": "v"},
        trigger_source="schedule",
        actor_user_id=None,
        attempt=attempt,
    )


class RecoverOneTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_toggle_off(self) -> None:
        from app.services.execution_recovery import ExecutionRecoveryService

        svc = ExecutionRecoveryService()
        orphan = _orphan(attempt=1)
        with (
            patch.object(
                svc, "_load_workflow", AsyncMock(return_value=MagicMock(auto_recover_runs=False))
            ),
            patch.object(svc, "_finalize", AsyncMock()) as finalize,
            patch.object(svc, "_rerun", AsyncMock()) as rerun,
        ):
            await svc._recover_one(orphan)
        finalize.assert_awaited_once()
        self.assertEqual(finalize.await_args.kwargs["status"], "skipped")
        rerun.assert_not_called()

    async def test_fails_when_attempts_exhausted(self) -> None:
        from app.services.execution_recovery import ExecutionRecoveryService

        svc = ExecutionRecoveryService()
        orphan = _orphan(attempt=2)
        with (
            patch.object(
                svc, "_load_workflow", AsyncMock(return_value=MagicMock(auto_recover_runs=True))
            ),
            patch.object(svc, "_finalize", AsyncMock()) as finalize,
            patch.object(svc, "_rerun", AsyncMock()) as rerun,
        ):
            await svc._recover_one(orphan)
        self.assertEqual(finalize.await_args.kwargs["status"], "failed")
        rerun.assert_not_called()

    async def test_fails_when_workflow_missing(self) -> None:
        from app.services.execution_recovery import ExecutionRecoveryService

        svc = ExecutionRecoveryService()
        orphan = _orphan(attempt=1)
        with (
            patch.object(svc, "_load_workflow", AsyncMock(return_value=None)),
            patch.object(svc, "_finalize", AsyncMock()) as finalize,
            patch.object(svc, "_rerun", AsyncMock()) as rerun,
        ):
            await svc._recover_one(orphan)
        self.assertEqual(finalize.await_args.kwargs["status"], "failed")
        rerun.assert_not_called()

    async def test_reruns_when_enabled(self) -> None:
        from app.services.execution_recovery import ExecutionRecoveryService

        svc = ExecutionRecoveryService()
        orphan = _orphan(attempt=1)
        with (
            patch.object(
                svc, "_load_workflow", AsyncMock(return_value=MagicMock(auto_recover_runs=True))
            ),
            patch.object(svc, "_finalize", AsyncMock()) as finalize,
            patch.object(svc, "_rerun", AsyncMock()) as rerun,
        ):
            await svc._recover_one(orphan)
        rerun.assert_awaited_once()
        finalize.assert_not_called()
