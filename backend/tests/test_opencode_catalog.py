import unittest

from app.services.opencode_catalog import (
    OPENCODE_DEFAULT_MODEL,
    OPENCODE_MODEL_FALLBACK,
    is_opencode_base_url,
    normalize_opencode_models,
    opencode_model_protocol,
    qualify_model_id,
)


class TestOpenCodeCatalog(unittest.TestCase):
    def test_default_is_in_fallback(self):
        ids = [m["id"] for m in OPENCODE_MODEL_FALLBACK]
        self.assertIn(OPENCODE_DEFAULT_MODEL, ids)
        self.assertEqual(OPENCODE_DEFAULT_MODEL, "opencode-go/kimi-k3")

    def test_normalize_openai_style_payload(self):
        payload = {"object": "list", "data": [{"id": "kimi-k3"}, {"id": "deepseek-v4-pro"}]}
        models = normalize_opencode_models(payload)
        self.assertEqual(models[0]["id"], "opencode-go/kimi-k3")
        self.assertEqual(models[1]["id"], "opencode-go/deepseek-v4-pro")

    def test_normalize_skips_blank_and_dedupes(self):
        payload = {"data": [{"id": "kimi-k3"}, {"id": "kimi-k3"}, {"id": ""}, {"id": None}]}
        models = normalize_opencode_models(payload)
        self.assertEqual([m["id"] for m in models], ["opencode-go/kimi-k3"])

    def test_normalize_already_prefixed(self):
        payload = {"data": [{"id": "opencode-go/kimi-k3"}]}
        self.assertEqual(normalize_opencode_models(payload)[0]["id"], "opencode-go/kimi-k3")

    def test_normalize_rewrites_legacy_provider_prefix(self):
        """The Go gateway is its own CLI provider; the old prefix no longer resolves."""
        payload = {"data": [{"id": "opencode/kimi-k3"}, {"id": "kimi-k3"}]}
        models = normalize_opencode_models(payload)
        self.assertEqual([m["id"] for m in models], ["opencode-go/kimi-k3"])
        self.assertEqual(models[0]["name"], "kimi-k3")

    def test_qualify_model_id(self):
        self.assertEqual(qualify_model_id("kimi-k3"), "opencode-go/kimi-k3")
        self.assertEqual(qualify_model_id("opencode/kimi-k3"), "opencode-go/kimi-k3")
        self.assertEqual(qualify_model_id("opencode-go/kimi-k3"), "opencode-go/kimi-k3")
        self.assertEqual(qualify_model_id("  "), "")

    def test_normalize_bad_input_returns_empty(self):
        self.assertEqual(normalize_opencode_models({"data": "nope"}), [])
        self.assertEqual(normalize_opencode_models(None), [])


class TestOpenCodeModelProtocol(unittest.TestCase):
    def test_gpt_and_grok_are_served_over_responses_only(self):
        for model in ("gpt-6-luna", "gpt-5.6-luna", "grok-4.7", "grok-4.6"):
            self.assertEqual(opencode_model_protocol(model), "responses", model)

    def test_claude_and_minimax_m27_are_served_over_messages_only(self):
        for model in ("claude-haiku-5-5", "minimax-m2.7"):
            self.assertEqual(opencode_model_protocol(model), "messages", model)

    def test_gemini_is_served_over_googles_own_api(self):
        self.assertEqual(opencode_model_protocol("gemini-4-argon-contributor"), "google")
        self.assertEqual(
            opencode_model_protocol("opencode-go/gemini-4-argon-contributor"), "google"
        )

    def test_models_the_gateway_translates_stay_on_chat(self):
        """The gateway answers these on /chat/completions even though its docs list another
        protocol for some of them, so the docs table must not be copied blindly."""
        for model in ("glm-5.3", "glm-5.3-flash", "kimi-k3", "minimax-m3", "qwen3.8-max"):
            self.assertEqual(opencode_model_protocol(model), "chat", model)

    def test_provider_prefix_is_ignored(self):
        self.assertEqual(opencode_model_protocol("opencode-go/gpt-6-luna"), "responses")
        self.assertEqual(opencode_model_protocol("OpenCode-Go/GLM-5.3"), "chat")

    def test_unknown_model_defaults_to_chat(self):
        self.assertEqual(opencode_model_protocol("some-new-model"), "chat")
        self.assertEqual(opencode_model_protocol(""), "chat")


class TestIsOpenCodeBaseUrl(unittest.TestCase):
    def test_gateway_urls(self):
        self.assertTrue(is_opencode_base_url("https://opencode.ai/inference/go/v1"))
        self.assertTrue(is_opencode_base_url("https://opencode.ai/zen/go/v1"))
        self.assertTrue(is_opencode_base_url("https://opencode.ai./inference/go/v1"))

    def test_lookalike_and_other_hosts_are_not_the_gateway(self):
        self.assertFalse(is_opencode_base_url("https://opencode.ai.evil.example/v1"))
        self.assertFalse(is_opencode_base_url("https://evil.example/opencode.ai/v1"))
        self.assertFalse(is_opencode_base_url("https://api.openai.com/v1"))
        self.assertFalse(is_opencode_base_url(None))
        self.assertFalse(is_opencode_base_url(""))
