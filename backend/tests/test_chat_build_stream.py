"""stream_dashboard_chat in build mode: tools per round, events, finish, budget, cancel."""

import json
import uuid
from contextlib import ExitStack
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import ai_assistant, chat_build
from app.db.models import Workflow
from app.services.chat_build_mode import MAX_BUILD_TEST_RUNS, BuildRequest
from app.services.credential_catalog import CredentialPromptMode
from app.services.llm_trace import LLMTraceContext

DSL = {
    "name": "Lead intake",
    "description": "Saves website leads",
    "nodes": [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "done",
            "type": "output",
            "position": {"x": 300, "y": 0},
            "data": {"label": "result", "message": "$start.text"},
        },
    ],
    "edges": [{"id": "e1", "source": "start", "target": "done"}],
}


def _usage() -> MagicMock:
    return MagicMock(prompt_tokens=10, completion_tokens=2, total_tokens=12)


def _tool_call(name: str, arguments: dict[str, Any], call_id: str) -> MagicMock:
    call = MagicMock()
    call.id = call_id
    call.function.name = name
    call.function.arguments = json.dumps(arguments)
    message = MagicMock(content=None, tool_calls=[call])
    return MagicMock(choices=[MagicMock(message=message)], usage=_usage())


def _text(text: str) -> MagicMock:
    message = MagicMock(content=text, tool_calls=None)
    return MagicMock(choices=[MagicMock(message=message)], usage=_usage())


def _run_result(status: str) -> str:
    return json.dumps(
        {
            "status": status,
            "outputs": {"result": "hi"},
            "node_results": [],
            "execution_time_ms": 300,
        }
    )


class ChatBuildStreamTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4(), email="owner@example.com", user_rules=None)
        self.db = MagicMock()
        self.db.commit = AsyncMock()
        self.db.refresh = AsyncMock()
        self.db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))
        self.runner = AsyncMock(return_value=_run_result("success"))
        self.cancel_event = Event()
        self.stack = ExitStack()
        for name, value in {
            "get_workflow_for_user": AsyncMock(side_effect=self._get_workflow),
            "user_can_write_workflow": AsyncMock(return_value=True),
            "load_credential_catalog": AsyncMock(return_value=[]),
            "load_data_table_catalog": AsyncMock(return_value=[]),
            "run_execute_workflow_tool": self.runner,
            "audit": MagicMock(),
            "announce_workflow_saved": AsyncMock(),
        }.items():
            self.stack.enter_context(patch.object(chat_build, name, value))
        self.record_trace = self.stack.enter_context(patch.object(ai_assistant, "record_llm_trace"))
        self.stack.enter_context(patch.object(ai_assistant, "record_run_history"))

    def tearDown(self) -> None:
        self.stack.close()

    async def _get_workflow(self, _db: Any, workflow_id: uuid.UUID, _user_id: uuid.UUID) -> Any:
        added = [c.args[0] for c in self.db.add.call_args_list if isinstance(c.args[0], Workflow)]
        return next((w for w in added if w.id == workflow_id), None)

    def _session(self) -> chat_build.ChatBuildSession:
        return chat_build.ChatBuildSession(
            db=self.db,
            user=self.user,
            request=BuildRequest(),
            selected_credential=SimpleNamespace(
                id=uuid.uuid4(), owner_id=self.user.id, type="openai"
            ),
            model="gpt-5.5",
            credential_mode=CredentialPromptMode.ASK_AND_CREATE,
            public_base_url="http://localhost",
            cancel_event=self.cancel_event,
            llm_session_id="conv-1",
        )

    async def _stream(
        self, responses: list[Any], build: chat_build.ChatBuildSession | None
    ) -> tuple[list[dict[str, Any]], MagicMock]:
        client = MagicMock()
        client.chat.completions.create.side_effect = responses
        events: list[dict[str, Any]] = []
        async for chunk in ai_assistant.stream_dashboard_chat(
            client,
            "gpt-5.5",
            "system",
            [{"role": "user", "content": "Build a lead intake workflow"}],
            self.db,
            self.user,
            "OpenAI",
            "http://localhost",
            LLMTraceContext(
                user_id=self.user.id,
                credential_id=uuid.uuid4(),
                node_label="Dashboard Chat",
                source="dashboard_chat",
                session_id="conv-1",
            ),
            self.cancel_event,
            build=build,
        ):
            if chunk.startswith("data: "):
                events.append(json.loads(chunk[6:].strip()))
        return events, client

    @staticmethod
    def _tool_names(client: MagicMock, call_index: int) -> list[str]:
        tools = client.chat.completions.create.call_args_list[call_index].kwargs["tools"]
        return [tool["function"]["name"] for tool in tools]

    async def test_save_run_finish_ends_the_turn_with_a_verified_card(self) -> None:
        events, client = await self._stream(
            [
                _tool_call("save_workflow", {"workflow": DSL}, "c1"),
                _tool_call(
                    "run_workflow_test", {"inputs": {"text": "hi"}, "expect": "Echoes hi"}, "c2"
                ),
                _tool_call("finish", {"summary": "Echoes the text it gets."}, "c3"),
                _text("never sent"),
            ],
            self._session(),
        )

        self.assertEqual(client.chat.completions.create.call_count, 3)
        types = [e["type"] for e in events]
        self.assertIn("workflow_created", types)
        self.assertEqual(types[-3:], ["verified", "content", "done"])
        verified = next(e for e in events if e["type"] == "verified")
        self.assertEqual(verified["summary"], "Echoes the text it gets.")
        save_start = next(
            e for e in events if e["type"] == "tool_start" and e["name"] == "save_workflow"
        )
        self.assertEqual(save_start["args"], {"name": "Lead intake", "nodes": 2, "edges": 1})
        names = self._tool_names(client, 0)
        self.assertIn("save_workflow", names)
        self.assertNotIn("create_workflow", names)

        trace_tools = self.record_trace.call_args.kwargs["response"]["tool_calls"]
        self.assertEqual(
            [t["name"] for t in trace_tools], ["save_workflow", "run_workflow_test", "finish"]
        )
        self.assertEqual(trace_tools[0]["arguments"]["nodes"], 2)

    async def test_without_build_mode_the_build_tools_are_not_offered(self) -> None:
        with patch.object(
            ai_assistant, "get_workflows_for_user_with_inputs", AsyncMock(return_value=[])
        ):
            _, client = await self._stream([_text("Hello")], None)

        names = self._tool_names(client, 0)
        self.assertNotIn("save_workflow", names)
        self.assertNotIn("run_workflow_test", names)
        self.assertNotIn("finish", names)
        self.assertIn("create_workflow", names)

    async def test_cancel_during_a_test_run_ends_the_turn(self) -> None:
        async def cancelled_run(*_args: Any, **_kwargs: Any) -> str:
            self.cancel_event.set()
            return json.dumps({"status": "cancelled", "error": "Execution cancelled"})

        self.runner.side_effect = cancelled_run
        events, client = await self._stream(
            [
                _tool_call("save_workflow", {"workflow": DSL}, "c1"),
                _tool_call("run_workflow_test", {"inputs": {}, "expect": ""}, "c2"),
                _text("never sent"),
            ],
            self._session(),
        )

        self.assertEqual(client.chat.completions.create.call_count, 2)
        ends = [e for e in events if e["type"] == "tool_end"]
        self.assertEqual(ends[-1]["status"], "cancelled")
        self.assertNotIn("done", [e["type"] for e in events])

    async def test_a_spent_budget_takes_the_build_tools_away(self) -> None:
        self.runner.return_value = _run_result("error")
        runs = [
            _tool_call("run_workflow_test", {"inputs": {}, "expect": ""}, f"r{i}")
            for i in range(MAX_BUILD_TEST_RUNS)
        ]
        events, client = await self._stream(
            [_tool_call("save_workflow", {"workflow": DSL}, "c1"), *runs, _text("It still fails.")],
            self._session(),
        )

        self.assertEqual(self.runner.await_count, MAX_BUILD_TEST_RUNS)
        last_names = self._tool_names(client, MAX_BUILD_TEST_RUNS + 1)
        self.assertFalse({"save_workflow", "run_workflow_test", "finish"} & set(last_names))
        self.assertEqual(events[-1]["type"], "done")
