"""A Loop whose Array field is blank fails instead of looping over the inputs as text.

`arrayExpression` "" does not start with "$", so it went through evaluate_message_template,
which renders a blank template as str(inputs): the loop ran once with the Python repr of
every input, request headers included, as its item.
"""

import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor


def _run(array_expression: str) -> dict:
    nodes = [
        {"id": "in_1", "type": "textInput", "data": {"label": "userInput"}},
        {
            "id": "l1",
            "type": "loop",
            "data": {"label": "each", "arrayExpression": array_expression},
        },
        {
            "id": "s1",
            "type": "set",
            "data": {"label": "seen", "mappings": [{"key": "item", "value": "$each.item"}]},
        },
        {"id": "o1", "type": "output", "data": {"label": "result", "message": "$each.results"}},
    ]
    edges = [
        {"id": "e1", "source": "in_1", "target": "l1"},
        {"id": "e2", "source": "l1", "sourceHandle": "loop", "target": "s1"},
        {"id": "e3", "source": "s1", "target": "l1", "targetHandle": "loop"},
        {"id": "e4", "source": "l1", "sourceHandle": "done", "target": "o1"},
    ]
    result = WorkflowExecutor(nodes=nodes, edges=edges).execute(
        workflow_id=uuid.uuid4(),
        initial_inputs={
            "headers": {"authorization": "Bearer s3cret"},
            "query": {},
            "body": {"rows": ["a", "b"]},
        },
    )
    return {row["node_label"]: row for row in result.node_results}


class LoopBlankArrayExpressionTests(unittest.TestCase):
    def test_blank_array_expression_fails(self) -> None:
        for blank in ("", "   "):
            with self.subTest(array_expression=blank):
                each = _run(blank)["each"]
                self.assertEqual(each["status"], "error")
                self.assertIn("Loop node requires an array expression", each["error"])

    def test_array_expression_still_loops(self) -> None:
        rows = _run("$userInput.body.rows")
        self.assertEqual(rows["result"]["output"], {"result": [{"item": "a"}, {"item": "b"}]})


if __name__ == "__main__":
    unittest.main()
