"""The instance filter on the per-workflow history endpoint."""

import unittest
import uuid

from sqlalchemy import select

from app.api.workflows import apply_instance_filter, filters_to_workflow_runs
from app.db.models import ExecutionHistory


class InstanceFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = select(ExecutionHistory).where(ExecutionHistory.workflow_id == uuid.uuid4())

    def test_no_instance_leaves_the_query_untouched(self) -> None:
        self.assertIs(apply_instance_filter(self.base, None), self.base)

    def test_an_empty_instance_leaves_the_query_untouched(self) -> None:
        self.assertIs(apply_instance_filter(self.base, "   "), self.base)

    def test_an_instance_id_adds_a_where_clause(self) -> None:
        filtered = apply_instance_filter(self.base, "worker-a")
        self.assertIn("executed_by_instance_id", str(filtered))

    def test_the_filter_matches_on_id_not_name(self) -> None:
        """Names are snapshots and can repeat; ids cannot.

        Asserted against the WHERE clause, not the rendered statement: every
        column appears in the SELECT list regardless of what is filtered.
        """
        where = str(apply_instance_filter(self.base, "worker-a").whereclause)
        self.assertIn("executed_by_instance_id", where)
        self.assertNotIn("executed_by_instance_name", where)

    def test_surrounding_whitespace_is_trimmed(self) -> None:
        filtered = apply_instance_filter(self.base, "  worker-a  ")
        self.assertIn("executed_by_instance_id", str(filtered))

    def test_an_unresolved_query_default_is_not_a_filter(self) -> None:
        """Calling the endpoint function directly leaves FastAPI's Query object in place."""
        from fastapi import Query

        self.assertIs(apply_instance_filter(self.base, Query(default=None)), self.base)


class AllHistoryScopeTests(unittest.TestCase):
    def test_an_instance_filter_excludes_non_workflow_runs(self) -> None:
        """Chat and assistant runs have no instance; counting them would be wrong."""
        self.assertTrue(filters_to_workflow_runs("worker-a"))

    def test_no_instance_filter_keeps_them(self) -> None:
        self.assertFalse(filters_to_workflow_runs(None))
        self.assertFalse(filters_to_workflow_runs("   "))

    def test_an_unresolved_query_default_keeps_them(self) -> None:
        from fastapi import Query

        self.assertFalse(filters_to_workflow_runs(Query(default=None)))
