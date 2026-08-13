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

    def test_commit_title_skips_placeholder_done(self):
        self.assertEqual(
            pr_publish.commit_title(
                "",
                "Done. Move the chat list toggle before History on mobile.",
                fallback="Apply changes",
            ),
            "Move the chat list toggle before History on mobile.",
        )

    def test_commit_title_skips_placeholder_pr_title(self):
        self.assertEqual(
            pr_publish.commit_title(
                "Done.",
                "Close the mobile sidebar after selecting a chat.",
                fallback="Apply changes",
            ),
            "Close the mobile sidebar after selecting a chat.",
        )

    def test_commit_title_uses_pr_title_line(self):
        self.assertEqual(
            pr_publish.commit_title(
                "",
                "Implemented the mobile drawer fix.\n\nPR_TITLE: Reorder mobile chat header actions",
                fallback="Apply changes",
            ),
            "Reorder mobile chat header actions",
        )

    def test_commit_title_fallback(self):
        self.assertEqual(pr_publish.commit_title("", "", fallback="Apply changes"), "Apply changes")
        self.assertEqual(
            pr_publish.commit_title("Done.", "Done.", fallback="Apply changes"), "Apply changes"
        )

    def test_extract_pr_title_line(self):
        title, summary = pr_publish.extract_pr_title_line(
            "Finished the work.\nPR_TITLE: Fix mobile chat drawer\n"
        )
        self.assertEqual(title, "Fix mobile chat drawer")
        self.assertEqual(summary, "Finished the work.")

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

    def test_discover_finds_case_insensitive_screenshot_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            shot = workspace / "ScreenShot-Mobile.png"
            shot.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            found = pr_publish.discover_pr_screenshots(workspace, lambda _cmd, _ws: "")
            self.assertEqual([p.resolve() for p in found], [shot.resolve()])

    def test_discover_finds_common_screenshot_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            shot = workspace / "e2e" / "screenshots" / "after.png"
            shot.parent.mkdir(parents=True)
            shot.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            found = pr_publish.discover_pr_screenshots(workspace, lambda _cmd, _ws: "")
            self.assertEqual([p.resolve() for p in found], [shot.resolve()])

    def test_discover_skips_tracked_screenshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            shot = workspace / "docs" / "screenshots" / "login.png"
            shot.parent.mkdir(parents=True)
            shot.write_bytes(b"tracked")
            found = pr_publish.discover_pr_screenshots(
                workspace, lambda _cmd, _ws: "docs/screenshots/login.png\n"
            )
            self.assertEqual(found, [])

    def test_discover_respects_max_file_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            for index in range(7):
                shot = workspace / "frontend" / ".e2e-artifacts" / f"ui-{index}.png"
                shot.parent.mkdir(parents=True, exist_ok=True)
                shot.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            found = pr_publish.discover_pr_screenshots(workspace, lambda _cmd, _ws: "")
            self.assertEqual(len(found), pr_publish.PR_SCREENSHOT_MAX_FILES)

    def test_upload_and_inject_uses_gh(self):
        gh = MagicMock()
        gh.get_release_by_tag.side_effect = ValueError("Not Found")
        gh.create_release.return_value = {"id": 9, "upload_url": None, "assets": []}
        gh.upload_release_asset.return_value = {
            "browser_download_url": "http://x/opencode-run-ui.png",
            "name": "opencode-run-ui.png",
        }
        body = pr_publish.upload_and_inject_screenshots(
            gh,
            screenshots=[Path("/tmp/ws/ui.png")],
            owner="acme",
            repo="app",
            base_branch="main",
            asset_slug="opencode/run",
            base_body="Body",
            release_tag="opencode-pr-assets",
            release_name="OpenCode PR screenshots",
            release_body="bucket",
        )
        gh.get_release_by_tag.assert_called_once_with("acme", "app", "opencode-pr-assets")
        # Asset name is keyed on the (sanitized) branch, not the PR number.
        self.assertIn("![opencode-run-ui.png](http://x/opencode-run-ui.png)", body)
        self.assertEqual(gh.upload_release_asset.call_args.kwargs["name"], "opencode-run-ui.png")


