"""Execute node whose target workflow is missing from the run's workflow cache."""

import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor

_START = {
    "id": "start",
    "type": "textInput",
    "position": {"x": 0, "y": 0},
    "data": {"label": "start", "inputFields": [{"key": "text"}]},
}
_CHILD = {
    "nodes": [
        _START,
        {
            "id": "set_1",
            "type": "set",
            "position": {"x": 300, "y": 0},
            "data": {"label": "echo", "mappings": [{"key": "reply", "value": "$start.body.text"}]},
        },
    ],
    "edges": [{"id": "e1", "source": "start", "target": "set_1"}],
    "name": "Echo",
    "input_fields": [],
}


def _run(target_id: str, cache: dict) -> dict:
    call = {
        "id": "call",
        "type": "execute",
        "position": {"x": 300, "y": 0},
        "data": {
            "label": "callEcho",
            "executeWorkflowId": target_id,
            "executeInputMappings": [{"key": "text", "value": "$start.body.text"}],
        },
    }
    executor = WorkflowExecutor(
        nodes=[_START, call],
        edges=[{"id": "e1", "source": "start", "target": "call"}],
        workflow_cache=cache,
    )
    result = executor.execute(
        workflow_id=uuid.uuid4(),
        initial_inputs={"headers": {}, "query": {}, "body": {"text": "Bonjour from Zürich"}},
    )
    return next(row for row in result.node_results if row["node_label"] == "callEcho")


class ExecuteNodeMissingTargetTests(unittest.TestCase):
    def test_a_deleted_target_fails_the_node(self) -> None:
        # The cache a run builds leaves out a target that was deleted or has no nodes.
        deleted = str(uuid.uuid4())

        row = _run(deleted, {})

        self.assertEqual(row["status"], "error")
        self.assertEqual(
            row["error"], f"The workflow to execute ({deleted}) was not found or has no nodes"
        )

    def test_a_target_in_the_cache_still_runs(self) -> None:
        target = str(uuid.uuid4())

        row = _run(target, {target: _CHILD})

        self.assertEqual(row["status"], "success")
        self.assertEqual(row["output"]["outputs"], {"echo": {"reply": "Bonjour from Zürich"}})

    def test_no_selected_workflow_still_passes_the_input_through(self) -> None:
        row = _run("", {})

        self.assertEqual(row["status"], "success")
        self.assertEqual(row["output"], {"text": "Bonjour from Zürich"})

    def test_a_nested_deleted_target_fails_the_calling_execute_node(self) -> None:
        deleted = str(uuid.uuid4())
        child_id = str(uuid.uuid4())
        child_call = {
            "id": "child_call",
            "type": "execute",
            "position": {"x": 300, "y": 0},
            "data": {
                "label": "callMissing",
                "executeWorkflowId": deleted,
                "executeInputMappings": [{"key": "text", "value": "$start.body.text"}],
            },
        }
        child_workflow = {
            "nodes": [_START, child_call],
            "edges": [{"id": "ce1", "source": "start", "target": "child_call"}],
            "name": "ChildCallingMissing",
            "input_fields": [],
        }

        row = _run(child_id, {child_id: child_workflow})

        self.assertEqual(row["status"], "error")
        self.assertEqual(
            row["error"], f"The workflow to execute ({deleted}) was not found or has no nodes"
        )


if __name__ == "__main__":
    unittest.main()
