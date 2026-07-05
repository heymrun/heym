import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import get_masked_value, validate_credential_config
from app.db.models import CredentialType
from app.services.codex_followup_service import (
    build_codex_answer_output,
    ensure_codex_followup_is_actionable,
    is_codex_pending_execution,
)
from app.services.codex_runner_service import CodexJsonlParser, CodexRunResult
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import codex_node


class TestCodexCredentialValidation(unittest.TestCase):
    def test_codex_requires_access_token(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.codex, {})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("access_token", str(ctx.exception.detail))

    def test_codex_rejects_api_key(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(
                CredentialType.codex,
                {"access_token": "codex-token", "api_key": "sk-should-not-work"},
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("does not accept api_key", str(ctx.exception.detail))

    def test_codex_valid_config_masks_access_token(self) -> None:
        validate_credential_config(CredentialType.codex, {"access_token": "codex-secret-token"})
        self.assertEqual(
            get_masked_value(CredentialType.codex, {"access_token": "codex-secret-token"}),
            "codex-s**",
        )


class TestCodexJsonlParser(unittest.TestCase):
    def test_parse_completed_final_payload(self) -> None:
        stdout = "\n".join(
            [
                json.dumps({"thread_id": "thread-1", "usage": {"total_tokens": 123}}),
                json.dumps(
                    {
                        "result": {
                            "status": "completed",
                            "summary": "Fixed tests",
                            "validation": "npm test",
                        }
                    }
                ),
            ]
        )
        result = CodexJsonlParser().parse(stdout)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.summary, "Fixed tests")
        self.assertEqual(result.validation, "npm test")
        self.assertEqual(result.thread_id, "thread-1")
        self.assertEqual(result.usage, {"total_tokens": 123})

    def test_parse_needs_input_from_embedded_output(self) -> None:
        stdout = json.dumps(
            {
                "output": json.dumps(
                    {
                        "status": "needs_input",
                        "summary": "Need a decision",
                        "question": "Should I update the API contract?",
                    }
                )
            }
        )
        result = CodexJsonlParser().parse(stdout)
        self.assertEqual(result.status, "needs_input")
        self.assertEqual(result.question, "Should I update the API contract?")

    def test_parse_agent_message_final_payload(self) -> None:
        # codex exec 0.142.x emits the schema output as an agent_message item's text.
        stdout = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "thread-9"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": json.dumps(
                                {
                                    "status": "completed",
                                    "summary": "Translated the README to Turkish.",
                                    "validation": "make lint",
                                }
                            ),
                        },
                    }
                ),
                json.dumps({"type": "turn.completed", "usage": {"output_tokens": 12}}),
            ]
        )
        result = CodexJsonlParser().parse(stdout)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.summary, "Translated the README to Turkish.")
        self.assertEqual(result.validation, "make lint")
        self.assertEqual(result.thread_id, "thread-9")
        self.assertEqual(result.usage, {"output_tokens": 12})

    def test_parse_extracts_pull_request_fields(self) -> None:
        stdout = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps(
                        {
                            "status": "completed",
                            "summary": "Did the thing.",
                            "pull_request_title": "Add feature X",
                            "pull_request_body": "This PR adds X.",
                        }
                    ),
                },
            }
        )
        result = CodexJsonlParser().parse(stdout)
        self.assertEqual(result.pull_request_title, "Add feature X")
        self.assertEqual(result.pull_request_body, "This PR adds X.")

    def test_parse_agent_message_needs_input(self) -> None:
        stdout = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps(
                        {
                            "status": "needs_input",
                            "summary": "Need a decision",
                            "question": "Which port should n8n9 use?",
                        }
                    ),
                },
            }
        )
        result = CodexJsonlParser().parse(stdout)
        self.assertEqual(result.status, "needs_input")
        self.assertEqual(result.question, "Which port should n8n9 use?")

    def test_parse_invalid_status_defaults_to_completed(self) -> None:
        result = CodexJsonlParser().parse(
            json.dumps({"status": "error", "summary": "Something happened"})
        )
        self.assertEqual(result.status, "completed")


