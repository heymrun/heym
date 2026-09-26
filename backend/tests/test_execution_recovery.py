import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.cluster.run_history import summarize
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

    async def test_worker_owned_and_queued_executions_not_backdated_on_dispatcher_shutdown(
        self,
    ) -> None:
        """Dispatcher shutdown must not backdate rows belonging to other workers
        or rows that are queued/waiting in the run queue.
        """
        from app.services.execution_cancellation import mark_own_executions_orphaned

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
        session.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.execution_cancellation.async_session_maker", return_value=cm):
            await mark_own_executions_orphaned()

        stmt = session.execute.await_args.args[0]
        # Inspect statement parameters and clauses
        params = stmt.compile().params
        from app.services.execution_cancellation import _WORKER_ID

        # Proves it binds the dispatcher's own instance_id as worker_id filter
        self.assertIn(_WORKER_ID, params.values())
        # Proves it excludes queued, waiting_for_main, and terminal runs from orphan marking
        self.assertIn(
            ["queued", "waiting_for_main", "done", "failed", "skipped_late"], params.values()
        )


class RelinquishedDispatcherDoesNotKeepExecutionAliveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from app.services.execution_cancellation import _ACTIVE_EXECUTIONS

        _ACTIVE_EXECUTIONS.clear()

    async def test_relinquished_execution_is_not_heartbeated_by_dispatcher(self) -> None:
        """Proves a dispatcher waiting on a relinquished run does not keep the row alive."""
        from app.services.execution_cancellation import (
            ActiveExecutionRegistry,
            get_active_execution_handle,
            register_execution,
            relinquish_execution,
        )

        wf_id = uuid.uuid4()
        run_id = uuid.uuid4()

        # Dispatcher registers
        register_execution(workflow_id=wf_id, execution_id=run_id)
        handle = get_active_execution_handle(run_id)
        self.assertIsNotNone(handle)

        # Dispatcher relinquishes
        relinquish_execution(run_id, handle=handle)

        # Dispatcher sync loop ticks
        disp_registry = ActiveExecutionRegistry()
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.session.async_session_maker", return_value=cm):
            await disp_registry._sync_local_handles()

        # Dispatcher emitted NO statements for run_id
        session.execute.assert_not_called()


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
        # First claim wins (rowcount=1 for active row, rowcount=1 for queue row), second loses (rowcount=0).
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                select_result,
                MagicMock(rowcount=1),
                MagicMock(rowcount=1),
                MagicMock(rowcount=0),
            ]
        )
        session.commit = AsyncMock()
        # begin_nested() is a plain method returning an async context manager, so it
        # must not be an AsyncMock coroutine.
        savepoint = MagicMock()
        savepoint.__aenter__ = AsyncMock(return_value=savepoint)
        savepoint.__aexit__ = AsyncMock(return_value=False)
        session.begin_nested = MagicMock(return_value=savepoint)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch("app.services.execution_cancellation.async_session_maker", return_value=cm):
            claimed = await claim_orphaned_executions(now=now)
        self.assertEqual([c.execution_id for c in claimed], [ex_won])
        self.assertEqual(claimed[0].attempt, 1)

    async def test_claim_candidates_query_excludes_queued_terminal_and_history_rows(self) -> None:
        from app.services.execution_cancellation import claim_orphaned_executions

        executed_stmts = []

        async def fake_execute(stmt):
            executed_stmts.append(stmt)
            res = MagicMock()
            res.all.return_value = []
            return res

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)
        session.commit = AsyncMock()
        savepoint = MagicMock()
        savepoint.__aenter__ = AsyncMock(return_value=savepoint)
        savepoint.__aexit__ = AsyncMock(return_value=False)
        session.begin_nested = MagicMock(return_value=savepoint)

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.execution_cancellation.async_session_maker", return_value=cm):
            await claim_orphaned_executions()

        self.assertTrue(len(executed_stmts) >= 1)
        select_stmt = executed_stmts[0]
        params = select_stmt.compile().params
        self.assertIn(
            ["queued", "waiting_for_main", "done", "failed", "skipped_late"], params.values()
        )
        self.assertIn("claimed", params.values())

    async def test_claim_candidates_query_excludes_recently_claimed_runs(self) -> None:
        from app.services.execution_cancellation import claim_orphaned_executions

        executed_stmts = []

        async def fake_execute(stmt):
            executed_stmts.append(stmt)
            res = MagicMock()
            res.all.return_value = []
            return res

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)
        session.commit = AsyncMock()
        savepoint = MagicMock()
        savepoint.__aenter__ = AsyncMock(return_value=savepoint)
        savepoint.__aexit__ = AsyncMock(return_value=False)
        session.begin_nested = MagicMock(return_value=savepoint)

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.execution_cancellation.async_session_maker", return_value=cm):
            await claim_orphaned_executions()

        self.assertTrue(len(executed_stmts) >= 1)
        select_stmt = executed_stmts[0]
        params = select_stmt.compile().params
        self.assertIn("claimed", params.values())


class CleanupStalePersistedExecutionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_stale_excludes_queued_and_waiting_runs(self) -> None:
        from app.services.execution_cancellation import cleanup_stale_persisted_executions

        executed_stmts = []

        async def fake_execute(stmt):
            executed_stmts.append(stmt)
            return MagicMock(rowcount=0)

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)
        session.commit = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.execution_cancellation.async_session_maker", return_value=cm):
            await cleanup_stale_persisted_executions()

        self.assertEqual(len(executed_stmts), 1)
        delete_stmt = executed_stmts[0]
        params = delete_stmt.compile().params
        self.assertIn(["queued", "waiting_for_main"], params.values())

    async def test_cleanup_completed_active_executions_deletes_rows_with_history(self) -> None:
        from app.services.execution_cancellation import cleanup_completed_active_executions

        executed_stmts = []

        async def fake_execute(stmt):
            executed_stmts.append(stmt)
            return MagicMock(rowcount=3)

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)
        session.commit = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.execution_cancellation.async_session_maker", return_value=cm):
            deleted = await cleanup_completed_active_executions()

        self.assertEqual(deleted, 3)
        self.assertEqual(len(executed_stmts), 1)
        self.assertIn("execution_history", str(executed_stmts[0]))

    async def test_sweep_once_invokes_cleanup_completed_active_executions(self) -> None:
        from app.services.execution_recovery import ExecutionRecoveryService

        svc = ExecutionRecoveryService()
        with (
            patch(
                "app.services.execution_recovery.cleanup_completed_active_executions",
                AsyncMock(return_value=1),
            ) as mock_cleanup,
            patch(
                "app.services.execution_recovery.claim_orphaned_executions",
                AsyncMock(return_value=[]),
            ),
        ):
            await svc._sweep_once()

        mock_cleanup.assert_awaited_once()


def _orphan(attempt: int = 1, trigger_source: str = "schedule"):
    from app.services.execution_cancellation import ClaimedOrphan

    return ClaimedOrphan(
        execution_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        inputs={"k": "v"},
        trigger_source=trigger_source,
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


class RerunCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_board_recovery_syncs_card_after_history_is_persisted(self) -> None:
        from app.services.execution_recovery import ExecutionRecoveryService

        svc = ExecutionRecoveryService()
        orphan = _orphan(trigger_source="board")
        workflow = SimpleNamespace(
            id=orphan.workflow_id,
            owner_id=uuid.uuid4(),
            name="Deploy",
            nodes=[],
            edges=[],
        )
        result = SimpleNamespace(
            outputs={"text": "done"},
            node_results=[],
            status="success",
            execution_time_ms=10.0,
            sub_workflow_executions=[],
        )
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        session.add = MagicMock()
        session.commit = AsyncMock()
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.db.session.async_session_maker", return_value=session_context),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch("app.services.execution_cancellation.register_execution", MagicMock()),
            patch("app.services.execution_cancellation.clear_execution", MagicMock()),
            patch(
                "app.services.execution_recovery.asyncio.to_thread", AsyncMock(return_value=result)
            ),
            patch("app.api.analytics.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(
                "app.api.workflows._persist_global_variables_from_execution",
                AsyncMock(),
            ),
            patch(
                "app.services.board_run_service.sync_recovered_board_run",
                AsyncMock(),
            ) as sync_board,
        ):
            await svc._rerun(orphan, workflow)

        session.commit.assert_awaited_once()
        sync_board.assert_awaited_once_with(orphan.execution_id)


