"""The admission rule, held-row shape, status mapping and token comparison."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from app.services.cluster import run_queue
from app.services.secret_tokens import hash_secret
from app.services.workflow_concurrency import (
    Admission,
    ConcurrencySettings,
    HeldRun,
    QueueInfo,
    decide_admission,
    held_expires_at,
    held_values,
    history_view,
    queued_body,
    status_token_matches,
    status_view,
)


def _cfg(
    limit: int | None = 1, max_queue: int | None = None, max_wait: int | None = None
) -> ConcurrencySettings:
    return ConcurrencySettings(limit=limit, max_queue=max_queue, max_wait_seconds=max_wait)


class DecideAdmissionTests(unittest.TestCase):
    def test_no_limit_means_unlimited(self) -> None:
        self.assertEqual(
            decide_admission(_cfg(limit=None), running=9, waiting=9, has_slot=False), "unlimited"
        )

    def test_a_free_slot_with_an_empty_queue_admits(self) -> None:
        self.assertEqual(
            decide_admission(_cfg(2), running=1, waiting=0, has_slot=False), "admitted"
        )

    def test_a_full_limit_queues(self) -> None:
        self.assertEqual(decide_admission(_cfg(1), running=1, waiting=0, has_slot=False), "queued")

    def test_nobody_overtakes_a_held_run(self) -> None:
        """FIFO: a slot that just freed belongs to the head of the queue."""
        self.assertEqual(decide_admission(_cfg(2), running=1, waiting=1, has_slot=False), "queued")

    def test_a_full_queue_rejects(self) -> None:
        self.assertEqual(
            decide_admission(_cfg(1, max_queue=2), running=1, waiting=2, has_slot=False),
            "queue_full",
        )

    def test_an_existing_slot_is_admitted_again(self) -> None:
        """Recovery re-runs reuse their execution id and keep the slot."""
        self.assertEqual(decide_admission(_cfg(1), running=1, waiting=3, has_slot=True), "admitted")


class HeldValuesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run = HeldRun(
            workflow_id=uuid.uuid4(),
            execution_id=uuid.uuid4(),
            placement="anywhere",
            inputs={"body": {"x": 1}},
            trigger_source="API",
            actor_user_id=uuid.uuid4(),
            credentials_owner_id=uuid.uuid4(),
            run_options={"run_error_workflow": True},
        )
        self.now = datetime.now(timezone.utc)

    def test_a_held_row_has_no_target_and_is_held(self) -> None:
        values = held_values(self.run, cfg=_cfg(1), now=self.now, token=None)
        self.assertEqual(values["status"], run_queue.STATUS_HELD)
        self.assertIsNone(values["target_instance_id"])
        self.assertFalse(values["test_run"])

    def test_the_token_is_stored_only_as_a_digest(self) -> None:
        values = held_values(self.run, cfg=_cfg(1), now=self.now, token="plain-token")
        self.assertEqual(values["status_token_hash"], hash_secret("plain-token"))
        self.assertNotIn("plain-token", repr(values))

    def test_a_held_row_never_carries_a_resolved_credential(self) -> None:
        values = held_values(self.run, cfg=_cfg(1), now=self.now, token=None)
        self.assertNotIn("credentials_context", values)
        self.assertEqual(values["credentials_owner_id"], self.run.credentials_owner_id)

    def test_expiry_follows_max_wait(self) -> None:
        self.assertIsNone(held_expires_at(_cfg(1), self.now))
        self.assertEqual(
            held_expires_at(_cfg(1, max_wait=30), self.now), self.now + timedelta(seconds=30)
        )


class StatusTokenTests(unittest.TestCase):
    def test_the_plaintext_matches_its_digest(self) -> None:
        self.assertTrue(status_token_matches(hash_secret("abc"), "abc"))

    def test_the_stored_digest_is_not_a_token(self) -> None:
        digest = hash_secret("abc")
        self.assertFalse(status_token_matches(digest, digest))

    def test_missing_values_never_match(self) -> None:
        self.assertFalse(status_token_matches(None, "abc"))
        self.assertFalse(status_token_matches(hash_secret("abc"), None))


class StatusViewTests(unittest.TestCase):
    def test_held_reads_as_queued(self) -> None:
        view = status_view(row_status="held", result=None, error=None)
        self.assertEqual(view["status"], "queued")

    def test_in_flight_rows_read_as_running(self) -> None:
        for status in ("queued", "waiting_for_main", "claimed"):
            with self.subTest(status=status):
                view = status_view(row_status=status, result=None, error=None)
                self.assertEqual(view["status"], "running")

    def test_a_done_row_reports_the_run_status_and_outputs(self) -> None:
        view = status_view(
            row_status="done",
            result={"status": "success", "outputs": {"a": 1}, "execution_time_ms": 12.0},
            error=None,
        )
        self.assertEqual(
            view,
            {"status": "success", "outputs": {"a": 1}, "error": None, "execution_time_ms": 12.0},
        )

    def test_an_expired_row_says_why(self) -> None:
        view = status_view(
            row_status="expired",
            result={
                "status": "expired",
                "outputs": {"error": "waited too long"},
                "execution_time_ms": 0.0,
            },
            error=None,
        )
        self.assertEqual(view["status"], "expired")
        self.assertEqual(view["error"], "waited too long")

    def test_a_failed_row_is_an_error(self) -> None:
        view = status_view(row_status="failed", result=None, error="boom")
        self.assertEqual((view["status"], view["error"]), ("error", "boom"))

    def test_history_view_reads_the_error_from_outputs(self) -> None:
        view = history_view(status="error", outputs={"error": "bad"}, execution_time_ms=3.0)
        self.assertEqual((view["status"], view["error"]), ("error", "bad"))


class QueuedBodyTests(unittest.TestCase):
    def test_the_body_names_the_status_url_and_queue(self) -> None:
        workflow_id, execution_id = uuid.uuid4(), uuid.uuid4()
        admission = Admission(
            kind="queued",
            execution_id=execution_id,
            queue=QueueInfo(position=2, size=5, running=1, limit=1),
            status_token="tok",
        )
        body = queued_body(admission, workflow_id=workflow_id, base_url="https://h.example")
        self.assertEqual(body["status"], "queued")
        self.assertEqual(
            body["status_url"],
            f"https://h.example/api/workflows/{workflow_id}/executions/{execution_id}/status",
        )
        self.assertEqual(body["queue"], {"position": 2, "size": 5, "running": 1, "limit": 1})
        self.assertEqual(body["status_token"], "tok")

    def test_no_token_key_without_a_token(self) -> None:
        admission = Admission(kind="queued", execution_id=uuid.uuid4(), queue=QueueInfo(1, 1, 1, 1))
        body = queued_body(admission, workflow_id=uuid.uuid4(), base_url="https://h.example")
        self.assertNotIn("status_token", body)


class RunQueueStatusTests(unittest.TestCase):
    def test_expired_and_cancelled_are_terminal_and_held_is_not(self) -> None:
        self.assertTrue(run_queue.is_terminal(run_queue.STATUS_EXPIRED))
        self.assertTrue(run_queue.is_terminal(run_queue.STATUS_CANCELLED))
        self.assertFalse(run_queue.is_terminal(run_queue.STATUS_HELD))
