"""MCP progress says what the request is doing, and its counter only grows."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.mcp import _run_mcp_operation_with_progress, dispatch_chat_tool_call
from app.services.heym_agent.progress import AgentProgress
from app.services.heym_agent.settings import AgentSettings
from app.services.heym_agent.turn import AgentTurnResult
from app.services.mcp_elicitation import MCPClientChannel
from app.services.mcp_progress import DEFAULT_PROGRESS_MESSAGE, MCPProgress, running_node_message


def _messages(send: AsyncMock) -> list[tuple[int, str]]:
    return [
        (call.args[0]["params"]["progress"], call.args[0]["params"]["message"])
        for call in send.await_args_list
    ]


class MCPProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_count_up_and_repeat_the_latest_step(self) -> None:
        send = AsyncMock()
        progress = MCPProgress("tok", send)

        await progress.report()
        await progress.report("Saving the workflow")
        await progress.report()

        self.assertEqual(
            _messages(send),
            [
                (0, DEFAULT_PROGRESS_MESSAGE),
                (1, "Saving the workflow"),
                (2, "Saving the workflow"),
            ],
        )
        self.assertEqual(send.await_args_list[0].args[0]["method"], "notifications/progress")

    async def test_without_a_token_nothing_is_sent(self) -> None:
        send = AsyncMock()
        await MCPProgress(None, send).report("x")
        send.assert_not_awaited()

    async def test_describe_refreshes_timer_ticks(self) -> None:
        send = AsyncMock()
        progress = MCPProgress("tok", send)
        progress.describe = lambda: "Running node Fetch"

        await progress.report()

        self.assertEqual(_messages(send), [(0, "Running node Fetch")])

    async def test_operation_wrapper_sends_a_first_report_and_a_keepalive(self) -> None:
        send = AsyncMock()
        keepalive = AsyncMock()

        async def operation() -> dict:
            return {"ok": True}

        result = await _run_mcp_operation_with_progress(
            operation, progress=MCPProgress("tok", send), send_keepalive=keepalive
        )

        self.assertEqual(result, {"ok": True})
        keepalive.assert_awaited_once()
        self.assertEqual(_messages(send), [(0, DEFAULT_PROGRESS_MESSAGE)])

    async def test_heym_chat_reports_the_agent_steps(self) -> None:
        send = AsyncMock()
        progress = MCPProgress("tok", send, message="Heym Agent is working")
        client = MCPClientChannel(frozenset(), send, progress=progress)

        async def run_chat_tool(db: object, **kwargs: object) -> AgentTurnResult:
            await kwargs["on_progress"](AgentProgress(1, "Listing workflows"))
            return AgentTurnResult(uuid.uuid4(), "Done.", [])

        with (
            patch("app.api.mcp.mcp_chat_service.run_chat_tool", run_chat_tool),
            patch("app.api.mcp.build_public_base_url", return_value="https://heym.test"),
        ):
            await dispatch_chat_tool_call(
                request=SimpleNamespace(),
                db=AsyncMock(),
                msg_id=1,
                user_id=uuid.uuid4(),
                chat_settings=AgentSettings(enabled=True, credential_id=None, model=None),
                arguments={"message": "list"},
                client=client,
            )

        self.assertEqual(_messages(send), [(0, "Listing workflows")])


class RunningNodeTests(unittest.TestCase):
    def test_names_the_running_nodes_by_label(self) -> None:
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            nodes=[{"id": "n1", "data": {"label": "Fetch"}}, {"id": "n2", "data": {}}],
        )
        with patch(
            "app.services.mcp_progress.get_active_execution_progress",
            return_value=(["n1", "n2"], []),
        ):
            self.assertEqual(running_node_message(uuid.uuid4(), workflow), "Running node Fetch, n2")

    def test_unknown_execution_says_nothing(self) -> None:
        workflow = SimpleNamespace(id=uuid.uuid4(), nodes=[])
        with patch("app.services.mcp_progress.get_active_execution_progress", return_value=None):
            self.assertIsNone(running_node_message(uuid.uuid4(), workflow))
