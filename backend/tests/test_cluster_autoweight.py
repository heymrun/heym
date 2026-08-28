"""Which instances a seeding pass may redistribute across."""

import unittest
from datetime import datetime, timedelta, timezone

from app.services.cluster.autoweight import seedable_pool
from app.services.cluster.registry import LIVENESS_WINDOW_SECONDS, InstanceView


def _view(**overrides: object) -> InstanceView:
    base = dict(
        id="worker-a",
        name="Worker A",
        role="worker",
        enabled=True,
        weight=0,
        weight_configured=False,
        version="1.2.3",
        schema_revision="119_add_auto_weighting",
        keys_fingerprint="aaaabbbb",
        docker_ok=True,
        db_latency_ms=3.0,
        heartbeat_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return InstanceView(**base)  # type: ignore[arg-type]


class SeedablePoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.main = _view(id="main", role="main", weight=100, weight_configured=True)

    def test_a_newcomer_and_main_are_both_in_the_pool(self) -> None:
        pool = seedable_pool([self.main, _view()], main=self.main, now=self.now)
        self.assertEqual(pool, {"main": (True, 100), "worker-a": (False, 0)})

    def test_a_disabled_instance_is_excluded(self) -> None:
        """Disabled is the operator saying 'not this one'."""
        pool = seedable_pool([self.main, _view(enabled=False)], main=self.main, now=self.now)
        self.assertEqual(list(pool), ["main"])

    def test_an_offline_instance_is_excluded(self) -> None:
        """Handing a share to a machine that cannot take work would strand it."""
        dead = _view(heartbeat_at=self.now - timedelta(seconds=LIVENESS_WINDOW_SECONDS + 1))
        pool = seedable_pool([self.main, dead], main=self.main, now=self.now)
        self.assertEqual(list(pool), ["main"])

    def test_an_incompatible_instance_is_excluded(self) -> None:
        pool = seedable_pool([self.main, _view(version="0.9.0")], main=self.main, now=self.now)
        self.assertEqual(list(pool), ["main"])

    def test_no_main_means_no_pool(self) -> None:
        self.assertEqual(seedable_pool([_view()], main=None, now=self.now), {})

    def test_main_is_never_a_newcomer(self) -> None:
        """Its 100 is deliberate, so seeding must never redistribute it away."""
        pool = seedable_pool([self.main], main=self.main, now=self.now)
        self.assertTrue(pool["main"][0])
