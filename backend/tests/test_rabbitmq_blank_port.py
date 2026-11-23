"""A RabbitMQ credential with a blank Port connects on 5672.

The credential form marks Port optional ("default: 5672") and saves "" when it is
cleared. The send node and the receive trigger read it with int(""), so a send failed with
"invalid literal for int() with base 10: ''" and the trigger never started consuming.
"""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.rabbitmq_consumer import ConsumerInfo, RabbitMQConsumerManager


def _send(config: dict) -> tuple[dict | None, AsyncMock]:
    from app.services.workflow_executor import WorkflowExecutor

    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "mq",
            "type": "rabbitmq",
            "position": {"x": 200, "y": 0},
            "data": {
                "label": "mqNode",
                "rabbitmqOperation": "send",
                "credentialId": str(uuid.uuid4()),
                "rabbitmqQueueName": "orders",
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
            patch("app.services.encryption.decrypt_config", return_value=config),
            patch("app.services.rabbitmq_pool.publish_message_direct", publish),
        ):
            executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs={"text": "hi"})
    node_result = next((r for r in result.node_results if r["node_label"] == "mqNode"), None)
    return node_result, publish


class RabbitMQSendBlankPortTests(unittest.TestCase):
    def test_blank_or_missing_port_is_5672(self) -> None:
        for config in (
            {"rabbitmq_host": "mq", "rabbitmq_port": ""},
            {"rabbitmq_host": "mq", "rabbitmq_port": "  "},
            {"rabbitmq_host": "mq", "rabbitmq_port": None},
            {"rabbitmq_host": "mq"},
        ):
            with self.subTest(config=config):
                node_result, publish = _send(config)
                self.assertEqual(node_result["status"], "success", node_result)
                self.assertEqual(publish.call_args.kwargs["port"], 5672)

    def test_a_set_port_is_used(self) -> None:
        for port, expected in (("5673", 5673), (" 5673 ", 5673), (5673, 5673)):
            with self.subTest(port=port):
                _, publish = _send({"rabbitmq_host": "mq", "rabbitmq_port": port})
                self.assertEqual(publish.call_args.kwargs["port"], expected)


class RabbitMQTriggerBlankPortTests(unittest.IsolatedAsyncioTestCase):
    async def _connect_port(self, config: dict) -> int | None:
        info = ConsumerInfo(uuid.uuid4(), str(uuid.uuid4()), "orders", "trigger-1")
        connect = AsyncMock(side_effect=ConnectionError("stop after connect"))
        with patch("app.services.rabbitmq_consumer.aio_pika.connect_robust", connect):
            await RabbitMQConsumerManager()._start_consumer(info, config)
        return connect.call_args.kwargs["port"] if connect.called else None

    async def test_blank_port_connects_on_5672(self) -> None:
        self.assertEqual(
            await self._connect_port({"rabbitmq_host": "mq", "rabbitmq_port": ""}), 5672
        )

    async def test_a_set_port_is_used(self) -> None:
        self.assertEqual(
            await self._connect_port({"rabbitmq_host": "mq", "rabbitmq_port": "5673"}), 5673
        )


if __name__ == "__main__":
    unittest.main()
