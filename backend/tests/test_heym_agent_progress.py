"""Progress reuses the chat engine's own step labels, so every surface says the same thing."""

import unittest

from app.services.heym_agent.progress import AgentProgress, TurnProgress, step_message


class StepMessageTests(unittest.TestCase):
    def test_tool_start_label_becomes_the_message(self) -> None:
        payload = {
            "type": "tool_start",
            "name": "run_workflow",
            "label": 'Running workflow "Invoice"...',
        }

        self.assertEqual(step_message(payload), 'Running workflow "Invoice"')

    def test_build_attempts_keep_their_counter(self) -> None:
        payload = {
            "type": "tool_start",
            "name": "run_workflow_test",
            "label": "Testing the workflow · attempt 2/5...",
        }

        self.assertEqual(step_message(payload), "Testing the workflow · attempt 2/5")

    def test_unlabelled_tool_falls_back_to_its_name(self) -> None:
        self.assertEqual(
            step_message({"type": "tool_start", "name": "list_boards"}), "Using list_boards"
        )

    def test_other_events_are_not_steps(self) -> None:
        for payload in ({"type": "content", "text": "hi"}, {"type": "tool_end", "name": "x"}, {}):
            with self.subTest(payload=payload):
                self.assertIsNone(step_message(payload))


class TurnProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_steps_are_numbered_in_order(self) -> None:
        seen: list[AgentProgress] = []

        async def on_progress(progress: AgentProgress) -> None:
            seen.append(progress)

        progress = TurnProgress(on_progress)
        await progress.observe({"type": "content", "text": "thinking"})
        await progress.observe({"type": "tool_start", "name": "a", "label": "Listing workflows..."})
        await progress.observe(
            {"type": "tool_start", "name": "b", "label": "Saving the workflow..."}
        )

        self.assertEqual(
            seen,
            [AgentProgress(1, "Listing workflows"), AgentProgress(2, "Saving the workflow")],
        )
