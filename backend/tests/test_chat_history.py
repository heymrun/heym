"""Send-now keeps earlier context without leaving the cancelled task active."""

import unittest
from types import SimpleNamespace

from app.services.chat_history import INTERRUPTED_TURN_INSTRUCTIONS, messages_for_chat_turn


class ChatHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.messages = [
            SimpleNamespace(role="user", content="Use the Sales workspace"),
            SimpleNamespace(role="assistant", content="Understood"),
            SimpleNamespace(role="user", content="Which workflows ran today?"),
            SimpleNamespace(role="assistant", content="Looking up runs"),
            SimpleNamespace(role="user", content="Skip the workflows, just show my teams"),
        ]

    def test_normal_follow_up_preserves_the_history(self) -> None:
        history = messages_for_chat_turn(self.messages)
        self.assertEqual([m["role"] for m in history], [m.role for m in self.messages])

    def test_interrupted_task_becomes_context_and_latest_request_stays_active(self) -> None:
        history = messages_for_chat_turn(self.messages, interrupted=True)
        self.assertEqual(history[:2], messages_for_chat_turn(self.messages[:2]))
        self.assertEqual(history[2]["role"], "assistant")
        self.assertIn("background context only", history[2]["content"])
        self.assertIn("The user cancelled the previous request", history[2]["content"])
        self.assertIn("sent a new message", history[2]["content"])
        self.assertIn("It is not pending, and you do not need to answer it", history[2]["content"])
        self.assertIn("Which workflows ran today?", history[2]["content"])
        self.assertEqual(history[-1], {"role": "user", "content": self.messages[-1].content})
        self.assertEqual(self.messages[2].role, "user")

    def test_refinement_can_still_read_the_original_request(self) -> None:
        self.messages[-1].content = "Keep that workflow, but use the billing SMTP credential"
        history = messages_for_chat_turn(self.messages, interrupted=True)
        self.assertIn("Which workflows ran today?", history[2]["content"])
        self.assertEqual(history[-1]["content"], self.messages[-1].content)
        self.assertIn("refines the same task", INTERRUPTED_TURN_INSTRUCTIONS)

    def test_single_message_and_empty_history_need_no_previous_task(self) -> None:
        self.assertEqual(messages_for_chat_turn([], interrupted=True), [])
        self.assertEqual(
            messages_for_chat_turn(self.messages[-1:], interrupted=True),
            [{"role": "user", "content": self.messages[-1].content}],
        )
