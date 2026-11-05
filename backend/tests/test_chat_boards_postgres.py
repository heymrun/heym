"""Board chat tools against a real PostgreSQL: access, filters, changes, safeguards."""

import unittest
import uuid
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import chat_boards
from app.db.models import Board, BoardCard, BoardCardActivity
from tests.board_pg_support import (
    cleanup,
    connect_or_skip,
    make_board,
    make_user,
    share_board,
)

BASE = "http://heym.test"


class ChatBoardToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = await connect_or_skip(self)
        self.owner = await make_user(self.engine, "owner")
        self.writer = await make_user(self.engine, "writer")
        self.reader = await make_user(self.engine, "reader")
        self.outsider = await make_user(self.engine, "outsider")
        self.users = [self.owner, self.writer, self.reader, self.outsider]
        self.board, self.columns = await make_board(self.engine, self.owner, auto_advance=False)
        await share_board(self.engine, self.board, self.writer, "write")
        await share_board(self.engine, self.board, self.reader, "read")

    async def asyncTearDown(self) -> None:
        await cleanup(self.engine, self.users)

    async def call(self, user, tool, /, **args):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            return await chat_boards.call_board_tool(db, user, tool, args, BASE)

    async def add(self, user, title, **fields):
        return await self.call(
            user, "create_board_task", board_id=str(self.board.id), title=title, **fields
        )

    async def set_run_status(self, card_id: str, run_status: str) -> None:
        async with AsyncSession(self.engine) as db:
            card = await db.get(BoardCard, uuid.UUID(card_id))
            card.run_status = run_status
            await db.commit()

    async def test_shared_boards_are_listed_with_permission(self) -> None:
        listed = await self.call(self.writer, "list_boards")
        entry = next(b for b in listed["boards"] if b["id"] == str(self.board.id))
        self.assertEqual(entry["permission"], "write")
        self.assertFalse(entry["auto_advance"])
        self.assertEqual(entry["column_count"], 4)
        self.assertIn("tab=board&board=", entry["url"])
        outsider = await self.call(self.outsider, "list_boards")
        self.assertNotIn(str(self.board.id), [b["id"] for b in outsider["boards"]])

    async def test_get_board_lists_columns_and_tasks(self) -> None:
        await self.add(self.owner, "NDA")
        board = await self.call(self.reader, "get_board", board_id=str(self.board.id))
        self.assertEqual(
            [c["name"] for c in board["columns"]], ["Backlog", "Planning", "Development", "Done"]
        )
        self.assertEqual(board["columns"][0]["card_count"], 1)
        self.assertEqual([t["title"] for t in board["tasks"]], ["NDA"])
        self.assertEqual(board["board"]["permission"], "read")
        denied = await self.call(self.outsider, "get_board", board_id=str(self.board.id))
        self.assertIn("not found", denied["error"].lower())

    async def test_create_with_fields_then_filter(self) -> None:
        yesterday = date.today() - timedelta(days=1)
        created = await self.add(
            self.writer,
            "NDA",
            assignee_user_id=str(self.writer.id),
            priority="urgent",
            due_date=str(yesterday),
            labels=["Acme"],
        )
        self.assertTrue(created["created"], created)
        self.assertEqual(created["task"]["assignee"]["name"], "writer")
        await self.add(self.owner, "Unassigned brief")
        mine = await self.call(self.writer, "get_board", board_id=str(self.board.id), assignee="me")
        self.assertEqual([t["title"] for t in mine["tasks"]], ["NDA"])
        overdue = await self.call(self.owner, "get_board_tasks", due="overdue")
        self.assertEqual([t["title"] for t in overdue["tasks"]], ["NDA"])
        unassigned = await self.call(
            self.owner, "get_board_tasks", board_id=str(self.board.id), assignee="unassigned"
        )
        self.assertEqual([t["title"] for t in unassigned["tasks"]], ["Unassigned brief"])
        by_label = await self.call(self.owner, "get_board_tasks", label="acme")
        self.assertEqual([t["title"] for t in by_label["tasks"]], ["NDA"])
        by_column = await self.call(
            self.owner, "get_board_tasks", column_name="backlog", priority="urgent"
        )
        self.assertEqual([t["title"] for t in by_column["tasks"]], ["NDA"])

    async def test_waiting_for_review_filter(self) -> None:
        created = await self.add(self.owner, "NDA")
        await self.add(self.owner, "Other")
        await self.set_run_status(created["task"]["id"], "pending")
        waiting = await self.call(self.owner, "get_board_tasks", run_status="pending")
        self.assertEqual([t["title"] for t in waiting["tasks"]], ["NDA"])

    async def test_reader_and_outsider_cannot_change(self) -> None:
        created = await self.add(self.owner, "NDA")
        card_id = created["task"]["id"]
        denied = await self.call(self.reader, "update_board_task", card_id=card_id, priority="low")
        self.assertIn("Read-only", denied["error"])
        hidden = await self.call(
            self.outsider, "update_board_task", card_id=card_id, priority="low"
        )
        self.assertIn("not found", hidden["error"].lower())
        moved = await self.call(
            self.reader,
            "move_board_task",
            card_id=card_id,
            to_column_id=str(self.columns[1].id),
        )
        self.assertIn("Read-only", moved["error"])

    async def test_assign_update_and_move(self) -> None:
        created = await self.add(self.owner, "NDA")
        card_id = created["task"]["id"]
        updated = await self.call(
            self.owner,
            "update_board_task",
            card_id=card_id,
            assignee_user_id=str(self.reader.id),
            title="NDA v2",
        )
        self.assertEqual(updated["task"]["assignee"]["id"], str(self.reader.id))
        self.assertEqual(updated["task"]["title"], "NDA v2")
        cleared = await self.call(
            self.owner, "update_board_task", card_id=card_id, assignee_user_id=None
        )
        self.assertIsNone(cleared["task"]["assignee"])
        moved = await self.call(
            self.owner, "move_board_task", card_id=card_id, to_column_id=str(self.columns[2].id)
        )
        self.assertEqual(moved["from_column"], "Backlog")
        self.assertEqual(moved["to_column"], "Development")
        self.assertNotIn("review_cancelled", moved)
        self.assertNotIn("auto_advanced_to", moved)

    async def test_non_member_cannot_be_assigned(self) -> None:
        created = await self.add(self.owner, "NDA")
        result = await self.call(
            self.owner,
            "update_board_task",
            card_id=created["task"]["id"],
            assignee_user_id=str(self.outsider.id),
        )
        self.assertIn("member", result["error"])

    async def test_moving_a_pending_card_reports_the_cancelled_review(self) -> None:
        created = await self.add(self.owner, "NDA")
        await self.set_run_status(created["task"]["id"], "pending")
        moved = await self.call(
            self.owner,
            "move_board_task",
            card_id=created["task"]["id"],
            to_column_id=str(self.columns[1].id),
        )
        self.assertTrue(moved["review_cancelled"])
        self.assertIn("not approved", moved["note"])

    async def test_running_card_cannot_change_column(self) -> None:
        created = await self.add(self.owner, "NDA")
        await self.set_run_status(created["task"]["id"], "running")
        moved = await self.call(
            self.owner,
            "move_board_task",
            card_id=created["task"]["id"],
            to_column_id=str(self.columns[1].id),
        )
        self.assertIn("still running", moved["error"])

    async def test_delete_task(self) -> None:
        created = await self.add(self.owner, "NDA")
        deleted = await self.call(self.writer, "delete_board_task", card_id=created["task"]["id"])
        self.assertTrue(deleted["deleted"])
        self.assertEqual(deleted["task"]["title"], "NDA")

    async def test_delete_board_needs_owner_and_exact_name(self) -> None:
        by_writer = await self.call(
            self.writer, "delete_board", board_id=str(self.board.id), confirm_name="Legal"
        )
        self.assertIn("owner", by_writer["error"])
        wrong = await self.call(
            self.owner, "delete_board", board_id=str(self.board.id), confirm_name="legal"
        )
        self.assertIn("confirm_name", wrong["error"])
        done = await self.call(
            self.owner, "delete_board", board_id=str(self.board.id), confirm_name="Legal"
        )
        self.assertTrue(done["deleted"])
        async with AsyncSession(self.engine) as db:
            self.assertIsNone(await db.get(Board, self.board.id))

    async def test_update_board_is_owner_only(self) -> None:
        refused = await self.call(
            self.writer, "update_board", board_id=str(self.board.id), name="Mine"
        )
        self.assertIn("owner", refused["error"])
        updated = await self.call(
            self.owner, "update_board", board_id=str(self.board.id), auto_advance=True
        )
        self.assertTrue(updated["board"]["auto_advance"])

    async def test_columns(self) -> None:
        added = await self.call(
            self.writer,
            "create_board_column",
            board_id=str(self.board.id),
            name="Review",
            position=2,
        )
        self.assertEqual(added["column"]["position"], 2)
        renamed = await self.call(
            self.writer,
            "update_board_column",
            board_id=str(self.board.id),
            column_id=added["column"]["id"],
            name="Legal review",
        )
        self.assertEqual(renamed["column"]["name"], "Legal review")
        await self.add(self.owner, "NDA", column_id=added["column"]["id"])
        refused = await self.call(
            self.owner,
            "delete_board_column",
            board_id=str(self.board.id),
            column_id=added["column"]["id"],
        )
        self.assertIn("Move or delete", refused["error"])
        moved = await self.call(
            self.owner,
            "delete_board_column",
            board_id=str(self.board.id),
            column_id=added["column"]["id"],
            move_cards_to_column_id=str(self.columns[0].id),
        )
        self.assertTrue(moved["deleted"])
        self.assertEqual(moved["column"]["name"], "Legal review")

    async def test_members(self) -> None:
        members = await self.call(self.reader, "list_board_members", board_id=str(self.board.id))
        self.assertEqual(members["count"], 3)
        self.assertEqual(members["members"][0]["permission"], "owner")

    async def test_card_detail_reaches_shared_boards(self) -> None:
        created = await self.add(self.owner, "NDA", labels=["Acme"])
        detail = await self.call(self.reader, "get_card_detail", card_id=created["task"]["id"])
        self.assertEqual(detail["title"], "NDA")
        self.assertEqual(detail["labels"], ["Acme"])
        self.assertNotIn("status", detail)

    async def test_create_board_with_auto_advance_off(self) -> None:
        created = await self.call(self.owner, "create_board", name="Team tasks", auto_advance=False)
        self.assertFalse(created["board"]["auto_advance"])
        self.assertEqual(created["board"]["permission"], "owner")

    async def test_create_task_without_board_asks_when_several_are_writable(self) -> None:
        await make_board(self.engine, self.owner, name="Second")
        asked = await self.call(self.owner, "create_board_task", title="Brief")
        self.assertTrue(asked["requires_board_selection"])
        self.assertEqual(asked["count"], 2)
        only = await self.call(self.writer, "create_board_task", title="Brief")
        self.assertTrue(only["created"], only)

    async def test_a_writer_comments_on_a_task_as_themselves(self) -> None:
        created = await self.add(self.owner, "NDA")
        card_id = created["task"]["id"]
        commented = await self.call(
            self.writer, "add_board_task_comment", card_id=card_id, content="  Sent to **Acme**  "
        )
        self.assertTrue(commented["commented"], commented)
        self.assertEqual(commented["comment"]["content"], "Sent to **Acme**")
        self.assertEqual(commented["comment"]["author"], self.writer.name)
        self.assertEqual(commented["task"]["title"], "NDA")
        self.assertNotIn("chain_started", commented)
        async with AsyncSession(self.engine) as db:
            stored = (
                await db.execute(
                    select(BoardCardActivity).where(
                        BoardCardActivity.card_id == uuid.UUID(card_id),
                        BoardCardActivity.kind == "comment",
                    )
                )
            ).scalar_one()
        self.assertEqual((stored.author_type, stored.author_user_id), ("user", self.writer.id))
        detail = await self.call(self.reader, "get_card_detail", card_id=card_id)
        self.assertEqual(
            [(c["author"], c["content"]) for c in detail["comments"]],
            [(self.writer.name, "Sent to **Acme**")],
        )

    async def test_reader_and_outsider_cannot_comment(self) -> None:
        created = await self.add(self.owner, "NDA")
        card_id = created["task"]["id"]
        denied = await self.call(
            self.reader, "add_board_task_comment", card_id=card_id, content="Hi"
        )
        self.assertIn("Read-only", denied["error"])
        hidden = await self.call(
            self.outsider, "add_board_task_comment", card_id=card_id, content="Hi"
        )
        self.assertIn("not found", hidden["error"].lower())

    async def test_answering_a_task_at_the_planning_step_says_it_moves_on(self) -> None:
        created = await self.add(self.owner, "NDA")
        card_id = created["task"]["id"]

        async def release(db, *, card, column, board):
            card.run_status = "running"
            await db.commit()
            return True

        with patch.object(
            chat_boards.boards_api.board_run_service, "answer_card_comment", side_effect=release
        ):
            answered = await self.call(
                self.owner, "add_board_task_comment", card_id=card_id, content="Use the 2025 terms"
            )
        self.assertTrue(answered["chain_started"])
        self.assertIn("planning step", answered["note"])
        self.assertEqual(answered["task"]["run_status"], "running")
