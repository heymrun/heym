"""Tests for the Cal.com API workflow node."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.cal_node import execute


class CalNodeTests(unittest.TestCase):
    def _context(self, data: dict[str, object]) -> NodeExecutionContext:
        executor = MagicMock()
        executor._get_accessible_credential.return_value = SimpleNamespace(
            type=CredentialType.cal_api,
            encrypted_config="encrypted",
        )
        executor.evaluate_message_template.side_effect = lambda value, *_args: value
        executor._is_single_dollar_expression.return_value = False
        return NodeExecutionContext(
            executor=executor,
            node_id="cal-node",
            allow_branch_skip=False,
            start_time=0,
            node={"id": "cal-node", "type": "cal"},
            node_type="cal",
            node_data={"credentialId": "credential", **data},
            node_label="cal",
            inputs={},
        )

    def test_list_webhooks_returns_count(self) -> None:
        context = self._context({"calOperation": "listWebhooks"})
        service = MagicMock()
        service.list_webhooks.return_value = [{"id": "one"}]
        with (
            patch("app.services.node_execution.nodes.cal_node.SessionLocal"),
            patch(
                "app.services.node_execution.nodes.cal_node.decrypt_config",
                return_value={"api_key": "secret"},
            ),
            patch(
                "app.services.node_execution.nodes.cal_node.CalApiService",
                return_value=service,
            ),
        ):
            output = execute(context)
        self.assertEqual(output["webhooks"], [{"id": "one"}])
        self.assertEqual(output["count"], 1)

    def test_create_webhook_accepts_json_object(self) -> None:
        context = self._context(
            {
                "calOperation": "createWebhook",
                "calWebhook": '{"subscriberUrl":"https://heym.test/hook"}',
            }
        )
        service = MagicMock()
        service.create_webhook.return_value = {"id": "created"}
        with (
            patch("app.services.node_execution.nodes.cal_node.SessionLocal"),
            patch(
                "app.services.node_execution.nodes.cal_node.decrypt_config",
                return_value={"api_key": "secret"},
            ),
            patch(
                "app.services.node_execution.nodes.cal_node.CalApiService",
                return_value=service,
            ),
        ):
            output = execute(context)
        service.create_webhook.assert_called_once_with({"subscriberUrl": "https://heym.test/hook"})
        self.assertEqual(output["webhook"], {"id": "created"})

    def test_update_and_delete_require_webhook_id(self) -> None:
        for operation in ("updateWebhook", "deleteWebhook"):
            with self.subTest(operation=operation):
                context = self._context({"calOperation": operation, "calWebhook": "{}"})
                with (
                    patch("app.services.node_execution.nodes.cal_node.SessionLocal"),
                    patch(
                        "app.services.node_execution.nodes.cal_node.decrypt_config",
                        return_value={"api_key": "secret"},
                    ),
                    patch("app.services.node_execution.nodes.cal_node.CalApiService"),
                    self.assertRaisesRegex(ValueError, "requires a webhook ID"),
                ):
                    execute(context)

    def test_rejects_wrong_credential_type(self) -> None:
        context = self._context({"calOperation": "listWebhooks"})
        context.executor._get_accessible_credential.return_value = SimpleNamespace(
            type=CredentialType.cal_trigger,
            encrypted_config="encrypted",
        )
        with (
            patch("app.services.node_execution.nodes.cal_node.SessionLocal"),
            self.assertRaisesRegex(ValueError, "requires a Cal.com API credential"),
        ):
            execute(context)
