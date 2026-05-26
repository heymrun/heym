import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.traces import _resolve_range, get_trace_stats


class RangeResolverTests(unittest.TestCase):
    def _fixed_now(self) -> datetime:
        return datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)

    def test_1h_window_5min_bucket(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("1h", now=now)
        self.assertEqual(end, now)
        self.assertEqual(start, now - timedelta(hours=1))
        self.assertEqual(bucket, 300)

    def test_24h_window_1h_bucket(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("24h", now=now)
        self.assertEqual(start, now - timedelta(hours=24))
        self.assertEqual(bucket, 3600)

    def test_7d_window_6h_bucket(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("7d", now=now)
        self.assertEqual(start, now - timedelta(days=7))
        self.assertEqual(bucket, 6 * 3600)

    def test_30d_window_1d_bucket(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("30d", now=now)
        self.assertEqual(start, now - timedelta(days=30))
        self.assertEqual(bucket, 86400)

    def test_all_returns_none_start_with_day_bucket(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("all", now=now)
        self.assertIsNone(start)
        self.assertEqual(bucket, 86400)

    def test_invalid_range_defaults_to_7d(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("invalid", now=now)
        self.assertEqual(start, now - timedelta(days=7))


class StatsEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = MagicMock()
        self.user.id = uuid.uuid4()

    async def test_empty_returns_zero_kpis(self):
        db = AsyncMock()
        kpi_row = MagicMock()
        kpi_row.total_calls = 0
        kpi_row.error_calls = 0
        kpi_row.prompt_tokens = 0
        kpi_row.completion_tokens = 0
        kpi_row.total_tokens = 0
        kpi_row.avg_elapsed_ms = None
        kpi_result = MagicMock()
        kpi_result.one = MagicMock(return_value=kpi_row)
        empty_result = MagicMock()
        empty_result.all = MagicMock(return_value=[])
        db.execute = AsyncMock(side_effect=[kpi_result, empty_result, empty_result])
        with (
            patch("app.api.traces.resolve_costs_for_user", AsyncMock(return_value=[])),
            patch("app.api.traces.ensure_pricing_synced", AsyncMock(return_value=False)),
        ):
            response = await get_trace_stats(
                range="7d",
                source=None,
                credential_id=None,
                workflow_id=None,
                status_filter=None,
                search=None,
                current_user=self.user,
                db=db,
            )
        self.assertEqual(response.kpis.total_calls, 0)
        self.assertEqual(response.kpis.total_cost_usd, Decimal("0"))
        self.assertEqual(response.by_model, [])
        self.assertEqual(response.kpis.unpriced_models, [])

    async def test_kpis_and_by_model_aggregated(self):
        db = AsyncMock()
        kpi_row = MagicMock()
        kpi_row.total_calls = 10
        kpi_row.error_calls = 2
        kpi_row.prompt_tokens = 1000
        kpi_row.completion_tokens = 500
        kpi_row.total_tokens = 1500
        kpi_row.avg_elapsed_ms = 250.0
        kpi_result = MagicMock()
        kpi_result.one = MagicMock(return_value=kpi_row)

        m_rows = [
            MagicMock(
                model="gpt-4o",
                provider="openai",
                calls=6,
                total_tokens=1000,
                prompt_tokens=700,
                completion_tokens=300,
            ),
            MagicMock(
                model="unknown-x",
                provider=None,
                calls=4,
                total_tokens=500,
                prompt_tokens=300,
                completion_tokens=200,
            ),
        ]
        m_result = MagicMock()
        m_result.all = MagicMock(return_value=m_rows)

        t_rows = [
            MagicMock(
                bucket_ts=datetime(2026, 5, 26, 0, 0, tzinfo=timezone.utc),
                model="gpt-4o",
                calls=10,
                success=8,
                error=2,
                prompt_tokens=1000,
                completion_tokens=500,
                total_tokens=1500,
            ),
        ]
        t_result = MagicMock()
        t_result.all = MagicMock(return_value=t_rows)

        db.execute = AsyncMock(side_effect=[kpi_result, m_result, t_result])

        async def fake_resolve(_db, _uid, pairs):
            out = []
            for model, _p, _c in pairs:
                if model == "gpt-4o":
                    out.append((Decimal("0.10"), True))
                else:
                    out.append((None, False))
            return out

        with (
            patch("app.api.traces.resolve_costs_for_user", side_effect=fake_resolve),
            patch("app.api.traces.ensure_pricing_synced", AsyncMock(return_value=False)),
        ):
            response = await get_trace_stats(
                range="7d",
                source=None,
                credential_id=None,
                workflow_id=None,
                status_filter=None,
                search=None,
                current_user=self.user,
                db=db,
            )

        self.assertEqual(response.kpis.total_calls, 10)
        self.assertEqual(response.kpis.error_calls, 2)
        self.assertEqual(response.kpis.success_calls, 8)
        self.assertAlmostEqual(response.kpis.error_pct, 20.0, places=1)
        self.assertEqual(response.kpis.avg_latency_ms, 250.0)
        self.assertEqual(response.kpis.unpriced_models, ["unknown-x"])
        self.assertEqual(response.by_model[0].model, "gpt-4o")
        self.assertEqual(response.by_model[0].cost_usd, Decimal("0.10"))
        self.assertFalse(response.by_model[1].is_priced)
        self.assertEqual(response.by_model[1].cost_usd, Decimal("0"))

    async def test_by_model_collapses_other_after_top8(self):
        db = AsyncMock()
        kpi_row = MagicMock(
            total_calls=10,
            error_calls=0,
            prompt_tokens=1000,
            completion_tokens=0,
            total_tokens=1000,
            avg_elapsed_ms=10.0,
        )
        kpi_result = MagicMock()
        kpi_result.one = MagicMock(return_value=kpi_row)

        m_rows = []
        for i in range(10):
            m_rows.append(
                MagicMock(
                    model=f"m{i}",
                    provider="openai",
                    calls=10 - i,
                    total_tokens=1000 - i * 50,
                    prompt_tokens=500 - i * 25,
                    completion_tokens=500 - i * 25,
                )
            )
        m_result = MagicMock()
        m_result.all = MagicMock(return_value=m_rows)
        empty = MagicMock()
        empty.all = MagicMock(return_value=[])

        db.execute = AsyncMock(side_effect=[kpi_result, m_result, empty])

        async def fake_resolve(_db, _uid, pairs):
            return [(Decimal("0.01"), True) for _ in pairs]

        with (
            patch("app.api.traces.resolve_costs_for_user", side_effect=fake_resolve),
            patch("app.api.traces.ensure_pricing_synced", AsyncMock(return_value=False)),
        ):
            response = await get_trace_stats(
                range="7d",
                source=None,
                credential_id=None,
                workflow_id=None,
                status_filter=None,
                search=None,
                current_user=self.user,
                db=db,
            )
        self.assertEqual(len(response.by_model), 9)
        self.assertEqual(response.by_model[-1].model, "Other")
        self.assertTrue(response.by_model[-1].is_other)
