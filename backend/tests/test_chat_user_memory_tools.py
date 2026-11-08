"""User memory tools: arguments, dispatch, audit, summaries, and chat wiring."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import chat_memory
from app.services.user_memory import (
    STATUS_ADDED,
    STATUS_REFUSED,
    UserMemoryWriteResult,
    snapshot_of,
)


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), email="ada@example.com")


class CallToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_reads_the_memory(self) -> None:
        user = _user()
        with patch.object(
            chat_memory.user_memory,
            "read_user_memory",
            AsyncMock(return_value=snapshot_of("Answer in English")),
        ) as read:
            result = await chat_memory.call_user_memory_tool(
                AsyncMock(), user, "get_user_memory", {}, source="chat"
            )
        read.assert_awaited_once()
        self.assertEqual(result["content"], "Answer in English")
        self.assertIn("revision", result)

    async def test_append_writes_and_audits_without_the_text(self) -> None:
        user = _user()
        written = UserMemoryWriteResult(STATUS_ADDED, snapshot_of("Prefers short answers"))
        with (
            patch.object(
                chat_memory.user_memory,
                "append_user_memory",
                AsyncMock(return_value=written),
            ) as append,
            patch.object(chat_memory, "audit") as audit,
        ):
            result = await chat_memory.call_user_memory_tool(
                AsyncMock(),
                user,
                "set_user_memory",
                {"mode": "append", "content": "Prefers short answers"},
                source="chat",
            )
        append.assert_awaited_once()
        self.assertEqual(result["status"], STATUS_ADDED)
        audit.assert_called_once()
        kwargs = audit.call_args.kwargs
        self.assertEqual(kwargs["action"], "user.memory.updated")
        self.assertEqual(kwargs["source"], "chat")
        self.assertEqual(kwargs["mode"], "append")
        self.assertNotIn("Prefers short answers", json.dumps(kwargs, default=str))

    async def test_a_refused_write_is_not_audited(self) -> None:
        refused = UserMemoryWriteResult(STATUS_REFUSED, snapshot_of(""), error="no")
        with (
            patch.object(
                chat_memory.user_memory,
                "append_user_memory",
                AsyncMock(return_value=refused),
            ),
            patch.object(chat_memory, "audit") as audit,
        ):
            result = await chat_memory.call_user_memory_tool(
                AsyncMock(),
                _user(),
                "set_user_memory",
                {"mode": "append", "content": "x"},
                source="mcp",
            )
        self.assertEqual(result["error"], "no")
        audit.assert_not_called()

    async def test_replace_without_revision_is_an_error(self) -> None:
        result = await chat_memory.call_user_memory_tool(
            AsyncMock(),
            _user(),
            "set_user_memory",
            {"mode": "replace", "content": "x"},
            source="chat",
        )
        self.assertIn("revision", result["error"])

    async def test_an_unknown_mode_is_an_error(self) -> None:
        result = await chat_memory.call_user_memory_tool(
            AsyncMock(),
            _user(),
            "set_user_memory",
            {"mode": "overwrite", "content": "x"},
            source="chat",
        )
        self.assertIn("error", result)

    async def test_replace_passes_the_revision(self) -> None:
        written = UserMemoryWriteResult("replaced", snapshot_of("new"))
        with (
            patch.object(
                chat_memory.user_memory,
                "replace_user_memory",
                AsyncMock(return_value=written),
            ) as replace,
            patch.object(chat_memory, "audit"),
        ):
            await chat_memory.call_user_memory_tool(
                AsyncMock(),
                _user(),
                "set_user_memory",
                {"mode": "replace", "content": "new", "revision": "abc"},
                source="chat",
            )
        self.assertEqual(replace.await_args.args[2:], ("new", "abc"))


class SummaryTests(unittest.TestCase):
    def test_summaries(self) -> None:
        summarize = chat_memory.summarize_user_memory_tool
        self.assertEqual(
            summarize("get_user_memory", {"length": 12, "max_length": 4000}),
            "Memory read (12/4000 characters)",
        )
        self.assertEqual(summarize("set_user_memory", {"status": "added"}), "Added to memory")
        self.assertEqual(summarize("set_user_memory", {"status": "replaced"}), "Memory updated")
        self.assertEqual(summarize("set_user_memory", {"status": "unchanged"}), "Already in memory")
        self.assertEqual(
            summarize("set_user_memory", {"status": "conflict"}),
            "Memory changed elsewhere; read it again",
        )
        self.assertEqual(
            summarize("set_user_memory", {"status": "refused", "error": "x", "reason": "a key"}),
            "Not saved: looks like a credential",
        )
        self.assertEqual(summarize("set_user_memory", {"error": "Too long"}), "Error: Too long")

    def test_labels(self) -> None:
        self.assertEqual(chat_memory.user_memory_tool_label("get_user_memory"), "Reading memory...")
        self.assertEqual(
            chat_memory.user_memory_tool_label("set_user_memory"), "Saving to memory..."
        )


class SchemaTests(unittest.TestCase):
    def test_chat_schemas(self) -> None:
        names = [s["function"]["name"] for s in chat_memory.USER_MEMORY_TOOL_SCHEMAS]
        self.assertEqual(names, ["get_user_memory", "set_user_memory"])
        set_schema = chat_memory.USER_MEMORY_TOOL_SCHEMAS[1]["function"]
        self.assertEqual(set_schema["parameters"]["required"], ["mode", "content"])
        self.assertEqual(
            set_schema["parameters"]["properties"]["mode"]["enum"], ["append", "replace"]
        )
        self.assertIn("credentials", set_schema["description"])

    def test_mcp_tools(self) -> None:
        tools = chat_memory.build_user_memory_mcp_tools()
        self.assertEqual([t.name for t in tools], ["get_user_memory", "set_user_memory"])
        self.assertEqual(tools[1].inputSchema.required, ["mode", "content"])
        self.assertIn("credentials", tools[1].description or "")


class ChatWiringTests(unittest.TestCase):
    def test_every_dashboard_chat_turn_offers_the_tools(self) -> None:
        from app.api import ai_assistant

        names = [tool["function"]["name"] for tool in ai_assistant.DASHBOARD_CHAT_TOOLS]
        self.assertIn("get_user_memory", names)
        self.assertIn("set_user_memory", names)

    def test_the_prompt_carries_the_write_rule(self) -> None:
        from app.api import ai_assistant

        self.assertIn(chat_memory.USER_MEMORY_PROMPT, ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT)
        self.assertIn("Never save details", ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT)

    def test_run_history_summaries_route_here(self) -> None:
        from app.api import ai_assistant

        self.assertEqual(
            ai_assistant._summarize_tool_result("set_user_memory", json.dumps({"status": "added"})),
            "Added to memory",
        )


class ChatDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_dispatches_memory_tools(self) -> None:
        from app.api import ai_assistant

        user = SimpleNamespace(id=uuid.uuid4())
        arguments = {"mode": "append", "content": "Prefers short answers"}
        tool_message = MagicMock(content=None)
        tool_call = MagicMock()
        tool_call.id = "memory-call"
        tool_call.function.name = "set_user_memory"
        tool_call.function.arguments = json.dumps(arguments)
        tool_message.tool_calls = [tool_call]
        final_message = MagicMock(content="Saved.", tool_calls=None)
        usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=tool_message)], usage=usage),
            MagicMock(choices=[MagicMock(message=final_message)], usage=usage),
        ]
        db = AsyncMock()

        with (
            patch.object(ai_assistant, "record_run_history"),
            patch.object(
                ai_assistant,
                "call_user_memory_tool",
                AsyncMock(return_value={"status": "added", "length": 21}),
            ) as call_tool,
        ):
            chunks = [
                chunk
                async for chunk in ai_assistant.stream_dashboard_chat(
                    client,
                    "gpt-4o-mini",
                    "system",
                    [{"role": "user", "content": "remember that I prefer short answers"}],
                    db,
                    user,
                    "OpenAI",
                    "https://heym.example",
                )
            ]

        call_tool.assert_awaited_once_with(db, user, "set_user_memory", arguments, source="chat")
        joined = "".join(chunks)
        self.assertIn("Saving to memory...", joined)
        self.assertIn("Added to memory", joined)


if __name__ == "__main__":
    unittest.main()
