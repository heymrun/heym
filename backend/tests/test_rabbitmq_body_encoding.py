"""RabbitMQ Send node: the body goes out as JSON whenever it is not text, against a fake broker."""

from __future__ import annotations

import json
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.workflow_executor import WorkflowExecutor

DECLARED_EXCHANGES = {"events"}


def _run_send(node_data: dict, items: object = None) -> dict:
    published: list[dict] = []

    def exchange_for(name: str) -> MagicMock:
        exchange = MagicMock()

        async def publish(message: object, routing_key: str) -> None:
            if name and name not in DECLARED_EXCHANGES:
                raise RuntimeError(f"404 NOT_FOUND - no exchange {name[:50]!r} in vhost '/'")
            published.append(
                {
                    "exchange": name or "(default)",
                    "routing_key": routing_key,
                    "body": message.body,
                    "content_type": message.content_type,
                }
            )

        exchange.publish = AsyncMock(side_effect=publish)
        return exchange

    channel = MagicMock()
    channel.default_exchange = exchange_for("")
    channel.get_exchange = AsyncMock(side_effect=lambda name, ensure=False: exchange_for(name))
    connection = MagicMock()
    connection.channel = AsyncMock(return_value=channel)
    connection.close = AsyncMock()

    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "inputFields": [{"key": "items"}]},
        },
        {
            "id": "mq",
            "type": "rabbitmq",
            "position": {"x": 200, "y": 0},
            "data": {
                "label": "publish",
                "credentialId": "cred-1",
                "rabbitmqOperation": "send",
                **node_data,
            },
        },
        {
            "id": "out",
            "type": "output",
            "position": {"x": 400, "y": 0},
            "data": {"label": "out", "message": "$publish", "allowDownstream": False},
        },
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "mq"},
        {"id": "e2", "source": "mq", "target": "out"},
    ]
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    db.query.return_value.filter.return_value.first.return_value = MagicMock(encrypted_config="{}")
    with (
        patch("app.db.session.SessionLocal", return_value=db),
        patch("app.services.encryption.decrypt_config", return_value={"rabbitmq_host": "mq"}),
        patch(
            "app.services.rabbitmq_pool.aio_pika.connect_robust",
            AsyncMock(return_value=connection),
        ),
    ):
        result = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()).execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"items": items}},
        )
    row = next(r for r in result.node_results if r["node_label"] == "publish")
    return {
        "status": row["status"],
        "error": str(row.get("error") or "")[:110],
        "published": published[0] if published else None,
    }


BODY = '{"order": 42}'


class RabbitmqSendBodyTests(unittest.TestCase):
    TARGET = {"rabbitmqExchange": "events", "rabbitmqRoutingKey": "order.created"}

    def _body(self, template: str, items: object = None) -> bytes:
        result = _run_send({**self.TARGET, "rabbitmqMessageBody": template}, items)
        self.assertEqual(result["status"], "success", result["error"])
        return result["published"]["body"]

    def test_a_json_array_body_is_published_as_json(self) -> None:
        self.assertEqual(json.loads(self._body('[{"id": 1}, {"id": 2}]')), [{"id": 1}, {"id": 2}])
        self.assertEqual(json.loads(self._body("$start.body.items", [{"id": 1}])), [{"id": 1}])

    def test_json_scalars_are_published_as_json(self) -> None:
        self.assertEqual(self._body("true"), b"true")
        self.assertEqual(self._body("null"), b"null")
        self.assertEqual(self._body("42"), b"42")

    def test_objects_and_plain_text_are_unchanged(self) -> None:
        self.assertEqual(json.loads(self._body(BODY)), {"order": 42})
        self.assertEqual(self._body("order shipped"), b"order shipped")

    def test_encode_body(self) -> None:
        from app.services.rabbitmq_pool import _encode_body

        self.assertEqual(_encode_body({"a": [1, True, None]}), b'{"a": [1, true, null]}')
        self.assertEqual(_encode_body([1, 2]), b"[1, 2]")
        self.assertEqual(_encode_body(False), b"false")
        self.assertEqual(_encode_body("caf\u00e9"), "caf\u00e9".encode())


if __name__ == "__main__":
    unittest.main()
