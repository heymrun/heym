"""Unit tests for Telegram executor nodes."""

import unittest
import uuid
from unittest.mock import MagicMock, patch


def _make_telegram_workflow(telegram_data: dict) -> tuple[list, list, dict]:
    """Build a minimal textInput -> telegram -> output workflow."""
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "inputFields": [{"key": "text"}, {"key": "chat_id"}]},
        },
        {
            "id": "telegram",
            "type": "telegram",
            "position": {"x": 200, "y": 0},
            "data": {"label": "telegramSend", **telegram_data},
        },
        {
            "id": "out",
            "type": "output",
            "position": {"x": 400, "y": 0},
            "data": {"label": "out", "message": "$telegramSend", "allowDownstream": False},
        },
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "telegram"},
        {"id": "e2", "source": "telegram", "target": "out"},
    ]
    inputs = {"headers": {}, "query": {}, "body": {"text": "hello", "chat_id": 12345}}
    return nodes, edges, inputs


class TestTelegramExecutorBranch(unittest.TestCase):
    def test_missing_credential_results_in_error(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_telegram_workflow(
            {"credentialId": "", "chatId": "$start.body.chat_id", "message": "$start.body.text"}
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "error")
        telegram_result = next(
            (row for row in result.node_results if row["node_label"] == "telegramSend"),
            None,
        )
        self.assertIsNotNone(telegram_result)
        self.assertEqual(telegram_result["status"], "error")
        self.assertIn("credential", telegram_result.get("error", "").lower())

    def test_send_message_calls_telegram_api(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_telegram_workflow(
            {
                "credentialId": "cred-1",
                "chatId": "$start.body.chat_id",
                "message": "Received: $start.body.text",
            }
        )

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
            encrypted_config="{}"
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 77, "chat": {"id": 12345}},
        }

        mock_http_client = MagicMock()
        mock_http_client.post.return_value = mock_response

        with (
            patch("app.db.session.SessionLocal", return_value=mock_db),
            patch(
                "app.services.encryption.decrypt_config",
                return_value={"bot_token": "123:telegram-token"},
            ),
            patch("app.services.workflow_executor.get_http_client", return_value=mock_http_client),
        ):
            executor = WorkflowExecutor(nodes=nodes, edges=edges)
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "success")
        telegram_result = next(
            (row for row in result.node_results if row["node_label"] == "telegramSend"),
            None,
        )
        self.assertIsNotNone(telegram_result)
        self.assertEqual(telegram_result["status"], "success")
        self.assertEqual(telegram_result["output"]["result"]["message_id"], 77)

        mock_http_client.post.assert_called_once_with(
            "https://api.telegram.org/bot123:telegram-token/sendMessage",
            json={"chat_id": 12345, "text": "Received: hello"},
        )


if __name__ == "__main__":
    unittest.main()
