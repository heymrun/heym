"""The node analytics marker and rollup table, as the models and migration 148 declare them."""

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

from app.db.models import ExecutionHistory, NodeAnalyticsSnapshot

_MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "148_node_analytics.py"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_148_node_analytics", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NodeAnalyticsModelTests(unittest.TestCase):
    def test_new_history_rows_start_pending(self) -> None:
        column = ExecutionHistory.__table__.c.node_analytics_pending
        self.assertFalse(column.nullable)
        self.assertIs(column.default.arg, True)

    def test_snapshot_scope_is_unique_per_workflow_type_and_hour(self) -> None:
        constraint = next(
            c
            for c in NodeAnalyticsSnapshot.__table__.constraints
            if c.name == "uq_node_analytics_snapshot_scope"
        )
        self.assertEqual(
            [column.name for column in constraint.columns],
            ["workflow_id", "node_type", "bucket_start"],
        )

    def test_snapshots_go_with_their_workflow(self) -> None:
        fk = next(iter(NodeAnalyticsSnapshot.__table__.c.workflow_id.foreign_keys))
        self.assertEqual(fk.ondelete, "CASCADE")


class NodeAnalyticsMigrationTests(unittest.TestCase):
    def test_existing_rows_read_counted_and_new_rows_start_pending(self) -> None:
        migration = _load_migration()
        op = MagicMock()
        migration.op = op

        migration.upgrade()

        added = op.add_column.call_args
        self.assertEqual(added.args[0], "execution_history")
        self.assertEqual(str(added.args[1].server_default.arg), "false")
        altered = op.alter_column.call_args
        self.assertEqual(altered.args[:2], ("execution_history", "node_analytics_pending"))
        self.assertEqual(str(altered.kwargs["server_default"]), "true")
        names = [call[0] for call in op.method_calls]
        self.assertLess(names.index("add_column"), names.index("alter_column"))

    def test_pending_index_is_built_concurrently_outside_the_transaction(self) -> None:
        migration = _load_migration()
        op = MagicMock()
        migration.op = op

        migration.upgrade()

        op.get_context.return_value.autocommit_block.assert_called_once()
        pending_index = next(
            call
            for call in op.create_index.call_args_list
            if call.args[0] == "ix_execution_history_node_analytics_pending"
        )
        self.assertTrue(pending_index.kwargs["postgresql_concurrently"])
        self.assertEqual(str(pending_index.kwargs["postgresql_where"]), "node_analytics_pending")
