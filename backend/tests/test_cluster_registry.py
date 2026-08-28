"""Liveness, compatibility, and the candidate pool."""

import unittest
from datetime import datetime, timedelta, timezone

from app.services.cluster.registry import (
    HEARTBEAT_INTERVAL_SECONDS,
    LIVENESS_WINDOW_SECONDS,
    InstanceView,
    candidate_instances,
    is_compatible_with,
    is_live,
    is_live_now,
)


def _view(**overrides: object) -> InstanceView:
    base = dict(
        id="worker-a",
        name="Worker A",
        role="worker",
        enabled=True,
        weight=30,
        weight_configured=True,
        version="1.2.3",
        schema_revision="116_add_cluster_instances",
        keys_fingerprint="aaaabbbb",
        docker_ok=True,
        db_latency_ms=3.0,
        heartbeat_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return InstanceView(**base)  # type: ignore[arg-type]


class LivenessTests(unittest.TestCase):
    def test_a_fresh_heartbeat_is_live(self) -> None:
        self.assertTrue(is_live(_view(), now=datetime.now(timezone.utc)))

    def test_one_missed_beat_is_still_live(self) -> None:
        now = datetime.now(timezone.utc)
        stale = _view(heartbeat_at=now - timedelta(seconds=HEARTBEAT_INTERVAL_SECONDS + 1))
        self.assertTrue(is_live(stale, now=now))

    def test_a_heartbeat_past_the_window_is_dead(self) -> None:
        now = datetime.now(timezone.utc)
        dead = _view(heartbeat_at=now - timedelta(seconds=LIVENESS_WINDOW_SECONDS + 1))
        self.assertFalse(is_live(dead, now=now))


class CompatibilityTests(unittest.TestCase):
    def test_matching_instances_are_compatible(self) -> None:
        self.assertTrue(is_compatible_with(_view(), _view(id="main", role="main")))

    def test_a_different_version_is_incompatible(self) -> None:
        main = _view(id="main", role="main")
        self.assertFalse(is_compatible_with(_view(version="1.2.2"), main))

    def test_a_different_schema_revision_is_incompatible(self) -> None:
        main = _view(id="main", role="main")
        self.assertFalse(is_compatible_with(_view(schema_revision="115_add_sso_settings"), main))

    def test_a_different_key_fingerprint_is_incompatible(self) -> None:
        main = _view(id="main", role="main")
        self.assertFalse(is_compatible_with(_view(keys_fingerprint="ccccdddd"), main))


class CandidatePoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.main = _view(id="main", role="main", weight=70)

    def test_pool_holds_live_enabled_compatible_instances(self) -> None:
        pool = candidate_instances([self.main, _view()], now=self.now)
        self.assertEqual([i.id for i in pool], ["main", "worker-a"])

    def test_a_disabled_instance_is_excluded(self) -> None:
        pool = candidate_instances([self.main, _view(enabled=False)], now=self.now)
        self.assertEqual([i.id for i in pool], ["main"])

    def test_a_dead_instance_is_excluded(self) -> None:
        dead = _view(heartbeat_at=self.now - timedelta(seconds=LIVENESS_WINDOW_SECONDS + 1))
        pool = candidate_instances([self.main, dead], now=self.now)
        self.assertEqual([i.id for i in pool], ["main"])

    def test_an_incompatible_instance_is_excluded(self) -> None:
        pool = candidate_instances([self.main, _view(version="0.9.0")], now=self.now)
        self.assertEqual([i.id for i in pool], ["main"])

    def test_a_zero_weight_instance_is_excluded(self) -> None:
        pool = candidate_instances([self.main, _view(weight=0)], now=self.now)
        self.assertEqual([i.id for i in pool], ["main"])

    def test_an_empty_pool_when_main_is_missing(self) -> None:
        """Without a main row there is no compatibility reference, so nobody runs."""
        self.assertEqual(candidate_instances([_view()], now=self.now), [])


class ConnectionAwareLivenessTests(unittest.TestCase):
    """A stopped container drops its database connections within seconds.

    The heartbeat alone cannot beat its own window, so the admin view combines
    both: gone from pg_stat_activity means gone now, and a stale heartbeat still
    catches an instance whose process is up but wedged.
    """

    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)

    def test_connected_and_beating_is_live(self) -> None:
        self.assertTrue(is_live_now(_view(), now=self.now, connected_ids={"worker-a"}))

    def test_no_connections_is_offline_immediately(self) -> None:
        """Heartbeat is still fresh, but the process is already gone."""
        self.assertFalse(is_live_now(_view(), now=self.now, connected_ids=set()))

    def test_connected_but_not_beating_is_offline(self) -> None:
        """Process up, event loop wedged: connections linger, the heartbeat does not."""
        stale = _view(heartbeat_at=self.now - timedelta(seconds=LIVENESS_WINDOW_SECONDS + 1))
        self.assertFalse(is_live_now(stale, now=self.now, connected_ids={"worker-a"}))

    def test_an_unknown_connection_set_falls_back_to_the_heartbeat(self) -> None:
        """pg_stat_activity can be unreadable; never report a healthy instance dead."""
        self.assertTrue(is_live_now(_view(), now=self.now, connected_ids=None))
        stale = _view(heartbeat_at=self.now - timedelta(seconds=LIVENESS_WINDOW_SECONDS + 1))
        self.assertFalse(is_live_now(stale, now=self.now, connected_ids=None))
