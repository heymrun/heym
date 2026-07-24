"""Tests for attaching Codex-generated UI screenshots to pull requests via release assets."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.codex_runner_service import (
    CodexRunnerService,
    CodexRunRequest,
    CodexRunResult,
)


def _request(publish_mode: str = "open_pr") -> CodexRunRequest:
    return CodexRunRequest(
        repository_url="https://github.com/acme/app",
        base_branch="main",
        task_prompt="fix ui",
        branch_name="codex/run",
        publish_mode=publish_mode,
        timeout_seconds=60.0,
        codex_access_token="tok",
        github_config={"api_key": "ghp"},
    )


class TestDiscoverPrScreenshots(unittest.TestCase):
    def test_finds_gitignored_e2e_artifact_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            shot = workspace / "frontend" / ".e2e-artifacts" / "board-select.png"
            shot.parent.mkdir(parents=True)
            shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake")
            tracked = workspace / "docs" / "screenshots" / "login.png"
            tracked.parent.mkdir(parents=True)
            tracked.write_bytes(b"tracked")

            found = CodexRunnerService()._discover_pr_screenshots(workspace)

            self.assertEqual([p.resolve() for p in found], [shot.resolve()])

    def test_finds_untracked_screenshot_named_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            shot = workspace / "tmp-screenshot-after.png"
            shot.write_bytes(b"img")

            found = CodexRunnerService()._discover_pr_screenshots(workspace)

            self.assertEqual([p.resolve() for p in found], [shot.resolve()])

    def test_ignores_tracked_docs_screenshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            tracked = workspace / "docs" / "screenshots" / "login.png"
            tracked.parent.mkdir(parents=True)
            tracked.write_bytes(b"tracked")

            runner = CodexRunnerService()
            with patch.object(
                runner,
                "_git_output",
                return_value="docs/screenshots/login.png\n",
            ):
                found = runner._discover_pr_screenshots(workspace)

            self.assertEqual(found, [])


class TestAttachPrScreenshots(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CodexRunnerService()
        self.workspace = Path("/tmp/ws")

    def test_create_pr_opens_already_containing_screenshots(self) -> None:
        # Screenshots are uploaded and embedded BEFORE the PR is created, so it opens with them
        # (no follow-up update_issue on the create path).
        shot = Path("/tmp/ws/frontend/.e2e-artifacts/ui.png")
        result = CodexRunResult(
            status="completed",
            summary="done",
            pull_request_body=(
                "## Summary\n\nfixed\n\n## Screenshot\n\n"
                "Attach the generated screenshot from "
                "`frontend/.e2e-artifacts/ui.png` when creating the merge request."
            ),
            changed_files=["a.vue"],
        )
        gh = MagicMock()
        gh.create_pull_request.return_value = {
            "number": 347,
            "html_url": "https://github.com/acme/app/pull/347",
        }
        gh.get_release_by_tag.side_effect = ValueError("Not Found")
        gh.create_release.return_value = {
            "id": 99,
            "upload_url": "https://uploads.github.com/repos/acme/app/releases/99/assets{?name,label}",
            "tag_name": "codex-pr-assets",
            "assets": [],
        }
        gh.upload_release_asset.return_value = {
            "browser_download_url": (
                "https://github.com/acme/app/releases/download/codex-pr-assets/codex-run-ui.png"
            ),
            "name": "codex-run-ui.png",
        }

        self.runner._discover_pr_screenshots = MagicMock(return_value=[shot])  # type: ignore[method-assign]

        with patch("app.services.codex_runner_service.GitHubService", return_value=gh) as gh_cls:
            url = self.runner._create_pr(
                self.workspace, _request(), result, "codex/run", draft=False
            )

        self.assertEqual(url, "https://github.com/acme/app/pull/347")
        gh_cls.assert_called()
        release_kwargs = gh.create_release.call_args.kwargs
        self.assertTrue(release_kwargs.get("prerelease"))
        # Asset name is keyed on the branch (available before the PR exists), not the PR number.
        self.assertEqual(gh.upload_release_asset.call_args.kwargs["name"], "codex-run-ui.png")
        # The PR is created with the screenshot already in its body; no post-create body update.
        gh.update_issue.assert_not_called()
        created_body = gh.create_pull_request.call_args.kwargs["body"]
        self.assertIn(
            "https://github.com/acme/app/releases/download/codex-pr-assets/codex-run-ui.png",
            created_body,
        )
        self.assertIn("![codex-run-ui.png]", created_body)
        self.assertNotIn("Attach the generated screenshot", created_body)
        self.assertEqual(result.pull_request_body, created_body)

    def test_reuses_shared_release_and_replaces_same_named_asset(self) -> None:
        shot = Path("/tmp/ws/frontend/.e2e-artifacts/ui.png")
        result = CodexRunResult(status="completed", summary="done", changed_files=["a.vue"])
        gh = MagicMock()
        gh.create_pull_request.return_value = {
            "number": 347,
            "html_url": "https://github.com/acme/app/pull/347",
        }
        gh.get_release_by_tag.return_value = {
            "id": 99,
            "upload_url": "https://uploads.github.com/repos/acme/app/releases/99/assets{?name,label}",
            "tag_name": "codex-pr-assets",
            "assets": [{"id": 55, "name": "codex-run-ui.png"}],
        }
        gh.upload_release_asset.return_value = {
            "browser_download_url": (
                "https://github.com/acme/app/releases/download/codex-pr-assets/codex-run-ui.png"
            ),
            "name": "codex-run-ui.png",
        }
        self.runner._discover_pr_screenshots = MagicMock(return_value=[shot])  # type: ignore[method-assign]

        with patch("app.services.codex_runner_service.GitHubService", return_value=gh):
            self.runner._create_pr(self.workspace, _request(), result, "codex/run", draft=False)

        gh.create_release.assert_not_called()
        gh.delete_release_asset.assert_called_once_with("acme", "app", 55)
        self.assertEqual(gh.upload_release_asset.call_args.kwargs["name"], "codex-run-ui.png")

    def test_attach_failure_does_not_raise(self) -> None:
        result = CodexRunResult(
            status="completed",
            summary="done",
            pull_request_body="body",
            changed_files=["a.vue"],
        )
        gh = MagicMock()
        gh.create_pull_request.return_value = {
            "number": 1,
            "html_url": "https://github.com/acme/app/pull/1",
        }
        self.runner._discover_pr_screenshots = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("disk boom")
        )

        with patch("app.services.codex_runner_service.GitHubService", return_value=gh):
            url = self.runner._create_pr(
                self.workspace, _request(), result, "codex/run", draft=True
            )

        self.assertEqual(url, "https://github.com/acme/app/pull/1")
        gh.create_release.assert_not_called()

    def test_update_existing_pr_updates_body_with_screenshots(self) -> None:
        result = CodexRunResult(status="completed", summary="done", changed_files=["a.vue"])
        self.runner._commit_changes = MagicMock()  # type: ignore[method-assign]
        self.runner._push_branch = MagicMock()  # type: ignore[method-assign]
        self.runner._current_branch = MagicMock(return_value="codex/run")  # type: ignore[method-assign]
        self.runner._open_pr_url_for_head = MagicMock(  # type: ignore[method-assign]
            return_value="https://github.com/acme/app/pull/42"
        )
        self.runner._update_pr_body_with_screenshots = MagicMock()  # type: ignore[method-assign]

        self.runner._publish(self.workspace, _request("update_existing_pr"), result)

        self.runner._update_pr_body_with_screenshots.assert_called_once()
        args = self.runner._update_pr_body_with_screenshots.call_args
        self.assertEqual(args.args[0], self.workspace)
        self.assertIs(args.args[2], result)
        self.assertEqual(args.args[3], "codex/run")
        self.assertEqual(args.args[4], "https://github.com/acme/app/pull/42")
        self.assertEqual(result.pull_request_url, "https://github.com/acme/app/pull/42")

    def test_open_or_update_pr_updates_existing(self) -> None:
        # The new intuitive mode shares the update-or-open path.
        result = CodexRunResult(status="completed", summary="done", changed_files=["a.vue"])
        self.runner._commit_changes = MagicMock()  # type: ignore[method-assign]
        self.runner._push_branch = MagicMock()  # type: ignore[method-assign]
        self.runner._current_branch = MagicMock(return_value="codex/run")  # type: ignore[method-assign]
        self.runner._open_pr_url_for_head = MagicMock(  # type: ignore[method-assign]
            return_value="https://github.com/acme/app/pull/42"
        )
        self.runner._update_pr_body_with_screenshots = MagicMock()  # type: ignore[method-assign]
        self.runner._create_pr = MagicMock()  # type: ignore[method-assign]

        self.runner._publish(self.workspace, _request("open_or_update_pr"), result)

        self.runner._update_pr_body_with_screenshots.assert_called_once()
        self.runner._create_pr.assert_not_called()
        self.assertEqual(result.pull_request_url, "https://github.com/acme/app/pull/42")


class TestScreenshotBodyHelpers(unittest.TestCase):
    def test_inject_replaces_placeholder_section(self) -> None:
        body = (
            "## Summary\n\nfix\n\n## Screenshot\n\n"
            "Attach the generated screenshot from `x.png` when creating the merge request."
        )
        urls = [("pr-1-x.png", "https://example.com/x.png")]
        updated = CodexRunnerService._inject_screenshot_markdown(body, urls)
        self.assertIn("![pr-1-x.png](https://example.com/x.png)", updated)
        self.assertNotIn("Attach the generated", updated)
        self.assertIn("## Summary", updated)

    def test_release_asset_name_prefixes_sanitized_branch(self) -> None:
        self.assertEqual(
            CodexRunnerService._release_asset_name(Path("ui.png"), "codex/run", 0),
            "codex-run-ui.png",
        )
        self.assertEqual(
            CodexRunnerService._release_asset_name(Path("board.png"), "codex/run", 1),
            "codex-run-board-1.png",
        )

    def test_parse_pr_number_from_url(self) -> None:
        self.assertEqual(
            CodexRunnerService._pr_number_from_url("https://github.com/acme/app/pull/347"),
            347,
        )
        self.assertIsNone(CodexRunnerService._pr_number_from_url("https://github.com/acme/app"))


if __name__ == "__main__":
    unittest.main()
