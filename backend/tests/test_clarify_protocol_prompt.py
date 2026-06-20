import re
import unittest
from pathlib import Path

from app.services.workflow_dsl_prompt import (
    CLARIFY_PROTOCOL_PROMPT,
    WORKFLOW_DSL_SYSTEM_PROMPT,
)


class TestClarifyProtocolConstant(unittest.TestCase):
    def test_constant_has_key_instructions(self) -> None:
        text = CLARIFY_PROTOCOL_PROMPT
        self.assertIn("heym-clarify", text)
        self.assertIn("[Plan answers]", text)
        # ambiguous -> don't emit DSL
        self.assertIn("ambiguous", text.lower())
        self.assertIn("do not emit", text.lower())
        self.assertRegex(text.lower(), r"workflow json block")

    def test_synced_dsl_prompt_stays_clean(self) -> None:
        # heymweb sync extracts only WORKFLOW_DSL_SYSTEM_PROMPT; it must NOT
        # contain the clarify protocol, or /convert would start asking questions.
        self.assertNotIn("heym-clarify", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertNotIn("[Plan answers]", WORKFLOW_DSL_SYSTEM_PROMPT)

    def test_exactly_one_triple_quoted_dsl_block(self) -> None:
        # The heymweb sync regex is non-greedy: a second """ block could shift
        # the captured boundary. Guard the source so the synced text is stable.
        src = Path("app/services/workflow_dsl_prompt.py").read_text(encoding="utf-8")
        matches = re.findall(r'WORKFLOW_DSL_SYSTEM_PROMPT\s*=\s*"""', src)
        self.assertEqual(len(matches), 1)


from app.api.ai_assistant import (  # noqa: E402
    CANVAS_ASK_SYSTEM_PROMPT,
    DASHBOARD_CHAT_SYSTEM_PROMPT,
)
from app.services.workflow_dsl_prompt import build_assistant_prompt  # noqa: E402


class TestClarifyProtocolInjection(unittest.TestCase):
    def test_build_assistant_prompt_includes_protocol(self) -> None:
        prompt = build_assistant_prompt()
        self.assertIn("heym-clarify", prompt)

    def test_canvas_ask_prompt_includes_protocol(self) -> None:
        self.assertIn("heym-clarify", CANVAS_ASK_SYSTEM_PROMPT)

    def test_dashboard_chat_prompt_includes_protocol(self) -> None:
        self.assertIn("heym-clarify", DASHBOARD_CHAT_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
