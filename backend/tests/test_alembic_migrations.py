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
        self.assertEqual(self.script.get_heads(), ["101_add_user_ai_defaults"])

    def test_opencode_revision_follows_board_shares(self) -> None:
        opencode_revision = self.script.get_revision("100_add_opencode_credential_type")

        self.assertIsNotNone(opencode_revision)
        self.assertEqual(opencode_revision.down_revision, "099_add_board_shares")

    def test_user_ai_defaults_revision_follows_opencode(self) -> None:
        ai_defaults_revision = self.script.get_revision("101_add_user_ai_defaults")

        self.assertIsNotNone(ai_defaults_revision)
        self.assertEqual(ai_defaults_revision.down_revision, "100_add_opencode_credential_type")

    def test_revision_ids_fit_default_alembic_version_column(self) -> None:
        for revision in self.script.walk_revisions():
            with self.subTest(revision=revision.revision):
                self.assertLessEqual(len(revision.revision), 32)

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

    def test_codex_revision_follows_sentry_revision(self) -> None:
        codex_revision = self.script.get_revision("093_add_codex_node_support")

        self.assertIsNotNone(codex_revision)
        self.assertEqual(codex_revision.down_revision, "092_add_sentry_credential_type")

    def test_jira_revision_follows_codex_revision(self) -> None:
        jira_revision = self.script.get_revision("095_add_jira_credential_type")

        self.assertIsNotNone(jira_revision)
        self.assertEqual(jira_revision.down_revision, "093_add_codex_node_support")

    def test_file_team_shares_revision_follows_codex_revision(self) -> None:
        file_team_shares_revision = self.script.get_revision("094_add_file_team_shares")

        self.assertIsNotNone(file_team_shares_revision)
        self.assertEqual(file_team_shares_revision.down_revision, "093_add_codex_node_support")

    def test_jira_and_file_team_share_heads_are_merged(self) -> None:
        merge_revision = self.script.get_revision("096_merge_jira_file_heads")

        self.assertIsNotNone(merge_revision)
        self.assertEqual(
            set(merge_revision.down_revision),
            {"095_add_jira_credential_type", "094_add_file_team_shares"},
        )

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
