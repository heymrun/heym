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
        self.assertEqual(self.script.get_heads(), ["088_error_wf_time_saved"])

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
