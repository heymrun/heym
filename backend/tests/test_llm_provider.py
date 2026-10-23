import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.llm_provider import (
    CUSTOM_RESPONSES_SUPPORT_MESSAGE,
    GOOGLE_RESPONSES_UNSUPPORTED_MESSAGE,
    OPENAI_RESPONSES_SUPPORT_MESSAGE,
    fetch_openai_models,
    get_default_google_models,
    get_default_openai_models,
    is_openai_chat_model,
    is_reasoning_model,
    opencode_responses_support,
)

# A slice of OpenAI's /v1/models answer (2026-10-22).
LISTED_BEFORE = (
    "gpt-4o",
    "gpt-4o-mini-tts",
    "gpt-4.1-nano",
    "gpt-3.5-turbo-instruct",
    "o1-pro",
    "o3-mini",
    "chatgpt-image-latest",
    "ft:gpt-4o-mini-2024-07-18:acme::abc123",
)
HIDDEN_BEFORE = (
    "gpt-5",
    "gpt-5.1-codex-max",
    "gpt-5.5-pro",
    "gpt-5.6-sol",
    "gpt-6-luna",
    "gpt-6.1-sol",
    "o4-mini",
    "o4-mini-2025-04-16",
    "ft:gpt-5.4-mini:acme::def456",
)
NOT_CHAT = (
    "text-embedding-3-small",
    "whisper-1",
    "tts-1-hd",
    "gpt-image-2",
    "gpt-realtime-2",
    "gpt-audio-mini",
    "gpt-transcribe",
    "omni-moderation-latest",
    "davinci-002",
    "sora-2",
)


def _listed_by_the_old_markers(model_id: str) -> bool:
    return any(x in model_id for x in ["gpt-4", "gpt-3.5", "o1", "o3", "chatgpt"])


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
        for model in ("o1", "o3-mini", "o4-mini", "openai/o4-mini", "ft:o4-mini:acme::abc"):
            self.assertTrue(is_reasoning_model(model), model)


class TestOpenAIModelList(unittest.IsolatedAsyncioTestCase):
    def test_every_model_listed_before_is_still_listed(self) -> None:
        for model in LISTED_BEFORE + HIDDEN_BEFORE + NOT_CHAT:
            if _listed_by_the_old_markers(model):
                self.assertTrue(is_openai_chat_model(model), model)

    def test_gpt_5_and_later_and_the_o_series_are_listed(self) -> None:
        for model in HIDDEN_BEFORE:
            self.assertFalse(_listed_by_the_old_markers(model), model)
            self.assertTrue(is_openai_chat_model(model), model)

    def test_audio_image_embedding_and_moderation_models_stay_out(self) -> None:
        for model in NOT_CHAT:
            self.assertFalse(is_openai_chat_model(model), model)

    async def test_the_credential_lists_gpt_6_as_a_reasoning_model(self) -> None:
        ids = ["gpt-6.1-sol", "gpt-4o", "o4-mini", "whisper-1", "gpt-image-2"]
        response = MagicMock()
        response.json.return_value = {"data": [{"id": model} for model in ids]}

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=response)):
            models = await fetch_openai_models("test-key")

        self.assertEqual([m.id for m in models], ["gpt-6.1-sol", "o4-mini", "gpt-4o"])
        self.assertEqual([m.is_reasoning for m in models], [True, True, False])
        self.assertTrue(all(m.supports_responses for m in models))


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
