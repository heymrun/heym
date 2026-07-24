import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import settings
from app.services.codex_runner_service import (
    _CODEX_REMOTE_PUBLISH_MODES,
    CODEX_FINAL_OUTPUT_SCHEMA,
    CODEX_PUBLISH_MODES,
    CodexRunnerService,
    CodexRunRequest,
    CodexRunResult,
)
from app.services.coding_agent import pr_publish


class TestOutputSchema(unittest.TestCase):
    def test_required_covers_all_properties(self) -> None:
        # OpenAI strict structured output rejects schemas whose `required` omits any property.
        self.assertEqual(
            set(CODEX_FINAL_OUTPUT_SCHEMA["required"]),
            set(CODEX_FINAL_OUTPUT_SCHEMA["properties"]),
        )


def _request(publish_mode: str) -> CodexRunRequest:
    return CodexRunRequest(
        repository_url="https://github.com/acme/app",
        base_branch="main",
        task_prompt="do it",
        branch_name="codex/run",
        publish_mode=publish_mode,
        timeout_seconds=60.0,
        codex_access_token="tok",
        github_config={"api_key": "ghp"},
    )


class TestPublishModeConstants(unittest.TestCase):
    def test_all_modes_registered(self) -> None:
        self.assertEqual(
            CODEX_PUBLISH_MODES,
            {
                "diff_only",
                "draft_pr",
                "open_pr",
                "commit_push",
                "direct_commit",
                "update_existing_pr",
                "open_or_update_pr",
                "patch_artifact",
            },
        )

    def test_local_modes_do_not_push(self) -> None:
        self.assertNotIn("diff_only", _CODEX_REMOTE_PUBLISH_MODES)
        self.assertNotIn("patch_artifact", _CODEX_REMOTE_PUBLISH_MODES)

    def test_build_prompt_forbids_git_and_github(self) -> None:
        prompt = CodexRunnerService._build_prompt("translate the readme")
        self.assertIn("Do NOT run git", prompt)
        self.assertIn("GitHub API", prompt)
        self.assertIn("Heym performs every git", prompt)
        self.assertIn("frontend/.e2e-artifacts/", prompt)
        self.assertIn("bun install", prompt)
        self.assertIn("Never use placeholder titles", prompt)
        self.assertIn("translate the readme", prompt)

    def test_resume_prompt_forbids_git_and_github(self) -> None:
        prompt = CodexRunnerService._build_resume_prompt("use port 1234")
        self.assertIn("Do NOT run git", prompt)
        self.assertIn("use port 1234", prompt)

    def test_build_prompt_states_pull_request_content_policy(self) -> None:
        prompt = CodexRunnerService._build_prompt("translate the readme")
        self.assertIn("the task prompt is PRIVATE", prompt)
        self.assertIn("## Change Summary", prompt)
        self.assertIn("## Screenshots", prompt)

    def test_resume_prompt_states_pull_request_content_policy(self) -> None:
        self.assertIn(
            pr_publish.PR_CONTENT_POLICY, CodexRunnerService._build_resume_prompt("use port 1234")
        )

    def test_build_prompt_forbids_ending_on_a_screenshot_announcement(self) -> None:
        # Regression for the observed "…Now let me take a screenshot" early stop.
        prompt = CodexRunnerService._build_prompt("add a badge")
        self.assertIn("BEFORE you return your final result", prompt)
        self.assertIn("Now let me take a screenshot", prompt)

    def test_finishing_prompt_states_the_finishing_preamble(self) -> None:
        prompt = CodexRunnerService._build_finishing_prompt()
        self.assertIn(pr_publish.FINISHING_PASS_PREAMBLE, prompt)
        self.assertIn("Do NOT run git", prompt)
        self.assertIn("## Change Summary", prompt)


