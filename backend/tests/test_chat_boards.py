"""Board chat tools: registration, schemas, prompt, dispatch and summaries."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import ai_assistant, chat_boards


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


class RegistrationTests(unittest.TestCase):
    def test_every_board_tool_is_offered_once(self) -> None:
        names = [t["function"]["name"] for t in ai_assistant.DASHBOARD_CHAT_TOOLS]
        for name in chat_boards.BOARD_TOOL_NAMES:
            self.assertEqual(names.count(name), 1, name)
        self.assertEqual(
            chat_boards.BOARD_TOOL_NAMES,
            {
                "list_boards",
                "get_board",
                "get_board_tasks",
                "get_card_detail",
                "list_board_members",
                "create_board",
                "update_board",
                "delete_board",
                "create_board_column",
                "update_board_column",
                "delete_board_column",
                "create_board_task",
                "update_board_task",
                "move_board_task",
                "add_board_task_comment",
                "delete_board_task",
            },
        )

    def test_schemas_carry_no_string_formats(self) -> None:
        for schema in chat_boards.BOARD_TOOL_SCHEMAS:
            for node in _walk(schema):
                self.assertNotIn("format", node)

    def test_create_task_only_requires_a_title(self) -> None:
        schema = next(
            s
            for s in chat_boards.BOARD_TOOL_SCHEMAS
            if s["function"]["name"] == "create_board_task"
        )
        self.assertEqual(schema["function"]["parameters"]["required"], ["title"])

    def test_prompt_states_the_review_rule_and_board_selection(self) -> None:
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        for needle in (
            "move_board_task",
            "never approves",
            "requires_board_selection",
            "type single",
            "confirm_name",
            "auto_advance false",
            "add_board_task_comment",
            "A comment never approves a review",
            "use_chat_model",
        ):
            self.assertIn(needle, prompt)

    def test_agent_profile_names_task_management(self) -> None:
        from app.services.heym_agent import profile

        self.assertIn("assign, prioritize, schedule, move", profile.AGENT_CAPABILITIES)
        self.assertIn("comment on", profile.AGENT_CAPABILITIES)


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_arguments_return_an_error_without_db(self) -> None:
        db = AsyncMock()
        result = await chat_boards.call_board_tool(
            db, SimpleNamespace(id=uuid.uuid4()), "move_board_task", {"card_id": "x"}, "http://h"
        )
        self.assertIn("error", result)
        self.assertIn("card_id", result["error"])

    async def test_a_blank_comment_is_refused_without_db(self) -> None:
        db = AsyncMock()
        for content in ("", "   \n"):
            result = await chat_boards.call_board_tool(
                db,
                SimpleNamespace(id=uuid.uuid4()),
                "add_board_task_comment",
                {"card_id": str(uuid.uuid4()), "content": content},
                "http://h",
            )
            self.assertIn("content", result["error"])
        db.execute.assert_not_called()
        db.execute.assert_not_awaited()

    async def test_stream_dispatches_board_tools(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        tool_message = MagicMock(content=None)
        tool_call = MagicMock()
        tool_call.id = "call"
        tool_call.function.name = "move_board_task"
        tool_call.function.arguments = json.dumps(
            {"card_id": str(uuid.uuid4()), "to_column_id": str(uuid.uuid4())}
        )
        tool_message.tool_calls = [tool_call]
        final_message = MagicMock(content="Moved.", tool_calls=None)
        usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=tool_message)], usage=usage),
            MagicMock(choices=[MagicMock(message=final_message)], usage=usage),
        ]
        with (
            patch.object(ai_assistant, "record_run_history"),
            patch.object(
                ai_assistant,
                "call_board_tool",
                AsyncMock(
                    return_value={"moved": True, "task": {"title": "NDA"}, "to_column": "Review"}
                ),
            ) as call,
        ):
            chunks = [
                chunk
                async for chunk in ai_assistant.stream_dashboard_chat(
                    client,
                    "gpt-4o-mini",
                    "system",
                    [{"role": "user", "content": "move NDA to Review"}],
                    AsyncMock(),
                    user,
                    "OpenAI",
                    "http://localhost",
                )
            ]
        call.assert_awaited_once()
        self.assertEqual(call.await_args.args[2], "move_board_task")
        self.assertIn("Moved task", "".join(chunks))


class SummaryTests(unittest.TestCase):
    def test_summaries(self) -> None:
        s = chat_boards.summarize_board_tool
        self.assertEqual(s("list_boards", {"count": 2, "boards": []}), "2 board(s) listed")
        self.assertEqual(s("get_board_tasks", {"count": 3, "tasks": []}), "3 task(s) listed")
        self.assertTrue(s("delete_board", {"error": "no"}).startswith("Error"))
        self.assertEqual(
            s("move_board_task", {"moved": True, "task": {"title": "NDA"}, "to_column": "Done"}),
            "Moved task 'NDA' to Done",
        )
        self.assertEqual(
            s("create_board_task", {"requires_board_selection": True, "count": 2}),
            "Board selection required (2 available)",
        )
        self.assertEqual(
            s("create_board_column", {"created": True, "column": {"name": "Review"}}),
            "Added column 'Review'",
        )
        self.assertEqual(
            s("add_board_task_comment", {"commented": True, "task": {"title": "NDA"}}),
            "Commented on task 'NDA'",
        )


class CreateBoardModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_board_the_chat_creates_maps_cards_with_the_chats_model(self) -> None:
        credential_id = uuid.uuid4()
        summary = SimpleNamespace(id=uuid.uuid4())
        board = SimpleNamespace(
            id=summary.id,
            name="Team",
            description=None,
            auto_advance=False,
            mapper_credential_id=credential_id,
            mapper_model="gpt-4o",
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=board)
        with patch.object(
            chat_boards.boards_api, "create_board", AsyncMock(return_value=summary)
        ) as create:
            result = await chat_boards.call_board_tool(
                db,
                SimpleNamespace(id=uuid.uuid4()),
                "create_board",
                {"name": "Team", "auto_advance": False},
                "http://h",
                (credential_id, "gpt-4o"),
            )
        request = create.await_args.kwargs["request"]
        self.assertEqual(request.mapper_credential_id, credential_id)
        self.assertEqual(request.mapper_model, "gpt-4o")
        self.assertTrue(result["created"])
        self.assertEqual(result["board"]["agentic_kanban_model"], "gpt-4o")
        self.assertNotIn("note", result)

    async def test_without_a_usable_credential_the_board_is_still_created(self) -> None:
        from fastapi import HTTPException

        summary = SimpleNamespace(id=uuid.uuid4())
        board = SimpleNamespace(
            id=summary.id,
            name="Team",
            description=None,
            auto_advance=True,
            mapper_credential_id=None,
            mapper_model=None,
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=board)
        create = AsyncMock(side_effect=[HTTPException(400, "Credential not found"), summary])
        with patch.object(chat_boards.boards_api, "create_board", create):
            result = await chat_boards.call_board_tool(
                db,
                SimpleNamespace(id=uuid.uuid4()),
                "create_board",
                {"name": "Team"},
                "http://h",
                (uuid.uuid4(), "gpt-4o"),
            )
        self.assertTrue(result["created"])
        self.assertIsNone(create.await_args_list[1].kwargs["request"].mapper_credential_id)
        self.assertIsNone(result["board"]["agentic_kanban_model"])
        self.assertIn("Agentic Kanban Model", result["note"])
