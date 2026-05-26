import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.llm_pricing_sync import (
    HELICONE_URL,
    ensure_pricing_synced,
    sync_pricing_from_helicone,
)

SAMPLE_PAYLOAD = {
    "metadata": {"total_models": 2},
    "data": [
        {
            "provider": "ANTHROPIC",
            "model": "claude-3-5-sonnet-20241022",
            "operator": "equals",
            "input_cost_per_1m": 3.0,
            "output_cost_per_1m": 15.0,
        },
        {
            "provider": "OPENAI",
            "model": "gpt-4o",
            "operator": "equals",
            "input_cost_per_1m": 5.0,
            "output_cost_per_1m": 15.0,
        },
    ],
}


def _mock_httpx_get(payload=SAMPLE_PAYLOAD, status_code=200, raise_exc=None):
    async def _get(url, *a, **kw):
        if raise_exc is not None:
            raise raise_exc
        resp = MagicMock()
        resp.status_code = status_code
        resp.json = MagicMock(return_value=payload)
        resp.raise_for_status = MagicMock()
        return resp

    return _get


class SyncFromHeliconeTests(unittest.IsolatedAsyncioTestCase):
    async def test_upserts_helicone_rows(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        with patch("httpx.AsyncClient") as client_cls:
            instance = client_cls.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_mock_httpx_get())
            inserted = await sync_pricing_from_helicone(db)
        self.assertEqual(inserted, 2)
        self.assertEqual(db.execute.await_count, 2)
        db.commit.assert_awaited_once()

    async def test_fetch_failure_logs_and_returns_zero(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        with patch("httpx.AsyncClient") as client_cls:
            instance = client_cls.return_value.__aenter__.return_value
            instance.get = AsyncMock(
                side_effect=_mock_httpx_get(raise_exc=httpx.ConnectError("boom"))
            )
            inserted = await sync_pricing_from_helicone(db)
        self.assertEqual(inserted, 0)
        db.execute.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_skips_negative_sentinel_costs(self):
        payload = {
            "data": [
                {
                    "provider": "OPENROUTER",
                    "model": "openrouter/auto",
                    "operator": "equals",
                    "input_cost_per_1m": -1000000,
                    "output_cost_per_1m": -1000000,
                },
                {
                    "provider": "OPENAI",
                    "model": "gpt-4o",
                    "operator": "equals",
                    "input_cost_per_1m": 5.0,
                    "output_cost_per_1m": 15.0,
                },
            ],
        }
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        with patch("httpx.AsyncClient") as client_cls:
            instance = client_cls.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_mock_httpx_get(payload=payload))
            inserted = await sync_pricing_from_helicone(db)
        # Only the gpt-4o row should have been upserted; the sentinel row skipped.
        self.assertEqual(inserted, 1)
        self.assertEqual(db.execute.await_count, 1)

    async def test_bad_payload_handled(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        with patch("httpx.AsyncClient") as client_cls:
            instance = client_cls.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_mock_httpx_get(payload={"nope": True}))
            inserted = await sync_pricing_from_helicone(db)
        self.assertEqual(inserted, 0)


class EnsurePricingSyncedTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_fresh_within_ttl(self):
        db = AsyncMock()
        fresh = datetime.now(timezone.utc) - timedelta(hours=1)
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=fresh)
        db.execute = AsyncMock(return_value=scalar_result)

        with patch("app.services.llm_pricing_sync.sync_pricing_from_helicone") as sync_mock:
            sync_mock.return_value = 0
            triggered = await ensure_pricing_synced(db, force=False)
        self.assertFalse(triggered)
        sync_mock.assert_not_called()

    async def test_schedules_async_sync_when_stale(self):
        db = AsyncMock()
        stale = datetime.now(timezone.utc) - timedelta(hours=48)
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=stale)
        db.execute = AsyncMock(return_value=scalar_result)

        with (
            patch("app.services.llm_pricing_sync.async_session_maker") as session_cls,
            patch(
                "app.services.llm_pricing_sync.sync_pricing_from_helicone",
                AsyncMock(return_value=2),
            ) as sync_mock,
        ):
            session_ctx = session_cls.return_value
            session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
            session_ctx.__aexit__ = AsyncMock(return_value=False)
            triggered = await ensure_pricing_synced(db, force=False)
            import asyncio

            await asyncio.sleep(0)
            await asyncio.sleep(0)
        self.assertTrue(triggered)
        sync_mock.assert_awaited()

    async def test_force_bypasses_ttl(self):
        db = AsyncMock()
        fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=fresh)
        db.execute = AsyncMock(return_value=scalar_result)

        with (
            patch("app.services.llm_pricing_sync.async_session_maker") as session_cls,
            patch(
                "app.services.llm_pricing_sync.sync_pricing_from_helicone",
                AsyncMock(return_value=0),
            ),
        ):
            session_ctx = session_cls.return_value
            session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
            session_ctx.__aexit__ = AsyncMock(return_value=False)
            triggered = await ensure_pricing_synced(db, force=True)
        self.assertTrue(triggered)


class HeliconeUrlTests(unittest.TestCase):
    def test_helicone_url_constant(self):
        self.assertEqual(HELICONE_URL, "https://www.helicone.ai/api/llm-costs")
