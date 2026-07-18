import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext


def _ctx(node_data, inputs=None):
    executor = MagicMock()
    executor.evaluate_nonempty_message_template.side_effect = lambda v, *_a, **_k: v
    executor.evaluate_message_template.side_effect = lambda v, *_a, **_k: v
    executor.execution_id = "exec1234abcd"
    ctx = NodeExecutionContext(
        executor=executor,
        node_id="oc_1",
        inputs=inputs or {"text": "do the thing"},
        allow_branch_skip=False,
        start_time=0.0,
        node={"id": "oc_1", "type": "opencodeGo"},
        node_type="opencodeGo",
        node_data=node_data,
        node_label="opencodeFix",
    )
    return ctx, executor


class TestOpenCodeGoNode(unittest.TestCase):
    def test_missing_credential_raises(self):
        from app.services.node_execution.nodes import opencode_go_node

        ctx, _ = _ctx({"repositoryUrl": "https://github.com/a/b", "githubCredentialId": "gh"})
        with self.assertRaises(ValueError):
            opencode_go_node.execute(ctx)

    def test_missing_repo_url_raises(self):
        from app.services.node_execution.nodes import opencode_go_node

        with patch.object(
            opencode_go_node,
            "_load_credentials",
            return_value=({"api_key": "sk", "base_url": ""}, {"api_key": "gh"}),
        ):
            ctx, _ = _ctx({"credentialId": "oc", "githubCredentialId": "gh", "repositoryUrl": ""})
            with self.assertRaises(ValueError):
                opencode_go_node.execute(ctx)

    def test_missing_prompt_raises(self):
        from app.services.node_execution.nodes import opencode_go_node

        with patch.object(
            opencode_go_node,
            "_load_credentials",
            return_value=({"api_key": "sk", "base_url": ""}, {"api_key": "gh"}),
        ):
            ctx, _ = _ctx(
                {
                    "credentialId": "oc",
                    "githubCredentialId": "gh",
                    "repositoryUrl": "https://github.com/a/b",
                    "taskPrompt": "",
                }
            )
            with self.assertRaises(ValueError):
                opencode_go_node.execute(ctx)

    def test_completed_run_returns_output(self):
        from app.services.node_execution.nodes import opencode_go_node
        from app.services.opencode_runner_service import OpenCodeRunResult

        result = OpenCodeRunResult(status="completed", summary="done", branch_name="opencode/x")
        with (
            patch.object(
                opencode_go_node,
                "_load_credentials",
                return_value=({"api_key": "sk", "base_url": ""}, {"api_key": "gh"}),
            ),
            patch(
                "app.services.opencode_runner_service.OpenCodeRunnerService.run_task",
                return_value=result,
            ),
        ):
            ctx, _ = _ctx(
                {
                    "credentialId": "oc",
                    "githubCredentialId": "gh",
                    "repositoryUrl": "https://github.com/a/b",
                    "taskPrompt": "$input.text",
                    "publishMode": "diff_only",
                }
            )
            output = opencode_go_node.execute(ctx)
            self.assertEqual(output["status"], "completed")
            self.assertEqual(output["summary"], "done")

    def test_registered_in_registry(self):
        from app.services.node_execution.registry import get_node_handler

        self.assertIsNotNone(get_node_handler("opencodeGo"))
