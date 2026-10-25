"""MCP gets a queued result to poll, and the status tool sees only exposed workflows."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import mcp_execution_status
from app.services.workflow_concurrency import Admission, QueueInfo


def _wf(limit: int | None = 1) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), concurrency_limit=limit)


class ToolListingTests(unittest.TestCase):
    def test_listed_only_when_an_exposed_workflow_has_a_limit(self) -> None:
        self.assertTrue(mcp_execution_status.should_list([_wf(None), _wf(2)]))
        self.assertFalse(mcp_execution_status.should_list([_wf(None)]))

    def test_the_tool_takes_an_execution_id(self) -> None:
        tool = mcp_execution_status.build_execution_status_tool()
        self.assertEqual(tool.name, "heym_execution_status")
        schema = tool.inputSchema.model_dump()
        self.assertIn("execution_id", schema["properties"])
        self.assertEqual(schema["required"], ["execution_id"])


class QueuedTextTests(unittest.TestCase):
    def test_a_queued_admission_is_a_non_error_with_a_next_step(self) -> None:
        execution_id = uuid.uuid4()
        text, is_error = mcp_execution_status.admission_tool_text(
            Admission(kind="queued", execution_id=execution_id, queue=QueueInfo(2, 3, 1, 1))
        )
        payload = json.loads(text)
        self.assertFalse(is_error)
        self.assertEqual(payload["execution_id"], str(execution_id))
        self.assertEqual(payload["queue"]["position"], 2)
        self.assertIn("heym_execution_status", payload["next_step"])

    def test_a_full_queue_is_an_error(self) -> None:
        text, is_error = mcp_execution_status.admission_tool_text(
            Admission(kind="queue_full", execution_id=uuid.uuid4())
        )
        self.assertTrue(is_error)
        self.assertIn("full", text)


class StatusToolCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_exposed_workflows_run_is_found(self) -> None:
        workflow = _wf()
        body = {"execution_id": "e", "workflow_id": str(workflow.id), "status": "running"}
        with (
            patch.object(
                mcp_execution_status,
                "_workflow_of_execution",
                AsyncMock(return_value=workflow.id),
            ),
            patch.object(
                mcp_execution_status.workflow_concurrency,
                "build_status_body",
                AsyncMock(return_value=body),
            ),
        ):
            text, is_error = await mcp_execution_status.run_execution_status_tool(
                [workflow], {"execution_id": str(uuid.uuid4())}
            )
        self.assertFalse(is_error)
        self.assertEqual(json.loads(text)["status"], "running")

    async def test_another_workflows_run_is_not_found(self) -> None:
        with patch.object(
            mcp_execution_status, "_workflow_of_execution", AsyncMock(return_value=uuid.uuid4())
        ):
            text, is_error = await mcp_execution_status.run_execution_status_tool(
                [_wf()], {"execution_id": str(uuid.uuid4())}
            )
        self.assertTrue(is_error)
        self.assertIn("not found", text.lower())

    async def test_a_malformed_id_is_an_error(self) -> None:
        text, is_error = await mcp_execution_status.run_execution_status_tool(
            [_wf()], {"execution_id": "nope"}
        )
        self.assertTrue(is_error)


class ToolsWithChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_status_tool_joins_the_list_when_a_limit_exists(self) -> None:
        from app.api.mcp import build_tools_with_chat

        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            name="Queue me",
            description=None,
            nodes=[],
            edges=[],
            concurrency_limit=1,
        )
        chat = SimpleNamespace(enabled=False)
        with patch("app.api.mcp.extract_input_fields_from_workflow", return_value=[]):
            tools = await build_tools_with_chat([workflow], chat)
        self.assertIn("heym_execution_status", [t.name for t in tools])
