"""Unit tests for Discord executor nodes."""

import unittest
import uuid
from unittest.mock import MagicMock, patch


def _make_discord_workflow(discord_data: dict) -> tuple[list, list, dict]:
    """Build a minimal textInput -> discord -> output workflow."""
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "inputFields": [{"key": "text"}, {"key": "username"}]},
        },
        {
            "id": "discord",
            "type": "discord",
            "position": {"x": 200, "y": 0},
            "data": {"label": "discordSend", **discord_data},
        },
        {
            "id": "out",
            "type": "output",
            "position": {"x": 400, "y": 0},
            "data": {"label": "out", "message": "$discordSend", "allowDownstream": False},
        },
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "discord"},
        {"id": "e2", "source": "discord", "target": "out"},
    ]
    inputs = {"headers": {}, "query": {}, "body": {"text": "hello", "username": "Heym Bot"}}
    return nodes, edges, inputs


class TestDiscordExecutorBranch(unittest.TestCase):
    def test_missing_credential_results_in_error(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_discord_workflow(
            {"credentialId": "", "message": "$start.body.text"}
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "error")
        discord_result = next(
            (row for row in result.node_results if row["node_label"] == "discordSend"),
            None,
        )
        self.assertIsNotNone(discord_result)
        self.assertEqual(discord_result["status"], "error")
        self.assertIn("credential", discord_result.get("error", "").lower())

    def test_empty_message_results_in_error(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_discord_workflow({"credentialId": "cred-1", "message": "   "})
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "error")
        discord_result = next(
            (row for row in result.node_results if row["node_label"] == "discordSend"),
            None,
        )
        self.assertIsNotNone(discord_result)
        self.assertEqual(discord_result["status"], "error")
        self.assertIn("non-empty message", discord_result.get("error", "").lower())

    def test_send_message_calls_discord_webhook(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_discord_workflow(
            {
                "credentialId": "cred-1",
                "message": "Received: $start.body.text",
                "username": "$start.body.username",
                "avatarUrl": "https://example.com/heym.png",
            }
        )

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
            encrypted_config="{}"
        )

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.text = ""

        mock_http_client = MagicMock()
        mock_http_client.post.return_value = mock_response

        with (
            patch("app.db.session.SessionLocal", return_value=mock_db),
            patch(
                "app.services.encryption.decrypt_config",
                return_value={"webhook_url": "https://discord.com/api/webhooks/123/abc"},
            ),
            patch(
                "app.services.ssrf_guard.get_guarded_http_client",
                return_value=mock_http_client,
            ),
        ):
            executor = WorkflowExecutor(
                nodes=nodes,
                edges=edges,
                actor_user_id=uuid.uuid4(),
            )
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "success")
        discord_result = next(
            (row for row in result.node_results if row["node_label"] == "discordSend"),
            None,
        )
        self.assertIsNotNone(discord_result)
        self.assertEqual(discord_result["status"], "success")
        self.assertEqual(discord_result["output"]["status"], 204)
        self.assertEqual(discord_result["output"]["message"], "Received: hello")
        self.assertEqual(discord_result["output"]["username"], "Heym Bot")
        self.assertEqual(
            discord_result["output"]["avatar_url"],
            "https://example.com/heym.png",
        )

        mock_http_client.post.assert_called_once_with(
            "https://discord.com/api/webhooks/123/abc?wait=true",
            json={
                "content": "Received: hello",
                "username": "Heym Bot",
                "avatar_url": "https://example.com/heym.png",
            },
        )


if __name__ == "__main__":
    unittest.main()