class TestTaskPromptRedaction(unittest.TestCase):
    PROMPT = "Rework the mobile chat header so History sits last, then run the e2e suite."

    def test_removes_task_section(self):
        body = f"## Change Summary\n\nMoved History last.\n\n## Task\n\n{self.PROMPT}\n"
        self.assertEqual(
            pr_publish.redact_task_prompt(body, self.PROMPT),
            "## Change Summary\n\nMoved History last.",
        )

    def test_section_removal_is_case_and_label_tolerant(self):
        for heading in ("### Original Request", "## Instructions:", "## **User Prompt**"):
            body = f"## Change Summary\n\nMoved History last.\n\n{heading}\n\nsecret guidance\n"
            with self.subTest(heading=heading):
                self.assertNotIn("secret guidance", pr_publish.redact_task_prompt(body, ""))

    def test_prompt_section_removal_stops_at_next_same_level_heading(self):
        body = (
            "## Task\n\nprivate guidance here\n\n"
            "### Details\n\nmore private guidance\n\n"
            "## Screenshots\n\n![ui](http://x/ui.png)\n"
        )
        cleaned = pr_publish.redact_task_prompt(body, "")
        self.assertNotIn("private guidance", cleaned)
        self.assertIn("![ui](http://x/ui.png)", cleaned)

    def test_removes_verbatim_prompt_paragraph_without_a_heading(self):
        body = f"{self.PROMPT}\n\nMoved History last."
        self.assertEqual(pr_publish.redact_task_prompt(body, self.PROMPT), "Moved History last.")

    def test_keeps_wording_that_merely_overlaps_the_prompt(self):
        body = "## Change Summary\n\nMoved History last in the mobile chat header."
        self.assertEqual(pr_publish.redact_task_prompt(body, self.PROMPT), body)

    def test_short_prompts_do_not_trigger_paragraph_removal(self):
        body = "Fix the tests"
        self.assertEqual(pr_publish.redact_task_prompt(body, "Fix the tests"), body)

    def test_empty_input_is_safe(self):
        self.assertEqual(pr_publish.redact_task_prompt("", self.PROMPT), "")


class TestAgentNarrationDetection(unittest.TestCase):
    NARRATION = (
        "Both pass. Let me do a final review of the complete changes:",
        "Let me do a final review of the complete changes:",
        "Now let me verify the store wiring.",
        "I'll run the e2e suite next.",
        "Perfect! Now I will check the remaining callers.",
        "All tests pass, moving on.",
        "It works. Next, I check the docs.",
        "Good, the swap is correct.",
        "Perfect! The build is clean.",
        "First, check dependencies and start a preview server:",
        "Applying the remaining changes now:",
    )
    # Real titles from merged agent pull requests — the guard must leave every one of them alone.
    DESCRIPTIONS = (
        "Hide Execution Highlights panel by default on mobile",
        "Auto-scroll console to selected node's most recent execution log",
        "Swap Traces and Templates tab positions in dashboard nav bar",
        "Hide JSON tree/plain toggle buttons in console output when node is running",
        "Update trace detail json tree view",
        "Add a stale-save override dialog for concurrent workflow edits",
        "Fix OpenCode fallback summary when no assistant message is returned",
        "Let the workflow store detect a newer server revision before saving",
        "Passing the loaded revision through to the save call",
        # "Good" only opens narration when it is an interjection ("Good, …").
        "Good defaults for the retry policy",
    )

    def test_narration_is_detected(self):
        for text in self.NARRATION:
            with self.subTest(text=text):
                self.assertTrue(pr_publish.is_agent_narration(text))

    def test_change_descriptions_are_not_narration(self):
        for text in self.DESCRIPTIONS:
            with self.subTest(text=text):
                self.assertFalse(pr_publish.is_agent_narration(text))

    def test_narration_is_rejected_as_a_commit_title(self):
        # Regression: PR #397 shipped with this exact string as its title.
        self.assertFalse(
            pr_publish.is_meaningful_commit_title(
                "Both pass. Let me do a final review of the complete changes:"
            )
        )

    def test_every_sentence_of_a_narrated_summary_is_rejected(self):
        # Regression: PR #389 shipped with this exact string as its title and commit subject.
        # `commit_title` walks sentence by sentence, so each one has to be caught.
        summary = (
            "Good, the swap is correct. Now let me take a screenshot. "
            "First, check dependencies and start a preview server:"
        )
        self.assertEqual(pr_publish.commit_title("", summary, fallback="Fallback"), "Fallback")

    def test_commit_title_falls_back_when_the_summary_only_narrates(self):
        title = pr_publish.commit_title(
            "", "Both pass. Let me do a final review of the complete changes:", fallback="Fallback"
        )
        self.assertEqual(title, "Fallback")


