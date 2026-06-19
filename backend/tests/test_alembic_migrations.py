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
        self.assertEqual(self.script.get_heads(), ["080_merge_github_supabase_heads"])

    def test_github_and_supabase_revisions_are_merged(self) -> None:
        merge_revision = self.script.get_revision("080_merge_github_supabase_heads")

        self.assertIsNotNone(merge_revision)
        self.assertEqual(
            set(merge_revision.down_revision),
            {"077_add_github_credential_type", "079_add_supabase_credential_type"},
        )
