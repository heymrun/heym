import datetime
import threading
import unittest
import uuid
from datetime import timezone

from app.services.execution_cancellation import (
    _ACTIVE_EXECUTIONS,
    cancel_execution,
    clear_execution,
    get_active_execution_handle,
    list_active_executions,
    register_execution,
    relinquish_execution,
)


def _flush() -> None:
    """Clear global state between tests."""
    with threading.Lock():
        _ACTIVE_EXECUTIONS.clear()


class RegisterExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        _flush()

    def test_returns_threading_event(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        event = register_execution(workflow_id=wf_id, execution_id=ex_id)
        self.assertIsInstance(event, threading.Event)

    def test_event_is_not_set_initially(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        event = register_execution(workflow_id=wf_id, execution_id=ex_id)
        self.assertFalse(event.is_set())

    def test_execution_is_stored(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        self.assertIn(ex_id, _ACTIVE_EXECUTIONS)

    def test_multiple_executions_stored_independently(self) -> None:
        wf_id = uuid.uuid4()
        ex1 = uuid.uuid4()
        ex2 = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex1)
        register_execution(workflow_id=wf_id, execution_id=ex2)
        self.assertIn(ex1, _ACTIVE_EXECUTIONS)
        self.assertIn(ex2, _ACTIVE_EXECUTIONS)

    def test_handle_has_started_at(self) -> None:
        before = datetime.datetime.now(timezone.utc)
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle = _ACTIVE_EXECUTIONS[ex_id]
        after = datetime.datetime.now(timezone.utc)
        self.assertGreaterEqual(handle.started_at, before)
        self.assertLessEqual(handle.started_at, after)


class RegisterExecutionRecoveryFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        _flush()

    def test_handle_carries_recovery_fields(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        actor = uuid.uuid4()
        register_execution(
            workflow_id=wf_id,
            execution_id=ex_id,
            inputs={"a": 1},
            trigger_source="schedule",
            actor_user_id=actor,
            recoverable=True,
        )
        handle = _ACTIVE_EXECUTIONS[ex_id]
        self.assertEqual(handle.inputs, {"a": 1})
        self.assertEqual(handle.trigger_source, "schedule")
        self.assertEqual(handle.actor_user_id, actor)
        self.assertTrue(handle.recoverable)

    def test_defaults_are_safe(self) -> None:
        register_execution(workflow_id=uuid.uuid4(), execution_id=uuid.uuid4())
        handle = next(iter(_ACTIVE_EXECUTIONS.values()))
        self.assertEqual(handle.inputs, {})
        self.assertIsNone(handle.trigger_source)
        self.assertIsNone(handle.actor_user_id)
        self.assertTrue(handle.recoverable)


class CancelExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        _flush()

    def test_returns_true_and_sets_event_when_matching(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        event = register_execution(workflow_id=wf_id, execution_id=ex_id)

        result = cancel_execution(workflow_id=wf_id, execution_id=ex_id)

        self.assertTrue(result)
        self.assertTrue(event.is_set())

    def test_returns_false_for_unknown_execution(self) -> None:
        wf_id = uuid.uuid4()
        result = cancel_execution(workflow_id=wf_id, execution_id=uuid.uuid4())
        self.assertFalse(result)

    def test_returns_false_when_workflow_id_does_not_match(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)

        result = cancel_execution(workflow_id=uuid.uuid4(), execution_id=ex_id)

        self.assertFalse(result)

    def test_does_not_set_event_on_wrong_workflow_id(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        event = register_execution(workflow_id=wf_id, execution_id=ex_id)
        cancel_execution(workflow_id=uuid.uuid4(), execution_id=ex_id)
        self.assertFalse(event.is_set())


class ClearExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        _flush()

    def test_removes_registered_execution(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)

        clear_execution(ex_id)

        self.assertNotIn(ex_id, _ACTIVE_EXECUTIONS)

    def test_is_idempotent_for_missing_execution(self) -> None:
        # Must not raise
        clear_execution(uuid.uuid4())

    def test_cancel_returns_false_after_clear(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        clear_execution(ex_id)

        result = cancel_execution(workflow_id=wf_id, execution_id=ex_id)
        self.assertFalse(result)


class ListActiveExecutionsTests(unittest.TestCase):
    def setUp(self) -> None:
        _flush()

    def test_empty_when_no_executions(self) -> None:
        result = list_active_executions()
        self.assertEqual(result, [])

    def test_returns_all_registered_handles(self) -> None:
        wf_id = uuid.uuid4()
        ex1 = uuid.uuid4()
        ex2 = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex1)
        register_execution(workflow_id=wf_id, execution_id=ex2)
        result = list_active_executions()
        execution_ids = {h.execution_id for h in result}
        self.assertEqual(execution_ids, {ex1, ex2})

    def test_does_not_return_cleared_execution(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        clear_execution(ex_id)
        result = list_active_executions()
        self.assertEqual(result, [])


class RelinquishExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _flush()

    def test_relinquish_drops_handle_and_marks_relinquished(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle = get_active_execution_handle(ex_id)
        self.assertIsNotNone(handle)

        relinquish_execution(ex_id, handle=handle)
        self.assertNotIn(ex_id, _ACTIVE_EXECUTIONS)
        self.assertTrue(handle.relinquished)

    def test_relinquish_with_wrong_handle_preserves_active(self) -> None:
        from app.services.execution_cancellation import ExecutionCancellationHandle

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        original_handle = get_active_execution_handle(ex_id)
        wrong_handle = ExecutionCancellationHandle(
            workflow_id=wf_id,
            execution_id=ex_id,
            event=threading.Event(),
            started_at=datetime.datetime.now(timezone.utc),
        )

        relinquish_execution(ex_id, handle=wrong_handle)
        self.assertIs(_ACTIVE_EXECUTIONS.get(ex_id), original_handle)

    def test_clear_relinquished_execution_returns_false_and_no_record_finished(self) -> None:
        from unittest.mock import patch

        from app.services.execution_cancellation import active_execution_registry

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle = get_active_execution_handle(ex_id)
        self.assertIsNotNone(handle)
        relinquish_execution(ex_id, handle=handle)

        with patch.object(active_execution_registry, "record_finished") as mock_record:
            cleared = clear_execution(ex_id, handle=handle)
            self.assertIs(cleared, False)
            mock_record.assert_not_called()

    def test_same_process_race_ordering_a_relinquish_before_worker_register(self) -> None:
        """Ordering A: Dispatcher registers -> relinquishes -> worker registers ->
        dispatcher clears (safe no-op) -> worker completes effectively.
        """
        from unittest.mock import patch

        from app.services.execution_cancellation import (
            active_execution_registry,
            complete_execution,
        )

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()

        # Dispatcher registers handle_a
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle_a = get_active_execution_handle(ex_id)
        self.assertIsNotNone(handle_a)

        # Dispatcher relinquishes
        relinquish_execution(ex_id, handle=handle_a)
        self.assertNotIn(ex_id, _ACTIVE_EXECUTIONS)
        self.assertTrue(handle_a.relinquished)

        # Worker on same process registers handle_b
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle_b = get_active_execution_handle(ex_id)
        self.assertIsNotNone(handle_b)
        self.assertIsNot(handle_a, handle_b)
        self.assertNotEqual(handle_a.registration_token, handle_b.registration_token)
        self.assertFalse(handle_b.relinquished)

        # Dispatcher caller runs clear_execution with handle_a
        with patch.object(active_execution_registry, "record_finished") as mock_record:
            cleared = clear_execution(ex_id, handle=handle_a)
            self.assertIs(cleared, False)
            mock_record.assert_not_called()

        # Worker handle_b is preserved and still active
        self.assertIs(_ACTIVE_EXECUTIONS.get(ex_id), handle_b)

        # Worker completes execution with handle_b
        with patch.object(active_execution_registry, "record_finished") as mock_record:
            completed = complete_execution(
                ex_id, workflow_id=wf_id, result={"status": "ok"}, handle=handle_b
            )
            self.assertIs(completed, True)
            self.assertNotIn(ex_id, _ACTIVE_EXECUTIONS)
            mock_record.assert_called_once_with(
                ex_id, registration_token=handle_b.registration_token
            )

    def test_same_process_race_ordering_b_worker_registers_before_relinquish(self) -> None:
        """Ordering B: Dispatcher registers -> worker registers before dispatcher relinquishes ->
        dispatcher relinquishes (must NOT drop worker handle!) -> dispatcher clears -> worker completes.
        """
        from unittest.mock import patch

        from app.services.execution_cancellation import (
            active_execution_registry,
            complete_execution,
        )

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()

        # Dispatcher registers handle_a
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle_a = get_active_execution_handle(ex_id)
        self.assertIsNotNone(handle_a)

        # Worker registers handle_b BEFORE dispatcher relinquishes
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle_b = get_active_execution_handle(ex_id)
        self.assertIs(_ACTIVE_EXECUTIONS.get(ex_id), handle_b)
        self.assertIsNot(handle_a, handle_b)

        # Dispatcher relinquishes handle_a: MUST NOT remove handle_b!
        relinquish_execution(ex_id, handle=handle_a)
        self.assertTrue(handle_a.relinquished)
        self.assertIs(_ACTIVE_EXECUTIONS.get(ex_id), handle_b)

        # Dispatcher clears with handle_a: safe NO-OP
        with patch.object(active_execution_registry, "record_finished") as mock_record:
            cleared = clear_execution(ex_id, handle=handle_a)
            self.assertIs(cleared, False)
            mock_record.assert_not_called()
        self.assertIs(_ACTIVE_EXECUTIONS.get(ex_id), handle_b)

        # Worker completes effectively
        with patch.object(active_execution_registry, "record_finished") as mock_record:
            completed = complete_execution(
                ex_id, workflow_id=wf_id, result={"status": "ok"}, handle=handle_b
            )
            self.assertIs(completed, True)
            self.assertNotIn(ex_id, _ACTIVE_EXECUTIONS)
            mock_record.assert_called_once_with(
                ex_id, registration_token=handle_b.registration_token
            )

    def test_same_process_race_ordering_c_worker_completes_before_dispatcher_cleanup(self) -> None:
        """Ordering C: Worker completes before dispatcher caller cleanup."""
        from unittest.mock import patch

        from app.services.execution_cancellation import (
            active_execution_registry,
            complete_execution,
        )

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()

        # Dispatcher registers handle_a
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle_a = get_active_execution_handle(ex_id)

        # Worker registers handle_b
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle_b = get_active_execution_handle(ex_id)

        # Dispatcher relinquishes handle_a
        relinquish_execution(ex_id, handle=handle_a)

        # Worker completes before dispatcher clear runs
        with patch.object(active_execution_registry, "record_finished") as mock_record:
            completed = complete_execution(ex_id, workflow_id=wf_id, result={}, handle=handle_b)
            self.assertIs(completed, True)
            self.assertNotIn(ex_id, _ACTIVE_EXECUTIONS)
            mock_record.assert_called_once_with(
                ex_id, registration_token=handle_b.registration_token
            )

        # Dispatcher clear runs now: safe no-op
        with patch.object(active_execution_registry, "record_finished") as mock_record:
            cleared = clear_execution(ex_id, handle=handle_a)
            self.assertIs(cleared, False)
            mock_record.assert_not_called()

    async def test_same_process_worker_completion_drains_finish_before_dispatcher_cleanup(
        self,
    ) -> None:
        """Proves the full pipeline: worker completes -> command drains to DB ->
        ActiveWorkflowExecution row deleted -> dispatcher cleanup is safe no-op.
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services.execution_cancellation import (
            _ACTIVE_EXECUTIONS,
            active_execution_registry,
            clear_execution,
            complete_execution,
            get_active_execution_handle,
            register_execution,
            relinquish_execution,
        )

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()

        active_execution_registry._running = True
        self.addCleanup(setattr, active_execution_registry, "_running", False)

        # 1. Dispatcher registers handle_a
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle_a = get_active_execution_handle(ex_id)
        self.assertIsNotNone(handle_a)

        # 2. Worker registers handle_b
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle_b = get_active_execution_handle(ex_id)
        self.assertIsNotNone(handle_b)

        # 3. Dispatcher relinquishes handle_a
        relinquish_execution(ex_id, handle=handle_a)
        self.assertTrue(handle_a.relinquished)

        # 4. Worker completes execution with handle_b (real record_finished call)
        completed = complete_execution(ex_id, workflow_id=wf_id, result={}, handle=handle_b)
        self.assertIs(completed, True)
        self.assertNotIn(ex_id, _ACTIVE_EXECUTIONS)

        # 5. Registry drains commands against database session
        executed_stmts = []
        mock_session = AsyncMock()

        async def fake_execute(stmt):
            executed_stmts.append(stmt)
            res = MagicMock(rowcount=1)
            res.scalar.return_value = False
            return res

        mock_session.execute = AsyncMock(side_effect=fake_execute)
        mock_session.commit = AsyncMock()

        savepoint = MagicMock()
        savepoint.__aenter__ = AsyncMock(return_value=savepoint)
        savepoint.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin_nested = MagicMock(return_value=savepoint)

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.session.async_session_maker", return_value=cm):
            await active_execution_registry._drain_commands()

        # Verify DELETE statement was executed for ex_id
        delete_stmts = [
            s for s in executed_stmts if "DELETE FROM active_workflow_executions" in str(s)
        ]
        self.assertTrue(len(delete_stmts) >= 1)

        # 6. Dispatcher caller cleanup runs: safe no-op
        cleared = clear_execution(ex_id, handle=handle_a)
        self.assertIs(cleared, False)

    def test_register_execution_attaches_handle_to_event(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        event = register_execution(workflow_id=wf_id, execution_id=ex_id)
        self.assertTrue(hasattr(event, "_execution_handle"))
        handle = getattr(event, "_execution_handle")
        self.assertEqual(handle.execution_id, ex_id)
        self.assertEqual(handle.workflow_id, wf_id)
        self.assertIsInstance(handle.registration_token, uuid.UUID)

    def test_unqualified_clear_execution_for_legacy_in_process(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle = get_active_execution_handle(ex_id)
        self.assertIsNotNone(handle)

        from unittest.mock import patch

        from app.services.execution_cancellation import active_execution_registry

        with patch.object(active_execution_registry, "record_finished") as mock_record:
            cleared = clear_execution(ex_id)
            self.assertIs(cleared, True)
            self.assertNotIn(ex_id, _ACTIVE_EXECUTIONS)
            mock_record.assert_called_once_with(ex_id, registration_token=handle.registration_token)

        # Calling again when not active returns False
        cleared_again = clear_execution(ex_id)
        self.assertIs(cleared_again, False)
