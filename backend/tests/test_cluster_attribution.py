"""What the executing instance stamps onto a run's history row."""

import unittest
import uuid
from unittest.mock import patch

from app.services.cluster import identity
from app.services.cluster.attribution import attribution_fields


class AttributionTests(unittest.TestCase):
    def test_a_clustered_run_records_id_and_name(self) -> None:
        with (
            patch.object(identity.settings, "cluster_enabled", True),
            patch.object(identity.settings, "instance_id", "worker-a"),
            patch.object(identity.settings, "instance_name", "Worker A"),
        ):
            fields = attribution_fields()
        self.assertEqual(fields["executed_by_instance_id"], "worker-a")
        self.assertEqual(fields["executed_by_instance_name"], "Worker A")

    def test_a_single_instance_run_records_nothing(self) -> None:
        """History on a single-instance install must look exactly as it does today."""
        with patch.object(identity.settings, "cluster_enabled", False):
            fields = attribution_fields()
        self.assertIsNone(fields["executed_by_instance_id"])
        self.assertIsNone(fields["executed_by_instance_name"])

    def test_the_name_is_a_snapshot_not_a_reference(self) -> None:
        """Renaming an instance later must not rewrite old history."""
        with (
            patch.object(identity.settings, "cluster_enabled", True),
            patch.object(identity.settings, "instance_id", "worker-a"),
            patch.object(identity.settings, "instance_name", "Old Name"),
        ):
            first = attribution_fields()
        with (
            patch.object(identity.settings, "cluster_enabled", True),
            patch.object(identity.settings, "instance_id", "worker-a"),
            patch.object(identity.settings, "instance_name", "New Name"),
        ):
            second = attribution_fields()
        self.assertEqual(first["executed_by_instance_name"], "Old Name")
        self.assertEqual(second["executed_by_instance_name"], "New Name")

    def test_the_fields_match_the_history_columns(self) -> None:
        """A typo here would silently drop attribution at the ORM boundary."""
        from app.db.models import ExecutionHistory

        for key in attribution_fields():
            self.assertIn(key, ExecutionHistory.__table__.columns)

    def test_clustered_main_stamps_unattributed_history_rows(self) -> None:
        """Every in-process execution records the main instance once clustering is enabled."""
        from app.db.models import ExecutionHistory, stamp_execution_history_attribution

        history = ExecutionHistory(workflow_id=uuid.uuid4(), status="success")
        with (
            patch.object(identity.settings, "cluster_enabled", True),
            patch.object(identity.settings, "instance_id", "main"),
            patch.object(identity.settings, "instance_name", "Mini"),
        ):
            stamp_execution_history_attribution(None, None, history)

        self.assertEqual(history.executed_by_instance_id, "main")
        self.assertEqual(history.executed_by_instance_name, "Mini")
