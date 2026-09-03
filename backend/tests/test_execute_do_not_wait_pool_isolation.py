"""A fire-and-forget dispatch must not consume the pool the calling run schedules on.

A sub-workflow run blocks on the node futures it submits. While those runs sat on
`_SHARED_EXECUTOR` alongside the nodes they were waiting for, enough of them at once left
every worker waiting for a task that could never be scheduled - a fan-out of 8
`executeDoNotWait` nodes killed the pool for the whole process, and a loop dispatching
one sub-workflow per item stalled between iterations behind the waits it had started.
"""

import threading
import time
import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor

TARGET_WF_ID = "44444444-4444-4444-4444-444444444444"

# Longer than one wait, far shorter than the serialized-by-starvation alternative.
_WAIT_MS = 700

_WORKFLOW_CACHE = {
    TARGET_WF_ID: {
        "nodes": [
            {
                "id": "t1",
                "type": "textInput",
                "data": {"label": "start", "inputFields": [{"key": "n"}]},
            },
            {"id": "t2", "type": "wait", "data": {"label": "wait", "duration": _WAIT_MS}},
            {"id": "t3", "type": "output", "data": {"label": "output", "message": "ok"}},
        ],
        "edges": [
            {"id": "te1", "source": "t1", "target": "t2"},
            {"id": "te2", "source": "t2", "target": "t3"},
        ],
        "name": "Target",
    }
}

# More dispatches than `_SHARED_EXECUTOR` has workers, so the old arrangement had no
# worker left to run the nodes those dispatches were waiting on.
_FAN_OUT = 12


def _execute_node(node_id: str) -> dict:
    return {
        "id": node_id,
        "type": "execute",
        "data": {
            "label": node_id,
            "executeWorkflowId": TARGET_WF_ID,
            "executeInputMappings": [{"key": "n", "value": "1"}],
            "executeDoNotWait": True,
        },
    }


class DoNotWaitPoolIsolationTests(unittest.TestCase):
    def _run_in_thread(self, executor: WorkflowExecutor, timeout: float) -> float | None:
        """Return the parent's own runtime, or None if the run never finished."""
        finished = threading.Event()
        elapsed: dict[str, float] = {}

        def _run() -> None:
            started = time.monotonic()
            executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "x"}},
            )
            elapsed["parent"] = time.monotonic() - started
            executor.drain_bg_futures()
            elapsed["total"] = time.monotonic() - started
            finished.set()

        threading.Thread(target=_run, daemon=True).start()
        if not finished.wait(timeout):
            return None
        return elapsed["total"]

    def test_parallel_dispatches_do_not_deadlock_the_node_pool(self) -> None:
        nodes: list[dict] = [
            {
                "id": "start",
                "type": "textInput",
                "data": {"label": "start", "inputFields": [{"key": "text"}]},
            }
        ]
        edges: list[dict] = []
        for index in range(_FAN_OUT):
            node_id = f"x{index}"
            nodes.append(_execute_node(node_id))
            edges.append({"id": f"e{index}", "source": "start", "target": node_id})

        executor = WorkflowExecutor(
            nodes=nodes,
            edges=edges,
            workflow_cache=_WORKFLOW_CACHE,
            workflow_id=uuid.uuid4(),
        )
        total = self._run_in_thread(executor, timeout=30)
        self.assertIsNotNone(
            total,
            f"{_FAN_OUT} parallel executeDoNotWait dispatches deadlocked the node pool",
        )
        self.assertEqual(len(executor.sub_workflow_executions), _FAN_OUT)
        self.assertEqual(
            {sub.status for sub in executor.sub_workflow_executions},
            {"success"},
        )

    def test_a_loop_keeps_dispatching_while_earlier_dispatches_run(self) -> None:
        nodes = [
            {
                "id": "loop",
                "type": "loop",
                "data": {"label": "loop", "arrayExpression": "$array(1,2,3,4,5,6,7,8,9,10)"},
            },
            _execute_node("exec"),
        ]
        edges = [
            {
                "id": "e1",
                "source": "loop",
                "target": "exec",
                "sourceHandle": "loop",
                "targetHandle": "input",
            },
            {
                "id": "e2",
                "source": "exec",
                "target": "loop",
                "sourceHandle": "output",
                "targetHandle": "loop",
            },
        ]
        executor = WorkflowExecutor(
            nodes=nodes,
            edges=edges,
            workflow_cache=_WORKFLOW_CACHE,
            workflow_id=uuid.uuid4(),
        )
        total = self._run_in_thread(executor, timeout=30)
        self.assertIsNotNone(total, "the loop never finished dispatching")
        assert total is not None
        self.assertEqual(len(executor.sub_workflow_executions), 10)
        # Overlapping dispatches hold more work than the wall clock allows for; serialized
        # ones converge on it. A ratio survives CI load, the absolute budget here did not.
        dispatched_work = (
            sum(sub.execution_time_ms for sub in executor.sub_workflow_executions) / 1000.0
        )
        self.assertGreater(
            dispatched_work,
            total * 2,
            "dispatched sub-workflows were serialized behind the caller's node pool",
        )


if __name__ == "__main__":
    unittest.main()
