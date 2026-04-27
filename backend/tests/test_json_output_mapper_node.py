"""JSON output mapper: mapping execution and sole-terminal unwrapped outputs."""

import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor, execute_workflow


class JsonOutputMapperNodeTests(unittest.TestCase):
    def test_sole_terminal_unwraps_to_top_level_json(self) -> None:
        nodes = [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "map1",
                "type": "jsonOutputMapper",
                "data": {
                    "label": "api",
                    "mappings": [
                        {"key": "echo", "value": "$userInput.text"},
                        {"key": "extra", "value": "1"},
                    ],
                },
            },
        ]
        edges = [{"id": "e1", "source": "in1", "target": "map1"}]
        initial = {"headers": {}, "query": {}, "body": {"text": "hello"}}
        ex = WorkflowExecutor(nodes=nodes, edges=edges)
        result = ex.execute(workflow_id=uuid.uuid4(), initial_inputs=initial)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.outputs, {"echo": "hello", "extra": "1"})

    def test_multiple_terminals_keeps_label_wrapped_shape(self) -> None:
        nodes = [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "set1",
                "type": "set",
                "data": {
                    "label": "side",
                    "mappings": [{"key": "x", "value": "1"}],
                },
            },
            {
                "id": "map1",
                "type": "jsonOutputMapper",
                "data": {
                    "label": "api",
                    "mappings": [{"key": "echo", "value": "$userInput.text"}],
                },
            },
        ]
        edges = [
            {"id": "e1", "source": "in1", "target": "set1"},
            {"id": "e2", "source": "in1", "target": "map1"},
        ]
        initial = {"headers": {}, "query": {}, "body": {"text": "hi"}}
        ex = WorkflowExecutor(nodes=nodes, edges=edges)
        result = ex.execute(workflow_id=uuid.uuid4(), initial_inputs=initial)
        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.outputs,
            {
                "side": {"x": "1"},
                "api": {"echo": "hi"},
            },
        )

    def test_execute_workflow_module_matches(self) -> None:
        nodes = [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "map1",
                "type": "jsonOutputMapper",
                "data": {
                    "label": "root",
                    "mappings": [{"key": "k", "value": "$userInput.text"}],
                },
            },
        ]
        edges = [{"id": "e1", "source": "in1", "target": "map1"}]
        initial = {"headers": {}, "query": {}, "body": {"text": "v"}}
        result = execute_workflow(
            uuid.uuid4(),
            nodes,
            edges,
            initial,
            test_run=True,
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.outputs, {"k": "v"})

    def test_node_result_records_mapper_output_dict(self) -> None:
        nodes = [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "map1",
                "type": "jsonOutputMapper",
                "data": {
                    "label": "api",
                    "mappings": [{"key": "a", "value": "$userInput.text"}],
                },
            },
        ]
        edges = [{"id": "e1", "source": "in1", "target": "map1"}]
        initial = {"headers": {}, "query": {}, "body": {"text": "z"}}
        ex = WorkflowExecutor(nodes=nodes, edges=edges)
        result = ex.execute(workflow_id=uuid.uuid4(), initial_inputs=initial)
        mapper_nr = next(nr for nr in result.node_results if nr["node_type"] == "jsonOutputMapper")
        self.assertEqual(mapper_nr["output"], {"a": "z"})


if __name__ == "__main__":
    unittest.main()
