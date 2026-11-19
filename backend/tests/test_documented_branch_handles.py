"""The branch handle names the docs and the DSL prompt give are the ones the executor routes on.

An edge whose sourceHandle the executor does not know is never skipped, so a Condition or
Switch built from a wrong name runs every branch.
"""

import re
import unittest
import uuid
from pathlib import Path

from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT
from app.services.workflow_executor import WorkflowExecutor

DOCS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "docs" / "content" / "nodes"


def _ran(nodes: list[dict], edges: list[dict], body: dict) -> set[str]:
    result = WorkflowExecutor(nodes=nodes, edges=edges).execute(
        workflow_id=uuid.uuid4(), initial_inputs={"body": body}
    )
    return {row["node_label"] for row in result.node_results if row["status"] == "success"}


class DocumentedBranchHandleTests(unittest.TestCase):
    def test_the_condition_reference_names_the_true_and_false_handles(self) -> None:
        reference = re.search(
            r"### 6\. condition.*?\*\*Outputs\*\*: 2 \(([^)]*)\)", WORKFLOW_DSL_SYSTEM_PROMPT, re.S
        ).group(1)
        handles = re.findall(r'sourceHandle "([\w-]+)"', reference)
        self.assertEqual(handles, ["true", "false"])

        nodes = [
            {"id": "in", "type": "textInput", "data": {"label": "userInput"}},
            {
                "id": "c",
                "type": "condition",
                "data": {"label": "cond", "condition": "$userInput.body.x > 1"},
            },
            {"id": "y", "type": "set", "data": {"label": "yes", "mappings": []}},
            {"id": "n", "type": "set", "data": {"label": "no", "mappings": []}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "c"},
            {"id": "e2", "source": "c", "target": "y", "sourceHandle": handles[0]},
            {"id": "e3", "source": "c", "target": "n", "sourceHandle": handles[1]},
        ]
        self.assertEqual(_ran(nodes, edges, {"x": 5}) & {"yes", "no"}, {"yes"})
        self.assertEqual(_ran(nodes, edges, {"x": 0}) & {"yes", "no"}, {"no"})

    def test_the_switch_docs_name_the_case_and_default_handles(self) -> None:
        doc = (DOCS / "switch-node.md").read_text()
        self.assertNotIn("case index (0, 1, 2)", doc)
        self.assertIn("`case-0`", doc)
        self.assertIn("`default`", doc)

        nodes = [
            {"id": "in", "type": "textInput", "data": {"label": "userInput"}},
            {
                "id": "s",
                "type": "switch",
                "data": {"label": "route", "expression": "$userInput.body.v", "cases": ["a"]},
            },
            {"id": "pa", "type": "set", "data": {"label": "pathA", "mappings": []}},
            {"id": "pd", "type": "set", "data": {"label": "pathDefault", "mappings": []}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "s"},
            {"id": "e2", "source": "s", "target": "pa", "sourceHandle": "case-0"},
            {"id": "e3", "source": "s", "target": "pd", "sourceHandle": "default"},
        ]
        self.assertEqual(_ran(nodes, edges, {"v": "a"}) & {"pathA", "pathDefault"}, {"pathA"})
        self.assertEqual(
            _ran(nodes, edges, {"v": "zz"}) & {"pathA", "pathDefault"}, {"pathDefault"}
        )


if __name__ == "__main__":
    unittest.main()
