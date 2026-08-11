import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.alert_schemas import parse_alert_config
from app.services.alerts.context import AlertEvaluationContext
from app.services.alerts.types import (
    error_threshold,
    execution_count,
    token_cost,
    workflow_duration,
)

WF_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
WF_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _ctx(db, config, workflow_ids=None, window_minutes=10):
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    return AlertEvaluationContext(
        db=db,
        owner_id=uuid.uuid4(),
        workflow_ids=workflow_ids if workflow_ids is not None else [uuid.uuid4()],
        window_start=now - timedelta(minutes=window_minutes),
        window_end=now,
        config=config,
    )


def _scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _rows_result(rows):
    result = MagicMock()
    result.all.return_value = rows
    return result


class TestErrorThresholdHandler(unittest.IsolatedAsyncioTestCase):
    async def test_counts_errors_in_window(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(12),
                _rows_result([(WF_A, 7), (WF_B, 5)]),
            ]
        )
        config = parse_alert_config("error_threshold", {"window_minutes": 10, "threshold_count": 5})
        observation = await error_threshold.evaluate(_ctx(db, config))
        self.assertEqual(observation.observed_value, 12.0)
        self.assertEqual(observation.threshold_value, 5.0)
        self.assertTrue(observation.breached)
        self.assertEqual(observation.context["error_count"], 12)
        self.assertEqual(observation.contributing_workflows, {WF_A: 7.0, WF_B: 5.0})

    async def test_no_errors_is_not_breached(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_scalar_result(0), _rows_result([])])
        config = parse_alert_config("error_threshold", {"window_minutes": 10, "threshold_count": 5})
        observation = await error_threshold.evaluate(_ctx(db, config))
        self.assertEqual(observation.observed_value, 0.0)
        self.assertFalse(observation.breached)

    async def test_empty_scope_short_circuits_without_querying(self):
        db = MagicMock()
        db.execute = AsyncMock()
        config = parse_alert_config("error_threshold", {"window_minutes": 10, "threshold_count": 5})
        observation = await error_threshold.evaluate(_ctx(db, config, workflow_ids=[]))
        self.assertEqual(observation.observed_value, 0.0)
        db.execute.assert_not_awaited()

    async def test_exact_threshold_counts_as_breach(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_scalar_result(5), _rows_result([])])
        config = parse_alert_config("error_threshold", {"window_minutes": 10, "threshold_count": 5})
        observation = await error_threshold.evaluate(_ctx(db, config))
        self.assertTrue(observation.breached)

    async def test_only_the_count_and_the_per_workflow_split_are_queried(self):
        # No per-execution sampling: the count plus where it came from is the whole
        # contract, and the firing links back to execution history for the detail.
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_scalar_result(1), _rows_result([(WF_A, 1)])])
        config = parse_alert_config("error_threshold", {"window_minutes": 10, "threshold_count": 1})
        observation = await error_threshold.evaluate(_ctx(db, config))
        self.assertEqual(db.execute.await_count, 2)
        self.assertEqual(set(observation.context), {"error_count"})
        self.assertEqual(observation.contributing_workflows, {WF_A: 1.0})


class TestExecutionCountHandler(unittest.IsolatedAsyncioTestCase):
    async def test_counts_all_statuses(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(2000),
                _rows_result([("cron", 1990), ("manual", 10)]),
                _rows_result([(WF_A, 1995), (WF_B, 5)]),
            ]
        )
        config = parse_alert_config(
            "execution_count", {"window_minutes": 60, "threshold_count": 100}
        )
        observation = await execution_count.evaluate(_ctx(db, config, window_minutes=60))
        self.assertEqual(observation.observed_value, 2000.0)
        self.assertTrue(observation.breached)
        self.assertEqual(observation.context["by_trigger_source"]["cron"], 1990)

    async def test_under_threshold_not_breached(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(20),
                _rows_result([("cron", 20)]),
                _rows_result([(WF_A, 20)]),
            ]
        )
        config = parse_alert_config(
            "execution_count", {"window_minutes": 60, "threshold_count": 100}
        )
        observation = await execution_count.evaluate(_ctx(db, config, window_minutes=60))
        self.assertFalse(observation.breached)

    async def test_null_trigger_source_becomes_unknown(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(3),
                _rows_result([(None, 3)]),
                _rows_result([(WF_A, 3)]),
            ]
        )
        config = parse_alert_config("execution_count", {"window_minutes": 60, "threshold_count": 1})
        observation = await execution_count.evaluate(_ctx(db, config, window_minutes=60))
        self.assertEqual(observation.context["by_trigger_source"]["unknown"], 3)

    async def test_empty_scope_short_circuits(self):
        db = MagicMock()
        db.execute = AsyncMock()
        config = parse_alert_config(
            "execution_count", {"window_minutes": 60, "threshold_count": 100}
        )
        observation = await execution_count.evaluate(_ctx(db, config, workflow_ids=[]))
        self.assertEqual(observation.observed_value, 0.0)
        db.execute.assert_not_awaited()


