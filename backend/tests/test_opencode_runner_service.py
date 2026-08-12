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
        model="opencode-go/kimi-k3",
        variant="",
    )
    base.update(overrides)
    return OpenCodeRunRequest(**base)


class TestOpenCodeRunCommand(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(cli_command="opencode", workspace_root="/tmp/heym-oc-ws")

    def test_run_command_shape(self):
        cmd = self.svc.build_run_command("opencode-go/kimi-k3", _request(), _WS)
        self.assertEqual(cmd[0], "opencode")
        self.assertEqual(cmd[1], "run")
        self.assertIn("--format", cmd)
        self.assertEqual(cmd[cmd.index("--format") + 1], "json")
        self.assertEqual(cmd[cmd.index("--model") + 1], "opencode-go/kimi-k3")
        self.assertEqual(cmd[cmd.index("--agent") + 1], "build")
        self.assertNotIn("--variant", cmd)
        self.assertIn("Task:", cmd[-1])
        self.assertIn("Do NOT run git", cmd[-1])
        self.assertIn("bun install", cmd[-1])
        self.assertIn("PR_TITLE:", cmd[-1])
        self.assertNotIn("./check.sh", cmd[-1])
        self.assertNotIn("Do NOT install package managers", cmd[-1])

    def test_run_command_states_pull_request_content_policy(self):
        prompt = self.svc.build_run_command("opencode-go/kimi-k3", _request(), _WS)[-1]
        self.assertIn(pr_publish.PR_CONTENT_POLICY, prompt)
        self.assertIn("## Change Summary", prompt)

    def test_run_command_emphasizes_mandatory_pr_title(self):
        cmd = self.svc.build_run_command("opencode-go/kimi-k3", _request(), _WS)
        prompt = cmd[-1]
        self.assertIn("PR metadata is MANDATORY", prompt)
        self.assertIn("good PR title is specific", prompt)
        self.assertIn("Bad titles are generic", prompt)
        self.assertIn("## Change Summary", prompt)

    def test_run_command_includes_screenshot_instructions(self):
        cmd = self.svc.build_run_command("opencode-go/kimi-k3", _request(), _WS)
        prompt = cmd[-1]
        self.assertIn("MUST save at least one PNG screenshot", prompt)
        self.assertIn("frontend/.e2e-artifacts/", prompt)
        self.assertIn("Do not commit screenshot binaries", prompt)

    def test_run_command_forbids_ending_on_screenshot_announcement(self):
        # Regression for the observed "…Now let me take a screenshot" early stop.
        prompt = self.svc.build_run_command("opencode-go/kimi-k3", _request(), _WS)[-1]
        self.assertIn("Capture screenshots BEFORE you write your final message", prompt)
        self.assertIn("Now let me take a screenshot", prompt)

    def test_build_run_command_prompt_override(self):
        cmd = self.svc.build_run_command(
            "opencode-go/kimi-k3", _request(), _WS, prompt="FINISH NOW"
        )
        self.assertEqual(cmd[-1], "FINISH NOW")

    def test_run_command_pins_workspace_dir(self):
        cmd = self.svc.build_run_command("opencode-go/kimi-k3", _request(), _WS)
        self.assertEqual(cmd[cmd.index("--dir") + 1], str(_WS))

    def test_run_command_timeout_stays_value_error_for_git_recovery(self) -> None:
        import subprocess

        with patch(
            "app.services.opencode_runner_service.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git", "clone"], timeout=1),
        ):
            with self.assertRaises(ValueError) as ctx:
                self.svc._run_command(["git", "clone", "repo"], cwd=_WS)
        self.assertIn("timed out", str(ctx.exception))

    def test_opencode_exec_timeout_raises_timeout_error(self) -> None:
        from app.services.opencode_runner_service import _CliOutcome

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            home = Path(f"{tmp}.oc-home")
            home.mkdir()
            outcome = _CliOutcome(returncode=-9, stdout="", stderr="", timed_out=True)
            with patch(
                "app.services.opencode_runner_service.subprocess.Popen",
                return_value=MagicMock(),
            ):
                with patch.object(self.svc, "_supervise_cli", return_value=outcome):
                    # subprocess.run() also builds a Popen, so the patch above would break the
                    # container cleanup call.
                    with patch.object(self.svc, "_remove_runner_container"):
                        with self.assertRaises(TimeoutError) as ctx:
                            self.svc._exec_opencode(
                                workspace,
                                home,
                                _request(timeout_seconds=1),
                                "opencode-go/kimi-k3",
                            )
        self.assertIn("OpenCode timed out", str(ctx.exception))

    def test_run_command_includes_variant(self):
        cmd = self.svc.build_run_command("opencode-go/kimi-k3", _request(variant="high"), _WS)
        self.assertEqual(cmd[cmd.index("--variant") + 1], "high")

    def test_run_command_uses_wrapper_cli(self):
        svc = OpenCodeRunnerService(
            cli_command="/usr/local/bin/heym-opencode-docker", workspace_root="/tmp/x"
        )
        cmd = svc.build_run_command("opencode-go/kimi-k3", _request(), _WS)
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
                model="opencode-go/kimi-k3",
            )
            auth = json.loads((home / ".local" / "share" / "opencode" / "auth.json").read_text())
            self.assertEqual(auth["opencode-go"], {"type": "api", "key": "sk-secret"})
            cfg = json.loads((home / ".config" / "opencode" / "opencode.json").read_text())
            self.assertEqual(cfg["permission"]["edit"], "allow")
            self.assertEqual(cfg["permission"]["bash"], "allow")
            self.assertEqual(cfg["model"], "opencode-go/kimi-k3")
            options = cfg["provider"]["opencode-go"]["options"]
            self.assertEqual(options["baseURL"], "https://opencode.ai/zen/go/v1")
            self.assertEqual(options["apiKey"], "sk-secret")

    def test_default_model_when_empty(self):
        self.assertEqual(self.svc._resolve_model(""), "opencode-go/kimi-k3")
        self.assertEqual(
            self.svc._resolve_model("opencode-go/deepseek-v4-pro"), "opencode-go/deepseek-v4-pro"
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
                self.ws, self.home, _request(), "opencode-go/kimi-k3", result
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
                self.ws, self.home, _request(), "opencode-go/kimi-k3", result
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


class TestOpenCodeGoProvider(unittest.TestCase):
    """The Go gateway is its own CLI provider (``opencode-go``), not plain ``opencode``."""

    def setUp(self):
        self.svc = OpenCodeRunnerService(cli_command="opencode", workspace_root="/tmp/heym-oc-ws")

    def test_legacy_model_id_is_rewritten(self):
        self.assertEqual(self.svc._resolve_model("opencode/kimi-k3"), "opencode-go/kimi-k3")
        self.assertEqual(self.svc._resolve_model("kimi-k3"), "opencode-go/kimi-k3")

    def test_run_command_qualifies_legacy_model(self):
        cmd = self.svc.build_run_command("opencode/deepseek-v4-pro", _request(), _WS)
        self.assertEqual(cmd[cmd.index("--model") + 1], "opencode-go/deepseek-v4-pro")

    def test_run_command_enables_cli_logs(self):
        cmd = self.svc.build_run_command("opencode-go/kimi-k3", _request(), _WS)
        self.assertIn("--print-logs", cmd)
        self.assertEqual(cmd[cmd.index("--log-level") + 1], "ERROR")

    def test_config_uses_go_provider_and_trims_base_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.svc._write_opencode_config(
                home,
                api_key="sk-secret",
                base_url="https://opencode.ai/zen/go/v1/",
                model="opencode/kimi-k3",
            )
            auth = json.loads((home / ".local" / "share" / "opencode" / "auth.json").read_text())
            cfg = json.loads((home / ".config" / "opencode" / "opencode.json").read_text())
        self.assertEqual(auth["opencode-go"], {"type": "api", "key": "sk-secret"})
        self.assertNotIn("opencode", auth)
        self.assertEqual(cfg["model"], "opencode-go/kimi-k3")
        # A trailing slash would produce ".../v1//chat/completions".
        self.assertEqual(
            cfg["provider"]["opencode-go"]["options"]["baseURL"],
            "https://opencode.ai/zen/go/v1",
        )


class TestOpenCodeCliSupervision(unittest.TestCase):
    """The CLI can report a fatal provider error and then never exit."""

    def setUp(self):
        self.svc = OpenCodeRunnerService(cli_command="opencode", workspace_root="/tmp/heym-oc-ws")

    @staticmethod
    def _spawn(script: str):
        import subprocess
        import sys

        return subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

    def test_normal_exit_returns_streams(self):
        process = self._spawn(
            'import sys; sys.stdout.write(\'{"type":"step"}\\n\'); sys.stdout.flush()'
        )
        outcome = self.svc._supervise_cli(process, timeout_seconds=30)
        self.assertEqual(outcome.returncode, 0)
        self.assertIn('"type":"step"', outcome.stdout)
        self.assertFalse(outcome.timed_out)
        self.assertEqual(outcome.stalled_reason, "")

    def test_fatal_stream_error_without_exit_is_ended(self):
        # OpenCode Zen's "Monthly usage limit reached": logged, no JSON event, never exits.
        script = (
            "import sys, time\n"
            'sys.stderr.write(\'timestamp=1 level=ERROR message="stream error" '
            'providerID=opencode-go small=false error.error="AI_APICallError: Monthly usage limit '
            "reached.\"\\n')\n"
            "sys.stderr.flush()\n"
            "time.sleep(600)\n"
        )
        process = self._spawn(script)
        with patch("app.services.opencode_runner_service._FATAL_ERROR_GRACE_SECONDS", 1.0):
            outcome = self.svc._supervise_cli(process, timeout_seconds=120)
        self.assertIn("Monthly usage limit reached.", outcome.stalled_reason)
        self.assertIn("never exited", outcome.stalled_reason)
        self.assertFalse(outcome.timed_out)
        self.assertIsNotNone(process.poll())

    def test_title_agent_error_is_not_fatal(self):
        # small=true is the title agent; the CLI recovers from those on its own.
        script = (
            "import sys\n"
            'sys.stderr.write(\'timestamp=1 level=ERROR message="stream error" small=true '
            'error.error="AI_APICallError: Model gpt-5-nano is not supported"\\n\')\n'
            "sys.stderr.flush()\n"
            'sys.stdout.write(\'{"type":"step"}\\n\')\n'
        )
        process = self._spawn(script)
        with patch("app.services.opencode_runner_service._FATAL_ERROR_GRACE_SECONDS", 1.0):
            outcome = self.svc._supervise_cli(process, timeout_seconds=30)
        self.assertEqual(outcome.stalled_reason, "")
        self.assertEqual(outcome.returncode, 0)

    def test_silent_process_is_ended_as_unresponsive(self):
        process = self._spawn("import time; time.sleep(600)")
        with patch("app.services.opencode_runner_service._STALL_TIMEOUT_SECONDS", 1.0):
            outcome = self.svc._supervise_cli(process, timeout_seconds=120)
        self.assertIn("unresponsive", outcome.stalled_reason)
        self.assertIsNotNone(process.poll())

    def test_timeout_is_reported_and_process_killed(self):
        process = self._spawn("import time; time.sleep(600)")
        outcome = self.svc._supervise_cli(process, timeout_seconds=1)
        self.assertTrue(outcome.timed_out)
        self.assertIsNotNone(process.poll())


class TestOpenCodeFailureDetail(unittest.TestCase):
    def test_provider_error_from_logs_replaces_oom_guess(self):
        stderr = (
            'timestamp=1 level=ERROR message="stream error" small=false '
            'error.error="AI_APICallError: Invalid API key."\n'
        )
        stdout = json.dumps({"type": "error", "sessionID": "ses_1", "error": {"name": "X"}})
        detail = OpenCodeRunnerService._format_exec_failure(1, stdout, stderr)
        self.assertEqual(detail, "AI_APICallError: Invalid API key.")
        self.assertNotIn("OOM", detail)

    def test_nested_error_event_message_is_read(self):
        stdout = json.dumps(
            {
                "type": "error",
                "sessionID": "ses_1",
                "error": {
                    "name": "UnknownError",
                    "data": {"message": "Unexpected server error.", "ref": "err_1"},
                },
            }
        )
        detail = OpenCodeRunnerService._format_exec_failure(1, stdout, "")
        self.assertEqual(detail, "UnknownError: Unexpected server error.")

    def test_title_agent_log_error_is_ignored(self):
        stderr = (
            'timestamp=1 level=ERROR message="stream error" small=true '
            'error.error="AI_APICallError: Model gpt-5-nano is not supported"\n'
        )
        self.assertEqual(OpenCodeRunnerService._extract_log_error(stderr), "")


class TestOpenCodeCancellation(unittest.TestCase):
    """A stopped workflow must end the CLI instead of waiting it out."""

    @staticmethod
    def _spawn():
        import subprocess
        import sys

        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

    def test_cancel_ends_the_run_and_kills_the_process(self):
        svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws", is_cancelled=lambda: True)
        process = self._spawn()
        outcome = svc._supervise_cli(process, timeout_seconds=600)
        self.assertTrue(outcome.cancelled)
        self.assertFalse(outcome.timed_out)
        self.assertIsNotNone(process.poll())

    def test_cancel_reaps_the_server_the_cli_spawned(self):
        import os
        import subprocess
        import sys
        import time

        script = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "print('PID', child.pid, flush=True)\n"
            "time.sleep(60)\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws", is_cancelled=lambda: True)
        outcome = svc._supervise_cli(process, timeout_seconds=60)
        child_pid = int(outcome.stdout.split()[1])
        time.sleep(0.5)
        with self.assertRaises(OSError):
            os.kill(child_pid, 0)

    def test_broken_cancel_probe_does_not_fail_the_run(self):
        def _boom() -> bool:
            raise RuntimeError("registry down")

        svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws", is_cancelled=_boom)
        self.assertFalse(svc._cancelled())

    def test_exec_raises_cancelled_error(self):
        from app.services.opencode_runner_service import OpenCodeCancelledError, _CliOutcome

        svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            home = Path(f"{tmp}.oc-home")
            home.mkdir()
            outcome = _CliOutcome(returncode=-15, stdout="", stderr="", cancelled=True)
            with patch(
                "app.services.opencode_runner_service.subprocess.Popen", return_value=MagicMock()
            ):
                with patch.object(svc, "_supervise_cli", return_value=outcome):
                    with patch.object(svc, "_remove_runner_container"):
                        with self.assertRaises(OpenCodeCancelledError):
                            svc._exec_opencode(workspace, home, _request(), "opencode-go/kimi-k3")

    def test_failed_run_cleans_up_its_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            svc = OpenCodeRunnerService(workspace_root=root)
            with patch.object(svc, "_run_in_workspace", side_effect=ValueError("boom")):
                with self.assertRaises(ValueError):
                    svc.run_task(_request())
            leftovers = [p.name for p in Path(root).iterdir()]
        self.assertEqual(leftovers, [])


