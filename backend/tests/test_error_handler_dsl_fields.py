"""The Error Handler fields the AI builder's DSL names are the ones the node outputs.

The DSL listed `$errorHandler.error` as the message and `.errorNode`, `.errorNodeType` and
`.timestamp`, which are the body of the separate error workflow. The node outputs
`{"error": {"node_id", "node_label", "node_type", "message"}}`, so a notification the
builder wrote from the DSL read `Error in $catchErrors.errorNode: {"node_id": ...}`.
"""

import re
import unittest
import uuid

from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT
from app.services.workflow_executor import WorkflowExecutor


def _handler_output(notice: str) -> tuple[dict, str]:
    nodes = [
        {
            "id": "in_1",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "t1",
            "type": "throwError",
            "position": {"x": 300, "y": 0},
            "data": {"label": "checkOrder", "errorMessage": "Order 42 not found"},
        },
        {
            "id": "eh",
            "type": "errorHandler",
            "position": {"x": 0, "y": 300},
            "data": {"label": "errorHandler"},
        },
        {
            "id": "s1",
            "type": "set",
            "position": {"x": 300, "y": 300},
            "data": {"label": "notice", "mappings": [{"key": "text", "value": notice}]},
        },
    ]
    edges = [
        {"id": "e1", "source": "in_1", "target": "t1"},
        {"id": "e2", "source": "eh", "target": "s1"},
    ]
    result = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()).execute(
        workflow_id=uuid.uuid4(),
        initial_inputs={"headers": {}, "query": {}, "body": {"text": "x"}},
    )
    rows = {row["node_label"]: row for row in result.node_results}
    return rows["errorHandler"]["output"], rows["notice"]["output"]["text"]


class ErrorHandlerDslFieldTests(unittest.TestCase):
    def test_every_field_the_dsl_names_is_in_the_output(self) -> None:
        output, _ = _handler_output("x")
        named = set(re.findall(r"\$errorHandler\.error\.(\w+)", WORKFLOW_DSL_SYSTEM_PROMPT))

        self.assertTrue(named)
        self.assertLessEqual(named, set(output["error"]))
        for missing in ("errorNode", "errorNodeType", "timestamp"):
            self.assertNotIn(f"$errorHandler.{missing}", WORKFLOW_DSL_SYSTEM_PROMPT)
        # `$errorHandler.error` alone is the whole object, which renders as JSON in text.
        self.assertIsNone(re.search(r"\$errorHandler\.error(?![.\w])", WORKFLOW_DSL_SYSTEM_PROMPT))

    def test_the_dsl_notification_example_reads_the_failure(self) -> None:
        example = re.search(r'Error notification: `"(.+?)"`', WORKFLOW_DSL_SYSTEM_PROMPT)
        assert example is not None
        _, notice = _handler_output(example.group(1))

        self.assertEqual(notice, "Error in checkOrder: Order 42 not found")


if __name__ == "__main__":
    unittest.main()