class TestWorkflowDurationHandler(unittest.IsolatedAsyncioTestCase):
    async def test_max_aggregation(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[_rows_result([(WF_A, 1000.0), (WF_B, 9000.0), (WF_A, 3000.0)])]
        )
        config = parse_alert_config(
            "workflow_duration",
            {"window_minutes": 30, "threshold_ms": 5000, "aggregation": "max"},
        )
        observation = await workflow_duration.evaluate(_ctx(db, config, window_minutes=30))
        self.assertEqual(observation.observed_value, 9000.0)
        self.assertTrue(observation.breached)
        self.assertEqual(observation.context["sample_count"], 3)

    async def test_avg_aggregation(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[_rows_result([(WF_A, 1000.0), (WF_A, 2000.0), (WF_B, 3000.0)])]
        )
        config = parse_alert_config(
            "workflow_duration",
            {"window_minutes": 30, "threshold_ms": 5000, "aggregation": "avg"},
        )
        observation = await workflow_duration.evaluate(_ctx(db, config, window_minutes=30))
        self.assertEqual(observation.observed_value, 2000.0)
        self.assertFalse(observation.breached)

    async def test_p95_matches_analytics_percentile_helper(self):
        from app.api.analytics import calculate_percentile

        values = [float(v) for v in range(1, 101)]
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([(WF_A, v) for v in values])])
        config = parse_alert_config(
            "workflow_duration",
            {"window_minutes": 30, "threshold_ms": 1, "aggregation": "p95"},
        )
        observation = await workflow_duration.evaluate(_ctx(db, config, window_minutes=30))
        self.assertEqual(observation.observed_value, calculate_percentile(values, 95))

    async def test_min_samples_suppresses(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([(WF_A, 90000.0)])])
        config = parse_alert_config(
            "workflow_duration",
            {"window_minutes": 30, "threshold_ms": 5000, "min_samples": 5},
        )
        observation = await workflow_duration.evaluate(_ctx(db, config, window_minutes=30))
        self.assertIsNone(observation.observed_value)
        self.assertFalse(observation.breached)

    async def test_empty_window_is_not_breached(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([])])
        config = parse_alert_config(
            "workflow_duration", {"window_minutes": 30, "threshold_ms": 5000}
        )
        observation = await workflow_duration.evaluate(_ctx(db, config, window_minutes=30))
        self.assertIsNone(observation.observed_value)
        self.assertFalse(observation.breached)

    async def test_null_durations_are_ignored(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([(WF_A, None), (WF_B, 7000.0)])])
        config = parse_alert_config(
            "workflow_duration", {"window_minutes": 30, "threshold_ms": 5000}
        )
        observation = await workflow_duration.evaluate(_ctx(db, config, window_minutes=30))
        self.assertEqual(observation.observed_value, 7000.0)
        self.assertEqual(observation.context["sample_count"], 1)


class TestTokenCostHandler(unittest.IsolatedAsyncioTestCase):
    async def test_total_tokens_metric(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _rows_result([("gpt-5", 1000, 500, 1500, WF_A), ("gpt-5", 2000, 1000, 3000, WF_B)])
            ]
        )
        config = parse_alert_config(
            "token_cost",
            {"window_minutes": 60, "metric": "total_tokens", "threshold": 4000},
        )
        observation = await token_cost.evaluate(_ctx(db, config, window_minutes=60))
        self.assertEqual(observation.observed_value, 4500.0)
        self.assertTrue(observation.breached)
        self.assertEqual(observation.context["by_model"]["gpt-5"]["total_tokens"], 4500)

    async def test_usd_metric_uses_pricing_service(self):
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[_rows_result([("gpt-5", 1_000_000, 0, 1_000_000, WF_A)])]
        )
        config = parse_alert_config(
            "token_cost", {"window_minutes": 60, "metric": "usd", "threshold": 1.0}
        )
        with patch(
            "app.services.alerts.types.token_cost.resolve_costs_for_user",
            new=AsyncMock(return_value=[(Decimal("2.50"), True)]),
        ):
            observation = await token_cost.evaluate(_ctx(db, config, window_minutes=60))
        self.assertAlmostEqual(observation.observed_value, 2.50)
        self.assertTrue(observation.breached)

    async def test_no_traces_is_zero(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([])])
        config = parse_alert_config(
            "token_cost",
            {"window_minutes": 60, "metric": "total_tokens", "threshold": 100},
        )
        observation = await token_cost.evaluate(_ctx(db, config, window_minutes=60))
        self.assertEqual(observation.observed_value, 0.0)
        self.assertFalse(observation.breached)

    async def test_unpriced_model_is_flagged_in_context(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([("mystery-model", 100, 100, 200, WF_A)])])
        config = parse_alert_config(
            "token_cost", {"window_minutes": 60, "metric": "usd", "threshold": 1.0}
        )
        with patch(
            "app.services.alerts.types.token_cost.resolve_costs_for_user",
            new=AsyncMock(return_value=[(None, False)]),
        ):
            observation = await token_cost.evaluate(_ctx(db, config, window_minutes=60))
        self.assertEqual(observation.observed_value, 0.0)
        self.assertIn("mystery-model", observation.context["unpriced_models"])

    async def test_system_scope_with_no_workflows_still_counts_user_spend(self):
        """LLM calls outside a workflow carry workflow_id NULL and must still count."""
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows_result([("gpt-5", 10, 10, 20, None)])])
        config = parse_alert_config(
            "token_cost",
            {"window_minutes": 60, "metric": "total_tokens", "threshold": 1},
        )
        observation = await token_cost.evaluate(
            _ctx(db, config, workflow_ids=[], window_minutes=60)
        )
        self.assertEqual(observation.observed_value, 20.0)
        db.execute.assert_awaited_once()