class TestOpenCodeRunnerContainerCleanup(unittest.TestCase):
    """Killing ``docker run`` leaves the container alive; it has to be removed by name."""

    def test_removes_container_by_run_id(self):
        with patch(
            "app.services.opencode_runner_service.shutil.which", return_value="/usr/bin/docker"
        ):
            with patch("app.services.opencode_runner_service.subprocess.run") as run:
                OpenCodeRunnerService._remove_runner_container("abc123")
        self.assertEqual(run.call_args[0][0], ["docker", "rm", "-f", "heym-opencode-abc123"])

    def test_no_docker_is_a_noop(self):
        with patch("app.services.opencode_runner_service.shutil.which", return_value=None):
            with patch("app.services.opencode_runner_service.subprocess.run") as run:
                OpenCodeRunnerService._remove_runner_container("abc123")
        run.assert_not_called()

    def test_exec_passes_run_id_to_the_wrapper(self):
        svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")
        from app.services.opencode_runner_service import _CliOutcome

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            home = Path(f"{tmp}.oc-home")
            home.mkdir()
            with patch(
                "app.services.opencode_runner_service.subprocess.Popen", return_value=MagicMock()
            ) as popen:
                with patch.object(
                    svc,
                    "_supervise_cli",
                    return_value=_CliOutcome(returncode=0, stdout="{}", stderr=""),
                ):
                    with patch.object(svc, "_remove_runner_container") as remove:
                        svc._exec_opencode(workspace, home, _request(), "opencode-go/kimi-k3")
        run_id = popen.call_args.kwargs["env"]["HEYM_OPENCODE_RUN_ID"]
        self.assertTrue(run_id)
        remove.assert_called_once_with(run_id)
