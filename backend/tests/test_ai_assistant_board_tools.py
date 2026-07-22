import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import ai_assistant


def _scalars(items):
    res = MagicMock()
    res.scalars.return_value.all.return_value = items
    return res


def _scalar(value):
    res = MagicMock()
    res.scalar.return_value = value
    return res


def _scalar_one(value):
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


class TestBoardToolsRegistered(unittest.TestCase):
    def test_tools_present(self):
        names = {t["function"]["name"] for t in ai_assistant.DASHBOARD_CHAT_TOOLS}
        self.assertIn("list_boards", names)
        self.assertIn("create_board_task", names)
        self.assertIn("get_board_tasks", names)
        self.assertIn("get_card_detail", names)

    def test_create_tool_only_requires_title_and_exposes_no_column(self):
        tool = next(
            item
            for item in ai_assistant.DASHBOARD_CHAT_TOOLS
            if item["function"]["name"] == "create_board_task"
        )
        parameters = tool["function"]["parameters"]
        self.assertEqual(parameters["required"], ["title"])
        self.assertNotIn("column_id", parameters["properties"])

    def test_prompt_requires_board_selection_and_first_column(self):
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        self.assertIn("create_board_task", prompt)
        self.assertIn("requires_board_selection", prompt)
        self.assertIn("type single", prompt)
        self.assertIn("first column", prompt)


class TestListBoardsForChat(unittest.IsolatedAsyncioTestCase):
    async def test_lists_boards_with_status_counts(self):
        board = SimpleNamespace(id=uuid.uuid4(), name="Launch", description=None)
        db = AsyncMock()
        # 1: boards, 2: column count, 3: card statuses
        db.execute = AsyncMock(
            side_effect=[
                _scalars([board]),
                _scalar(6),
                _scalars(["success", "success", "failed"]),
            ]
        )
        result = await ai_assistant.list_boards_for_chat(db, uuid.uuid4())
        self.assertEqual(result["count"], 1)
        b = result["boards"][0]
        self.assertEqual(b["name"], "Launch")
        self.assertEqual(b["column_count"], 6)
        self.assertEqual(b["card_count"], 3)
        self.assertEqual(b["status_counts"], {"success": 2, "failed": 1})


class TestGetBoardTasksForChat(unittest.IsolatedAsyncioTestCase):
    async def test_lists_tasks_with_column_and_status(self):
        board = SimpleNamespace(id=uuid.uuid4(), name="Launch")
        column = SimpleNamespace(id=uuid.uuid4(), name="Planning")
        card = SimpleNamespace(
            id=uuid.uuid4(),
            title="Write email",
            run_status="running",
            board_id=board.id,
            column_id=column.id,
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_scalars([board]), _scalars([column]), _scalars([card])]
        )
        result = await ai_assistant.get_board_tasks_for_chat(db, uuid.uuid4())
        self.assertEqual(result["count"], 1)
        task = result["tasks"][0]
        self.assertEqual(task["title"], "Write email")
        self.assertEqual(task["status"], "running")
        self.assertEqual(task["board"], "Launch")
        self.assertEqual(task["column"], "Planning")

    async def test_invalid_board_id(self):
        db = AsyncMock()
        result = await ai_assistant.get_board_tasks_for_chat(db, uuid.uuid4(), board_id="nope")
        self.assertIn("error", result)