class TestChangeSummaryExtraction(unittest.TestCase):
    def test_extracts_section_and_drops_surrounding_narration(self):
        text = (
            "Let me do a final review of the complete changes:\n\n"
            "## Change Summary\n\n"
            "Added a stale-save override dialog.\n\n"
            "## Screenshots\n\n"
            "![ui](frontend/.e2e-artifacts/ui.png)\n"
        )
        self.assertEqual(
            pr_publish.extract_change_summary_section(text), "Added a stale-save override dialog."
        )

    def test_keeps_nested_subsections(self):
        text = "## Change Summary\n\nTop level.\n\n### Store\n\nStore detail.\n\n## Task\n\nsecret"
        section = pr_publish.extract_change_summary_section(text)
        self.assertIn("### Store", section)
        self.assertIn("Store detail.", section)
        self.assertNotIn("secret", section)

    def test_last_section_wins(self):
        text = "## Change Summary\n\nFirst draft.\n\n# Redo\n\n## Change Summary\n\nFinal wording."
        self.assertEqual(pr_publish.extract_change_summary_section(text), "Final wording.")

    def test_absent_section_returns_empty(self):
        self.assertEqual(pr_publish.extract_change_summary_section("Just prose."), "")


def _pr(
    head: str,
    base: str = "main",
    login: str = "heym-coder",
    updated_at: str = "",
    number: int = 1,
) -> dict:
    return {
        "head": {"ref": head},
        "base": {"ref": base},
        "user": {"login": login},
        "updated_at": updated_at,
        "number": number,
        "html_url": f"https://github.com/acme/app/pull/{number}",
    }


class TestResolveUpdateExistingPrBranch(unittest.TestCase):
    """update_existing_pr must find this task's open PR, never an unrelated one."""

    def _gh(self, pulls: list[dict], login: str = "heym-coder") -> MagicMock:
        gh = MagicMock()
        gh.list_pull_requests.return_value = pulls
        gh.get_authenticated_user.return_value = {"login": login}
        return gh

    def test_exact_head_match_wins(self):
        gh = self._gh([_pr("feature-a"), _pr("configured")])
        branch = pr_publish.resolve_update_existing_pr_branch(
            gh, "acme", "app", base_branch="main", configured_branch="configured"
        )
        self.assertEqual(branch, "configured")

    def test_branch_naming_a_pull_request_resolves_to_its_head(self):
        # The board bug behind this fallback: the planner emitted a placeholder for PR #401.
        gh = self._gh([_pr("feat/running-workflow-count-badge", number=401)])
        branch = pr_publish.resolve_update_existing_pr_branch(
            gh, "acme", "app", base_branch="main", configured_branch="reuse-branch-from-pr-401"
        )
        self.assertEqual(branch, "feat/running-workflow-count-badge")

    def test_adopts_the_same_task_under_a_different_agent_prefix(self):
        gh = self._gh([_pr("codex/alerts-dialog-improvements", number=7)])
        branch = pr_publish.resolve_update_existing_pr_branch(
            gh,
            "acme",
            "app",
            base_branch="main",
            configured_branch="opencode/alerts-dialog-improvements",
        )
        self.assertEqual(branch, "codex/alerts-dialog-improvements")

    def test_never_adopts_an_unrelated_task(self):
        # A concurrent card pushed its alerts work onto an unrelated dialog PR this way.
        gh = self._gh(
            [
                _pr(
                    "codex/traces-models-without-pricing-dialog", updated_at="2026-08-13T15:00:00Z"
                ),
                _pr("opencode/board-card-filters", updated_at="2026-08-13T14:00:00Z"),
            ]
        )
        branch = pr_publish.resolve_update_existing_pr_branch(
            gh,
            "acme",
            "app",
            base_branch="main",
            configured_branch="opencode/alerts-dialog-improvements",
        )
        self.assertEqual(branch, "opencode/alerts-dialog-improvements")

    def test_ignores_other_authors_and_other_base_branches(self):
        gh = self._gh(
            [
                _pr("human/unmatched", login="someone-else"),
                _pr("bot/unmatched", base="develop"),
            ]
        )
        branch = pr_publish.resolve_update_existing_pr_branch(
            gh, "acme", "app", base_branch="main", configured_branch="agent/unmatched"
        )
        self.assertEqual(branch, "agent/unmatched")

    def test_without_a_readable_author_nothing_is_adopted(self):
        gh = self._gh([_pr("codex/alerts-dialog-improvements")])
        gh.get_authenticated_user.side_effect = ValueError("token cannot read /user")
        branch = pr_publish.resolve_update_existing_pr_branch(
            gh,
            "acme",
            "app",
            base_branch="main",
            configured_branch="opencode/alerts-dialog-improvements",
        )
        self.assertEqual(branch, "opencode/alerts-dialog-improvements")

    def test_github_error_falls_back_to_configured_branch(self):
        gh = MagicMock()
        gh.list_pull_requests.side_effect = ValueError("boom")
        branch = pr_publish.resolve_update_existing_pr_branch(
            gh, "acme", "app", base_branch="main", configured_branch="configured"
        )
        self.assertEqual(branch, "configured")


