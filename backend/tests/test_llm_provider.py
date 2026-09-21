import unittest

from app.services.llm_provider import (
    CUSTOM_RESPONSES_SUPPORT_MESSAGE,
    GOOGLE_RESPONSES_UNSUPPORTED_MESSAGE,
    OPENAI_RESPONSES_SUPPORT_MESSAGE,
    get_default_google_models,
    get_default_openai_models,
)


class TestResponsesCapability(unittest.TestCase):
    def test_openai_defaults_support_responses(self) -> None:
        for model in get_default_openai_models():
            self.assertTrue(model.supports_responses, model.id)
            self.assertEqual(model.responses_support_reason, OPENAI_RESPONSES_SUPPORT_MESSAGE)

    def test_google_defaults_do_not_support_responses(self) -> None:
        for model in get_default_google_models():
            self.assertFalse(model.supports_responses, model.id)
            self.assertEqual(model.responses_support_reason, GOOGLE_RESPONSES_UNSUPPORTED_MESSAGE)

    def test_custom_message_is_a_caveat_not_a_promise(self) -> None:
        """A custom gateway may not implement the endpoint, so the copy has to warn
        rather than promise."""
        self.assertIn("gateway", CUSTOM_RESPONSES_SUPPORT_MESSAGE)
        self.assertIn("fail", CUSTOM_RESPONSES_SUPPORT_MESSAGE)
