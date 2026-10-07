"""The trigger nodes a run hands its initial inputs to."""

import unittest

from app.services.trigger_inputs import receives_initial_inputs


class ReceivesInitialInputsTests(unittest.TestCase):
    def test_chat_mail_socket_and_heym_triggers_receive_them(self) -> None:
        for node_type in (
            "imapTrigger",
            "websocketTrigger",
            "slackTrigger",
            "discordTrigger",
            "telegramTrigger",
            "heymTrigger",
        ):
            with self.subTest(node_type=node_type):
                self.assertTrue(receives_initial_inputs({"type": node_type, "data": {}}))

    def test_only_a_receiving_rabbitmq_node_does(self) -> None:
        receive = {"type": "rabbitmq", "data": {"rabbitmqOperation": "receive"}}
        send = {"type": "rabbitmq", "data": {"rabbitmqOperation": "send"}}

        self.assertTrue(receives_initial_inputs(receive))
        self.assertFalse(receives_initial_inputs(send))
        self.assertFalse(receives_initial_inputs({"type": "rabbitmq"}))

    def test_other_nodes_do_not(self) -> None:
        # textInput copies its text too, so the run paths handle it apart.
        for node_type in ("textInput", "cron", "set", "fileUploadTrigger"):
            with self.subTest(node_type=node_type):
                self.assertFalse(receives_initial_inputs({"type": node_type, "data": {}}))


if __name__ == "__main__":
    unittest.main()
