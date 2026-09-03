"""Credential errors must say which of the two things actually went wrong.

Slack, Discord, Telegram, and Send Email all read a missing or inaccessible
credential into an empty config, then failed on the first absent field. The
resulting "requires webhook_url" pointed the operator at the credential's
contents when the real problem was that the node could not read the credential
at all. Both cases still fail closed; only the message was wrong.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import (
    discord_node,
    send_email_node,
    slack_node,
    telegram_node,
)

_NODES = {
    "slack": (slack_node, {"credentialId": "cred-1", "message": "hi"}),
    "discord": (discord_node, {"credentialId": "cred-1", "message": "hi"}),
    "telegram": (telegram_node, {"credentialId": "cred-1", "message": "hi", "chatId": "42"}),
    "sendEmail": (
        send_email_node,
        {"credentialId": "cred-1", "to": "ada@example.com", "subject": "s", "emailBody": "b"},
    ),
}


def _context(node_type: str, node_data: dict, credential: object | None) -> NodeExecutionContext:
    executor = MagicMock()
    executor.evaluate_message_template.side_effect = lambda template, *_a, **_kw: template
    executor.resolve_expression.side_effect = lambda template, *_a, **_kw: template
    executor._get_accessible_credential.return_value = credential
    return NodeExecutionContext(
        executor=executor,
        node_id="n1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={"id": "n1", "type": node_type, "data": node_data},
        node_type=node_type,
        node_data=node_data,
        node_label=node_type,
    )


def _run(node_type: str, credential: object | None, config: dict) -> str:
    module, node_data = _NODES[node_type]
    ctx = _context(node_type, node_data, credential)
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    with (
        patch("app.db.session.SessionLocal", return_value=db),
        patch("app.services.encryption.decrypt_config", return_value=config),
    ):
        with unittest.TestCase().assertRaises(ValueError) as ctx_manager:
            module.execute(ctx)
    return str(ctx_manager.exception)


class UnreadableCredentialMessageTests(unittest.TestCase):
    def test_an_unreadable_credential_is_not_reported_as_a_missing_field(self) -> None:
        for node_type in _NODES:
            with self.subTest(node=node_type):
                message = _run(node_type, None, {})
                self.assertIn("not found or not accessible", message)
                self.assertNotIn("requires", message)

    def test_each_node_names_its_own_credential_in_the_message(self) -> None:
        expected = {
            "slack": "Slack credential",
            "discord": "Discord credential",
            "telegram": "Telegram credential",
            "sendEmail": "SMTP credential",
        }
        for node_type, prefix in expected.items():
            with self.subTest(node=node_type):
                self.assertTrue(_run(node_type, None, {}).startswith(prefix))


class MissingFieldMessageTests(unittest.TestCase):
    """A readable credential that is genuinely incomplete still names the field."""

    def test_readable_credential_missing_its_field_still_says_requires(self) -> None:
        expected = {
            "slack": "Slack credential requires webhook_url",
            "discord": "Discord credential requires webhook_url",
            "telegram": "Telegram credential requires bot_token",
        }
        for node_type, message in expected.items():
            with self.subTest(node=node_type):
                self.assertEqual(_run(node_type, MagicMock(), {}), message)

    def test_send_email_names_every_missing_smtp_field(self) -> None:
        self.assertEqual(
            _run("sendEmail", MagicMock(), {}),
            "SMTP credential requires smtp_server, smtp_email, smtp_password",
        )

    def test_send_email_names_only_the_field_that_is_missing(self) -> None:
        config = {
            "smtp_server": "smtp.example.com",
            "smtp_email": "bot@example.com",
            "smtp_password": "",
        }
        self.assertEqual(
            _run("sendEmail", MagicMock(), config),
            "SMTP credential requires smtp_password",
        )


if __name__ == "__main__":
    unittest.main()
