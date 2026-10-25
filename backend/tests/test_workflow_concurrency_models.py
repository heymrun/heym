"""The concurrency columns and table exist with the shapes the service relies on."""

import unittest

from app.db.models import Workflow, WorkflowConcurrencySlot, WorkflowRunQueue


class ConcurrencyModelTests(unittest.TestCase):
    def test_workflow_has_three_nullable_settings(self) -> None:
        for name in ("concurrency_limit", "concurrency_max_queue", "concurrency_max_wait_seconds"):
            column = Workflow.__table__.c[name]
            self.assertTrue(column.nullable, name)

    def test_slot_is_keyed_by_execution_and_cascades_with_the_workflow(self) -> None:
        table = WorkflowConcurrencySlot.__table__
        self.assertEqual([c.name for c in table.primary_key.columns], ["execution_id"])
        (fk,) = table.c.workflow_id.foreign_keys
        self.assertEqual(fk.ondelete, "CASCADE")

    def test_queue_rows_carry_concurrency_fields(self) -> None:
        columns = WorkflowRunQueue.__table__.c
        for name in ("concurrency_seq", "expires_at", "status_token_hash", "run_options"):
            self.assertTrue(columns[name].nullable, name)
