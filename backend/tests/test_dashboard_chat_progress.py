"""Chat shows a turn while it happens: streamed text, the tool call being written, the running node."""

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import ai_assistant
from app.services import chat_progress, chat_round_stream
from app.services.chat_progress import ToolProgress
from app.services.execution_cancellation import record_execution_node_started
from app.services.llm_trace import LLMTraceContext


def _chunk(text: str | None = None, calls: list[dict[str, Any]] | None = None) -> SimpleNamespace:
    tool_calls = [
        SimpleNamespace(
            index=0,
            id=call.get("id"),
            function=SimpleNamespace(name=call.get("name"), arguments=call.get("arguments")),
        )
        for call in calls or []
    ]
    delta = SimpleNamespace(content=text, tool_calls=tool_calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=None)], usage=None)


async def _events(client: Any, user_id: uuid.UUID) -> list[dict[str, Any]]:
    trace_context = LLMTraceContext(
        user_id=user_id,
        credential_id=uuid.uuid4(),
        node_label="Dashboard Chat",
        source="dashboard_chat",
        session_id="conv-1",
    )
    events: list[dict[str, Any]] = []
    async for chunk in ai_assistant.stream_dashboard_chat(
        client,
        "gpt-5.5",
        "system",
        [{"role": "user", "content": "Run the digest"}],
        AsyncMock(),
        SimpleNamespace(id=user_id),
        "OpenAI",
        "http://localhost",
        trace_context,
        None,
    ):
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))
    return events


class DashboardChatProgressTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user_id = uuid.uuid4()
        for target, values in (
            (chat_round_stream, {"DRAFT_FLUSH_SECONDS": 0, "PROGRESS_REFRESH_SECONDS": 0}),
            (chat_progress, {"TOOL_PROGRESS_POLL_SECONDS": 0.01}),
            (
                ai_assistant,
                {
                    "record_llm_trace": MagicMock(),
                    "record_run_history": MagicMock(),
                    "get_workflow_for_user": AsyncMock(
                        return_value=SimpleNamespace(name="Digest", nodes=[])
                    ),
                },
            ),
        ):
            patcher = patch.multiple(target, **values)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_a_turn_streams_drafts_progress_running_nodes_then_the_answer(self) -> None:
        workflow_id = str(uuid.uuid4())
        client = MagicMock()
        client.base_url = "https://llm.example/v1"
        client.chat.completions.create.side_effect = [
            iter(
                [
                    _chunk("Let me run it."),
                    _chunk(calls=[{"id": "call_1", "name": "execute_workflow"}]),
                    _chunk(calls=[{"arguments": json.dumps({"workflow_id": workflow_id})}]),
                ]
            ),
            iter([_chunk("The digest "), _chunk("ran.")]),
        ]

        async def run_tool(*_args: Any, progress: ToolProgress, **_kwargs: Any) -> str:
            progress.message = "Running node Fetch"
            await asyncio.sleep(0.05)
            return json.dumps({"status": "success", "outputs": {}, "node_results": []})

        with patch.object(ai_assistant, "run_execute_workflow_tool", side_effect=run_tool):
            events = await _events(client, self.user_id)

        types = [e["type"] for e in events]
        self.assertEqual(events[0], {"type": "draft", "round": 1, "text": "Let me run it."})
        self.assertIn({"type": "progress", "round": 1, "message": "Preparing the run"}, events)
        start = types.index("tool_start")
        progress = events[types.index("tool_progress")]
        self.assertEqual(
            progress, {"type": "tool_progress", "id": "call_1", "message": "Running node Fetch"}
        )
        self.assertLess(start, types.index("tool_progress"))
        self.assertLess(types.index("tool_progress"), types.index("tool_end"))
        second_round = [e["text"] for e in events if e["type"] == "draft" and e["round"] == 2]
        self.assertEqual("".join(second_round), "The digest ran.")
        self.assertEqual([e["text"] for e in events if e["type"] == "content"], ["The digest ran."])
        self.assertEqual(types[-1], "done")


class RunWorkflowProgressTests(IsolatedAsyncioTestCase):
    async def test_a_chat_run_describes_its_running_node(self) -> None:
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            name="Digest",
            owner_id=uuid.uuid4(),
            nodes=[{"id": "n1", "type": "http", "data": {"label": "Fetch"}}],
            edges=[],
        )
        progress = ToolProgress()
        seen: list[str | None] = []

        def execute(**kwargs: Any) -> Any:
            record_execution_node_started(kwargs["execution_id"], "n1")
            seen.append(progress.current())
            return SimpleNamespace(
                status="success",
                outputs={},
                node_results=[],
                execution_time_ms=1.0,
                sub_workflow_executions=[],
                allow_downstream_pending=False,
            )

        db = MagicMock()
        db.flush = AsyncMock()
        with (
            patch.object(ai_assistant, "get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch.object(ai_assistant, "collect_referenced_workflows", AsyncMock(return_value={})),
            patch.object(ai_assistant, "get_credentials_context", AsyncMock(return_value={})),
            patch.object(ai_assistant, "get_global_variables_context", AsyncMock(return_value={})),
            patch.object(ai_assistant, "upsert_workflow_analytics_snapshot", AsyncMock()),
            patch.object(ai_assistant, "_persist_global_variables_from_execution", AsyncMock()),
            patch.object(ai_assistant, "execute_workflow", side_effect=execute),
        ):
            raw = await ai_assistant.run_execute_workflow_tool(
                db, uuid.uuid4(), str(workflow.id), {}, "http://localhost", progress=progress
            )

        self.assertEqual(json.loads(raw)["status"], "success")
        self.assertEqual(seen, ["Running node Fetch"])
        self.assertIsNone(progress.describe)
