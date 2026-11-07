"""Compatibility while two keys are live, and who may lead (#862)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.services.cluster import registry
from app.services.cluster.registry import InstanceView, candidate_instances, compatible_ids
from app.services.distributed_lock import DistributedLockService

OLD, NEW, TYPO = "o" * 16, "n" * 16, "t" * 16
SECRET = "s" * 16
NOW = datetime.now(timezone.utc)


def _view(
    id: str,
    primary: str,
    decrypts: tuple[str, ...] = (),
    *,
    role: str = "worker",
    secret: str = SECRET,
    live: bool = True,
    **overrides: object,
) -> InstanceView:
    beat = NOW if live else NOW - timedelta(minutes=10)
    base = dict(
        id=id,
        name=id,
        role=role,
        enabled=True,
        weight=50,
        weight_configured=True,
        version="1.0.0",
        schema_revision="152_encryption_key_rotation",
        keys_fingerprint=primary + secret,
        docker_ok=True,
        db_latency_ms=1.0,
        heartbeat_at=beat,
        credentials_synced_at=beat,
        decrypt_fingerprints=decrypts or (primary,),
    )
    base.update(overrides)
    return InstanceView(**base)  # type: ignore[arg-type]


def _main(primary: str, decrypts: tuple[str, ...] = (), **kw: object) -> InstanceView:
    return _view("main", primary, decrypts, role="main", **kw)


class RotationPhaseTests(unittest.TestCase):
    def test_without_a_rotation_the_rule_is_an_exact_match(self) -> None:
        instances = [_main(OLD), _view("w1", OLD), _view("w2", NEW)]

        self.assertEqual(compatible_ids(instances, now=NOW), {"main", "w1"})

    def test_phase_1_a_mixed_fleet_stays_eligible(self) -> None:
        # Some instances rolled to (OLD, extra NEW), others not yet: nothing writes NEW.
        instances = [_main(OLD, (OLD, NEW)), _view("w1", OLD), _view("w2", OLD, (OLD, NEW))]

        self.assertEqual(compatible_ids(instances, now=NOW), {"main", "w1", "w2"})

    def test_phase_2_a_worker_that_skipped_phase_1_is_excluded(self) -> None:
        # main hasn't rolled yet, so w1 matches main; but w2 already writes NEW.
        instances = [_main(OLD, (OLD, NEW)), _view("w1", OLD), _view("w2", NEW, (NEW, OLD))]

        self.assertEqual(compatible_ids(instances, now=NOW), {"main", "w2"})

    def test_phase_2_complete_fleet(self) -> None:
        instances = [_main(NEW, (NEW, OLD)), _view("w1", NEW, (NEW, OLD)), _view("w2", NEW)]

        self.assertEqual(compatible_ids(instances, now=NOW), {"main", "w1", "w2"})

    def test_a_stopped_writer_doesnt_exclude_anyone(self) -> None:
        instances = [_main(OLD, (OLD, NEW)), _view("w1", OLD), _view("w2", NEW, live=False)]

        self.assertIn("w1", compatible_ids(instances, now=NOW))


class AnchoredOnMainTests(unittest.TestCase):
    def test_a_typo_in_a_workers_key_excludes_only_that_worker(self) -> None:
        instances = [_main(OLD), _view("w1", OLD), _view("typo", TYPO)]

        self.assertEqual(compatible_ids(instances, now=NOW), {"main", "w1"})

    def test_main_never_drops_out(self) -> None:
        # Three primaries at once: w1 and w2 each fail on the other, main stays.
        instances = [
            _main(OLD, (OLD, NEW, TYPO)),
            _view("w1", NEW, (NEW, OLD)),
            _view("w2", TYPO, (TYPO, OLD)),
        ]

        self.assertEqual(compatible_ids(instances, now=NOW), {"main"})

    def test_secret_key_must_still_match_exactly(self) -> None:
        instances = [_main(OLD), _view("w1", OLD, secret="x" * 16)]

        self.assertEqual(compatible_ids(instances, now=NOW), {"main"})

    def test_an_instance_from_before_key_rotation_decrypts_with_its_primary(self) -> None:
        legacy = _view("w1", OLD, decrypt_fingerprints=())

        self.assertTrue(registry.can_decrypt(legacy, OLD))
        self.assertFalse(registry.can_decrypt(legacy, NEW))

    def test_no_main_means_no_one(self) -> None:
        self.assertEqual(compatible_ids([_view("w1", OLD)], now=NOW), set())

    def test_dispatch_uses_the_rule(self) -> None:
        instances = [_main(OLD, (OLD, NEW)), _view("w1", OLD), _view("w2", NEW, (NEW, OLD))]

        pool = [i.id for i in candidate_instances(instances, now=NOW)]

        self.assertEqual(pool, ["main", "w2"])


class MayLeadTests(unittest.IsolatedAsyncioTestCase):
    async def _may_lead(self, own: str, instances: list[InstanceView]) -> bool:
        with (
            patch.object(registry.settings, "cluster_enabled", True),
            patch.object(registry.identity, "instance_id", return_value=own),
            patch.object(registry, "list_instances", AsyncMock(return_value=instances)),
        ):
            return await registry.may_lead()

    async def test_outside_cluster_mode_anyone_leads(self) -> None:
        with patch.object(registry.settings, "cluster_enabled", False):
            self.assertTrue(await registry.may_lead())

    async def test_an_instance_without_a_heartbeat_row_cant_lead(self) -> None:
        self.assertFalse(await self._may_lead("w9", [_main(OLD)]))

    async def test_an_incompatible_worker_cant_lead(self) -> None:
        instances = [_main(OLD, (OLD, NEW)), _view("w1", OLD), _view("w2", NEW, (NEW, OLD))]

        self.assertFalse(await self._may_lead("w1", instances))
        self.assertTrue(await self._may_lead("w2", instances))

    async def test_weight_and_enabled_dont_matter(self) -> None:
        # A main kept at weight 0 for the UI, and a disabled worker, can still lead.
        instances = [_main(OLD, weight=0), _view("w1", OLD, enabled=False)]

        self.assertTrue(await self._may_lead("main", instances))
        self.assertTrue(await self._may_lead("w1", instances))

    async def test_a_worker_leads_while_main_is_down(self) -> None:
        instances = [_main(OLD, live=False), _view("w1", OLD)]

        self.assertTrue(await self._may_lead("w1", instances))


class LeaderLoopTests(unittest.IsolatedAsyncioTestCase):
    async def _one_pass(self, service: DistributedLockService) -> None:
        async def stop_after_one_sleep(_seconds: float) -> None:
            service._running = False

        service._running = True
        with patch("app.services.distributed_lock.asyncio.sleep", stop_after_one_sleep):
            await service._leader_election_loop()

    async def test_an_ineligible_process_doesnt_try_the_lock(self) -> None:
        service = DistributedLockService()
        service.set_eligibility(AsyncMock(return_value=False))
        service._try_acquire_leader_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]

        await self._one_pass(service)

        service._try_acquire_leader_lock.assert_not_awaited()
        self.assertFalse(service.is_leader)

    async def test_an_eligible_process_takes_the_lock(self) -> None:
        service = DistributedLockService()
        service.set_eligibility(AsyncMock(return_value=True))
        service._try_acquire_leader_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]

        await self._one_pass(service)

        self.assertTrue(service.is_leader)

    async def test_a_leader_that_becomes_ineligible_lets_go(self) -> None:
        service = DistributedLockService()
        service._is_leader = True
        service._check_leader_lock_valid = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service._release_leader_session = AsyncMock()  # type: ignore[method-assign]
        service.set_eligibility(AsyncMock(return_value=False))

        await self._one_pass(service)

        service._release_leader_session.assert_awaited_once()

    async def test_a_failed_check_keeps_a_leader_and_blocks_a_follower(self) -> None:
        leader = DistributedLockService()
        leader._is_leader = True
        leader._check_leader_lock_valid = AsyncMock(return_value=True)  # type: ignore[method-assign]
        leader._release_leader_session = AsyncMock()  # type: ignore[method-assign]
        leader.set_eligibility(AsyncMock(side_effect=RuntimeError("db blip")))
        await self._one_pass(leader)
        leader._release_leader_session.assert_not_awaited()

        follower = DistributedLockService()
        follower.set_eligibility(AsyncMock(side_effect=RuntimeError("db blip")))
        follower._try_acquire_leader_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
        await self._one_pass(follower)
        follower._try_acquire_leader_lock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
