"""Optimistic concurrency on workflow updates (`base_updated_at` -> 409)."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.workflows import _reject_stale_update


def _workflow(updated_at: datetime | None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), updated_at=updated_at)


class RejectStaleUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stored_at = datetime(2026, 7, 22, 8, 30, tzinfo=timezone.utc)

    def test_no_base_revision_is_an_explicit_override(self) -> None:
        # The "Override" button omits the base so the write always lands.
        _reject_stale_update(_workflow(self.stored_at), None)

    def test_same_revision_is_accepted(self) -> None:
        _reject_stale_update(_workflow(self.stored_at), self.stored_at)

    def test_newer_base_revision_is_accepted(self) -> None:
        # This tab wrote after it loaded, so its base is ahead of nothing stored newer.
        _reject_stale_update(_workflow(self.stored_at), self.stored_at + timedelta(seconds=5))

    def test_stale_base_revision_is_rejected_with_the_server_revision(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _reject_stale_update(_workflow(self.stored_at), self.stored_at - timedelta(seconds=1))

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["updated_at"], self.stored_at.isoformat())

    def test_naive_stored_timestamp_is_compared_as_utc(self) -> None:
        # SQLite/older rows can hand back naive datetimes; comparing them must not raise.
        naive = self.stored_at.replace(tzinfo=None)
        with self.assertRaises(HTTPException):
            _reject_stale_update(_workflow(naive), self.stored_at - timedelta(seconds=1))
        _reject_stale_update(_workflow(naive), self.stored_at)

    def test_missing_stored_timestamp_is_not_a_conflict(self) -> None:
        _reject_stale_update(_workflow(None), self.stored_at)


class WorkflowUpdateSchemaTests(unittest.TestCase):
    def test_base_updated_at_defaults_to_none(self) -> None:
        from app.models.schemas import WorkflowUpdate

        self.assertIsNone(WorkflowUpdate().base_updated_at)

    def test_base_updated_at_parses_an_iso_string(self) -> None:
        from app.models.schemas import WorkflowUpdate

        payload = WorkflowUpdate(base_updated_at="2026-07-22T08:30:00+00:00")
        self.assertEqual(payload.base_updated_at, datetime(2026, 7, 22, 8, 30, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
