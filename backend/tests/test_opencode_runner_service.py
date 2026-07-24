import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import settings
from app.services.coding_agent import pr_publish
from app.services.opencode_runner_service import (
    OpenCodeRunnerService,
    OpenCodeRunRequest,
    OpenCodeRunResult,
)

_WS = Path("/tmp/heym-oc-ws/run1")


def _request(**overrides) -> OpenCodeRunRequest:
    base = dict(
        repository_url="https://github.com/acme/app",
        base_branch="main",
        task_prompt="fix the tests",
        branch_name="opencode/run",
        publish_mode="diff_only",
        timeout_seconds=60.0,
        api_key="sk-secret",
        base_url="",
        github_config={"api_key": "ghp"},
        model="opencode/kimi-k3",
        variant="",
    )
    base.update(overrides)
    return OpenCodeRunRequest(**base)


class TestOpenCodeRunCommand(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(cli_command="opencode", workspace_root="/tmp/heym-oc-ws")

    def test_run_command_shape(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        self.assertEqual(cmd[0], "opencode")
        self.assertEqual(cmd[1], "run")
        self.assertIn("--format", cmd)
        self.assertEqual(cmd[cmd.index("--format") + 1], "json")
        self.assertEqual(cmd[cmd.index("--model") + 1], "opencode/kimi-k3")
        self.assertEqual(cmd[cmd.index("--agent") + 1], "build")
        self.assertNotIn("--variant", cmd)
        self.assertIn("Task:", cmd[-1])
        self.assertIn("Do NOT run git", cmd[-1])
        self.assertIn("bun install", cmd[-1])
        self.assertIn("PR_TITLE:", cmd[-1])
        self.assertNotIn("./check.sh", cmd[-1])
        self.assertNotIn("Do NOT install package managers", cmd[-1])

    def test_run_command_states_pull_request_content_policy(self):
        prompt = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)[-1]
        self.assertIn(pr_publish.PR_CONTENT_POLICY, prompt)
        self.assertIn("## Change Summary", prompt)

    def test_run_command_emphasizes_mandatory_pr_title(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        prompt = cmd[-1]
        self.assertIn("PR metadata is MANDATORY", prompt)
        self.assertIn("good PR title is specific", prompt)
        self.assertIn("Bad titles are generic", prompt)
        self.assertIn("## Change Summary", prompt)

    def test_run_command_includes_screenshot_instructions(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        prompt = cmd[-1]
        self.assertIn("MUST save at least one PNG screenshot", prompt)
        self.assertIn("frontend/.e2e-artifacts/", prompt)
        self.assertIn("Do not commit screenshot binaries", prompt)

    def test_run_command_forbids_ending_on_screenshot_announcement(self):
        # Regression for the observed "…Now let me take a screenshot" early stop.
        prompt = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)[-1]
        self.assertIn("Capture screenshots BEFORE you write your final message", prompt)
        self.assertIn("Now let me take a screenshot", prompt)

    def test_build_run_command_prompt_override(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS, prompt="FINISH NOW")
        self.assertEqual(cmd[-1], "FINISH NOW")

    def test_run_command_pins_workspace_dir(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        self.assertEqual(cmd[cmd.index("--dir") + 1], str(_WS))

    def test_run_command_includes_variant(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(variant="high"), _WS)
        self.assertEqual(cmd[cmd.index("--variant") + 1], "high")

    def test_run_command_uses_wrapper_cli(self):
        svc = OpenCodeRunnerService(
            cli_command="/usr/local/bin/heym-opencode-docker", workspace_root="/tmp/x"
        )
        cmd = svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        self.assertEqual(cmd[0], "/usr/local/bin/heym-opencode-docker")


class TestOpenCodeAuthConfig(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_write_config_writes_auth_and_opencode_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.svc._write_opencode_config(
                home,
                api_key="sk-secret",
                base_url="https://opencode.ai/zen/go/v1",
                model="opencode/kimi-k3",
            )
            auth = json.loads((home / ".local" / "share" / "opencode" / "auth.json").read_text())
            self.assertEqual(auth["opencode"], {"type": "api", "key": "sk-secret"})
            cfg = json.loads((home / ".config" / "opencode" / "opencode.json").read_text())
            self.assertEqual(cfg["permission"]["edit"], "allow")
            self.assertEqual(cfg["permission"]["bash"], "allow")
            self.assertEqual(cfg["model"], "opencode/kimi-k3")
            options = cfg["provider"]["opencode"]["options"]
            self.assertEqual(options["baseURL"], "https://opencode.ai/zen/go/v1")
            self.assertEqual(options["apiKey"], "sk-secret")

    def test_default_model_when_empty(self):
        self.assertEqual(self.svc._resolve_model(""), "opencode/kimi-k3")
        self.assertEqual(
            self.svc._resolve_model("opencode/deepseek-v4-pro"), "opencode/deepseek-v4-pro"
        )


class TestOpenCodeParser(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_parse_extracts_last_assistant_text(self):
        stdout = "\n".join(
            [
                json.dumps({"type": "message.updated", "role": "assistant", "text": "thinking"}),
                json.dumps({"role": "assistant", "text": "Implemented the change."}),
            ]
        )
        result = self.svc.parse_events(stdout)
        self.assertEqual(result.summary, "Implemented the change.")
        self.assertEqual(result.status, "completed")

    def test_parse_tolerates_non_json_lines(self):
        stdout = "not json\n" + json.dumps({"role": "assistant", "text": "Done."})
        self.assertEqual(self.svc.parse_events(stdout).summary, "Done.")

    def test_parse_extracts_pr_title_line(self):
        stdout = json.dumps(
            {
                "role": "assistant",
                "text": (
                    "Moved the chat list toggle before History.\n\n"
                    "PR_TITLE: Reorder mobile chat header actions"
                ),
            }
        )
        result = self.svc.parse_events(stdout)
        self.assertEqual(result.pull_request_title, "Reorder mobile chat header actions")
        self.assertEqual(result.summary, "Moved the chat list toggle before History.")
        self.assertNotIn("PR_TITLE:", result.summary)

    def test_parse_ignores_user_role(self):
        stdout = json.dumps({"role": "user", "text": "the task"})
        self.assertNotEqual(self.svc.parse_events(stdout).summary, "the task")

    def test_parse_empty_gives_default_summary(self):
        result = self.svc.parse_events("")
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.summary)

    def test_parse_fallback_summary_never_echoes_the_task_prompt(self):
        result = self.svc.parse_events("")
        self.assertEqual(result.summary, "OpenCode completed without a final assistant message.")


class TestOpenCodePrMetadataNormalization(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_ensure_meaningful_pr_title_prefers_agent_title(self):
        result = OpenCodeRunResult(
            summary="Did some work.",
            pull_request_title="Fix OpenCode fallback summary logic",
        )
        title = self.svc._ensure_meaningful_pr_title(result)
        self.assertEqual(title, "Fix OpenCode fallback summary logic")

    def test_ensure_meaningful_pr_title_derives_from_summary(self):
        result = OpenCodeRunResult(
            summary="Implemented the mobile drawer fix.", pull_request_title=""
        )
        result.publish_summary = self.svc._publishable_summary(result)
        title = self.svc._ensure_meaningful_pr_title(result)
        self.assertEqual(title, "Implemented the mobile drawer fix.")

    def test_ensure_meaningful_pr_title_last_resort_fallback(self):
        result = OpenCodeRunResult(summary="Done.", pull_request_title="")
        title = self.svc._ensure_meaningful_pr_title(result)
        self.assertEqual(title, "Apply OpenCode changes")

    def test_ensure_meaningful_pr_title_skips_missing_message_sentinel(self):
        result = OpenCodeRunResult(
            summary="OpenCode completed without a final assistant message.",
            pull_request_title="",
        )
        self.assertEqual(self.svc._ensure_meaningful_pr_title(result), "Apply OpenCode changes")

    def test_ensure_pr_body_wraps_summary_in_change_summary_section(self):
        result = OpenCodeRunResult(summary="Reordered the mobile header actions.")
        result.publish_summary = self.svc._publishable_summary(result)
        body = self.svc._ensure_pr_body(result)
        self.assertEqual(body, "## Change Summary\n\nReordered the mobile header actions.")

    def test_ensure_pr_body_keeps_existing_body(self):
        long_body = "This is a sufficiently long PR body with enough context to remain unchanged."
        result = OpenCodeRunResult(summary="Summary text.", pull_request_body=long_body)
        self.assertEqual(self.svc._ensure_pr_body(result), long_body)

    def test_normalize_pr_metadata_never_publishes_the_task_prompt(self):
        result = OpenCodeRunResult(summary="Done.", pull_request_title="Update")
        self.svc._normalize_pr_metadata(result, "Fix OpenCode fallback summary logic")
        self.assertEqual(result.pull_request_title, "Apply OpenCode changes")
        self.assertNotIn("## Task", result.pull_request_body)
        self.assertNotIn("Fix OpenCode fallback summary logic", result.pull_request_body)

    def test_normalize_pr_metadata_strips_task_section_from_agent_body(self):
        prompt = "Move the chat list toggle before History on mobile, then run the e2e suite."
        result = OpenCodeRunResult(
            summary="Reordered the mobile chat header actions.",
            pull_request_title="Reorder mobile chat header actions",
            pull_request_body=(
                "## Change Summary\n\nReordered the mobile chat header actions.\n\n"
                f"## Task\n\n{prompt}\n"
            ),
        )
        self.svc._normalize_pr_metadata(result, prompt)
        self.assertNotIn("## Task", result.pull_request_body)
        self.assertNotIn("run the e2e suite", result.pull_request_body)
        self.assertIn("Reordered the mobile chat header actions.", result.pull_request_body)

    def test_normalize_pr_metadata_strips_prompt_echo_from_summary(self):
        prompt = "Move the chat list toggle before History on mobile, then run the e2e suite."
        result = OpenCodeRunResult(summary=f"{prompt}\n\nReordered the header actions.")
        self.svc._normalize_pr_metadata(result, prompt)
        self.assertEqual(result.summary, "Reordered the header actions.")


class TestOpenCodeExecFailureFormatting(unittest.TestCase):
    def test_event_stream_is_not_dumped_as_error(self) -> None:
        stdout = "\n".join(
            [
                json.dumps({"type": "step_start", "sessionID": "ses_1"}),
                json.dumps(
                    {
                        "type": "tool_use",
                        "part": {
                            "tool": "bash",
                            "state": {
                                "status": "completed",
                                "title": "./check.sh",
                                "output": "FATAL ERROR: JavaScript heap out of memory",
                                "metadata": {"exit": 134},
                            },
                        },
                    }
                ),
                json.dumps({"type": "step_start", "sessionID": "ses_1"}),
            ]
        )
        detail = OpenCodeRunnerService._format_exec_failure(137, stdout, "")
        self.assertNotIn('"sessionID"', detail)
        self.assertIn("bash: ./check.sh failed", detail)
        self.assertIn("heap out of memory", detail)
        self.assertIn("exited with code 137", detail)
        self.assertIn("OOM", detail)
        self.assertNotIn("avoid heavy ./check.sh", detail)

    def test_plain_stderr_is_preserved(self) -> None:
        detail = OpenCodeRunnerService._format_exec_failure(1, "", "opencode: command failed")
        self.assertEqual(detail, "opencode: command failed")


class TestOpenCodeCreatePr(unittest.TestCase):
    def setUp(self):
        self.runner = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")
        self.workspace = Path("/tmp/ws")
        self.request = _request(publish_mode="open_pr", branch_name="opencode/run")

    def test_create_pr_publishes_change_summary_without_the_task_prompt(self):
        request = _request(
            publish_mode="open_pr",
            branch_name="opencode/run",
            task_prompt="Fix the flaky mobile execution-highlight e2e spec before Friday.",
        )
        result = OpenCodeRunResult(
            status="completed",
            summary="Ran the highlights spec through the keyboard shortcut instead of the menu.",
            pull_request_title="Update",
            pull_request_body="",
            changed_files=["a.vue"],
        )
        self.runner._normalize_pr_metadata(result, request.task_prompt)
        self.runner._screenshot_body = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda _ws, _req, res, _head: res.pull_request_body
        )
        gh = MagicMock()
        gh.create_pull_request.return_value = {
            "number": 1,
            "html_url": "https://github.com/acme/app/pull/1",
        }

        with patch("app.services.opencode_runner_service.GitHubService", return_value=gh) as gh_cls:
            url = self.runner._create_pr(
                self.workspace, request, result, "opencode/run", draft=False
            )

        self.assertEqual(url, "https://github.com/acme/app/pull/1")
        gh_cls.assert_called()
        title = gh.create_pull_request.call_args.args[2]
        body = gh.create_pull_request.call_args.kwargs["body"]
        self.assertNotEqual(title, "Update")
        self.assertIn("keyboard shortcut", title.lower())
        self.assertIn("## Change Summary", body)
        self.assertNotIn("## Task", body)
        self.assertNotIn("before friday", body.lower())


class TestOpenCodePushBranch(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")
        self.runner._run_command = MagicMock()  # type: ignore[method-assign]
        self.workspace = Path("/tmp/ws")
        self.request = _request(publish_mode="update_existing_pr", branch_name="opencode/run")

    def test_existing_remote_branch_rebase_includes_git_identity(self) -> None:
        self.runner._git_output = MagicMock(  # type: ignore[method-assign]
            return_value="abc123\trefs/heads/opencode/run\n"
        )

        self.runner._push_branch(self.workspace, self.request, "opencode/run")

        commands = [call.args[0] for call in self.runner._run_command.call_args_list]
        self.assertEqual(
            commands[1],
            [
                "git",
                *pr_publish.git_identity_args(
                    settings.opencode_git_author_name, settings.opencode_git_author_email
                ),
                "pull",
                "--rebase",
                "--strategy-option=theirs",
                "origin",
                "opencode/run",
            ],
        )
        self.assertEqual(commands[2], ["git", "push", "-u", "origin", "opencode/run"])


class TestOpenCodeNarrationIsNotPublished(unittest.TestCase):
    """Regression for PR #397: mid-run narration became the PR title and description."""

    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    @staticmethod
    def _stream(*texts: str) -> str:
        return "\n".join(json.dumps({"role": "assistant", "text": text}) for text in texts)

    def test_change_summary_section_wins_over_later_narration(self):
        stdout = self._stream(
            "Reading the workflow store.",
            "## Change Summary\n\nAdd a stale-save override dialog.\n\nPR_TITLE: Add stale-save"
            " override dialog",
            "Both pass. Let me do a final review of the complete changes:",
        )
        result = self.svc.parse_events(stdout)
        self.assertEqual(result.summary, "Add a stale-save override dialog.")
        self.assertEqual(result.pull_request_title, "Add stale-save override dialog")

    def test_narration_only_run_falls_back_to_the_changed_file_list(self):
        stdout = self._stream("Both pass. Let me do a final review of the complete changes:")
        result = self.svc.parse_events(stdout)
        result.changed_files = ["frontend/src/stores/workflow.ts", "frontend/src/views/Editor.vue"]

        self.svc._normalize_pr_metadata(result, "add an override dialog for stale saves")

        self.assertEqual(result.pull_request_title, "Apply OpenCode changes")
        self.assertNotIn("Let me do a final review", result.pull_request_body)
        self.assertIn("`frontend/src/stores/workflow.ts`", result.pull_request_body)
        # The raw message stays on the node output so the run is still debuggable in Heym.
        self.assertIn("Let me do a final review", result.summary)
        self.assertEqual(result.publish_summary, "")

    def test_narration_never_reaches_the_commit_message(self):
        result = OpenCodeRunResult(
            summary="Both pass. Let me do a final review of the complete changes:",
            changed_files=["a.ts"],
        )
        self.svc._normalize_pr_metadata(result, "")
        self.svc._run_command = MagicMock()  # type: ignore[method-assign]

        self.svc._commit_changes(Path("/tmp/ws"), "opencode/run", result, new_branch=True)

        commit_cmd = self.svc._run_command.call_args_list[-1].args[0]
        self.assertIn("Apply OpenCode changes", commit_cmd)
        self.assertNotIn("Both pass. Let me do a final review of the complete changes:", commit_cmd)

    def test_changed_file_list_is_capped(self):
        result = OpenCodeRunResult(summary="", changed_files=[f"file{i}.ts" for i in range(25)])
        self.svc._normalize_pr_metadata(result, "")
        self.assertIn("…and 5 more file(s)", result.pull_request_body)


class TestOpenCodeResolveExistingPrBranch(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_resolves_existing_pr_branch(self):
        request = _request(publish_mode="open_or_update_pr", branch_name="reuse-branch-from-pr-401")
        gh = MagicMock()
        with (
            patch("app.services.opencode_runner_service.GitHubService", return_value=gh),
            patch.object(
                pr_publish,
                "resolve_update_existing_pr_branch",
                return_value="feat/running-workflow-count-badge",
            ),
        ):
            branch = self.svc._resolve_existing_pr_branch(request)
        self.assertEqual(branch, "feat/running-workflow-count-badge")
        gh.close.assert_called_once()


class TestOpenCodeFinishIncompleteRun(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")
        self.svc._git_output = MagicMock(return_value="")  # type: ignore[method-assign]
        self.ws = Path("/tmp/ws")
        self.home = Path("/tmp/ws.oc-home")

    @staticmethod
    def _stream(*texts: str) -> str:
        return "\n".join(json.dumps({"role": "assistant", "text": text}) for text in texts)

    def test_reruns_and_updates_when_ui_change_has_no_screenshot(self):
        # Real PR #402 case: agent stopped right before capturing a screenshot of a UI change.
        result = OpenCodeRunResult(
            status="completed",
            summary="All checks pass - 2406 tests, 0 failures. Now let me take a screenshot.",
            changed_files=["frontend/src/views/DashboardView.vue"],
        )
        self.svc._normalize_pr_metadata(result, "")
        self.svc._changed_files = MagicMock(  # type: ignore[method-assign]
            return_value=["frontend/src/views/DashboardView.vue"]
        )
        finishing_stdout = self._stream(
            "## Change Summary\n\nAdd a live running-workflow count badge.\n\n"
            "PR_TITLE: Add running-workflow count badge"
        )
        self.svc._exec_opencode = MagicMock(return_value=finishing_stdout)  # type: ignore[method-assign]

        with patch.object(pr_publish, "discover_pr_screenshots", return_value=[]):
            self.svc._finish_incomplete_run(
                self.ws, self.home, _request(), "opencode/kimi-k3", result
            )

        self.svc._exec_opencode.assert_called_once()
        override = self.svc._exec_opencode.call_args.kwargs["prompt_override"]
        self.assertIn(pr_publish.FINISHING_PASS_PREAMBLE, override)
        self.assertEqual(result.pull_request_title, "Add running-workflow count badge")
        # A UI change with no screenshot after the pass gets a visible note.
        self.assertIn("## Screenshots", result.pull_request_body)

    def test_no_rerun_when_summary_and_screenshot_present(self):
        result = OpenCodeRunResult(
            status="completed",
            summary="Add a badge.",
            changed_files=["frontend/src/views/DashboardView.vue"],
        )
        self.svc._normalize_pr_metadata(result, "")
        self.svc._exec_opencode = MagicMock()  # type: ignore[method-assign]

        with patch.object(
            pr_publish,
            "discover_pr_screenshots",
            return_value=[Path("/tmp/ws/frontend/.e2e-artifacts/shot.png")],
        ):
            self.svc._finish_incomplete_run(
                self.ws, self.home, _request(), "opencode/kimi-k3", result
            )

        self.svc._exec_opencode.assert_not_called()


class TestOpenCodeOpenOrUpdatePublish(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")
        self.svc._commit_changes = MagicMock()  # type: ignore[method-assign]
        self.svc._push_branch = MagicMock()  # type: ignore[method-assign]
        self.svc._current_branch = MagicMock(return_value="opencode/run")  # type: ignore[method-assign]
        self.svc._create_pr = MagicMock()  # type: ignore[method-assign]
        self.svc._update_pr_body_with_screenshots = MagicMock()  # type: ignore[method-assign]
        self.ws = Path("/tmp/ws")

    def test_open_or_update_updates_existing_pr(self):
        self.svc._open_pr_url_for_head = MagicMock(  # type: ignore[method-assign]
            return_value="https://github.com/acme/app/pull/42"
        )
        result = OpenCodeRunResult(status="completed", summary="done", changed_files=["a.vue"])

        self.svc._publish(self.ws, _request(publish_mode="open_or_update_pr"), result)

        self.svc._update_pr_body_with_screenshots.assert_called_once()
        self.svc._create_pr.assert_not_called()
        self.assertEqual(result.pull_request_url, "https://github.com/acme/app/pull/42")

    def test_open_or_update_opens_new_pr_when_none_exists(self):
        self.svc._open_pr_url_for_head = MagicMock(return_value=None)  # type: ignore[method-assign]
        self.svc._create_pr = MagicMock(return_value="https://github.com/acme/app/pull/99")  # type: ignore[method-assign]
        result = OpenCodeRunResult(status="completed", summary="done", changed_files=["a.vue"])

        self.svc._publish(self.ws, _request(publish_mode="open_or_update_pr"), result)

        self.svc._create_pr.assert_called_once()
        self.assertEqual(result.pull_request_url, "https://github.com/acme/app/pull/99")
