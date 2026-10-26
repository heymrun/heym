import unittest

from app.api.ai_assistant import WORKFLOW_ANALYZE_SYSTEM_PROMPT


class TestAnalyzePrompt(unittest.TestCase):
    def test_mentions_three_capabilities(self) -> None:
        p = WORKFLOW_ANALYZE_SYSTEM_PROMPT.lower()
        self.assertIn("error handling", p)
        self.assertIn("error workflow", p)
        self.assertIn("time saved", p)
        self.assertIn("network", p)

    def test_recommends_evals_for_agent_and_llm_nodes(self) -> None:
        p = WORKFLOW_ANALYZE_SYSTEM_PROMPT
        self.assertIn("five checks", p)
        self.assertIn("**Agent Suite**", p)
        self.assertIn("**Prompt Suite**", p)
        self.assertIn("`hasAgentSuite`", p)


if __name__ == "__main__":
    unittest.main()
