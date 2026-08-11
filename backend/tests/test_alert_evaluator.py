import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.alerts import evaluator

MODULE = "app.services.alerts.evaluator"


def _alert(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "owner_id": uuid.uuid4(),
        "name": "Invoice failures",
        "alert_type": "error_threshold",
        "scope": "workflow",
        "workflow_id": uuid.uuid4(),
        "config": {"window_minutes": 10, "threshold_count": 5},
        "enabled": True,
        "notify_workflow_id": None,
        "state": "ok",
        "renotify_mode": "on_recovery",
        "cooldown_minutes": None,
        "check_interval_seconds": 60,
        "last_triggered_at": None,
        "last_observed_value": None,
        "last_evaluated_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


class TestResolveScope(unittest.IsolatedAsyncioTestCase):
    async def test_workflow_scope_returns_single_id(self):
        alert = _alert()
        ids = await evaluator.resolve_scope_workflow_ids(MagicMock(), alert)
        self.assertEqual(ids, [alert.workflow_id])

    async def test_workflow_scope_without_an_id_is_empty(self):
        alert = _alert(workflow_id=None)
        ids = await evaluator.resolve_scope_workflow_ids(MagicMock(), alert)
        self.assertEqual(ids, [])

    async def test_system_scope_uses_accessible_workflow_ids(self):
        alert = _alert(scope="system", workflow_id=None)
        accessible = [uuid.uuid4(), uuid.uuid4()]
        with patch(f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=accessible)):
            ids = await evaluator.resolve_scope_workflow_ids(MagicMock(), alert)
        self.assertEqual(ids, accessible)


class TestObserve(unittest.IsolatedAsyncioTestCase):
    async def test_observe_calls_the_registered_handler_with_the_right_window(self):
        alert = _alert()
        fake = SimpleNamespace(
            observed_value=9.0,
            threshold_value=5.0,
            breached=True,
            context={},
            contributing_workflows={},
        )
        handler = AsyncMock(return_value=fake)
        with patch(f"{MODULE}.get_alert_handler", return_value=handler):
            observation, window_start, window_end = await evaluator.observe(
                MagicMock(), alert, now=NOW
            )
        self.assertEqual(observation.observed_value, 9.0)
        self.assertEqual(window_end, NOW)
        self.assertEqual(window_start, NOW - timedelta(minutes=10))
        ctx = handler.await_args.args[0]
        self.assertEqual(ctx.owner_id, alert.owner_id)
        self.assertEqual(ctx.workflow_ids, [alert.workflow_id])


class TestShouldFire(unittest.TestCase):
    def test_ok_plus_breach_fires(self):
        self.assertTrue(evaluator.should_fire(_alert(state="ok"), breached=True, now=NOW))

    def test_ok_without_breach_does_not_fire(self):
        self.assertFalse(evaluator.should_fire(_alert(state="ok"), breached=False, now=NOW))

    def test_triggered_on_recovery_stays_silent_while_breached(self):
        alert = _alert(
            state="triggered",
            renotify_mode="on_recovery",
            last_triggered_at=NOW - timedelta(hours=5),
        )
        self.assertFalse(evaluator.should_fire(alert, breached=True, now=NOW))

    def test_triggered_cooldown_refires_after_the_interval(self):
        alert = _alert(
            state="triggered",
            renotify_mode="cooldown",
            cooldown_minutes=30,
            last_triggered_at=NOW - timedelta(minutes=31),
        )
        self.assertTrue(evaluator.should_fire(alert, breached=True, now=NOW))

    def test_triggered_cooldown_silent_inside_the_interval(self):
        alert = _alert(
            state="triggered",
            renotify_mode="cooldown",
            cooldown_minutes=30,
            last_triggered_at=NOW - timedelta(minutes=5),
        )
        self.assertFalse(evaluator.should_fire(alert, breached=True, now=NOW))

    def test_recovery_then_breach_fires_again(self):
        alert = _alert(state="ok", last_triggered_at=NOW - timedelta(minutes=1))
        self.assertTrue(evaluator.should_fire(alert, breached=True, now=NOW))

    def test_naive_last_triggered_at_is_treated_as_utc(self):
        alert = _alert(
            state="triggered",
            renotify_mode="cooldown",
            cooldown_minutes=30,
            last_triggered_at=datetime(2026, 8, 9, 11, 0),
        )
        self.assertTrue(evaluator.should_fire(alert, breached=True, now=NOW))


class TestNextState(unittest.TestCase):
    def test_breach_moves_to_triggered(self):
        self.assertEqual(evaluator.next_state(breached=True), "triggered")

    def test_no_breach_moves_to_ok(self):
        self.assertEqual(evaluator.next_state(breached=False), "ok")