class TestCodexNodeHandler(unittest.TestCase):
    def _executor(self) -> SimpleNamespace:
        def evaluate_message_template(value: str, inputs: dict, _node_id: str) -> str:
            # Mirror the real footgun: a blank template resolves to str(inputs).
            if not value:
                return str(inputs)
            return value.replace("$input.text", str(inputs.get("text") or ""))

        def evaluate_nonempty_message_template(value: str, inputs: dict, _node_id: str) -> str:
            if not str(value or "").strip():
                return ""
            return evaluate_message_template(value, inputs, _node_id)

        return SimpleNamespace(
            execution_id="abc12345-0000",
            hitl_resume_context={},
            evaluate_message_template=evaluate_message_template,
            evaluate_nonempty_message_template=evaluate_nonempty_message_template,
        )

    def _ctx(self, node_data: dict, inputs: dict | None = None) -> NodeExecutionContext:
        return NodeExecutionContext(
            executor=self._executor(),
            node_id="codex-1",
            inputs=inputs or {"text": "Fix the bug"},
            allow_branch_skip=False,
            start_time=time.time(),
            node={"id": "codex-1", "type": "codex", "data": node_data},
            node_type="codex",
            node_data=node_data,
            node_label=str(node_data.get("label") or "CodexFix"),
        )

    @patch("app.services.node_execution.nodes.codex_node._load_credentials")
    @patch("app.services.node_execution.nodes.codex_node.CodexRunnerService")
    def test_completed_result_skips_question_branch(
        self,
        runner_cls: MagicMock,
        load_credentials: MagicMock,
    ) -> None:
        load_credentials.return_value = ({"access_token": "codex-token"}, {"api_key": "ghp-token"})
        runner = runner_cls.return_value
        runner.run_task.return_value = CodexRunResult(
            status="completed",
            summary="Done",
            diff="diff --git a/app.py b/app.py",
            changed_files=["app.py"],
            branch_name="codex/abc12345",
        )

        output = codex_node.execute(
            self._ctx(
                {
                    "label": "CodexFix",
                    "credentialId": "codex-id",
                    "githubCredentialId": "github-id",
                    "repositoryUrl": "https://github.com/acme/app",
                    "baseBranch": "main",
                    "taskPrompt": "$input.text",
                    "publishMode": "diff_only",
                    "codexModel": "gpt-5.4",
                }
            )
        )

        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["summary"], "Done")
        self.assertEqual(output["_skip_source_handles"], ["question"])
        request = runner.run_task.call_args.args[0]
        self.assertEqual(request.task_prompt, "Fix the bug")
        self.assertEqual(request.repository_url, "https://github.com/acme/app")
        self.assertEqual(request.model, "gpt-5.4")
        # Regression: an unset setupCommand must stay empty, not become str(inputs).
        self.assertEqual(request.setup_command, "")

    @patch("app.services.node_execution.nodes.codex_node._load_credentials")
    @patch("app.services.node_execution.nodes.codex_node.CodexRunnerService")
    def test_chatgpt_auth_is_forwarded_to_runner(
        self,
        runner_cls: MagicMock,
        load_credentials: MagicMock,
    ) -> None:
        chatgpt_config = {
            "auth_mode": "chatgpt",
            "access_token": "at",
            "refresh_token": "rt",
        }
        load_credentials.return_value = (chatgpt_config, {"api_key": "ghp-token"})
        runner = runner_cls.return_value
        runner.run_task.return_value = CodexRunResult(status="completed", summary="Done")

        codex_node.execute(
            self._ctx(
                {
                    "label": "CodexFix",
                    "credentialId": "codex-id",
                    "githubCredentialId": "github-id",
                    "repositoryUrl": "https://github.com/acme/app",
                    "taskPrompt": "$input.text",
                }
            )
        )

        request = runner.run_task.call_args.args[0]
        self.assertEqual(request.codex_auth["auth_mode"], "chatgpt")
        self.assertEqual(request.codex_auth["refresh_token"], "rt")

    @patch("app.services.node_execution.nodes.codex_node._load_credentials")
    @patch("app.services.node_execution.nodes.codex_node.CodexRunnerService")
    def test_needs_input_returns_pending_node_result_with_codex_metadata(
        self,
        runner_cls: MagicMock,
        load_credentials: MagicMock,
    ) -> None:
        load_credentials.return_value = ({"access_token": "codex-token"}, {"api_key": "ghp-token"})
        runner = runner_cls.return_value
        runner.run_task.return_value = CodexRunResult(
            status="needs_input",
            summary="Need product decision",
            question="Can I change the public API?",
            thread_id="thread-1",
            workspace_path="/tmp/codex",
            branch_name="codex/abc12345",
        )

        result = codex_node.execute(
            self._ctx(
                {
                    "label": "CodexFix",
                    "credentialId": "codex-id",
                    "githubCredentialId": "github-id",
                    "repositoryUrl": "https://github.com/acme/app",
                    "baseBranch": "main",
                    "taskPrompt": "$input.text",
                    "branchName": "codex/$executionId",
                }
            )
        )

        self.assertEqual(result.status, "pending")
        self.assertEqual(result.output["status"], "needs_input")
        self.assertEqual(result.metadata["codex"]["kind"], "codex")
        self.assertEqual(result.metadata["codex"]["task_prompt"], "Fix the bug")
        self.assertEqual(result.metadata["codex"]["repository_url"], "https://github.com/acme/app")
        self.assertEqual(result.metadata["codex"]["thread_id"], "thread-1")


class TestCodexFollowupHelpers(unittest.TestCase):
    def _followup(self, status: str = "pending", *, expired: bool = False) -> SimpleNamespace:
        return SimpleNamespace(
            id="req-1",
            status=status,
            expires_at=datetime.now(timezone.utc)
            + (timedelta(seconds=-1) if expired else timedelta(minutes=5)),
            summary="Need branch decision",
            question="Which branch should I target?",
            answer_text="main",
            thread_id="thread-1",
            workspace_path="/tmp/codex",
            repository_url="https://github.com/acme/app",
            base_branch="main",
            branch_name="codex/run",
            task_prompt="Fix tests",
        )

    def test_actionable_rejects_answered_followup(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            ensure_codex_followup_is_actionable(self._followup(status="answered"))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_actionable_rejects_expired_followup(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            ensure_codex_followup_is_actionable(self._followup(expired=True))
        self.assertEqual(ctx.exception.status_code, 410)

    def test_build_answer_output_contains_resume_context(self) -> None:
        output = build_codex_answer_output(self._followup())
        self.assertEqual(output["status"], "answered")
        self.assertEqual(output["answerText"], "main")
        self.assertEqual(output["threadId"], "thread-1")

    def test_is_codex_pending_execution(self) -> None:
        self.assertTrue(
            is_codex_pending_execution(SimpleNamespace(pending_review={"kind": "codex"}))
        )
        self.assertFalse(
            is_codex_pending_execution(SimpleNamespace(pending_review={"kind": "hitl"}))
        )


if __name__ == "__main__":
    unittest.main()
