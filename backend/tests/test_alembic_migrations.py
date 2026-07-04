"""Tests for the Alembic revision graph."""

import unittest
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


class AlembicMigrationGraphTest(unittest.TestCase):
    def setUp(self) -> None:
        backend_dir = Path(__file__).resolve().parents[1]
        config = Config(backend_dir / "alembic.ini")
        config.set_main_option("script_location", str(backend_dir / "alembic"))
        self.script = ScriptDirectory.from_config(config)

    def test_revision_graph_has_one_head(self) -> None:
        self.assertEqual(self.script.get_heads(), ["092_add_sentry_credential_type"])

    def test_plugins_revision_follows_workflow_timeout(self) -> None:
        plugins_revision = self.script.get_revision("090_add_plugins_table")

        self.assertIsNotNone(plugins_revision)
        self.assertEqual(plugins_revision.down_revision, "089_workflow_timeout")

    def test_dashboard_queue_revision_follows_plugins_revision(self) -> None:
        dashboard_revision = self.script.get_revision("091_dashboard_chat_queue")

        self.assertIsNotNone(dashboard_revision)
        self.assertEqual(dashboard_revision.down_revision, "090_add_plugins_table")

    def test_sentry_revision_follows_dashboard_queue_revision(self) -> None:
        sentry_revision = self.script.get_revision("092_add_sentry_credential_type")

        self.assertIsNotNone(sentry_revision)
        self.assertEqual(sentry_revision.down_revision, "091_dashboard_chat_queue")

    def test_github_and_supabase_revisions_are_merged(self) -> None:
        merge_revision = self.script.get_revision("080_merge_github_supabase_heads")

        self.assertIsNotNone(merge_revision)
        self.assertEqual(
            set(merge_revision.down_revision),
            {"077_add_github_credential_type", "079_add_supabase_credential_type"},
        )

    def test_notion_revision_follows_merged_head(self) -> None:
        notion_revision = self.script.get_revision("081_add_notion_credential_type")

        self.assertIsNotNone(notion_revision)
        self.assertEqual(notion_revision.down_revision, "080_merge_github_supabase_heads")

    def test_notion_and_pgvector_revisions_are_merged(self) -> None:
        merge_revision = self.script.get_revision("082_merge_notion_pgvector_heads")

        self.assertIsNotNone(merge_revision)
        self.assertEqual(
            set(merge_revision.down_revision),
            {"081_add_notion_credential_type", "9cbd3c82d23b"},
        )

    def test_linear_revision_follows_pgvector_head(self) -> None:
        linear_revision = self.script.get_revision("9d1f2a3b4c5d")

        self.assertIsNotNone(linear_revision)
        self.assertEqual(linear_revision.down_revision, "9cbd3c82d23b")

    def test_linear_and_notion_revisions_are_merged(self) -> None:
        merge_revision = self.script.get_revision("083_merge_linear_notion_heads")

        self.assertIsNotNone(merge_revision)
        self.assertEqual(
            set(merge_revision.down_revision),
            {"082_merge_notion_pgvector_heads", "9d1f2a3b4c5d"},
        )