class TestNotifyPayload(unittest.TestCase):
    def test_payload_carries_condition_and_observation(self):
        payload = evaluator.build_notify_payload(
            _alert(),
            observed_value=12.0,
            threshold_value=5.0,
            window_start=NOW - timedelta(minutes=10),
            window_end=NOW,
            context={"error_count": 12},
        )
        self.assertEqual(payload["alert_name"], "Invoice failures")
        self.assertEqual(payload["observed_value"], 12.0)
        self.assertEqual(payload["threshold_value"], 5.0)
        self.assertEqual(payload["window_minutes"], 10)
        self.assertEqual(payload["condition"], "5+ errors in 10m")
        self.assertEqual(payload["context"]["error_count"], 12)

    def test_contributing_workflows_are_always_an_array(self):
        # There is no singular workflow_id: it was null under system scope, which is
        # exactly when the question matters. workflows stays an array, empty rather
        # than null when nothing is attributable.
        payload = evaluator.build_notify_payload(
            _alert(scope="system", workflow_id=None),
            observed_value=6186.19,
            threshold_value=5000.0,
            window_start=NOW - timedelta(minutes=30),
            window_end=NOW,
            context={},
            workflows=None,
        )
        self.assertNotIn("workflow_id", payload)
        self.assertNotIn("workflow_name", payload)
        self.assertEqual(payload["workflows"], [])

    def test_system_scope_payload_names_the_contributing_workflows(self):
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        payload = evaluator.build_notify_payload(
            _alert(scope="system", workflow_id=None),
            observed_value=6186.19,
            threshold_value=5000.0,
            window_start=NOW - timedelta(minutes=30),
            window_end=NOW,
            context={},
            workflows=[
                {"id": second, "name": "Nightly", "value": 6186.19},
                {"id": first, "name": "Invoice Sync", "value": 900.0},
            ],
        )
        self.assertEqual([entry["id"] for entry in payload["workflows"]], [second, first])
        self.assertEqual(payload["workflows"][0]["value"], 6186.19)


class TestNotifyGuard(unittest.TestCase):
    def test_self_referential_notify_is_skipped(self):
        wf_id = uuid.uuid4()
        self.assertFalse(
            evaluator.should_dispatch_notify(_alert(workflow_id=wf_id, notify_workflow_id=wf_id))
        )

    def test_distinct_notify_workflow_is_dispatched(self):
        self.assertTrue(evaluator.should_dispatch_notify(_alert(notify_workflow_id=uuid.uuid4())))

    def test_no_notify_workflow_is_skipped(self):
        self.assertFalse(evaluator.should_dispatch_notify(_alert(notify_workflow_id=None)))


class TestEvaluateAlert(unittest.IsolatedAsyncioTestCase):
    def _db(self):
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        return db

    def _observation(self, observed, threshold=10.0, breached=True):
        return SimpleNamespace(
            observed_value=observed,
            threshold_value=threshold,
            breached=breached,
            context={},
            contributing_workflows={},
        )

    async def test_breach_writes_event_and_sets_triggered(self):
        alert = _alert(state="ok")
        db = self._db()
        with patch(
            f"{MODULE}.observe",
            new=AsyncMock(return_value=(self._observation(42.0), NOW - timedelta(minutes=10), NOW)),
        ):
            fired = await evaluator.evaluate_alert(db, alert, now=NOW)

        self.assertTrue(fired)
        self.assertEqual(alert.state, "triggered")
        self.assertEqual(alert.last_observed_value, 42.0)
        self.assertEqual(alert.last_triggered_at, NOW)
        db.add.assert_called_once()

    async def test_silent_while_already_triggered(self):
        alert = _alert(state="triggered", last_triggered_at=NOW - timedelta(hours=1))
        db = self._db()
        with patch(
            f"{MODULE}.observe",
            new=AsyncMock(return_value=(self._observation(42.0), NOW - timedelta(minutes=10), NOW)),
        ):
            fired = await evaluator.evaluate_alert(db, alert, now=NOW)

        self.assertFalse(fired)
        self.assertEqual(alert.state, "triggered")
        db.add.assert_not_called()

    async def test_recovery_resets_to_ok_without_an_event(self):
        alert = _alert(state="triggered")
        db = self._db()
        with patch(
            f"{MODULE}.observe",
            new=AsyncMock(
                return_value=(
                    self._observation(1.0, breached=False),
                    NOW - timedelta(minutes=10),
                    NOW,
                )
            ),
        ):
            fired = await evaluator.evaluate_alert(db, alert, now=NOW)

        self.assertFalse(fired)
        self.assertEqual(alert.state, "ok")
        db.add.assert_not_called()

    async def test_handler_exception_does_not_propagate(self):
        db = self._db()
        with patch(f"{MODULE}.observe", new=AsyncMock(side_effect=RuntimeError("bad query"))):
            fired = await evaluator.evaluate_alert(db, _alert(), now=NOW)
        self.assertFalse(fired)

    async def test_insufficient_data_leaves_state_untouched(self):
        alert = _alert(state="ok")
        db = self._db()
        with patch(
            f"{MODULE}.observe",
            new=AsyncMock(
                return_value=(
                    self._observation(None, breached=False),
                    NOW - timedelta(minutes=10),
                    NOW,
                )
            ),
        ):
            fired = await evaluator.evaluate_alert(db, alert, now=NOW)
        self.assertFalse(fired)
        self.assertEqual(alert.state, "ok")
        self.assertIsNone(alert.last_observed_value)

    async def test_notify_is_dispatched_after_the_event_is_committed(self):
        alert = _alert(state="ok", notify_workflow_id=uuid.uuid4())
        db = self._db()
        with patch(
            f"{MODULE}.observe",
            new=AsyncMock(return_value=(self._observation(42.0), NOW - timedelta(minutes=10), NOW)),
        ):
            with patch(f"{MODULE}.dispatch_notify") as dispatch:
                fired = await evaluator.evaluate_alert(db, alert, now=NOW)

        self.assertTrue(fired)
        dispatch.assert_called_once()
        db.commit.assert_awaited()

    async def test_no_notify_dispatch_when_none_configured(self):
        alert = _alert(state="ok", notify_workflow_id=None)
        db = self._db()
        with patch(
            f"{MODULE}.observe",
            new=AsyncMock(return_value=(self._observation(42.0), NOW - timedelta(minutes=10), NOW)),
        ):
            with patch(f"{MODULE}.dispatch_notify") as dispatch:
                await evaluator.evaluate_alert(db, alert, now=NOW)
        dispatch.assert_not_called()