class TestFinishingPassHelpers(unittest.TestCase):
    def test_changed_files_touch_ui_detects_vue_and_frontend_scripts(self):
        self.assertTrue(pr_publish.changed_files_touch_ui(["frontend/src/views/DashboardView.vue"]))
        self.assertTrue(pr_publish.changed_files_touch_ui(["frontend/src/views/Editor.ts"]))
        self.assertTrue(pr_publish.changed_files_touch_ui(["app/styles/theme.css"]))

    def test_changed_files_touch_ui_ignores_backend_only(self):
        self.assertFalse(
            pr_publish.changed_files_touch_ui(
                ["backend/app/api/workflows.py", "backend/tests/test_x.py"]
            )
        )

    def test_needs_finishing_pass_when_no_publishable_summary(self):
        self.assertTrue(
            pr_publish.needs_finishing_pass(
                will_publish=True,
                changed_files=["a.py"],
                publish_summary="",
                ui_change=False,
                has_screenshots=False,
            )
        )

    def test_needs_finishing_pass_when_ui_change_lacks_screenshot(self):
        self.assertTrue(
            pr_publish.needs_finishing_pass(
                will_publish=True,
                changed_files=["frontend/src/App.vue"],
                publish_summary="Add a badge.",
                ui_change=True,
                has_screenshots=False,
            )
        )

    def test_no_finishing_pass_when_summary_and_screenshot_present(self):
        self.assertFalse(
            pr_publish.needs_finishing_pass(
                will_publish=True,
                changed_files=["frontend/src/App.vue"],
                publish_summary="Add a badge.",
                ui_change=True,
                has_screenshots=True,
            )
        )

    def test_no_finishing_pass_without_changes_or_publish(self):
        self.assertFalse(
            pr_publish.needs_finishing_pass(
                will_publish=False,
                changed_files=["a.py"],
                publish_summary="",
                ui_change=False,
                has_screenshots=False,
            )
        )
        self.assertFalse(
            pr_publish.needs_finishing_pass(
                will_publish=True,
                changed_files=[],
                publish_summary="",
                ui_change=False,
                has_screenshots=False,
            )
        )

    def test_note_missing_ui_screenshot_appends_section(self):
        body = pr_publish.note_missing_ui_screenshot("## Change Summary\n\nAdd a badge.")
        self.assertIn("## Screenshots", body)
        self.assertIn("did not", body)
        self.assertIn("capture a screenshot", body)

    def test_note_missing_ui_screenshot_is_noop_when_screenshots_present(self):
        body = "## Change Summary\n\nx\n\n## Screenshots\n\n![shot](http://x/y.png)"
        self.assertEqual(pr_publish.note_missing_ui_screenshot(body).strip(), body.strip())
