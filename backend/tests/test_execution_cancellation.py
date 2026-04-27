import datetime
import threading
import unittest
import uuid
from datetime import timezone

from app.services.execution_cancellation import (
    _ACTIVE_EXECUTIONS,
    cancel_execution,
    clear_execution,
    list_active_executions,
    register_execution,
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