class TestCreateBoardTaskForChat(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_boards_require_selection_without_creating(self):
        boards = [
            SimpleNamespace(id=uuid.uuid4(), name="Launch", description="Q3 launch"),
            SimpleNamespace(id=uuid.uuid4(), name="Docs", description=None),
        ]
        user = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars(boards))

        with patch.object(ai_assistant, "create_board_card", AsyncMock()) as create_card:
            result = await ai_assistant.create_board_task_for_chat(
                db,
                user,
                title="Fix login bug",
            )

        self.assertTrue(result["requires_board_selection"])
        self.assertEqual([board["name"] for board in result["boards"]], ["Launch", "Docs"])
        create_card.assert_not_awaited()

    async def test_single_board_creates_in_default_first_column(self):
        board = SimpleNamespace(id=uuid.uuid4(), name="Launch", description=None)
        card = SimpleNamespace(
            id=uuid.uuid4(),
            column_id=uuid.uuid4(),
            title="Fix login bug",
            content="Handle expired sessions",
        )
        user = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars([board]))

        with patch.object(
            ai_assistant,
            "create_board_card",
            AsyncMock(return_value=card),
        ) as create_card:
            result = await ai_assistant.create_board_task_for_chat(
                db,
                user,
                title="  Fix login bug  ",
                description="  Handle expired sessions  ",
            )

        self.assertTrue(result["created"])
        self.assertEqual(result["board"]["id"], str(board.id))
        self.assertEqual(result["placement"]["column"], "first")
        request = create_card.await_args.kwargs["request"]
        self.assertEqual(request.title, "Fix login bug")
        self.assertEqual(request.content, "Handle expired sessions")
        self.assertIsNone(request.column_id)

    async def test_explicit_board_must_belong_to_user(self):
        user = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_one(None))

        with patch.object(ai_assistant, "create_board_card", AsyncMock()) as create_card:
            result = await ai_assistant.create_board_task_for_chat(
                db,
                user,
                title="Fix login bug",
                board_id=str(uuid.uuid4()),
            )

        self.assertEqual(result, {"error": "Board not found"})
        create_card.assert_not_awaited()

    async def test_rejects_empty_title_before_reading_boards(self):
        db = AsyncMock()
        result = await ai_assistant.create_board_task_for_chat(
            db,
            SimpleNamespace(id=uuid.uuid4()),
            title="   ",
        )
        self.assertEqual(result, {"error": "Task title is required"})
        db.execute.assert_not_awaited()

    async def test_stream_dispatches_create_task_tool(self):
        user = SimpleNamespace(id=uuid.uuid4())
        tool_message = MagicMock(content=None)
        tool_call = MagicMock()
        tool_call.id = "task-call"
        tool_call.function.name = "create_board_task"
        tool_call.function.arguments = '{"title":"Update documentation"}'
        tool_message.tool_calls = [tool_call]
        final_message = MagicMock(content="Task created.", tool_calls=None)
        first_response = MagicMock(
            choices=[MagicMock(message=tool_message)],
            usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
        final_response = MagicMock(
            choices=[MagicMock(message=final_message)],
            usage=MagicMock(prompt_tokens=20, completion_tokens=5, total_tokens=25),
        )
        client = MagicMock()
        client.chat.completions.create.side_effect = [first_response, final_response]
        db = AsyncMock()

        with (
            patch.object(ai_assistant, "record_run_history"),
            patch.object(
                ai_assistant,
                "create_board_task_for_chat",
                AsyncMock(
                    return_value={
                        "created": True,
                        "task": {"title": "Update documentation"},
                        "board": {"name": "Launch"},
                    }
                ),
            ) as create_task,
        ):
            chunks = [
                chunk
                async for chunk in ai_assistant.stream_dashboard_chat(
                    client,
                    "gpt-4o-mini",
                    "system",
                    [{"role": "user", "content": "create a new card Update documentation"}],
                    db,
                    user,
                    "OpenAI",
                    "http://localhost",
                )
            ]

        create_task.assert_awaited_once_with(
            db,
            user,
            title="Update documentation",
            description=None,
            board_id=None,
        )
        joined = "".join(chunks)
        self.assertIn('"name": "create_board_task"', joined)
        self.assertIn("Created task", joined)


class TestGetCardDetailForChat(unittest.IsolatedAsyncioTestCase):
    async def test_returns_content_comments_runs(self):
        from datetime import datetime, timezone

        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        card = SimpleNamespace(
            id=uuid.uuid4(),
            title="Write email",
            content="draft it",
            run_status="success",
            board_id=uuid.uuid4(),
            column_id=uuid.uuid4(),
        )
        board = SimpleNamespace(name="Launch")
        column = SimpleNamespace(name="Done")
        activity = SimpleNamespace(
            kind="comment", author_type="user", content="use Q3 tone", created_at=now
        )
        run = SimpleNamespace(
            workflow_name="Enrich",
            status="success",
            output={"text": "done"},
            error=None,
            started_at=now,
            finished_at=now,
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_scalar_one(card), _scalars([activity]), _scalars([run])]
        )
        db.get = AsyncMock(side_effect=[column, board])
        result = await ai_assistant.get_card_detail_for_chat(db, uuid.uuid4(), str(card.id))
        self.assertEqual(result["title"], "Write email")
        self.assertEqual(result["content"], "draft it")
        self.assertEqual(result["column"], "Done")
        self.assertEqual(result["comments"][0]["content"], "use Q3 tone")
        self.assertEqual(result["runs"][0]["workflow"], "Enrich")

    async def test_card_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_one(None))
        result = await ai_assistant.get_card_detail_for_chat(db, uuid.uuid4(), str(uuid.uuid4()))
        self.assertIn("error", result)
