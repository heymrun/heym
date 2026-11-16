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
            executor = WorkflowExecutor(
                nodes=nodes,
                edges=edges,
                actor_user_id=uuid.uuid4(),
            )
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
        self.assertEqual(
            telegram_result["output"]["results"], [{"message_id": 77, "chat": {"id": 12345}}]
        )

    def test_a_message_over_the_telegram_limit_is_sent_as_several(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_telegram_workflow(
            {
                "credentialId": "cred-1",
                "chatId": "$start.body.chat_id",
                "message": "$start.body.text",
            }
        )
        paragraph = "The deployment finished and every health check passed on the first try.\n"
        inputs["body"]["text"] = paragraph * 80

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
            encrypted_config="{}"
        )
        sent: list[str] = []

        def post(_url: str, json: dict) -> MagicMock:
            response = MagicMock()
            if len(json["text"]) > 4096:
                response.status_code = 400
                response.json.return_value = {
                    "ok": False,
                    "description": "Bad Request: message is too long",
                }
                return response
            sent.append(json["text"])
            response.status_code = 200
            response.json.return_value = {"ok": True, "result": {"message_id": len(sent)}}
            return response

        mock_http_client = MagicMock()
        mock_http_client.post.side_effect = post

        with (
            patch("app.db.session.SessionLocal", return_value=mock_db),
            patch("app.services.encryption.decrypt_config", return_value={"bot_token": "1:t"}),
            patch("app.services.workflow_executor.get_http_client", return_value=mock_http_client),
        ):
            executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "success")
        telegram_result = next(
            row for row in result.node_results if row["node_label"] == "telegramSend"
        )
        self.assertEqual(len(sent), 2)
        self.assertEqual("\n".join(sent), inputs["body"]["text"])
        self.assertEqual(telegram_result["output"]["result"], {"message_id": 1})
        self.assertEqual(
            telegram_result["output"]["results"], [{"message_id": 1}, {"message_id": 2}]
        )


class SplitMessageTextTests(unittest.TestCase):
    def test_a_text_within_the_limit_is_one_part(self) -> None:
        from app.services.message_parts import split_message_text

        self.assertEqual(split_message_text("x" * 4096, 4096), ["x" * 4096])
        self.assertEqual(split_message_text("", 4096), [""])

    def test_a_long_text_is_cut_at_a_space_and_nothing_is_lost(self) -> None:
        from app.services.message_parts import split_message_text

        text = "word " * 2000
        parts = split_message_text(text, 4096)

        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 4096 for part in parts))
        self.assertEqual(" ".join(parts), text)

    def test_a_text_without_separators_is_cut_at_the_limit(self) -> None:
        from app.services.message_parts import split_message_text

        self.assertEqual(split_message_text("a" * 9000, 4096), ["a" * 4096, "a" * 4096, "a" * 808])

    def test_characters_outside_the_bmp_count_as_two(self) -> None:
        from app.services.message_parts import split_message_text

        parts = split_message_text("\U0001f600" * 3000, 4096)

        self.assertEqual([len(part.encode("utf-16-le")) // 2 for part in parts], [4096, 1904])
        self.assertEqual("".join(parts), "\U0001f600" * 3000)


if __name__ == "__main__":
    unittest.main()
