"""The expression docs and the DSL prompt describe `.replace` the way it evaluates."""

import re
import unittest
from pathlib import Path

from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT
from app.services.workflow_executor import WorkflowExecutor

DOC = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "docs"
    / "content"
    / "reference"
    / "expression-dsl.md"
).read_text()


class ReplaceDocsTests(unittest.TestCase):
    def test_replace_is_documented_as_replacing_every_occurrence(self) -> None:
        result = WorkflowExecutor(nodes=[], edges=[]).resolve_expression(
            '$d.s.replace("a", "X")', {"d": {"s": "a-b-a-b"}}, preserve_type=True
        )
        self.assertEqual(result, "X-b-X-b")

        for name, text in (("docs", DOC), ("DSL prompt", WORKFLOW_DSL_SYSTEM_PROMPT)):
            with self.subTest(text=name):
                line = re.search(r"^- `\.replace\(old, new\)` - (.+)$", text, re.M).group(1)
                self.assertNotIn("first occurrence", line.lower())
                self.assertIn("every occurrence", line.lower())


if __name__ == "__main__":
    unittest.main()