class TestCodexResolveUpdateExistingPr(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CodexRunnerService()

    def test_non_update_mode_is_unchanged(self) -> None:
        request = _request("open_pr")
        self.assertIs(self.runner._resolve_update_existing_pr_request(request), request)

    def test_update_mode_swaps_in_the_existing_pr_branch(self) -> None:
        request = _request("update_existing_pr")
        gh = MagicMock()
        with (
            patch("app.services.codex_runner_service.GitHubService", return_value=gh),
            patch.object(
                pr_publish, "resolve_update_existing_pr_branch", return_value="feat/real-branch"
            ),
        ):
            resolved = self.runner._resolve_update_existing_pr_request(request)
        self.assertEqual(resolved.branch_name, "feat/real-branch")
        self.assertEqual(request.branch_name, "codex/run")  # original request untouched
        gh.close.assert_called_once()


class TestCodexFinishIncompleteRun(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CodexRunnerService()
        self.runner._git_output = MagicMock(return_value="")  # type: ignore[method-assign]
        self.ws = Path("/tmp/ws")

    def test_reruns_and_updates_summary_when_agent_stopped_mid_task(self) -> None:
        # Real PR #401 case: the agent stopped right before the screenshot ("Backend code is
        # clean. Let me now take a screenshot."). A UI change with no screenshot triggers the
        # finishing pass even though the summary is not empty.
        result = CodexRunResult(
            status="completed",
            summary="Backend code is clean. Let me now take a screenshot.",
            changed_files=["frontend/src/views/DashboardView.vue"],
        )
        CodexRunnerService._prepare_publishable_text(result, "")

        finished = CodexRunResult(
            status="completed",
            summary="Add a live running-workflow count badge to the toolbar.",
            pull_request_title="Add running-workflow count badge",
            pull_request_body="## Change Summary\n\nAdd a live badge.",
        )
        self.runner._run_codex_exec = MagicMock(return_value=finished)  # type: ignore[method-assign]
        self.runner._discover_pr_screenshots = MagicMock(return_value=[])  # type: ignore[method-assign]
        self.runner._changed_files = MagicMock(  # type: ignore[method-assign]
            return_value=["frontend/src/views/DashboardView.vue"]
        )

        self.runner._finish_incomplete_run(self.ws, _request("open_pr"), result)

        self.runner._run_codex_exec.assert_called_once()
        self.assertEqual(result.summary, "Add a live running-workflow count badge to the toolbar.")
        self.assertEqual(result.pull_request_title, "Add running-workflow count badge")
        # A UI change with no screenshot after the pass gets a visible note.
        self.assertIn("## Screenshots", result.pull_request_body)

    def test_no_rerun_when_summary_and_screenshot_present(self) -> None:
        result = CodexRunResult(
            status="completed",
            summary="Add a live badge.",
            changed_files=["frontend/src/views/DashboardView.vue"],
        )
        CodexRunnerService._prepare_publishable_text(result, "")
        self.runner._run_codex_exec = MagicMock()  # type: ignore[method-assign]
        self.runner._discover_pr_screenshots = MagicMock(  # type: ignore[method-assign]
            return_value=[Path("/tmp/ws/frontend/.e2e-artifacts/shot.png")]
        )

        self.runner._finish_incomplete_run(self.ws, _request("open_pr"), result)

        self.runner._run_codex_exec.assert_not_called()


class TestCodexPublishedTextRedaction(unittest.TestCase):
    def test_finalize_strips_task_prompt_echo_from_published_fields(self) -> None:
        prompt = "Add a retry to the webhook trigger and do not touch the scheduler."
        result = CodexRunResult(
            status="completed",
            summary=f"Added the retry loop.\n\n{prompt}",
            validation="Ran the backend suite.",
            pull_request_title="Add webhook trigger retry",
            pull_request_body=f"## Change Summary\n\nAdded the retry loop.\n\n## Task\n\n{prompt}",
        )

        CodexRunnerService._prepare_publishable_text(result, prompt)

        self.assertEqual(result.summary, "Added the retry loop.")
        self.assertEqual(result.validation, "Ran the backend suite.")
        self.assertNotIn("## Task", result.pull_request_body)
        self.assertNotIn("do not touch the scheduler", result.pull_request_body)
        self.assertIn("Added the retry loop.", result.pull_request_body)


class TestCommitMessage(unittest.TestCase):
    @staticmethod
    def _result(**kwargs) -> CodexRunResult:
        """Build a result the way the runner does, so `publish_summary` is populated."""
        result = CodexRunResult(status="completed", **kwargs)
        CodexRunnerService._prepare_publishable_text(result, "")
        return result

    def test_commit_title_keeps_full_single_sentence(self) -> None:
        # A long run-on summary (no early period) is kept whole, not cut at ~72 chars.
        summary = "Added n8n10 to docker-compose.yml using host port 2245, internal port 3032"
        result = self._result(summary=summary)
        self.assertEqual(CodexRunnerService._commit_title(result), summary)

    def test_commit_title_keeps_short_summary(self) -> None:
        result = self._result(summary="Fix typo")
        self.assertEqual(CodexRunnerService._commit_title(result), "Fix typo")

    def test_commit_title_prefers_pull_request_title(self) -> None:
        result = self._result(
            summary="A long detailed summary sentence describing everything that changed in depth.",
            pull_request_title="Add n8n10 service to compose and Traefik",
        )
        self.assertEqual(
            CodexRunnerService._commit_title(result), "Add n8n10 service to compose and Traefik"
        )

    def test_commit_title_uses_first_sentence(self) -> None:
        result = self._result(
            summary="README.md translated. Headings, tables, notes localized; commands preserved.",
        )
        self.assertEqual(CodexRunnerService._commit_title(result), "README.md translated.")

    def test_commit_title_skips_placeholder_done(self) -> None:
        result = self._result(
            summary="Done. Reorder the mobile chat header actions.",
            pull_request_title="Done.",
        )
        self.assertEqual(
            CodexRunnerService._commit_title(result),
            "Reorder the mobile chat header actions.",
        )

    def test_commit_body_has_full_summary_and_validation(self) -> None:
        result = self._result(summary="X" * 100, validation="ran docker compose config")
        body = CodexRunnerService._commit_body(result)
        self.assertIn("X" * 100, body)
        self.assertIn("ran docker compose config", body)


class TestPushBranch(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CodexRunnerService()
        self.runner._run_command = MagicMock()  # type: ignore[method-assign]
        self.workspace = Path("/tmp/ws")
        self.request = _request("commit_push")

    def test_existing_remote_branch_is_rebased_before_push(self) -> None:
        self.runner._git_output = MagicMock(  # type: ignore[method-assign]
            return_value="abc123\trefs/heads/codex/run\n"
        )

        self.runner._push_branch(self.workspace, self.request, "codex/run")

        commands = [call.args[0] for call in self.runner._run_command.call_args_list]
        self.assertEqual(
            commands[1],
            [
                "git",
                *pr_publish.git_identity_args(
                    settings.codex_git_author_name, settings.codex_git_author_email
                ),
                "pull",
                "--rebase",
                "--strategy-option=theirs",
                "origin",
                "codex/run",
            ],
        )
        self.assertEqual(commands[2], ["git", "push", "-u", "origin", "codex/run"])

    def test_new_remote_branch_skips_pull(self) -> None:
        self.runner._git_output = MagicMock(return_value="")  # type: ignore[method-assign]

        self.runner._push_branch(self.workspace, self.request, "codex/run")

        commands = [call.args[0] for call in self.runner._run_command.call_args_list]
        self.assertEqual(
            commands,
            [
                [
                    "git",
                    "remote",
                    "set-url",
                    "origin",
                    "https://x-access-token:ghp@github.com/acme/app",
                ],
                ["git", "push", "-u", "origin", "codex/run"],
            ],
        )

    def test_pull_conflict_aborts_rebase_and_does_not_push(self) -> None:
        self.runner._git_output = MagicMock(  # type: ignore[method-assign]
            return_value="abc123\trefs/heads/codex/run\n"
        )
        self.runner._run_command.side_effect = [None, ValueError("CONFLICT in app.py"), None]

        with self.assertRaisesRegex(ValueError, "Could not synchronize branch"):
            self.runner._push_branch(self.workspace, self.request, "codex/run")

        commands = [call.args[0] for call in self.runner._run_command.call_args_list]
        self.assertEqual(commands[-1], ["git", "rebase", "--abort"])
        self.assertNotIn(["git", "push", "-u", "origin", "codex/run"], commands)


class TestPublishDispatch(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CodexRunnerService()
        self.runner._commit_changes = MagicMock()  # type: ignore[method-assign]
        self.runner._push_branch = MagicMock()  # type: ignore[method-assign]
        self.runner._create_pr = MagicMock(return_value="https://pr")  # type: ignore[method-assign]
        self.runner._open_pr_url_for_head = MagicMock(return_value=None)  # type: ignore[method-assign]
        self.runner._current_branch = MagicMock(return_value="main")  # type: ignore[method-assign]
        self.ws = Path("/tmp/ws")

    def _result(self) -> CodexRunResult:
        return CodexRunResult(status="completed", summary="done", changed_files=["a.py"])

    def test_no_changes_skips_publish(self) -> None:
        result = CodexRunResult(status="completed", changed_files=[])
        self.runner._publish(self.ws, _request("open_pr"), result)
        self.runner._commit_changes.assert_not_called()
        self.assertEqual(result.pushed_branch, "")

    def test_open_pr_creates_non_draft(self) -> None:
        result = self._result()
        self.runner._publish(self.ws, _request("open_pr"), result)
        self.assertEqual(self.runner._create_pr.call_args.kwargs["draft"], False)
        self.assertEqual(result.pull_request_url, "https://pr")
        self.assertEqual(result.pushed_branch, "codex/run")

    def test_draft_pr_creates_draft(self) -> None:
        result = self._result()
        self.runner._publish(self.ws, _request("draft_pr"), result)
        self.assertEqual(self.runner._create_pr.call_args.kwargs["draft"], True)

    def test_commit_push_no_pr(self) -> None:
        result = self._result()
        self.runner._publish(self.ws, _request("commit_push"), result)
        self.runner._create_pr.assert_not_called()
        self.assertEqual(result.pushed_branch, "codex/run")
        self.assertIsNone(result.pull_request_url)

    def test_direct_commit_uses_base_branch(self) -> None:
        result = self._result()
        self.runner._publish(self.ws, _request("direct_commit"), result)
        args = self.runner._commit_changes.call_args
        self.assertEqual(args.args[1], "main")
        self.assertFalse(args.kwargs["new_branch"])
        self.assertEqual(result.pushed_branch, "main")

    def test_update_existing_pr_on_existing_branch_returns_existing(self) -> None:
        self.runner._current_branch = MagicMock(return_value="codex/run")  # type: ignore[method-assign]
        self.runner._open_pr_url_for_head = MagicMock(return_value="https://existing")  # type: ignore[method-assign]
        result = self._result()
        self.runner._publish(self.ws, _request("update_existing_pr"), result)
        self.assertFalse(self.runner._commit_changes.call_args.kwargs["new_branch"])
        self.runner._create_pr.assert_not_called()
        self.assertEqual(result.pull_request_url, "https://existing")

    def test_update_existing_pr_fallback_creates_pr(self) -> None:
        # current branch is base (fell back to base clone), no existing PR -> create one
        result = self._result()
        self.runner._publish(self.ws, _request("update_existing_pr"), result)
        self.assertTrue(self.runner._commit_changes.call_args.kwargs["new_branch"])
        self.runner._create_pr.assert_called_once()


if __name__ == "__main__":
    unittest.main()


class TestCodexNarrationIsNotPublished(unittest.TestCase):
    """The narration guard is shared with OpenCode; Codex must get the same treatment."""

    NARRATION = "Both pass. Let me do a final review of the complete changes:"

    def _prepared(self, **kwargs) -> CodexRunResult:
        result = CodexRunResult(status="completed", **kwargs)
        CodexRunnerService._prepare_publishable_text(result, "")
        return result

    def test_narration_summary_is_not_a_commit_title_or_body(self) -> None:
        result = self._prepared(summary=self.NARRATION, changed_files=["a.py"])

        self.assertEqual(result.publish_summary, "")
        self.assertEqual(CodexRunnerService._commit_title(result), "Apply Codex changes")
        self.assertNotIn("Let me do a final review", CodexRunnerService._commit_body(result))
        # The raw message stays on the node output so the run is still debuggable in Heym.
        self.assertIn("Let me do a final review", result.summary)

    def test_a_real_summary_still_reaches_the_commit(self) -> None:
        result = self._prepared(summary="Add a retry to the webhook trigger.")

        self.assertEqual(
            CodexRunnerService._commit_title(result), "Add a retry to the webhook trigger."
        )

    def test_pr_body_falls_back_to_the_changed_file_list(self) -> None:
        result = self._prepared(summary=self.NARRATION, changed_files=["app/main.py", "app/api.py"])
        gh = MagicMock()
        gh.create_pull_request.return_value = {"number": 7, "html_url": "https://x/pull/7"}
        runner = CodexRunnerService(workspace_root="/tmp/heym-codex-ws")
        runner._discover_pr_screenshots = MagicMock(return_value=[])  # type: ignore[method-assign]

        with patch("app.services.codex_runner_service.GitHubService", return_value=gh):
            runner._create_pr(
                Path("/tmp/ws"), _request("open_pr"), result, "codex/run", draft=False
            )

        body = gh.create_pull_request.call_args.kwargs["body"]
        self.assertNotIn("Let me do a final review", body)
        self.assertIn("`app/main.py`", body)
