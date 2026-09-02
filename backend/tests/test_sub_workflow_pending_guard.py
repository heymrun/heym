"""A sub-workflow that pauses must say so, never sit at pending unnoticed.

HITL is deliberately unsupported inside a sub-workflow: the Execute node, the
agent's sub-workflow tool and the sub-agent tool all refuse it with a message.
The fire-and-forget branch had no such guard, so a paused executeDoNotWait run
was recorded as `pending` and stranded - no review request, no link, no error,
and the pause metadata dropped at the callback boundary.
"""

import unittest
import uuid
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.workflow_executor import ExecutionResult, WorkflowExecutor


def _parent() -> SimpleNamespace:
    return SimpleNamespace(
        lock=MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False)),
        sub_workflow_executions=[],
        _invoked_by_agent=False,
    )


def _future(result: ExecutionResult) -> Future:
    future: Future = Future()
    future.set_result(result)
    return future


class BackgroundSubWorkflowPauseTests(unittest.TestCase):
    def _record(self, status: str) -> SimpleNamespace:
        workflow_id = uuid.uuid4()
        result = ExecutionResult(
            workflow_id=workflow_id,
            status=status,
            outputs={"Agent": {"text": "draft"}},
            execution_time_ms=4.0,
            node_results=[],
            pending_review=(
                {"summary": "Approve", "draft_text": "draft"} if status == "pending" else None
            ),
            resume_snapshot=(
                {"paused_node_id": "a", "paused_node_label": "Agent"}
                if status == "pending"
                else None
            ),
        )
        parent = _parent()
        WorkflowExecutor._record_bg_sub_workflow_done(
            _future(result), parent, str(workflow_id), "Sub B", {"x": 1}
        )
        return parent

    def test_a_paused_background_sub_workflow_is_recorded_as_an_error(self) -> None:
        parent = self._record("pending")
        recorded = parent.sub_workflow_executions[0]
        self.assertEqual(recorded.status, "error")

    def test_the_recorded_error_names_the_unsupported_case(self) -> None:
        parent = self._record("pending")
        self.assertIn("HITL is not supported", str(parent.sub_workflow_executions[0].outputs))

    def test_a_finished_background_sub_workflow_is_untouched(self) -> None:
        parent = self._record("success")
        recorded = parent.sub_workflow_executions[0]
        self.assertEqual(recorded.status, "success")
        self.assertEqual(recorded.outputs, {"Agent": {"text": "draft"}})


if __name__ == "__main__":
    unittest.main()
