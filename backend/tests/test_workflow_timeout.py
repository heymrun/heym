import time
import unittest
import uuid

from app.services.workflow_executor import (
    WorkflowExecutor,
    WorkflowTimeoutError,
    execute_workflow,
)


class TestDeadlineCheck(unittest.TestCase):
    def test_check_cancelled_raises_timeout_after_deadline(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[], timeout_seconds=0.01)
        ex._arm_deadline()
        time.sleep(0.03)
        with self.assertRaises(WorkflowTimeoutError):
            ex.check_cancelled()

    def test_no_timeout_when_disabled(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[], timeout_seconds=0)
        ex._arm_deadline()
        ex.check_cancelled()  # must not raise

    def test_no_timeout_before_deadline(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[], timeout_seconds=5)
        ex._arm_deadline()
        ex.check_cancelled()  # must not raise


class TestExecuteWorkflowTimeout(unittest.TestCase):
    def test_wait_node_workflow_times_out_to_error(self) -> None:
        nodes = [
            {
                "id": "in",
                "type": "textInput",
                "position": {"x": 0, "y": 0},
                "data": {"label": "in", "value": "hi"},
            },
            {
                "id": "wait",
                "type": "wait",
                "position": {"x": 200, "y": 0},
                "data": {"label": "wait", "duration": 3000},
            },
            {
                "id": "out",
                "type": "output",
                "position": {"x": 400, "y": 0},
                "data": {"label": "out", "message": "$wait"},
            },
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "wait"},
            {"id": "e2", "source": "wait", "target": "out"},
        ]

        started = time.time()
        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            timeout_seconds=1,
        )
        elapsed = time.time() - started

        self.assertEqual(result.status, "error")
        self.assertIn("timed out", str(result.outputs).lower())
        # The 3s wait is interrupted near the 1s deadline, not after the full wait.
        self.assertLess(elapsed, 2.5)


if __name__ == "__main__":
    unittest.main()