class RealPostgresExecutionRecoveryOwnershipTests(unittest.IsolatedAsyncioTestCase):
    """Deterministic PostgreSQL-backed behavioral tests for recovery ownership lifecycle.

    Proves:
    1. Recovery claim establishes matching registry ownership.
    2. Recovery START command is accepted after recovery claim.
    3. Recovery heartbeat uses the correct ownership identity.
    4. Old worker ownership cannot overwrite recovery ownership.
    5. A second orphan sweep cannot reclaim an actively executing recovery.
    6. Recovery completion remains authoritative.
    7. Recovery cannot lose its final history because another recovery finalized the same execution first.
    8. Stale dispatcher START still cannot reclaim recovery ownership.
    9. Same-process recovery ownership behaves correctly.
    10. Stale recovery owner cannot finalize or mutate superseded execution.
    11. Row-level FOR UPDATE locks prevent TOCTOU races during recovery finalization.
    12. Recovery rerun completes without self-drain race when registry loop is concurrent.
    """

    async def asyncSetUp(self) -> None:
        from app.db.models import User, Workflow
        from app.db.session import async_session_maker, engine
        from app.services.execution_cancellation import (
            _ACTIVE_EXECUTIONS,
            active_execution_registry,
        )

        _ACTIVE_EXECUTIONS.clear()
        with active_execution_registry._commands.mutex:
            active_execution_registry._commands.queue.clear()
        active_execution_registry._pending.clear()
        active_execution_registry._command_attempts.clear()
        active_execution_registry._loop = None
        active_execution_registry._wakeup = None

        await engine.dispose()
        active_execution_registry._running = True
        self.addCleanup(setattr, active_execution_registry, "_running", False)

        self.user_id = uuid.uuid4()
        self.wf_id = uuid.uuid4()
        self.ex_id = uuid.uuid4()

        async with async_session_maker() as session:
            session.add(
                User(
                    id=self.user_id,
                    email=f"recovery_test_{self.user_id.hex[:8]}@example.com",
                    hashed_password="test_hashed_password",
                    name="Test Recovery User",
                )
            )
            session.add(
                Workflow(
                    id=self.wf_id,
                    name="Test Recovery Workflow",
                    owner_id=self.user_id,
                    nodes=[],
                    edges=[],
                )
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        from sqlalchemy import delete

        from app.db.models import (
            ActiveWorkflowExecution,
            ExecutionHistory,
            User,
            Workflow,
            WorkflowRunQueue,
        )
        from app.db.session import async_session_maker, engine
        from app.services.execution_cancellation import (
            _ACTIVE_EXECUTIONS,
            active_execution_registry,
        )

        _ACTIVE_EXECUTIONS.clear()
        with active_execution_registry._commands.mutex:
            active_execution_registry._commands.queue.clear()
        active_execution_registry._pending.clear()
        active_execution_registry._command_attempts.clear()
        active_execution_registry._loop = None
        active_execution_registry._wakeup = None

        async with async_session_maker() as session:
            await session.execute(
                delete(ActiveWorkflowExecution).where(
                    ActiveWorkflowExecution.execution_id == self.ex_id
                )
            )
            await session.execute(
                delete(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
            )
            await session.execute(delete(ExecutionHistory).where(ExecutionHistory.id == self.ex_id))
            await session.execute(delete(Workflow).where(Workflow.id == self.wf_id))
            await session.execute(delete(User).where(User.id == self.user_id))
            await session.commit()
        await engine.dispose()

    async def _setup_orphaned_execution(
        self,
        *,
        heartbeat_age_seconds: float = 120.0,
        worker_id: str = "dead-worker:token-dead",
        claimed_by_process: str = "dead-worker-pid",
    ) -> datetime:
        from datetime import timedelta

        from app.db.models import ActiveWorkflowExecution, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_CLAIMED

        now = datetime.now(timezone.utc)
        crashed_time = now - timedelta(seconds=heartbeat_age_seconds)

        async with async_session_maker() as session:
            session.add(
                ActiveWorkflowExecution(
                    execution_id=self.ex_id,
                    workflow_id=self.wf_id,
                    worker_id=worker_id,
                    heartbeat_at=crashed_time,
                    started_at=crashed_time,
                    inputs={"x": 1},
                    trigger_source="api",
                    actor_user_id=self.user_id,
                    attempt=0,
                    recoverable=True,
                    cancel_requested_at=None,
                    running_node_ids=[],
                    running_node_started_at_ms={},
                    node_results=[],
                )
            )
            session.add(
                WorkflowRunQueue(
                    id=uuid.uuid4(),
                    workflow_id=self.wf_id,
                    execution_id=self.ex_id,
                    placement="anywhere",
                    target_instance_id="dead-instance",
                    status=STATUS_CLAIMED,
                    claimed_at=crashed_time,
                    claimed_by_process=claimed_by_process,
                    inputs={"x": 1},
                    trigger_source="api",
                    actor_user_id=self.user_id,
                    credentials_owner_id=self.user_id,
                    test_run=False,
                    timeout_seconds=60.0,
                    return_on_chart_output=False,
                    enqueued_at=crashed_time,
                    not_after=crashed_time + timedelta(seconds=600),
                )
            )
            await session.commit()
        return now

    async def test_recovery_claim_establishes_matching_registry_ownership(self) -> None:
        """1. Recovery claim establishes matching registry and queue ownership in PostgreSQL."""
        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_CLAIMED
        from app.services.execution_cancellation import _WORKER_ID, claim_orphaned_executions

        now = await self._setup_orphaned_execution()
        claimed = await claim_orphaned_executions(now=now)

        self.assertEqual(len(claimed), 1)
        orphan = claimed[0]
        self.assertEqual(orphan.execution_id, self.ex_id)
        self.assertEqual(orphan.attempt, 1)
        self.assertIsNotNone(orphan.claim_owner)
        self.assertIsNotNone(orphan.registration_token)
        expected_owner = f"{_WORKER_ID}:{orphan.registration_token}"
        self.assertEqual(orphan.claim_owner, expected_owner)

        async with async_session_maker() as session:
            active_row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            queue_row = (
                await session.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
                )
            ).scalar_one()

            # Active row has coordinated recovery worker_id
            self.assertEqual(active_row.worker_id, expected_owner)
            self.assertEqual(active_row.attempt, 1)
            self.assertEqual(active_row.heartbeat_at, now)

            # Queue row has matching claimed_by_process
            self.assertEqual(queue_row.claimed_by_process, expected_owner)
            self.assertEqual(queue_row.status, STATUS_CLAIMED)
            self.assertEqual(queue_row.claimed_at, now)

            # Invariant: queue.claimed_by_process == active_row.worker_id == orphan.claim_owner
            self.assertEqual(queue_row.claimed_by_process, active_row.worker_id)
            self.assertEqual(active_row.worker_id, orphan.claim_owner)

    async def test_recovery_start_command_is_accepted_after_recovery_claim(self) -> None:
        """2. Recovery START command carries claim_owner matching queue and is accepted."""
        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import (
            active_execution_registry,
            claim_orphaned_executions,
            register_execution,
        )

        now = await self._setup_orphaned_execution()
        claimed = await claim_orphaned_executions(now=now)
        orphan = claimed[0]

        # Recovery registers with claim_owner and registration_token
        event = register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            inputs={"recovered": True},
            claim_owner=orphan.claim_owner,
            registration_token=orphan.registration_token,
        )
        self.assertIsNotNone(event)

        # Drain start command to PostgreSQL
        await active_execution_registry._drain_commands()

        async with async_session_maker() as session:
            active_row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            # Command was ACCEPTED: worker_id and inputs updated
            self.assertEqual(active_row.worker_id, orphan.claim_owner)
            self.assertEqual(active_row.inputs, {"recovered": True})

    async def test_recovery_heartbeat_uses_correct_ownership_identity(self) -> None:
        """3. Recovery local handle heartbeats match active row token-scoped worker_id."""
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import (
            active_execution_registry,
            claim_orphaned_executions,
            get_active_execution_handle,
            register_execution,
        )

        now = await self._setup_orphaned_execution()
        claimed = await claim_orphaned_executions(now=now)
        orphan = claimed[0]

        register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            claim_owner=orphan.claim_owner,
            registration_token=orphan.registration_token,
        )
        handle = get_active_execution_handle(self.ex_id)
        self.assertIsNotNone(handle)

        await active_execution_registry._drain_commands()

        # Advance time and tick heartbeat sync
        new_heartbeat = now + timedelta(seconds=5)
        with patch("app.services.execution_cancellation._utcnow", return_value=new_heartbeat):
            await active_execution_registry._sync_local_handles()

        async with async_session_maker() as session:
            active_row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            # Heartbeat was successfully persisted because worker_id matches handle_worker_id
            self.assertEqual(active_row.heartbeat_at, new_heartbeat)
            self.assertEqual(active_row.worker_id, orphan.claim_owner)

    async def test_old_worker_ownership_cannot_overwrite_recovery_ownership(self) -> None:
        """4. Delayed commands from dead worker are rejected against recovery ownership."""
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import (
            _RegistryCommand,
            active_execution_registry,
            claim_orphaned_executions,
            register_execution,
        )

        dead_token = uuid.uuid4()
        now = await self._setup_orphaned_execution(
            worker_id=f"dead-worker:{dead_token}", claimed_by_process="dead-worker-pid"
        )
        claimed = await claim_orphaned_executions(now=now)
        orphan = claimed[0]

        register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            claim_owner=orphan.claim_owner,
            registration_token=orphan.registration_token,
        )
        await active_execution_registry._drain_commands()

        # Stale dead worker START command drains
        stale_start = _RegistryCommand(
            action="start",
            execution_id=self.ex_id,
            registration_token=dead_token,
            workflow_id=self.wf_id,
            started_at=now - timedelta(minutes=1),
            enqueued_at=now - timedelta(minutes=1),
            inputs={"dead": 1},
            claim_owner="dead-worker-pid",
        )
        active_execution_registry._commands.put(stale_start)
        await active_execution_registry._drain_commands()

        # Stale dead worker FINISH command drains
        stale_finish = _RegistryCommand(
            action="finish",
            execution_id=self.ex_id,
            registration_token=dead_token,
        )
        active_execution_registry._commands.put(stale_finish)
        await active_execution_registry._drain_commands()

        async with async_session_maker() as session:
            active_row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(active_row)
            # Row was neither overwritten nor deleted
            self.assertEqual(active_row.worker_id, orphan.claim_owner)
            self.assertNotEqual(active_row.inputs, {"dead": 1})

    async def test_second_orphan_sweep_cannot_reclaim_actively_executing_recovery(self) -> None:
        """5. An actively heartbeating recovery execution is protected from second recovery sweep."""
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import (
            active_execution_registry,
            claim_orphaned_executions,
            register_execution,
        )

        now = await self._setup_orphaned_execution()
        claimed = await claim_orphaned_executions(now=now)
        orphan = claimed[0]

        register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            claim_owner=orphan.claim_owner,
            registration_token=orphan.registration_token,
        )
        await active_execution_registry._drain_commands()

        # Recovery actively heartbeats after 10 seconds
        t10 = now + timedelta(seconds=10)
        with patch("app.services.execution_cancellation._utcnow", return_value=t10):
            await active_execution_registry._sync_local_handles()

        # Second recovery sweep runs at t10
        second_claimed = await claim_orphaned_executions(now=t10)
        self.assertEqual(len(second_claimed), 0)

        async with async_session_maker() as session:
            active_row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            # Attempt is still 1, NOT re-incremented
            self.assertEqual(active_row.attempt, 1)
            self.assertEqual(active_row.worker_id, orphan.claim_owner)

    async def test_recovery_completion_remains_authoritative(self) -> None:
        """6. Terminal recovery completion cleanly drops active row and finalizes queue and history."""
        from datetime import timedelta

        from sqlalchemy import select, update

        from app.db.models import ActiveWorkflowExecution, ExecutionHistory, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_DONE
        from app.services.execution_cancellation import (
            active_execution_registry,
            claim_orphaned_executions,
            clear_execution,
            get_active_execution_handle,
            register_execution,
        )

        now = await self._setup_orphaned_execution()
        claimed = await claim_orphaned_executions(now=now)
        orphan = claimed[0]

        register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            claim_owner=orphan.claim_owner,
            registration_token=orphan.registration_token,
        )
        await active_execution_registry._drain_commands()

        handle = get_active_execution_handle(self.ex_id)
        clear_execution(self.ex_id, handle=handle)
        await active_execution_registry._drain_commands()

        async with async_session_maker() as session:
            session.add(
                ExecutionHistory(
                    id=self.ex_id,
                    workflow_id=self.wf_id,
                    inputs={"x": 1},
                    outputs={"result": 42},
                    node_results=[],
                    status="success",
                    execution_time_ms=12.0,
                    trigger_source="api",
                    recovered=True,
                )
            )
            await session.execute(
                update(WorkflowRunQueue)
                .where(WorkflowRunQueue.execution_id == self.ex_id)
                .values(
                    status=STATUS_DONE,
                    finished_at=now,
                    result={"result": 42},
                )
            )
            await session.commit()

        # In PostgreSQL: active row deleted, history recorded, queue completed
        async with async_session_maker() as session:
            active_row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one_or_none()
            history_row = (
                await session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == self.ex_id)
                )
            ).scalar_one()
            queue_row = (
                await session.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
                )
            ).scalar_one()

            self.assertIsNone(active_row)
            self.assertEqual(history_row.status, "success")
            self.assertEqual(queue_row.status, STATUS_DONE)

        # Later sweep never re-claims terminal execution
        sweep = await claim_orphaned_executions(now=now + timedelta(seconds=120))
        self.assertEqual(len(sweep), 0)

    async def test_recovery_cannot_lose_history_due_to_concurrent_recovery(self) -> None:
        """7. Long-running recovery maintains heartbeats, preventing secondary recovery from writing
        failed history and causing primary key collisions.
        """
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.models import ExecutionHistory
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import (
            active_execution_registry,
            claim_orphaned_executions,
            clear_execution,
            get_active_execution_handle,
            register_execution,
        )

        now = await self._setup_orphaned_execution()
        claimed = await claim_orphaned_executions(now=now)
        orphan = claimed[0]

        register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            claim_owner=orphan.claim_owner,
            registration_token=orphan.registration_token,
        )
        await active_execution_registry._drain_commands()

        # Execution takes 75s (> 60s stale threshold).
        # Regular heartbeats occur at t=30 and t=60.
        for elapsed in (30, 60):
            tick = now + timedelta(seconds=elapsed)
            with patch("app.services.execution_cancellation._utcnow", return_value=tick):
                await active_execution_registry._sync_local_handles()

        # At t=75, another sweep runs.
        t75 = now + timedelta(seconds=75)
        sweep2 = await claim_orphaned_executions(now=t75)
        # Because heartbeats were maintained, sweep 2 CANNOT claim this run
        self.assertEqual(len(sweep2), 0)

        # Recovery 1 finishes at t=80 and writes history
        handle = get_active_execution_handle(self.ex_id)
        clear_execution(self.ex_id, handle=handle)
        await active_execution_registry._drain_commands()

        async with async_session_maker() as session:
            session.add(
                ExecutionHistory(
                    id=self.ex_id,
                    workflow_id=self.wf_id,
                    inputs=orphan.inputs,
                    outputs={"final": "real_result"},
                    node_results=[],
                    status="success",
                    execution_time_ms=35000.0,
                    trigger_source="api",
                    recovered=True,
                )
            )
            # This insert must NOT raise IntegrityError PK collision
            await session.commit()

        async with async_session_maker() as session:
            history = (
                await session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == self.ex_id)
                )
            ).scalar_one()
            self.assertEqual(history.status, "success")
            self.assertEqual(history.outputs, {"final": "real_result"})

    async def test_stale_dispatcher_start_cannot_reclaim_recovery_ownership(self) -> None:
        """8. Stale dispatcher START command is discarded and cannot overwrite recovery ownership."""
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import (
            _RegistryCommand,
            active_execution_registry,
            claim_orphaned_executions,
            register_execution,
        )

        now = await self._setup_orphaned_execution()
        claimed = await claim_orphaned_executions(now=now)
        orphan = claimed[0]

        register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            claim_owner=orphan.claim_owner,
            registration_token=orphan.registration_token,
        )
        await active_execution_registry._drain_commands()

        # Delayed dispatcher START command with claim_owner=None drains
        disp_token = uuid.uuid4()
        delayed_disp_cmd = _RegistryCommand(
            action="start",
            execution_id=self.ex_id,
            registration_token=disp_token,
            workflow_id=self.wf_id,
            started_at=now - timedelta(minutes=2),
            enqueued_at=now - timedelta(minutes=2),
            inputs={"disp": "stale"},
            claim_owner=None,  # Dispatcher has no claim owner
        )
        active_execution_registry._commands.put(delayed_disp_cmd)
        await active_execution_registry._drain_commands()

        async with async_session_maker() as session:
            active_row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            # Stale dispatcher was discarded; recovery ownership is preserved
            self.assertEqual(active_row.worker_id, orphan.claim_owner)
            self.assertNotEqual(active_row.inputs, {"disp": "stale"})

    async def test_same_process_recovery_ownership_behaves_correctly(self) -> None:
        """9. Recovery within the same process cleanly supersedes stale local commands and heartbeats."""
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution
        from app.db.session import async_session_maker
        from app.services.execution_cancellation import (
            _WORKER_ID,
            active_execution_registry,
            claim_orphaned_executions,
            get_active_execution_handle,
            register_execution,
        )

        # Worker crashed in this same process (worker_id starts with _WORKER_ID)
        local_crashed_worker = f"{_WORKER_ID}:{uuid.uuid4()}"
        now = await self._setup_orphaned_execution(
            worker_id=local_crashed_worker, claimed_by_process=f"{_WORKER_ID}-pid"
        )

        claimed = await claim_orphaned_executions(now=now)
        orphan = claimed[0]

        # Recovery registers in this same process with new recovery token
        register_execution(
            workflow_id=self.wf_id,
            execution_id=self.ex_id,
            claim_owner=orphan.claim_owner,
            registration_token=orphan.registration_token,
        )
        await active_execution_registry._drain_commands()

        handle = get_active_execution_handle(self.ex_id)
        self.assertIsNotNone(handle)
        self.assertEqual(handle.registration_token, orphan.registration_token)

        # Local sync ticks
        t5 = now + timedelta(seconds=5)
        with patch("app.services.execution_cancellation._utcnow", return_value=t5):
            await active_execution_registry._sync_local_handles()

        async with async_session_maker() as session:
            active_row = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            self.assertEqual(active_row.worker_id, orphan.claim_owner)
            self.assertEqual(active_row.heartbeat_at, t5)

    async def test_stale_recovery_owner_cannot_finalize_or_mutate_superseded_execution(
        self,
    ) -> None:
        """10. Stale Recovery A cannot finalize or mutate state after Recovery B has claimed ownership."""
        from datetime import timedelta

        from sqlalchemy import select, update

        from app.db.models import ActiveWorkflowExecution, ExecutionHistory, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_CLAIMED, STATUS_DONE
        from app.services.execution_cancellation import claim_orphaned_executions
        from app.services.execution_recovery import ExecutionRecoveryService

        now = await self._setup_orphaned_execution()
        claimed_a = await claim_orphaned_executions(now=now)
        self.assertEqual(len(claimed_a), 1)
        orphan_a = claimed_a[0]
        self.assertEqual(orphan_a.attempt, 1)

        # Stale out Recovery A: age heartbeat and queue claim beyond stale threshold
        stale_time = now - timedelta(seconds=120)
        async with async_session_maker() as session:
            await session.execute(
                update(ActiveWorkflowExecution)
                .where(ActiveWorkflowExecution.execution_id == self.ex_id)
                .values(heartbeat_at=stale_time)
            )
            await session.execute(
                update(WorkflowRunQueue)
                .where(WorkflowRunQueue.execution_id == self.ex_id)
                .values(claimed_at=stale_time)
            )
            await session.commit()

        # Recovery B claims the stale execution
        now_b = now + timedelta(seconds=120)
        claimed_b = await claim_orphaned_executions(now=now_b)
        self.assertEqual(len(claimed_b), 1)
        orphan_b = claimed_b[0]
        self.assertEqual(orphan_b.attempt, 2)
        self.assertNotEqual(orphan_b.claim_owner, orphan_a.claim_owner)

        # Verify Recovery B holds both rows before Recovery A attempts completion
        async with async_session_maker() as session:
            active_b = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            queue_b = (
                await session.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
                )
            ).scalar_one()
            self.assertEqual(active_b.worker_id, orphan_b.claim_owner)
            self.assertEqual(queue_b.claimed_by_process, orphan_b.claim_owner)
            self.assertEqual(queue_b.status, STATUS_CLAIMED)

        svc = ExecutionRecoveryService()
        workflow = SimpleNamespace(
            id=self.wf_id,
            owner_id=self.user_id,
            name="Test Recovery Workflow",
            nodes=[],
            edges=[],
        )

        # 1. Stale Recovery A attempts _finalize -> MUST BE FENCED OUT
        await svc._finalize(orphan=orphan_a, workflow=workflow, status="failed")

        async with async_session_maker() as session:
            history = (
                await session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == self.ex_id)
                )
            ).scalar_one_or_none()
            self.assertIsNone(history, "Stale Recovery A _finalize must not write ExecutionHistory")

            active = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            self.assertEqual(active.worker_id, orphan_b.claim_owner)

            queue = (
                await session.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
                )
            ).scalar_one()
            self.assertEqual(queue.claimed_by_process, orphan_b.claim_owner)
            self.assertEqual(queue.status, STATUS_CLAIMED)

        # 2. Stale Recovery A attempts _rerun -> MUST BE FENCED OUT
        mock_result_a = SimpleNamespace(
            outputs={"recovered_by": "A"},
            node_results=[],
            status="success",
            execution_time_ms=50.0,
            sub_workflow_executions=[],
        )
        with (
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.execution_recovery.asyncio.to_thread",
                AsyncMock(return_value=mock_result_a),
            ),
        ):
            await svc._rerun(orphan_a, workflow)

        async with async_session_maker() as session:
            history = (
                await session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == self.ex_id)
                )
            ).scalar_one_or_none()
            self.assertIsNone(history, "Stale Recovery A _rerun must not write ExecutionHistory")

            active = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one()
            self.assertEqual(active.worker_id, orphan_b.claim_owner)

            queue = (
                await session.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
                )
            ).scalar_one()
            self.assertEqual(queue.claimed_by_process, orphan_b.claim_owner)
            self.assertEqual(queue.status, STATUS_CLAIMED)

        # 3. Authoritative Recovery B completes cleanly
        mock_result_b = SimpleNamespace(
            outputs={"recovered_by": "B"},
            node_results=[],
            status="success",
            execution_time_ms=75.0,
            sub_workflow_executions=[],
        )
        with (
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.execution_recovery.asyncio.to_thread",
                AsyncMock(return_value=mock_result_b),
            ),
        ):
            await svc._rerun(orphan_b, workflow)

        async with async_session_maker() as session:
            history = (
                await session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == self.ex_id)
                )
            ).scalar_one()
            self.assertEqual(history.status, "success")
            self.assertEqual(history.outputs, {"recovered_by": "B"})

            active = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNone(active, "Active row dropped by authoritative Recovery B")

            queue = (
                await session.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
                )
            ).scalar_one()
            self.assertEqual(queue.status, STATUS_DONE)
            self.assertEqual(queue.result, summarize(mock_result_b, self.ex_id))

    async def test_concurrent_recovery_fencing_prevents_toctou_races(self) -> None:
        """11. FOR UPDATE row locks serialize concurrent recovery finalize and orphan claims without races."""
        import asyncio
        from datetime import timedelta

        from sqlalchemy import delete, select, update

        from app.db.models import ActiveWorkflowExecution, ExecutionHistory, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_DONE
        from app.services.execution_cancellation import claim_orphaned_executions

        now = await self._setup_orphaned_execution()
        claimed = await claim_orphaned_executions(now=now)
        self.assertEqual(len(claimed), 1)
        orphan = claimed[0]

        lock_acquired = asyncio.Event()
        release_lock = asyncio.Event()

        # Task 1 holds FOR UPDATE lock during finalization
        async def holding_finalization():
            async with async_session_maker() as session:
                active_row = (
                    await session.execute(
                        select(ActiveWorkflowExecution)
                        .where(ActiveWorkflowExecution.execution_id == orphan.execution_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                queue_row = (
                    await session.execute(
                        select(WorkflowRunQueue)
                        .where(WorkflowRunQueue.execution_id == orphan.execution_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                self.assertIsNotNone(active_row)
                self.assertIsNotNone(queue_row)
                lock_acquired.set()
                await release_lock.wait()

                # Complete finalization inside the locked transaction
                session.add(
                    ExecutionHistory(
                        id=orphan.execution_id,
                        workflow_id=orphan.workflow_id,
                        inputs=orphan.inputs,
                        outputs={"result": "locked_winner"},
                        node_results=[],
                        status="success",
                        execution_time_ms=10.0,
                        trigger_source=orphan.trigger_source,
                        recovered=True,
                    )
                )
                await session.execute(
                    delete(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == orphan.execution_id,
                        ActiveWorkflowExecution.worker_id == orphan.claim_owner,
                    )
                )
                await session.execute(
                    update(WorkflowRunQueue)
                    .where(
                        WorkflowRunQueue.execution_id == orphan.execution_id,
                        WorkflowRunQueue.claimed_by_process == orphan.claim_owner,
                    )
                    .values(
                        status=STATUS_DONE,
                        finished_at=now,
                        result={"result": "locked_winner"},
                    )
                )
                await session.commit()

        finalize_task = asyncio.create_task(holding_finalization())
        await lock_acquired.wait()

        # Task 2 attempts to claim while Task 1 holds row lock (stale threshold exceeded)
        sweep_future = asyncio.create_task(
            claim_orphaned_executions(now=now + timedelta(seconds=120))
        )
        # Give event loop a moment to start Task 2; it must block on the row lock
        await asyncio.sleep(0.05)
        self.assertFalse(
            sweep_future.done(), "Concurrent claim must block waiting on FOR UPDATE lock"
        )

        # Now release Task 1
        release_lock.set()
        await finalize_task

        # Task 2 unblocks: row was deleted and committed, so claim finds 0 candidates to claim
        sweep_result = await sweep_future
        self.assertEqual(
            len(sweep_result), 0, "Concurrent claim finds 0 rows after locked finalization"
        )

        async with async_session_maker() as session:
            history = (
                await session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == self.ex_id)
                )
            ).scalar_one()
            self.assertEqual(history.outputs, {"result": "locked_winner"})

            active = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNone(active)

            queue = (
                await session.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
                )
            ).scalar_one()
            self.assertEqual(queue.status, STATUS_DONE)

    async def test_recovery_rerun_completes_when_registry_finish_drains_concurrently(
        self,
    ) -> None:
        """12. Proves that background registry finish draining does not cause _rerun to discard its result."""
        import asyncio

        from sqlalchemy import select

        from app.db.models import ActiveWorkflowExecution, ExecutionHistory, WorkflowRunQueue
        from app.db.session import async_session_maker
        from app.services.cluster.run_queue import STATUS_DONE
        from app.services.execution_cancellation import (
            active_execution_registry,
            claim_orphaned_executions,
        )
        from app.services.execution_recovery import ExecutionRecoveryService

        now = await self._setup_orphaned_execution()
        claimed = await claim_orphaned_executions(now=now)
        self.assertEqual(len(claimed), 1)
        orphan = claimed[0]

        # Start the real active execution registry loop as a background task
        # with loop and wakeup configured so record_finished wakes it immediately
        active_execution_registry._loop = asyncio.get_running_loop()
        active_execution_registry._wakeup = asyncio.Event()
        self.addCleanup(setattr, active_execution_registry, "_loop", None)
        self.addCleanup(setattr, active_execution_registry, "_wakeup", None)
        drain_task = asyncio.create_task(active_execution_registry._run_loop())
        self.addCleanup(drain_task.cancel)

        svc = ExecutionRecoveryService()
        workflow = SimpleNamespace(
            id=self.wf_id,
            owner_id=self.user_id,
            name="Test Recovery Workflow",
            nodes=[],
            edges=[],
        )
        mock_result = SimpleNamespace(
            outputs={"recovered_text": "success_under_concurrent_drain"},
            node_results=[],
            status="success",
            execution_time_ms=30.0,
            sub_workflow_executions=[],
        )

        with (
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.execution_recovery.asyncio.to_thread",
                AsyncMock(return_value=mock_result),
            ),
        ):
            await svc._rerun(orphan, workflow)

        # Allow the background registry task to process the finish command enqueued by clear_execution
        active_execution_registry._wake()
        await asyncio.sleep(0.05)
        # Drain any residual commands deterministically
        await active_execution_registry._drain_commands()

        async with async_session_maker() as session:
            # 1. Exactly one ExecutionHistory row exists
            history = (
                await session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == self.ex_id)
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(history, "ExecutionHistory MUST be written; must not be discarded")
            self.assertEqual(history.status, "success")
            self.assertEqual(history.outputs, {"recovered_text": "success_under_concurrent_drain"})

            # 2. Queue reaches expected terminal state
            queue = (
                await session.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == self.ex_id)
                )
            ).scalar_one()
            self.assertEqual(queue.status, STATUS_DONE)
            self.assertEqual(queue.result, summarize(mock_result, self.ex_id))

            # 3. Active row is cleanly absent (cleared atomically and/or by idempotent finish)
            active = (
                await session.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == self.ex_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNone(active, "Active row must be absent after completion")
