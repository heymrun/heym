import unittest
from unittest.mock import AsyncMock, patch

from app.services.opencode_models import fetch_opencode_models


class TestFetchOpenCodeModels(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Isolate the module-level cache between tests.
        import app.services.opencode_models as mod

        mod._CACHE.clear()

    async def test_live_success(self):
        payload = {"object": "list", "data": [{"id": "kimi-k3"}, {"id": "deepseek-v4-pro"}]}
        with patch("app.services.opencode_models._get_json", new=AsyncMock(return_value=payload)):
            models, source = await fetch_opencode_models(base_url="https://opencode.ai/zen/go/v1")
        self.assertEqual(source, "live")
        self.assertEqual(models[0]["id"], "opencode-go/kimi-k3")

    async def test_fallback_on_error(self):
        with patch(
            "app.services.opencode_models._get_json", new=AsyncMock(side_effect=RuntimeError)
        ):
            models, source = await fetch_opencode_models(base_url="https://opencode.ai/zen/go/v1")
        self.assertEqual(source, "fallback")
        self.assertTrue(any(m["id"] == "opencode-go/kimi-k3" for m in models))

    async def test_fallback_on_empty(self):
        with patch(
            "app.services.opencode_models._get_json", new=AsyncMock(return_value={"data": []})
        ):
            models, source = await fetch_opencode_models(base_url="https://opencode.ai/zen/go/v1")
        self.assertEqual(source, "fallback")
