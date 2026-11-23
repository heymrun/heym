"""Exercise the Heym node's board reads with real PostgreSQL and the workflow executor."""

import unittest
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BoardCard
from app.services.workflow_executor import NodeResult, WorkflowExecutor
from tests.board_pg_support import (
    cleanup,
    connect_or_skip,
    make_board,
    make_user,
    share_board,
    share_board_with_team,
)


class HeymBoardNodeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = await connect_or_skip(self)
        self.owner = await make_user(self.engine, "board-owner")
        self.reader = await make_user(self.engine, "direct-reader")
        self.teammate = await make_user(self.engine, "team-reader")
        self.outsider = await make_user(self.engine, "board-outsider")
        self.board, self.columns = await make_board(self.engine, self.owner)
        self.team = await share_board_with_team(
            self.engine, self.board, self.owner, [self.teammate], "read"
        )
        self.addAsyncCleanup(
            cleanup,
            self.engine,
            [self.owner, self.reader, self.teammate, self.outsider],
            [self.team],
        )
        await share_board(self.engine, self.board, self.reader, "read")
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            self.card = BoardCard(
                board_id=self.board.id,
                column_id=self.columns[0].id,
                title="First card",
                content="Description in Markdown",
                position=0,
                card_metadata={"priority": "high", "labels": ["legal"]},
            )
            self.second_card = BoardCard(
                board_id=self.board.id, column_id=self.columns[0].id, title="Next card", position=1
            )
            db.add_all(
                [
                    self.second_card,
                    self.card,
                    BoardCard(
                        board_id=self.board.id, column_id=self.columns[1].id, title="Another column"
                    ),
                ]
            )
            await db.commit()

    def _read(self, actor_id: uuid.UUID, operation: str, field: str, target: str) -> NodeResult:
        executor = WorkflowExecutor(
            [
                {
                    "id": "read",
                    "type": "heym",
                    "data": {"heymOperation": operation, field: "$input.id"},
                }
            ],
            [],
            actor_user_id=actor_id,
        )
        return executor.execute_node("read", {"id": target})

    async def test_reads_board_column_and_card_in_display_order(self) -> None:
        board = self._read(self.owner.id, "getBoard", "heymBoardId", str(self.board.id))
        self.assertEqual(board.status, "success")
        self.assertEqual(board.output["name"], self.board.name)
        self.assertEqual(
            [(column["id"], column["name"]) for column in board.output["columns"]],
            [(str(column.id), column.name) for column in self.columns],
        )
        column = self._read(
            self.reader.id, "getBoardColumn", "heymBoardColumnId", board.output["columns"][0]["id"]
        )
        self.assertEqual(column.status, "success")
        self.assertEqual(column.output["board_id"], str(self.board.id))
        self.assertEqual(
            [(card["id"], card["title"]) for card in column.output["cards"]],
            [
                (str(self.card.id), self.card.title),
                (str(self.second_card.id), self.second_card.title),
            ],
        )
        empty = self._read(
            self.reader.id, "getBoardColumn", "heymBoardColumnId", str(self.columns[-1].id)
        )
        self.assertEqual(empty.output["cards"], [])
        card = self._read(
            self.teammate.id, "getBoardCardId", "heymBoardCardId", column.output["cards"][0]["id"]
        )
        self.assertEqual(card.status, "success")
        self.assertEqual(card.output["content"], self.card.content)
        self.assertEqual(card.output["fields"]["priority"], "high")
        self.assertEqual(card.output["fields"]["labels"], ["legal"])
        self.assertEqual(card.output["column_id"], str(self.columns[0].id))
        self.assertEqual(card.output["path"], f"/b/{self.board.id}/cards/{self.card.id}")
        self.assertEqual(column.output["cards"][0]["path"], card.output["path"])

    async def test_hides_all_board_data_from_outsiders(self) -> None:
        for operation, field, target in (
            ("getBoard", "heymBoardId", self.board.id),
            ("getBoardColumn", "heymBoardColumnId", self.columns[0].id),
            ("getBoardCardId", "heymBoardCardId", self.card.id),
        ):
            with self.subTest(operation=operation):
                forbidden = self._read(self.outsider.id, operation, field, str(target))
                missing = self._read(self.owner.id, operation, field, str(uuid.uuid4()))
                malformed = self._read(self.owner.id, operation, field, "invalid-id")
                blank = self._read(self.owner.id, operation, field, "")
                self.assertEqual(forbidden.status, "error")
                self.assertEqual(forbidden.error, missing.error)
                self.assertEqual(forbidden.error, malformed.error)
                self.assertEqual(blank.status, "error")
                self.assertIn("ID is required", blank.error)
