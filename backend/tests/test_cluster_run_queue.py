"""Enqueue shape, expiry, and the guarantee that no credential is stored."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

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
