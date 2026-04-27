"""Tests for Execute Workflow node executeDoNotWait option."""

import time
import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor

TARGET_WF_ID = "11111111-1111-1111-1111-111111111111"

_TARGET_NODES = [
    {"id": "t1", "type": "textInput", "data": {"label": "input", "inputFields": [{"key": "text"}]}},
    {"id": "t2", "type": "output", "data": {"label": "output"}},
]
_TARGET_EDGES = [{"id": "te1", "source": "t1", "target": "t2"}]
_ALLOW_DOWNSTREAM_TARGET_NODES = [
    {"id": "t1", "type": "textInput", "data": {"label": "input", "inputFields": [{"key": "text"}]}},
    {"id": "t2", "type": "wait", "data": {"label": "wait", "duration": 10}},
    {"id": "t3", "type": "output", "data": {"label": "output", "allowDownstream": True}},
    {"id": "t4", "type": "wait", "data": {"label": "wait1", "duration": 10}},
]
_ALLOW_DOWNSTREAM_TARGET_EDGES = [
    {"id": "te1", "source": "t1", "target": "t2"},
    {"id": "te2", "source": "t2", "target": "t3"},
    {"id": "te3", "source": "t3", "target": "t4"},
]
_WORKFLOW_CACHE = {
    TARGET_WF_ID: {
        "nodes": _TARGET_NODES,
        "edges": _TARGET_EDGES,
        "name": "Target",
    }
}


def _make_parent_nodes(do_not_wait: bool) -> list[dict]:
    execute_data: dict = {
        "label": "callWorkflow",
        "executeWorkflowId": TARGET_WF_ID,
        "executeInput": "$userInput.body.text",
    }
    if do_not_wait:
        execute_data["executeDoNotWait"] = True
    return [
        {
            "id": "n1",
            "type": "textInput",
            "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
        },
        {"id": "n2", "type": "execute", "data": execute_data},
        {"id": "n3", "type": "output", "data": {"label": "output"}},
    ]


_PARENT_EDGES = [
    {"id": "e1", "source": "n1", "target": "n2"},
    {"id": "e2", "source": "n2", "target": "n3"},
]

_ALLOW_DOWNSTREAM_PARENT_NODES = [
    {
        "id": "n1",
        "type": "textInput",
        "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
    },
    {"id": "n2", "type": "output", "data": {"label": "output", "allowDownstream": True}},
    {
        "id": "n3",
        "type": "execute",
        "data": {
            "label": "callWorkflow",
            "executeWorkflowId": TARGET_WF_ID,
            "executeInput": "$userInput.body.text",
            "executeDoNotWait": True,
        },
    },
]
_ALLOW_DOWNSTREAM_PARENT_EDGES = [
    {"id": "e1", "source": "n1", "target": "n2"},
    {"id": "e2", "source": "n2", "target": "n3"},
]

_INITIAL_INPUTS = {"headers": {}, "query": {}, "body": {"text": "hello"}}


