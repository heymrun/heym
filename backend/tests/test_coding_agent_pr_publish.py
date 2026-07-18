import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.services.coding_agent import pr_publish


class TestPrPublishHelpers(unittest.TestCase):
    def test_clone_url_injects_token(self):
        self.assertEqual(
            pr_publish.clone_url_with_token(
                "https://github.com/acme/repo.git", {"api_key": "ghp_secret"}
            ),
            "https://x-access-token:ghp_secret@github.com/acme/repo.git",
        )

    def test_clone_url_no_token_unchanged(self):
        self.assertEqual(
            pr_publish.clone_url_with_token("https://github.com/acme/repo.git", {}),
            "https://github.com/acme/repo.git",
        )

    def test_clone_url_skips_when_userinfo_present(self):
        original = "https://user@github.com/acme/repo.git"
        self.assertEqual(pr_publish.clone_url_with_token(original, {"api_key": "x"}), original)

    def test_parse_owner_repo(self):
        self.assertEqual(
            pr_publish.parse_github_owner_repo("https://github.com/acme/repo.git"), ("acme", "repo")
        )

    def test_parse_owner_repo_rejects_short(self):
        with self.assertRaises(ValueError):
            pr_publish.parse_github_owner_repo("https://github.com/acme")

    def test_mask_sensitive(self):
        self.assertEqual(pr_publish.mask_sensitive("token=abc", ["abc"]), "token=[masked]")

    def test_git_identity_args(self):
        self.assertEqual(
            pr_publish.git_identity_args("Heym Codex", "support@heym.run"),
            ["-c", "user.name=Heym Codex", "-c", "user.email=support@heym.run"],
        )

    def test_commit_title_prefers_pr_title(self):
        self.assertEqual(
            pr_publish.commit_title("Add feature", "ignored", fallback="fb"), "Add feature"
        )

    def test_commit_title_first_sentence(self):
        self.assertEqual(
            pr_publish.commit_title("", "Fix the bug. More detail.", fallback="fb"), "Fix the bug."
        )

    def test_commit_title_fallback(self):
        self.assertEqual(pr_publish.commit_title("", "", fallback="Apply changes"), "Apply changes")

    def test_pr_number_from_url(self):
        self.assertEqual(pr_publish.pr_number_from_url("https://github.com/a/b/pull/42"), 42)
        self.assertIsNone(pr_publish.pr_number_from_url("https://github.com/a/b"))

    def test_inject_screenshot_markdown_appends(self):
        out = pr_publish.inject_screenshot_markdown("Body", [("a.png", "http://x/a.png")])
        self.assertIn("## Screenshots", out)
        self.assertIn("![a.png](http://x/a.png)", out)

    def test_discover_finds_untracked_e2e_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            shot = workspace / "frontend" / ".e2e-artifacts" / "ui.png"
            shot.parent.mkdir(parents=True)
            shot.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            found = pr_publish.discover_pr_screenshots(workspace, lambda _cmd, _ws: "")
            self.assertEqual([p.resolve() for p in found], [shot.resolve()])

    def test_upload_and_inject_uses_gh(self):
        gh = MagicMock()
        gh.get_release_by_tag.side_effect = ValueError("Not Found")
        gh.create_release.return_value = {"id": 9, "upload_url": None, "assets": []}
        gh.upload_release_asset.return_value = {
            "browser_download_url": "http://x/pr-1-ui.png",
            "name": "pr-1-ui.png",
        }
        body = pr_publish.upload_and_inject_screenshots(
            gh,
            screenshots=[Path("/tmp/ws/ui.png")],
            owner="acme",
            repo="app",
            base_branch="main",
            pr_number=1,
            base_body="Body",
            release_tag="opencode-pr-assets",
            release_name="OpenCode PR screenshots",
            release_body="bucket",
        )
        gh.get_release_by_tag.assert_called_once_with("acme", "app", "opencode-pr-assets")
        self.assertIn("![pr-1-ui.png](http://x/pr-1-ui.png)", body)
