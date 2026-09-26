"""Enqueue shape, expiry, and the guarantee that no credential is stored."""

import contextlib
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.cluster.run_queue import (
    STATUS_QUEUED,
    STATUS_SKIPPED_LATE,
    STATUS_WAITING_FOR_MAIN,
    QueuedRun,
    build_queue_values,
    is_expired,
    is_stranded_claim,
    next_status,
)


class StatusTests(unittest.TestCase):
    def test_a_targeted_run_is_queued(self) -> None:
        self.assertEqual(next_status(target_instance_id="worker-a"), STATUS_QUEUED)

    def test_a_run_with_no_target_waits_for_main(self) -> None:
        self.assertEqual(next_status(target_instance_id=None), STATUS_WAITING_FOR_MAIN)


class ExpiryTests(unittest.TestCase):
    def test_a_row_inside_the_grace_window_is_not_expired(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertFalse(is_expired(not_after=now + timedelta(seconds=1), now=now))

    def test_a_row_past_the_grace_window_is_expired(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertTrue(is_expired(not_after=now - timedelta(seconds=1), now=now))

    def test_the_expired_status_names_the_reason(self) -> None:
        self.assertEqual(STATUS_SKIPPED_LATE, "skipped_late")


class QueueValueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run = QueuedRun(
            workflow_id=uuid.uuid4(),
            execution_id=uuid.uuid4(),
            placement="anywhere",
            inputs={"body": {"x": 1}},
            trigger_source="API",
            actor_user_id=uuid.uuid4(),
            credentials_owner_id=uuid.uuid4(),
            test_run=False,
            timeout_seconds=None,
            return_on_chart_output=False,
        )

    def test_values_carry_the_credentials_owner_not_a_context(self) -> None:
        values = build_queue_values(self.run, target_instance_id="worker-a", grace_seconds=600)
        self.assertEqual(values["credentials_owner_id"], self.run.credentials_owner_id)

    def test_values_never_contain_a_resolved_credential(self) -> None:
        """A queue row is readable by anything with database access."""
        values = build_queue_values(self.run, target_instance_id="worker-a", grace_seconds=600)
        self.assertNotIn("credentials_context", values)
        self.assertNotIn("credentials", values)

    def test_not_after_is_the_grace_window_from_now(self) -> None:
        values = build_queue_values(self.run, target_instance_id="worker-a", grace_seconds=600)
        delta = values["not_after"] - values["enqueued_at"]
        self.assertAlmostEqual(delta.total_seconds(), 600, delta=1)

    def test_a_run_with_no_target_is_stored_as_waiting(self) -> None:
        values = build_queue_values(self.run, target_instance_id=None, grace_seconds=600)
        self.assertEqual(values["status"], STATUS_WAITING_FOR_MAIN)
        self.assertIsNone(values["target_instance_id"])

    def test_values_preserve_chart_early_return_behavior(self) -> None:
        run = replace(self.run, return_on_chart_output=True)
        values = build_queue_values(run, target_instance_id="worker-a", grace_seconds=600)
        self.assertTrue(values["return_on_chart_output"])


class StrandedClaimTests(unittest.TestCase):
    """A claimed row whose runner died must not sit there forever.

    Expiring on age alone would kill legitimately long runs, so the deciding
    signal is the active-execution row: while a run is really executing, one
    exists and is heartbeating. Once it is gone the queue row is bookkeeping for
    a run nobody is doing - and orphan recovery, not the queue, owns re-running
    it, so the row is retired rather than requeued.
    """

    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)

    def test_a_running_claim_is_left_alone(self) -> None:
        self.assertFalse(
            is_stranded_claim(
                claimed_at=self.now - timedelta(hours=2),
                has_active_execution=True,
                now=self.now,
                grace_seconds=60,
            )
        )

    def test_a_claim_with_no_active_execution_is_stranded(self) -> None:
        self.assertTrue(
            is_stranded_claim(
                claimed_at=self.now - timedelta(seconds=61),
                has_active_execution=False,
                now=self.now,
                grace_seconds=60,
            )
        )

    def test_a_fresh_claim_is_never_stranded(self) -> None:
        """Claiming and registering the execution are not one atomic step."""
        self.assertFalse(
            is_stranded_claim(
                claimed_at=self.now - timedelta(seconds=1),
                has_active_execution=False,
                now=self.now,
                grace_seconds=60,
            )
        )

    def test_a_missing_claim_time_is_not_stranded(self) -> None:
        self.assertFalse(
            is_stranded_claim(
                claimed_at=None, has_active_execution=False, now=self.now, grace_seconds=60
            )
        )


def _instance(instance_id: str, *, role: str, weight: int, version: str = "1.0.0", **over: object):
    from app.services.cluster.registry import InstanceView

    fields: dict = dict(
        id=instance_id,
        name=instance_id,
        role=role,
        enabled=True,
        weight=weight,
        weight_configured=True,
        version=version,
        schema_revision="rev",
        keys_fingerprint="fp",
        docker_ok=True,
        db_latency_ms=1.0,
        heartbeat_at=datetime.now(timezone.utc),
    )
    fields.update(over)
    return InstanceView(**fields)


class ChooseTargetTests(unittest.IsolatedAsyncioTestCase):
    """The 70/30 split must survive a worker being away and coming back.

    Counters are lifetime totals, so a worker that spent a night Offline or on a
    mismatched version used to return owed every run it missed and take them all
    back-to-back - a 70/30 cluster running 0/100 for thousands of runs.
    """

    def setUp(self) -> None:
        self.state = SimpleNamespace(counters={})
        self.instances: list = []

    @contextlib.contextmanager
    def _patched(self):
        session = MagicMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: self.state)
        )

        @contextlib.asynccontextmanager
        async def maker():
            yield session

        with (
            patch("app.services.cluster.run_queue.async_session_maker", maker),
            patch(
                "app.services.cluster.run_queue.registry.list_instances",
                AsyncMock(side_effect=lambda **_kw: list(self.instances)),
            ),
        ):
            yield

    async def _dispatch(self, count: int, placement: str = "anywhere") -> dict[str, int]:
        from app.services.cluster.run_queue import choose_target

        taken: dict[str, int] = {}
        with self._patched():
            for _ in range(count):
                target = await choose_target(placement)
                taken[target] = taken.get(target, 0) + 1
        return taken

    async def test_a_worker_that_rejoins_after_a_mismatch_does_not_take_every_run(self) -> None:
        self.instances = [
            _instance("main", role="main", weight=70),
            _instance("worker", role="worker", weight=30, version="0.9.0"),
        ]
        away = await self._dispatch(200)
        self.assertEqual(away, {"main": 200})

        self.instances = [
            _instance("main", role="main", weight=70),
            _instance("worker", role="worker", weight=30),
        ]
        back = await self._dispatch(100)
        self.assertEqual(back, {"main": 70, "worker": 30})

    async def test_a_stretch_of_main_only_work_does_not_stale_an_absent_counter(self) -> None:
        """The counter of an away worker must be forgotten on any dispatch."""
        self.instances = [
            _instance("main", role="main", weight=70),
            _instance("worker", role="worker", weight=30),
        ]
        await self._dispatch(10)
        self.instances[1] = _instance("worker", role="worker", weight=30, version="0.9.0")
        await self._dispatch(200, placement="main_only")

        self.instances[1] = _instance("worker", role="worker", weight=30)
        back = await self._dispatch(100)
        self.assertEqual(back, {"main": 70, "worker": 30})

    async def test_main_only_work_still_spends_mains_quota(self) -> None:
        """The catch-up that makes main's percentage a ceiling is preserved."""
        self.instances = [
            _instance("main", role="main", weight=70),
            _instance("worker", role="worker", weight=30),
        ]
        await self._dispatch(30, placement="main_only")
        after = await self._dispatch(70)
        self.assertEqual(after, {"main": 40, "worker": 30})

    async def test_an_offline_worker_receives_nothing_and_rejoins_level(self) -> None:
        stale = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.instances = [
            _instance("main", role="main", weight=70),
            _instance("worker", role="worker", weight=30, heartbeat_at=stale),
        ]
        self.assertEqual(await self._dispatch(500), {"main": 500})

        self.instances[1] = _instance("worker", role="worker", weight=30)
        self.assertEqual(await self._dispatch(100), {"main": 70, "worker": 30})


class ExpireLateRowsTests(unittest.IsolatedAsyncioTestCase):
    async def test_expire_late_rows_atomically_cleans_active_workflow_executions(self) -> None:
        from app.services.cluster.run_queue import expire_late_rows

        ex_id_1 = uuid.uuid4()
        ex_id_2 = uuid.uuid4()

        update_result = MagicMock()
        update_result.all.return_value = [(ex_id_1,), (ex_id_2,)]

        executed_stmts = []

        async def fake_execute(stmt):
            executed_stmts.append(stmt)
            return update_result

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)
        session.commit = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.cluster.run_queue.async_session_maker", return_value=cm):
            count = await expire_late_rows()

        self.assertEqual(count, 2)
        self.assertEqual(len(executed_stmts), 2)
        session.commit.assert_awaited_once()

    async def test_expire_late_rows_no_expired_rows_does_not_call_delete(self) -> None:
        from app.services.cluster.run_queue import expire_late_rows

        update_result = MagicMock()
        update_result.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=update_result)
        session.commit = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.cluster.run_queue.async_session_maker", return_value=cm):
            count = await expire_late_rows()

        self.assertEqual(count, 0)
        session.execute.assert_awaited_once()
        session.commit.assert_awaited_once()
