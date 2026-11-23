"""Slack (webhook), Discord and Telegram nodes with a blank Message fail instead of posting.

The message went through evaluate_message_template, which renders a blank template as
str(inputs): the channel received the Python repr of every input of the run, request headers
included. The Slack node with a Bot credential already refused a blank message.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import discord_node, slack_node, telegram_node
from app.services.workflow_executor import WorkflowExecutor

_INPUTS = {"userInput": {"headers": {"user-agent": "curl"}, "body": {"text": "hi"}, "text": "hi"}}
_NODES = {
    "slack": (slack_node, "Slack message is required for this operation"),
    "discord": (discord_node, "Discord node requires a non-empty message"),
    "telegram": (telegram_node, "Telegram node requires a non-empty message"),
}


def _run(node_type: str, node_data: dict) -> tuple[object, MagicMock]:
    executor = WorkflowExecutor(nodes=[], edges=[])
    executor._get_accessible_credential = MagicMock(
        return_value=SimpleNamespace(type=node_type, encrypted_config="x")
    )
    client = MagicMock()
    client.post.return_value = MagicMock(status_code=200, text="ok")
    client.post.return_value.json.return_value = {"ok": True, "result": {}}
    ctx = NodeExecutionContext(
        executor=executor,
        node_id="n1",
        inputs=_INPUTS,
        allow_branch_skip=False,
        start_time=0.0,
        node={},
        node_type=node_type,
        node_data={"credentialId": "c1", "chatId": "42", **node_data},
        node_label="notify",
    )
    config = {"webhook_url": "https://hooks.example.com/x", "bot_token": "t"}
    with (
        patch("app.db.session.SessionLocal", MagicMock()),
        patch("app.services.encryption.decrypt_config", return_value=config),
        patch("app.services.ssrf_guard.guard_http_url", MagicMock()),
        patch("app.services.ssrf_guard.get_guarded_http_client", return_value=client),
        patch("app.services.workflow_executor.get_http_client", return_value=client),
    ):
        try:
            return _NODES[node_type][0].execute(ctx), client
        except ValueError as exc:
            return exc, client


def _posted_text(client: MagicMock) -> str:
    body = client.post.call_args.kwargs["json"]
    return str(body.get("text", body.get("content")))


class BlankMessageTests(unittest.TestCase):
    def test_a_blank_message_fails_and_posts_nothing(self) -> None:
        for node_type, (_, error) in _NODES.items():
            for message in ("", "   "):
                with self.subTest(node_type=node_type, message=message):
                    result, client = _run(node_type, {"message": message})

                    self.assertIsInstance(result, ValueError)
                    self.assertEqual(str(result), error)
                    client.post.assert_not_called()

    def test_a_message_is_still_rendered_and_posted(self) -> None:
        for node_type in _NODES:
            with self.subTest(node_type=node_type):
                result, client = _run(node_type, {"message": "Deploy: $userInput.text"})

                self.assertNotIsInstance(result, Exception)
                self.assertEqual(_posted_text(client), "Deploy: hi")

    def test_without_the_field_the_message_is_still_the_input_text(self) -> None:
        for node_type in _NODES:
            with self.subTest(node_type=node_type):
                result, client = _run(node_type, {})

                self.assertNotIsInstance(result, Exception)
                self.assertEqual(_posted_text(client), "hi")


if __name__ == "__main__":
    unittest.main()
