"""Progress lines for a chat turn: the workflow being written, and the node that runs."""

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from app.services import chat_progress
from app.services.chat_progress import (
    ToolProgress,
    follow_tool,
    tool_draft_message,
    workflow_draft_message,
)
from app.services.execution_cancellation import (
    get_active_execution_progress,
    record_execution_node_completed,
    record_execution_node_started,
    watch_execution_nodes,
)
from app.services.mcp_progress import running_node_message

DSL = json.dumps(
    {
        "workflow": {
            "name": 'Lead "intake"',
            "nodes": [
                {
                    "id": "a",
                    "type": "textInput",
                    "data": {"label": "start", "inputFields": [{"key": "text", "label": "Text"}]},
                },
                {"id": "b", "type": "agent", "data": {"label": "Qualify"}},
                {"id": "c", "type": "dataTable", "data": {"label": "Save lead"}},
                {"id": "d", "type": "output", "data": {"label": "result"}},
            ],
            "edges": [{"id": "e1", "source": "a", "target": "b"}],
        }
    },
    indent=2,
)


class WorkflowDraftMessageTests(TestCase):
    def test_names_the_workflow_and_the_latest_nodes(self) -> None:
        self.assertEqual(
            workflow_draft_message(DSL),
            'Writing "Lead "intake"" · 4 nodes (…, Qualify, Save lead, result)',
        )

    def test_reads_a_workflow_cut_anywhere(self) -> None:
        for end in range(0, len(DSL), 7):
            message = workflow_draft_message(DSL[:end])
            self.assertTrue(message.startswith("Writing"), message)

    def test_a_node_whose_label_is_not_written_yet_still_counts(self) -> None:
        cut = DSL.index('"Qualify"') + 4
        self.assertEqual(
            workflow_draft_message(DSL[:cut]), 'Writing "Lead "intake"" · 2 nodes (start)'
        )

    def test_a_field_label_inside_a_node_is_not_a_node(self) -> None:
        cut = DSL.rindex("{", 0, DSL.index('"id": "b"'))
        self.assertEqual(
            workflow_draft_message(DSL[:cut]), 'Writing "Lead "intake"" · 1 node (start)'
        )

    def test_before_any_node(self) -> None:
        self.assertEqual(workflow_draft_message('{"workflow": {"na'), "Writing the workflow")
        self.assertEqual(
            workflow_draft_message('{"name": "Digest", "nodes": ['), 'Writing "Digest"'
        )

    def test_builder_output_in_a_code_fence(self) -> None:
        text = 'Here it is:\n```json\n{"name": "Digest", "nodes": [{"id": "x", "data": {"label": "cron"}}'
        self.assertEqual(workflow_draft_message(text), 'Writing "Digest" · 1 node (cron)')


class ToolDraftMessageTests(TestCase):
    def test_slow_tools_have_a_line_and_quick_ones_none(self) -> None:
        self.assertEqual(tool_draft_message("save_workflow", ""), "Writing the workflow")
        self.assertEqual(tool_draft_message("apply_skill", "{}"), "Writing the skill")
        self.assertIsNone(tool_draft_message("list_workflows", "{}"))


class FollowToolTests(IsolatedAsyncioTestCase):
    async def test_yields_each_new_line_until_the_tool_finishes(self) -> None:
        progress = ToolProgress()

        async def tool() -> str:
            progress.message = "Writing the workflow"
            await asyncio.sleep(0.05)
            progress.message = "Running node Qualify"
            await asyncio.sleep(0.05)
            return "done"

        task = asyncio.ensure_future(tool())
        with patch.object(chat_progress, "TOOL_PROGRESS_POLL_SECONDS", 0.01):
            events = [json.loads(e[6:]) async for e in follow_tool(task, "call_1", progress)]

        self.assertEqual(task.result(), "done")
        self.assertEqual(
            [e["message"] for e in events], ["Writing the workflow", "Running node Qualify"]
        )
        self.assertEqual({e["type"] for e in events}, {"tool_progress"})
        self.assertEqual({e["id"] for e in events}, {"call_1"})

    async def test_describe_wins_over_the_last_message(self) -> None:
        progress = ToolProgress()
        progress.message = "Preparing the run"
        progress.describe = lambda: "Running node fetch"
        self.assertEqual(progress.current(), "Running node fetch")
        progress.describe = lambda: None
        self.assertEqual(progress.current(), "Preparing the run")

    async def test_a_stopped_turn_cancels_the_tool(self) -> None:
        task = asyncio.ensure_future(asyncio.sleep(10))
        events = follow_tool(task, "call_1", ToolProgress())
        waiting = asyncio.ensure_future(events.__anext__())
        await asyncio.sleep(0)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        await events.aclose()
        await asyncio.sleep(0)
        self.assertTrue(task.cancelled())


class NodeWatchTests(TestCase):
    def test_an_unregistered_run_reports_its_running_nodes_while_watched(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            nodes=[
                {"id": "n1", "data": {"label": "Fetch"}},
                {"id": "n2", "data": {"label": "Sum"}},
            ],
        )

        with watch_execution_nodes(workflow_id=workflow_id, execution_id=execution_id):
            record_execution_node_started(str(execution_id), "n1")
            self.assertEqual(running_node_message(execution_id, workflow), "Running node Fetch")
            record_execution_node_completed(str(execution_id), "n1", {})
            record_execution_node_started(str(execution_id), "n2")
            self.assertEqual(running_node_message(execution_id, workflow), "Running node Sum")
            self.assertIsNone(get_active_execution_progress(execution_id, workflow_id=uuid.uuid4()))

        self.assertIsNone(get_active_execution_progress(execution_id, workflow_id=workflow_id))
        record_execution_node_started(str(execution_id), "n1")
        self.assertIsNone(running_node_message(execution_id, workflow))
