import datetime
import threading
import unittest
import uuid
from datetime import timezone

from app.services.execution_cancellation import (
    _ACTIVE_EXECUTIONS,
    _RELINQUISHED_EXECUTIONS,
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
        _RELINQUISHED_EXECUTIONS.clear()


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


class RelinquishExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        _flush()

    def test_relinquish_drops_handle_and_records_relinquished(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle = get_active_execution_handle(ex_id)
        self.assertIsNotNone(handle)

        relinquish_execution(ex_id, handle=handle)
        self.assertNotIn(ex_id, _ACTIVE_EXECUTIONS)
        self.assertIn(ex_id, _RELINQUISHED_EXECUTIONS)

    def test_relinquish_with_wrong_handle_fails_and_preserves_active(self) -> None:
        from app.services.execution_cancellation import ExecutionCancellationHandle

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        wrong_handle = ExecutionCancellationHandle(
            workflow_id=wf_id,
            execution_id=ex_id,
            event=threading.Event(),
            started_at=datetime.datetime.now(timezone.utc),
        )

        relinquish_execution(ex_id, handle=wrong_handle)
        self.assertIn(ex_id, _ACTIVE_EXECUTIONS)

    def test_clear_relinquished_execution_does_not_call_record_finished(self) -> None:
        from unittest.mock import patch

        from app.services.execution_cancellation import active_execution_registry

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle = get_active_execution_handle(ex_id)
        relinquish_execution(ex_id, handle=handle)

        with patch.object(active_execution_registry, "record_finished") as mock_record:
            clear_execution(ex_id, handle=handle)
            mock_record.assert_not_called()
        self.assertNotIn(ex_id, _RELINQUISHED_EXECUTIONS)

    def test_same_process_handle_identity_preserved_during_clear(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()

        # Dispatcher registers handle_a
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle_a = get_active_execution_handle(ex_id)
        self.assertIsNotNone(handle_a)

        # Dispatcher relinquishes
        relinquish_execution(ex_id, handle=handle_a)
        self.assertNotIn(ex_id, _ACTIVE_EXECUTIONS)

        # Worker on same process registers handle_b
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        handle_b = get_active_execution_handle(ex_id)
        self.assertIsNotNone(handle_b)
        self.assertIsNot(handle_a, handle_b)

        # Dispatcher caller runs clear_execution with handle_a
        cleared = clear_execution(ex_id, handle=handle_a)
        self.assertFalse(cleared)

        # Worker handle_b is preserved and still active
        self.assertIs(_ACTIVE_EXECUTIONS.get(ex_id), handle_b)
