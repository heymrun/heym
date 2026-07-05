import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.services.codex_runner_service import (
    _CODEX_REMOTE_PUBLISH_MODES,
    CODEX_FINAL_OUTPUT_SCHEMA,
    CODEX_PUBLISH_MODES,
    CodexRunnerService,
    CodexRunRequest,
    CodexRunResult,
)


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
        setup_command="",
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
        self.assertIn("translate the readme", prompt)

    def test_resume_prompt_forbids_git_and_github(self) -> None:
        prompt = CodexRunnerService._build_resume_prompt("use port 1234")
        self.assertIn("Do NOT run git", prompt)
        self.assertIn("use port 1234", prompt)


class TestCommitMessage(unittest.TestCase):
    def test_commit_title_keeps_full_single_sentence(self) -> None:
        # A long run-on summary (no early period) is kept whole, not cut at ~72 chars.
        summary = "Added n8n10 to docker-compose.yml using host port 2245, internal port 3032"
        result = CodexRunResult(status="completed", summary=summary)
        self.assertEqual(CodexRunnerService._commit_title(result), summary)

    def test_commit_title_keeps_short_summary(self) -> None:
        result = CodexRunResult(status="completed", summary="Fix typo")
        self.assertEqual(CodexRunnerService._commit_title(result), "Fix typo")

    def test_commit_title_prefers_pull_request_title(self) -> None:
        result = CodexRunResult(
            status="completed",
            summary="A long detailed summary sentence describing everything that changed in depth.",
            pull_request_title="Add n8n10 service to compose and Traefik",
        )
        self.assertEqual(
            CodexRunnerService._commit_title(result), "Add n8n10 service to compose and Traefik"
        )

    def test_commit_title_uses_first_sentence(self) -> None:
        result = CodexRunResult(
            status="completed",
            summary="README.md translated. Headings, tables, notes localized; commands preserved.",
        )
        self.assertEqual(CodexRunnerService._commit_title(result), "README.md translated.")

    def test_commit_body_has_full_summary_and_validation(self) -> None:
        result = CodexRunResult(
            status="completed", summary="X" * 100, validation="ran docker compose config"
        )
        body = CodexRunnerService._commit_body(result)
        self.assertIn("X" * 100, body)
        self.assertIn("ran docker compose config", body)


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
