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
