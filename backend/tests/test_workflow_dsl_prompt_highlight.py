import unittest

from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT


class TestDslDocumentsHighlight(unittest.TestCase):
    def test_prompt_mentions_highlight_field(self):
        self.assertIn("highlight", WORKFLOW_DSL_SYSTEM_PROMPT)
        # Documented as a boolean node-data flag, default false
        self.assertIn('"highlight"', WORKFLOW_DSL_SYSTEM_PROMPT)

    def test_prompt_notes_highlight_default_false(self):
        self.assertIn("Highlight Node Output", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("default: false", WORKFLOW_DSL_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
