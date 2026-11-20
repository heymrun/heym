"""Heym Work's tools in a dashboard chat turn: offered, relayed, audited."""

import json
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import ai_assistant
from app.api.chat_work import ChatWorkTools
from app.services.work_assistant import ManifestState, WorkLink, WorkManifest, WorkTool

_LINK = WorkLink(work_url="https://work.example.com", key_hash="d" * 64)
_MANIFEST = WorkManifest(
    instructions="Corner data lives in Heym data tables.",
    tools=(
        WorkTool("get_world", "Read the world.", {"type": "object", "properties": {}}),
        WorkTool(
            "start_discover_search",
            "Start a search.",
            {"type": "object", "properties": {"input": {"type": "string"}}},
            long_running=True,
        ),
    ),
)


def _user(active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), is_active=active, email="member@example.com")


class LoadTests(unittest.IsolatedAsyncioTestCase):
    async def test_none_without_a_link(self) -> None:
        with patch("app.api.chat_work.load_work_link", AsyncMock(return_value=None)):
            self.assertIsNone(await ChatWorkTools.load(AsyncMock(), _user()))

    async def test_none_for_an_inactive_user(self) -> None:
        link = AsyncMock(return_value=_LINK)
        with patch("app.api.chat_work.load_work_link", link):
            self.assertIsNone(await ChatWorkTools.load(AsyncMock(), _user(active=False)))
        link.assert_not_awaited()

    async def test_none_when_work_turned_the_user_away(self) -> None:
        with (
            patch("app.api.chat_work.load_work_link", AsyncMock(return_value=_LINK)),
            patch(
                "app.api.chat_work.manifest_for",
                AsyncMock(return_value=ManifestState(None, unreachable=False)),
            ),
        ):
            self.assertIsNone(await ChatWorkTools.load(AsyncMock(), _user()))

    async def test_a_failing_lookup_leaves_the_turn_without_work(self) -> None:
        failing = AsyncMock(side_effect=RuntimeError("database went away"))
        with (
            patch("app.api.chat_work.load_work_link", failing),
            self.assertLogs("app.api.chat_work", level="WARNING"),
        ):
            self.assertIsNone(await ChatWorkTools.load(AsyncMock(), _user()))

    async def test_unreachable_work_gives_only_a_note(self) -> None:
        with (
            patch("app.api.chat_work.load_work_link", AsyncMock(return_value=_LINK)),
            patch(
                "app.api.chat_work.manifest_for",
                AsyncMock(return_value=ManifestState(None, unreachable=True)),
            ),
        ):
            tools = await ChatWorkTools.load(AsyncMock(), _user())
        assert tools is not None
        self.assertEqual(tools.schemas(), [])
        self.assertIn("did not answer", tools.prompt_block())

    async def test_tools_and_instructions(self) -> None:
        with (
            patch("app.api.chat_work.load_work_link", AsyncMock(return_value=_LINK)),
            patch(
                "app.api.chat_work.manifest_for",
                AsyncMock(return_value=ManifestState(_MANIFEST, unreachable=False)),
            ),
        ):
            tools = await ChatWorkTools.load(AsyncMock(), _user())
        assert tools is not None
        names = [schema["function"]["name"] for schema in tools.schemas()]
        self.assertEqual(names, ["work_get_world", "work_start_discover_search"])
        self.assertEqual(tools.schemas()[0]["function"]["description"], "Read the world.")
        block = tools.prompt_block()
        self.assertIn("## Heym Work (connected)", block)
        self.assertIn("Corner data lives in Heym data tables.", block)


