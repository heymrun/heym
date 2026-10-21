import unittest
from unittest.mock import AsyncMock, patch

import httpx

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

    async def test_live_http_filters_minimax_and_caches_normalized_result(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "minimax-m2.7"},
                        {"id": "minimax-m3"},
                        {"id": "kimi-k3"},
                        {"id": "minimax-m3.1-flash-free"},
                    ]
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch("app.services.opencode_models.httpx.AsyncClient", return_value=client):
            models, source = await fetch_opencode_models()
            cached, cached_source = await fetch_opencode_models()
        self.assertEqual(source, "live")
        self.assertEqual(cached_source, "live")
        self.assertEqual(cached, models)
        self.assertEqual(
            [m["id"] for m in models],
            [
                "opencode-go/minimax-m3.1-flash-free",
                "opencode-go/kimi-k3",
                "opencode-go/minimax-m3",
            ],
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(str(requests[0].url), "https://opencode.ai/zen/go/v1/models")

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
