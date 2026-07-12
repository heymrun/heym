import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api import ai_assistant


def _scalars(items):
    res = MagicMock()
    res.scalars.return_value.all.return_value = items
    return res


def _scalar(value):
    res = MagicMock()
    res.scalar.return_value = value
    return res


class TestBoardToolsRegistered(unittest.TestCase):
    def test_tools_present(self):
        names = {t["function"]["name"] for t in ai_assistant.DASHBOARD_CHAT_TOOLS}
        self.assertIn("list_boards", names)
        self.assertIn("get_board_tasks", names)


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
