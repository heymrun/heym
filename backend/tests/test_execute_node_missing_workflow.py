"""An Execute node whose workflow is gone fails instead of passing its input on as a result.

Every run builds its workflow cache with collect_referenced_workflows, which skips a target
that was deleted or has no nodes. The node used to treat that like an Execute node with no
workflow picked: it returned its own inputs as its output and reported success.
"""

from __future__ import annotations

import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor

SUB_ID = str(uuid.uuid4())
SUB_WORKFLOW = {
    "name": "Charge card",
    "nodes": [
        {
            "id": "in",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "subInput", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "out",
            "type": "output",
            "position": {"x": 200, "y": 0},
            "data": {"label": "subOutput", "message": "charged $subInput.body.text"},
        },
    ],
    "edges": [{"id": "e", "source": "in", "target": "out"}],
    "input_fields": [],
}


def _run(execute_workflow_id: str, cache: dict) -> dict:
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "call",
            "type": "execute",
            "position": {"x": 200, "y": 0},
            "data": {"label": "chargeCard", "executeWorkflowId": execute_workflow_id},
        },
    ]
    edges = [{"id": "e1", "source": "start", "target": "call"}]
    result = WorkflowExecutor(nodes=nodes, edges=edges, workflow_cache=cache).execute(
        workflow_id=uuid.uuid4(),
        initial_inputs={"headers": {}, "query": {}, "body": {"text": "order 42"}},
    )
    return next(r for r in result.node_results if r["node_label"] == "chargeCard")


class ExecuteNodeMissingWorkflowTests(unittest.TestCase):
    def test_a_workflow_missing_from_the_cache_fails_the_node(self) -> None:
        gone = str(uuid.uuid4())

        row = _run(gone, {SUB_ID: SUB_WORKFLOW})

        self.assertEqual(row["status"], "error")
        self.assertIn(f"The workflow to execute ({gone}) was not found", row["error"])
        self.assertNotIn("body", row.get("output") or {})

    def test_a_cached_workflow_still_runs(self) -> None:
        row = _run(SUB_ID, {SUB_ID: SUB_WORKFLOW})

        self.assertEqual(row["status"], "success")
        self.assertEqual(row["output"]["outputs"], {"subOutput": {"result": "charged order 42"}})

    def test_no_workflow_picked_still_passes_the_input_on(self) -> None:
        row = _run("", {})

        self.assertEqual(row["status"], "success")
        self.assertEqual(row["output"]["text"], "order 42")


if __name__ == "__main__":
    unittest.main()
