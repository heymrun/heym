import unittest

from app.services.llm_provider import (
    CUSTOM_RESPONSES_SUPPORT_MESSAGE,
    GOOGLE_RESPONSES_UNSUPPORTED_MESSAGE,
    OPENAI_RESPONSES_SUPPORT_MESSAGE,
    get_default_google_models,
    get_default_openai_models,
    is_reasoning_model,
    opencode_responses_support,
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


class TestIsReasoningModel(unittest.TestCase):
    def test_newer_gpt_generations_are_reasoning_models(self):
        """gpt-6-luna rejects `temperature`, so it must not be classified as a plain chat model."""
        for model in ("gpt-5", "gpt-5.6-luna", "gpt-6-luna", "gpt-7", "openai/gpt-6"):
            self.assertTrue(is_reasoning_model(model), model)

    def test_older_gpt_and_other_families_are_not(self):
        for model in ("gpt-4o", "gpt-4.1", "gpt-3.5-turbo", "glm-5.3", "kimi-k3", "chatgpt-4o"):
            self.assertFalse(is_reasoning_model(model), model)

    def test_o_series_still_match(self):
        for model in ("o1", "o3-mini"):
            self.assertTrue(is_reasoning_model(model), model)


class TestOpenCodeResponsesSupport(unittest.TestCase):
    def test_responses_only_models_are_supported(self):
        supported, reason = opencode_responses_support("gpt-6-luna")
        self.assertTrue(supported)
        self.assertIn("automatically", reason)

    def test_chat_models_reject_responses(self):
        supported, reason = opencode_responses_support("glm-5.3")
        self.assertFalse(supported)
        self.assertIn("Chat Completions", reason)

    def test_google_only_models_say_heym_calls_it_automatically(self):
        supported, reason = opencode_responses_support("gemini-4-argon-contributor")
        self.assertFalse(supported)
        self.assertIn("generateContent", reason)
        self.assertIn("automatically", reason)

    def test_messages_only_models_explain_the_gap(self):
        supported, reason = opencode_responses_support("claude-haiku-5-5")
        self.assertFalse(supported)
        self.assertIn("Anthropic Messages", reason)
