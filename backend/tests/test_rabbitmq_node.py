import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


def _run_send(rabbitmq_data: dict) -> tuple[dict | None, AsyncMock]:
    """Run textInput -> rabbitmq (send) with the credential and broker mocked."""
    from app.services.workflow_executor import WorkflowExecutor

    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "value": "hello", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "mq",
            "type": "rabbitmq",
            "position": {"x": 200, "y": 0},
            "data": {
                "label": "mqNode",
                "rabbitmqOperation": "send",
                "credentialId": str(uuid.uuid4()),
                **rabbitmq_data,
            },
        },
    ]
    edges = [{"id": "e1", "source": "start", "target": "mq"}]
    publish = AsyncMock(return_value={"published": True})
    with patch("app.db.session.SessionLocal") as mock_session:
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_session.return_value = mock_db
        with (
            patch.object(
                WorkflowExecutor,
                "_get_accessible_credential",
                return_value=MagicMock(encrypted_config="encrypted"),
            ),
            patch("app.services.encryption.decrypt_config", return_value={"rabbitmq_host": "mq"}),
            patch("app.services.rabbitmq_pool.publish_message_direct", publish),
        ):
            executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs={"text": "hello"})
    node_result = next((r for r in result.node_results if r["node_label"] == "mqNode"), None)
    return node_result, publish


class RabbitMQSendTargetTests(unittest.TestCase):
    def test_queue_name_alone_publishes_to_the_queue_through_the_default_exchange(self) -> None:
        node_result, publish = _run_send(
            {"rabbitmqQueueName": "orders", "rabbitmqExchange": "", "rabbitmqRoutingKey": ""}
        )

        self.assertEqual(node_result["status"], "success", node_result)
        publish.assert_awaited_once()
        self.assertEqual(publish.await_args.kwargs["exchange_name"], "")
        self.assertEqual(publish.await_args.kwargs["routing_key"], "orders")

    def test_missing_exchange_and_routing_key_fields_fall_back_to_the_queue(self) -> None:
        node_result, publish = _run_send({"rabbitmqQueueName": "orders"})

        self.assertEqual(node_result["status"], "success", node_result)
        self.assertEqual(publish.await_args.kwargs["exchange_name"], "")
        self.assertEqual(publish.await_args.kwargs["routing_key"], "orders")

    def test_exchange_without_routing_key_keeps_the_routing_key_empty(self) -> None:
        node_result, publish = _run_send(
            {"rabbitmqExchange": "events", "rabbitmqRoutingKey": "", "rabbitmqQueueName": ""}
        )

        self.assertEqual(node_result["status"], "success", node_result)
        self.assertEqual(publish.await_args.kwargs["exchange_name"], "events")
        self.assertEqual(publish.await_args.kwargs["routing_key"], "")

    def test_exchange_and_routing_key_are_rendered(self) -> None:
        node_result, publish = _run_send(
            {"rabbitmqExchange": "events", "rabbitmqRoutingKey": "user.$start.text"}
        )

        self.assertEqual(node_result["status"], "success", node_result)
        self.assertEqual(publish.await_args.kwargs["exchange_name"], "events")
        self.assertEqual(publish.await_args.kwargs["routing_key"], "user.hello")

    def test_no_exchange_routing_key_or_queue_is_an_error(self) -> None:
        node_result, publish = _run_send({})

        self.assertEqual(node_result["status"], "error", node_result)
        self.assertIn("routing key or queue name", str(node_result.get("error")))
        publish.assert_not_awaited()
