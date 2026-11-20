"""Unit tests for outbound WebSocket trigger and sender executor branches."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, patch

import websockets

from app.services import ssrf_guard
from app.services.websocket_utils import send_websocket_message


def _make_websocket_send_workflow(websocket_data: dict) -> tuple[list, list, dict]:
    """Build a minimal textInput -> websocketSend -> output workflow."""
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": "start",
                "inputFields": [{"key": "text"}, {"key": "userId"}],
            },
        },
        {
            "id": "socket-send",
            "type": "websocketSend",
            "position": {"x": 200, "y": 0},
            "data": {"label": "socketSend", **websocket_data},
        },
        {
            "id": "out",
            "type": "output",
            "position": {"x": 400, "y": 0},
            "data": {"label": "out", "message": "$socketSend.status", "allowDownstream": False},
        },
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "socket-send"},
        {"id": "e2", "source": "socket-send", "target": "out"},
    ]
    inputs = {"headers": {}, "query": {}, "body": {"text": "hello", "userId": 7}}
    return nodes, edges, inputs


class TestWebSocketExecutorBranches(unittest.TestCase):
    def test_websocket_send_resolves_url_headers_and_message(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_websocket_send_workflow(
            {
                "websocketUrl": "wss://socket.example.com/$start.body.userId",
                "websocketHeaders": '{"Authorization": "Bearer $start.body.text"}',
                "websocketSubprotocols": "json",
                "websocketMessage": "$start.body",
            }
        )

        send_mock = AsyncMock(
            return_value={
                "status": "sent",
                "url": "wss://socket.example.com/7",
                "message_type": "json",
                "size_bytes": 29,
                "subprotocol": "json",
                "sent_at": "2026-04-21T10:00:00+00:00",
            }
        )

        with patch("app.services.workflow_executor.send_websocket_message", send_mock):
            executor = WorkflowExecutor(nodes=nodes, edges=edges)
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "success")
        send_mock.assert_awaited_once_with(
            url="wss://socket.example.com/7",
            headers='{"Authorization": "Bearer hello"}',
            subprotocols="json",
            message={"text": "hello", "userId": 7},
        )

        websocket_result = next(
            (row for row in result.node_results if row["node_label"] == "socketSend"),
            None,
        )
        self.assertIsNotNone(websocket_result)
        self.assertEqual(websocket_result["status"], "success")
        self.assertEqual(websocket_result["output"]["message_type"], "json")
        self.assertEqual(websocket_result["output"]["status"], "sent")

    def test_a_quote_in_a_header_value_keeps_the_headers_json(self) -> None:
        from app.services.websocket_utils import normalize_websocket_headers
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_websocket_send_workflow(
            {
                "websocketUrl": "wss://socket.example.com/publish",
                "websocketHeaders": '{"X-Context": "$start.body.text"}',
                "websocketMessage": "ping",
            }
        )
        inputs["body"]["text"] = '{"tenant": "café", "path": "C:\\\\data"}'
        send_mock = AsyncMock(return_value={"status": "sent"})

        with patch("app.services.workflow_executor.send_websocket_message", send_mock):
            result = WorkflowExecutor(nodes=nodes, edges=edges).execute(
                workflow_id=uuid.uuid4(), initial_inputs=inputs
            )

        self.assertEqual(result.status, "success")
        headers = send_mock.await_args.kwargs["headers"]
        self.assertEqual(
            normalize_websocket_headers(headers), {"X-Context": inputs["body"]["text"]}
        )

    def test_websocket_trigger_exposes_event_payload_to_downstream_nodes(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes = [
            {
                "id": "trigger",
                "type": "websocketTrigger",
                "position": {"x": 0, "y": 0},
                "data": {
                    "label": "socketEvent",
                    "websocketUrl": "wss://feed.example.com",
                    "websocketTriggerEvents": ["onMessage"],
                },
            },
            {
                "id": "out",
                "type": "output",
                "position": {"x": 200, "y": 0},
                "data": {
                    "label": "out",
                    "message": "$socketEvent.message.data.price",
                    "allowDownstream": False,
                },
            },
        ]
        edges = [{"id": "e1", "source": "trigger", "target": "out"}]
        inputs = {
            "triggered_by": "websocket",
            "trigger_node_id": "trigger",
            "eventName": "onMessage",
            "url": "wss://feed.example.com",
            "triggered_at": "2026-04-21T10:00:00+00:00",
            "message": {
                "type": "text",
                "text": '{"price": 42}',
                "data": {"price": 42},
                "sizeBytes": 13,
                "isBinary": False,
                "isJson": True,
            },
        }

        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "success")
        trigger_result = next(
            (row for row in result.node_results if row["node_label"] == "socketEvent"),
            None,
        )
        self.assertIsNotNone(trigger_result)
        self.assertEqual(trigger_result["output"]["eventName"], "onMessage")
        self.assertEqual(trigger_result["output"]["message"]["data"]["price"], 42)

        output_result = next(
            (row for row in result.node_results if row["node_label"] == "out"),
            None,
        )
        self.assertIsNotNone(output_result)
        self.assertEqual(output_result["output"]["result"], 42)


class TestWebSocketSendIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_send_websocket_message_delivers_payload_before_close(self) -> None:
        received_messages: list[str] = []
        connection_closed = asyncio.Event()

        async def handler(websocket: websockets.ServerConnection) -> None:
            try:
                await asyncio.sleep(0.2)
                received_messages.append(await asyncio.wait_for(websocket.recv(), timeout=2))
            finally:
                connection_closed.set()

        server = await websockets.serve(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        # This asserts payload delivery, not egress policy: the send path now
        # runs through the SSRF guard, which refuses loopback. Use the operator
        # opt-out the guard already documents rather than bypassing it, so the
        # test still exercises the real dial.
        self.enterContext(patch.object(ssrf_guard.settings, "http_allow_private_urls", True))

        try:
            result = await send_websocket_message(
                url=f"ws://127.0.0.1:{port}",
                headers={},
                subprotocols=[],
                message={"kind": "ping"},
            )

            await asyncio.wait_for(connection_closed.wait(), timeout=2)
        finally:
            server.close()
            await server.wait_closed()

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["message_type"], "json")
        self.assertEqual(received_messages, ['{"kind": "ping"}'])

    async def test_guarded_send_uses_pinned_socket_and_origin_argument(self) -> None:
        received_messages: list[str] = []

        async def handler(websocket: websockets.ServerConnection) -> None:
            received_messages.append(await asyncio.wait_for(websocket.recv(), timeout=2))

        server = await websockets.serve(
            handler,
            "127.0.0.1",
            0,
            origins=["https://client.example"],
        )
        port = server.sockets[0].getsockname()[1]

        try:
            with (
                patch.object(ssrf_guard.settings, "http_allow_private_urls", False),
                patch.object(
                    ssrf_guard.socket,
                    "getaddrinfo",
                    return_value=[
                        (
                            ssrf_guard.socket.AF_INET,
                            ssrf_guard.socket.SOCK_STREAM,
                            0,
                            "",
                            ("93.184.216.34", 0),
                        )
                    ],
                ),
                patch.object(
                    ssrf_guard,
                    "_resolve_pinned_addresses",
                    return_value=[(ssrf_guard.socket.AF_INET, "127.0.0.1")],
                ),
            ):
                result = await send_websocket_message(
                    url=f"ws://public.example:{port}",
                    headers={"Origin": "https://client.example"},
                    subprotocols=[],
                    message="guarded payload",
                )
        finally:
            server.close()
            await server.wait_closed()

        self.assertEqual(result["status"], "sent")
        self.assertEqual(received_messages, ["guarded payload"])


if __name__ == "__main__":
    unittest.main()
