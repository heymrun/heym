"""Orphan output nodes: skip only when other executable nodes exist on the canvas."""

import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor


class TestOrphanOutputSkip(unittest.TestCase):
    def test_solo_output_without_incoming_edge_is_not_skipped(self) -> None:
        nodes = [
            {
                "id": "out1",
                "type": "output",
                "data": {"label": "out", "message": "hi"},
            },
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=[])
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {}},
        )
        self.assertNotIn("out1", executor.skipped_nodes)
        by_id = {nr["node_id"]: nr for nr in result.node_results}
        self.assertEqual(by_id["out1"]["status"], "success")
        self.assertEqual(by_id["out1"]["output"], {"result": "hi"})
        self.assertEqual(result.status, "success")
        self.assertEqual(result.outputs, {"out": {"result": "hi"}})

    def test_solo_output_with_sticky_note_is_not_skipped(self) -> None:
        nodes = [
            {
                "id": "out1",
                "type": "output",
                "data": {"label": "out", "message": "hi"},
            },
            {
                "id": "note1",
                "type": "sticky",
                "data": {"label": "note", "text": "reminder"},
            },
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=[])
        self.assertNotIn("out1", executor.skipped_nodes)

    def test_orphan_output_with_sibling_node_is_skipped(self) -> None:
        nodes = [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "out1",
                "type": "output",
                "data": {"label": "out", "message": "hi"},
            },
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=[])
        self.assertIn("out1", executor.skipped_nodes)


if __name__ == "__main__":
    unittest.main()