class CallTests(unittest.IsolatedAsyncioTestCase):
    def _tools(self) -> ChatWorkTools:
        return ChatWorkTools(user=_user(), link=_LINK, manifest=_MANIFEST)

    def test_handles_only_this_turns_prefixed_names(self) -> None:
        tools = self._tools()
        self.assertTrue(tools.handles("work_get_world"))
        self.assertFalse(tools.handles("get_world"))
        self.assertFalse(tools.handles("work_list_flows"))
        self.assertFalse(tools.handles("list_workflows"))

    async def test_relays_the_unprefixed_tool_and_audits(self) -> None:
        tools = self._tools()
        call = AsyncMock(return_value={"corners": []})
        with (
            patch("app.api.chat_work.call_tool", call),
            patch("app.api.chat_work.audit") as audit,
        ):
            outcome = await tools.call("work_start_discover_search", {"input": "pdf skills"})

        relayed: Any = call.await_args
        self.assertEqual(relayed.args[2].name, "start_discover_search")
        self.assertTrue(relayed.args[2].long_running)
        self.assertEqual(relayed.args[3], {"input": "pdf skills"})
        self.assertEqual(json.loads(outcome.result), {"corners": []})
        self.assertEqual(outcome.status, "success")
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "work.assistant_call")
        self.assertEqual(audit.call_args.kwargs["tool"], "start_discover_search")
        self.assertEqual(audit.call_args.kwargs["outcome"], "success")
        self.assertIsNone(audit.call_args.kwargs["http_status"])

    async def test_error_result(self) -> None:
        tools = self._tools()
        with (
            patch(
                "app.api.chat_work.call_tool",
                AsyncMock(return_value={"error": "Needs an Editor.", "status": 403}),
            ),
            patch("app.api.chat_work.audit") as audit,
        ):
            outcome = await tools.call("work_get_world", {})

        self.assertEqual(outcome.status, "error")
        self.assertIn("Needs an Editor.", outcome.summary)
        self.assertEqual(audit.call_args.kwargs["outcome"], "failure")
        self.assertEqual(audit.call_args.kwargs["http_status"], 403)


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_offers_and_dispatches_work_tools(self) -> None:
        user = _user()
        tool_message = MagicMock(content=None)
        tool_call = MagicMock()
        tool_call.id = "call"
        tool_call.function.name = "work_get_world"
        tool_call.function.arguments = "{}"
        tool_message.tool_calls = [tool_call]
        final_message = MagicMock(content="Three corners.", tool_calls=None)
        usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=tool_message)], usage=usage),
            MagicMock(choices=[MagicMock(message=final_message)], usage=usage),
        ]
        work = ChatWorkTools(user=user, link=_LINK, manifest=_MANIFEST)
        with (
            patch.object(ai_assistant, "record_run_history"),
            patch(
                "app.api.chat_work.call_tool",
                AsyncMock(return_value={"corners": [{"key": "orders"}]}),
            ) as call,
            patch("app.api.chat_work.audit"),
        ):
            chunks = [
                chunk
                async for chunk in ai_assistant.stream_dashboard_chat(
                    client,
                    "gpt-4o-mini",
                    "system",
                    [{"role": "user", "content": "What is in my world?"}],
                    AsyncMock(),
                    user,
                    "OpenAI",
                    "http://localhost",
                    work=work,
                )
            ]

        call.assert_awaited_once()
        first = client.chat.completions.create.call_args_list[0].kwargs
        offered = [tool["function"]["name"] for tool in first["tools"]]
        self.assertIn("work_get_world", offered)
        self.assertIn("list_workflows", offered)
        second = client.chat.completions.create.call_args_list[1].kwargs
        tool_results = [m for m in second["messages"] if m.get("role") == "tool"]
        self.assertIn("orders", tool_results[-1]["content"])
        self.assertIn("Asking Heym Work...", "".join(chunks))

    async def test_stream_without_work_offers_no_work_tools(self) -> None:
        final_message = MagicMock(content="Hello.", tool_calls=None)
        usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=final_message)], usage=usage),
        ]
        with patch.object(ai_assistant, "record_run_history"):
            async for _chunk in ai_assistant.stream_dashboard_chat(
                client,
                "gpt-4o-mini",
                "system",
                [{"role": "user", "content": "hi"}],
                AsyncMock(),
                _user(),
                "OpenAI",
                "http://localhost",
            ):
                pass
        offered = [
            tool["function"]["name"]
            for tool in client.chat.completions.create.call_args_list[0].kwargs["tools"]
        ]
        self.assertFalse([name for name in offered if name.startswith("work_")])


if __name__ == "__main__":
    unittest.main()
