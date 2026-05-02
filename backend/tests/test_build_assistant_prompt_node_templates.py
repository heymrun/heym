"""Tests for workflow assistant prompt including node templates."""

import unittest

from app.services.workflow_dsl_prompt import build_assistant_prompt


class TestBuildAssistantPromptNodeTemplates(unittest.TestCase):
    """Verify node templates are surfaced to the canvas AI builder prompt."""

    def test_includes_node_templates_section(self) -> None:
        templates = [
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "name": "Shared LLM preset",
                "description": "A shared configuration",
                "tags": ["demo"],
                "node_type": "llm",
                "node_data": {"label": "llm1", "userMessage": "Hi"},
            }
        ]
        prompt = build_assistant_prompt(
            None,
            None,
            None,
            available_node_templates=templates,
        )
        self.assertIn("## Available node templates", prompt)
        self.assertIn("Shared LLM preset", prompt)
        self.assertIn("node_type", prompt)

    def test_includes_current_workflow_goal_without_nodes(self) -> None:
        prompt = build_assistant_prompt(
            {
                "id": "00000000-0000-4000-8000-000000000002",
                "name": "Lead qualification workflow",
                "description": "Score inbound leads and route qualified prospects.",
                "nodes": [],
                "edges": [],
            }
        )

        self.assertIn("## Current Workflow Goal", prompt)
        self.assertIn("Lead qualification workflow", prompt)
        self.assertIn("Score inbound leads", prompt)
        self.assertIn("when the user says to generate/build/create it", prompt)

    def test_includes_imap_trigger_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("imapTrigger", prompt)
        self.assertIn("pollIntervalMinutes", prompt)
        self.assertIn("imap-credential-uuid", prompt)

    def test_includes_telegram_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("telegramTrigger", prompt)
        self.assertIn('"type": "telegram"', prompt)
        self.assertIn("telegram-credential-uuid", prompt)

    def test_includes_websocket_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("websocketTrigger", prompt)
        self.assertIn("websocketSend", prompt)
        self.assertIn("websocketTriggerEvents", prompt)
        self.assertIn("websocketMessage", prompt)


if __name__ == "__main__":
    unittest.main()
