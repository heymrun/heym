import unittest
import uuid

from pydantic import ValidationError

from app.models.alert_schemas import AlertCreate, describe_condition, parse_alert_config


class TestAlertConfigUnion(unittest.TestCase):
    def test_error_threshold_config_parses(self):
        cfg = parse_alert_config("error_threshold", {"window_minutes": 10, "threshold_count": 5})
        self.assertEqual(cfg.threshold_count, 5)
        self.assertEqual(cfg.window_minutes, 10)

    def test_duration_config_defaults_to_max(self):
        cfg = parse_alert_config("workflow_duration", {"window_minutes": 30, "threshold_ms": 5000})
        self.assertEqual(cfg.aggregation, "max")
        self.assertEqual(cfg.min_samples, 1)

    def test_token_cost_requires_known_metric(self):
        with self.assertRaises(ValidationError):
            parse_alert_config(
                "token_cost",
                {"window_minutes": 60, "metric": "bananas", "threshold": 1.0},
            )

    def test_unknown_alert_type_raises(self):
        with self.assertRaises(ValueError):
            parse_alert_config("cosmic_rays", {"window_minutes": 5})

    def test_window_minutes_upper_bound(self):
        with self.assertRaises(ValidationError):
            parse_alert_config("execution_count", {"window_minutes": 10081, "threshold_count": 1})

    def test_window_minutes_lower_bound(self):
        with self.assertRaises(ValidationError):
            parse_alert_config("execution_count", {"window_minutes": 0, "threshold_count": 1})


class TestDescribeCondition(unittest.TestCase):
    def test_error_threshold_summary(self):
        summary = describe_condition(
            "error_threshold", {"window_minutes": 10, "threshold_count": 5}
        )
        self.assertEqual(summary, "5+ errors in 10m")

    def test_duration_summary(self):
        summary = describe_condition(
            "workflow_duration",
            {"window_minutes": 30, "threshold_ms": 5000, "aggregation": "p95"},
        )
        self.assertEqual(summary, "p95 duration over 5000ms in 30m")

    def test_cost_summary_uses_the_metric_unit(self):
        self.assertEqual(
            describe_condition(
                "token_cost", {"window_minutes": 60, "metric": "usd", "threshold": 25}
            ),
            "25 USD spent in 60m",
        )
        self.assertEqual(
            describe_condition(
                "token_cost",
                {"window_minutes": 60, "metric": "total_tokens", "threshold": 100000},
            ),
            "100000 tokens spent in 60m",
        )

    def test_execution_count_summary(self):
        summary = describe_condition(
            "execution_count", {"window_minutes": 60, "threshold_count": 100}
        )
        self.assertEqual(summary, "100+ executions in 60m")


class TestAlertCreateValidation(unittest.TestCase):
    def _base(self, **overrides):
        payload = {
            "name": "Invoice failures",
            "alert_type": "error_threshold",
            "scope": "workflow",
            "workflow_id": str(uuid.uuid4()),
            "config": {"window_minutes": 10, "threshold_count": 5},
        }
        payload.update(overrides)
        return payload

    def test_valid_workflow_scope(self):
        model = AlertCreate(**self._base())
        self.assertEqual(model.scope, "workflow")

    def test_workflow_scope_requires_workflow_id(self):
        with self.assertRaises(ValidationError):
            AlertCreate(**self._base(workflow_id=None))

    def test_system_scope_rejects_workflow_id(self):
        with self.assertRaises(ValidationError):
            AlertCreate(**self._base(scope="system"))

    def test_system_scope_without_workflow_id_is_valid(self):
        model = AlertCreate(**self._base(scope="system", workflow_id=None))
        self.assertEqual(model.scope, "system")

    def test_cooldown_mode_requires_cooldown_minutes(self):
        with self.assertRaises(ValidationError):
            AlertCreate(**self._base(renotify_mode="cooldown"))

    def test_cooldown_mode_with_minutes_is_valid(self):
        model = AlertCreate(**self._base(renotify_mode="cooldown", cooldown_minutes=30))
        self.assertEqual(model.cooldown_minutes, 30)

    def test_check_interval_floor_is_sixty(self):
        with self.assertRaises(ValidationError):
            AlertCreate(**self._base(check_interval_seconds=15))

    def test_config_must_match_the_alert_type(self):
        with self.assertRaises(ValidationError):
            AlertCreate(
                **self._base(
                    alert_type="token_cost",
                    config={"window_minutes": 60, "threshold_count": 5},
                )
            )
