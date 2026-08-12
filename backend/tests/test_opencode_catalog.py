import unittest

from app.services.opencode_catalog import (
    OPENCODE_DEFAULT_MODEL,
    OPENCODE_MODEL_FALLBACK,
    normalize_opencode_models,
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
