import unittest

from app.api.ai_assistant import WORKFLOW_ANALYZE_SYSTEM_PROMPT


class TestAnalyzePrompt(unittest.TestCase):
    def test_mentions_three_capabilities(self) -> None:
        p = WORKFLOW_ANALYZE_SYSTEM_PROMPT.lower()
        self.assertIn("error handling", p)
        self.assertIn("error workflow", p)
        self.assertIn("time saved", p)
        self.assertIn("network", p)


if __name__ == "__main__":
    unittest.main()