class ExecuteNodeDoNotWaitTests(unittest.TestCase):
    """Covers both synchronous (regression) and fire-and-forget modes."""

    def test_wait_mode_returns_sub_result(self) -> None:
        """executeDoNotWait absent: returns sub-workflow result synchronously."""
        executor = WorkflowExecutor(
            nodes=_make_parent_nodes(do_not_wait=False),
            edges=_PARENT_EDGES,
            workflow_cache=dict(_WORKFLOW_CACHE),
        )
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs=_INITIAL_INPUTS,
        )
        self.assertEqual(result.status, "success")
        execute_result = next(
            (nr for nr in result.node_results if nr["node_type"] == "execute"), None
        )
        self.assertIsNotNone(execute_result)
        self.assertIn("outputs", execute_result["output"])
        self.assertEqual(execute_result["output"].get("workflow_id"), TARGET_WF_ID)
        self.assertEqual(len(result.sub_workflow_executions), 1)
        self.assertEqual(result.sub_workflow_executions[0].workflow_id, TARGET_WF_ID)

    def test_do_not_wait_returns_dispatched(self) -> None:
        """executeDoNotWait: true -> node output is dispatched status, not sub-result."""
        executor = WorkflowExecutor(
            nodes=_make_parent_nodes(do_not_wait=True),
            edges=_PARENT_EDGES,
            workflow_cache=dict(_WORKFLOW_CACHE),
        )
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs=_INITIAL_INPUTS,
        )
        self.assertEqual(result.status, "success")
        execute_result = next(
            (nr for nr in result.node_results if nr["node_type"] == "execute"), None
        )
        self.assertIsNotNone(execute_result)
        self.assertEqual(execute_result["output"].get("status"), "dispatched")
        self.assertEqual(execute_result["output"].get("workflow_id"), TARGET_WF_ID)
        self.assertNotIn("outputs", execute_result["output"])

    def test_do_not_wait_background_records_trace(self) -> None:
        """Background sub-workflow appends SubWorkflowExecution to executor after completion."""
        executor = WorkflowExecutor(
            nodes=_make_parent_nodes(do_not_wait=True),
            edges=_PARENT_EDGES,
            workflow_cache=dict(_WORKFLOW_CACHE),
        )
        executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs=_INITIAL_INPUTS,
        )
        # Give background thread time to finish (sub-workflow is trivial, 0.5 s is generous)
        time.sleep(0.5)
        with executor.lock:
            bg_execs = list(executor.sub_workflow_executions)
        self.assertEqual(len(bg_execs), 1)
        self.assertEqual(bg_execs[0].workflow_id, TARGET_WF_ID)
        self.assertEqual(bg_execs[0].status, "success")

    def test_allow_downstream_join_drains_do_not_wait_subworkflow(self) -> None:
        """allowDownstream finalization waits for fire-and-forget sub-workflows."""
        executor = WorkflowExecutor(
            nodes=_ALLOW_DOWNSTREAM_PARENT_NODES,
            edges=_ALLOW_DOWNSTREAM_PARENT_EDGES,
            workflow_cache=dict(_WORKFLOW_CACHE),
        )
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs=_INITIAL_INPUTS,
        )

        self.assertTrue(result.allow_downstream_pending)
        result.join_allow_downstream()

        execute_result = next(
            (nr for nr in result.node_results if nr["node_type"] == "execute"), None
        )
        self.assertIsNotNone(execute_result)
        self.assertEqual(execute_result["output"].get("status"), "dispatched")
        self.assertEqual(len(result.sub_workflow_executions), 1)
        self.assertEqual(result.sub_workflow_executions[0].workflow_id, TARGET_WF_ID)
        self.assertEqual(result.sub_workflow_executions[0].status, "success")

    def test_do_not_wait_records_nested_allow_downstream_subworkflow(self) -> None:
        """Fire-and-forget sub-workflows include their own output downstream history."""
        workflow_cache = {
            TARGET_WF_ID: {
                "nodes": _ALLOW_DOWNSTREAM_TARGET_NODES,
                "edges": _ALLOW_DOWNSTREAM_TARGET_EDGES,
                "name": "Target",
            }
        }
        executor = WorkflowExecutor(
            nodes=_ALLOW_DOWNSTREAM_PARENT_NODES,
            edges=_ALLOW_DOWNSTREAM_PARENT_EDGES,
            workflow_cache=workflow_cache,
        )
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs=_INITIAL_INPUTS,
        )

        self.assertTrue(result.allow_downstream_pending)
        result.join_allow_downstream()

        self.assertEqual(len(result.sub_workflow_executions), 1)
        sub_exec = result.sub_workflow_executions[0]
        self.assertEqual(sub_exec.workflow_id, TARGET_WF_ID)
        self.assertEqual(sub_exec.status, "success")
        self.assertEqual(
            [item["node_id"] for item in sub_exec.node_results],
            ["t1", "t2", "t3", "t4"],
        )


if __name__ == "__main__":
    unittest.main()
