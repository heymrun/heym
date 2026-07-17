"""Tests for Codex model and reasoning-effort catalog."""

import unittest

from app.services.codex_catalog import CODEX_MODEL_SUGGESTIONS, CODEX_REASONING_EFFORTS


class TestCodexCatalog(unittest.TestCase):
    def test_includes_gpt_5_6_family(self) -> None:
        self.assertIn("gpt-5.6-sol", CODEX_MODEL_SUGGESTIONS)
        self.assertIn("gpt-5.6-terra", CODEX_MODEL_SUGGESTIONS)
        self.assertIn("gpt-5.6-luna", CODEX_MODEL_SUGGESTIONS)

    def test_omits_deprecated_models(self) -> None:
        self.assertNotIn("gpt-5.2", CODEX_MODEL_SUGGESTIONS)
        self.assertNotIn("gpt-5.3-codex", CODEX_MODEL_SUGGESTIONS)

    def test_reasoning_efforts_include_gpt_5_6_levels(self) -> None:
        for effort in ("low", "medium", "high", "xhigh", "max", "ultra"):
            self.assertIn(effort, CODEX_REASONING_EFFORTS)


if __name__ == "__main__":
    unittest.main()
