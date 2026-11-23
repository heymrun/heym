"""A WebSocket Send node with a blank Message fails instead of sending the inputs.

A blank `websocketMessage` went through evaluate_message_template, which renders a blank
template as str(inputs): the server received the Python repr of every input of the run.
The editor already refuses a blank Message ("Message is required").
"""

import unittest
from unittest.mock import patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import websocket_send_node
from app.services.workflow_executor import WorkflowExecutor

_INPUTS = {"userInput": {"headers": {"user-agent": "curl"}, "body": {"text": "hi"}, "text": "hi"}}


def _sent(message_template: str) -> object:
    captured: dict = {}

    async def fake_send(url, headers, subprotocols, message):  # noqa: ANN001, ANN202
        captured["message"] = message
        return {"status": "sent"}

    ctx = NodeExecutionContext(
        executor=WorkflowExecutor(nodes=[], edges=[]),
        node_id="ws_1",
        inputs=_INPUTS,
        allow_branch_skip=False,
        start_time=0.0,
        node={},
        node_type="websocketSend",
        node_data={"websocketUrl": "ws://127.0.0.1:1", "websocketMessage": message_template},
        node_label="notify",
    )
    with patch("app.services.workflow_executor.send_websocket_message", fake_send):
        websocket_send_node.execute(ctx)
    return captured["message"]


class WebSocketSendBlankMessageTests(unittest.TestCase):
    def test_blank_message_fails_and_sends_nothing(self) -> None:
        for blank in ("", "   "):
            with self.subTest(message=blank):
                with self.assertRaisesRegex(ValueError, "WebSocket Send node requires a message"):
                    _sent(blank)

    def test_messages_still_resolve(self) -> None:
        self.assertEqual(_sent("ping $userInput.text"), "ping hi")
        self.assertEqual(_sent("plain text"), "plain text")
        self.assertEqual(_sent("$userInput.body"), {"text": "hi"})


if __name__ == "__main__":
    unittest.main()
