"""Board API behavior for team kanban use, on a real PostgreSQL."""

import unittest
import uuid
from datetime import date

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import boards as boards_api
from app.db.models import BoardCard, ExecutionHistory, Workflow
from app.models.board_schemas import (
    BoardCreateRequest,
    BoardUpdateRequest,
    CardCreateRequest,
    CardLinkModel,
    CardMoveRequest,
    CardUpdateRequest,
)
from tests.board_pg_support import cleanup, connect_or_skip, make_board, make_user, share_board


class KanbanPgCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = await connect_or_skip(self)
        self.owner = await make_user(self.engine, "owner")
        self.users = [self.owner]
        self.teams = []

    async def asyncTearDown(self) -> None:
        await cleanup(self.engine, self.users, self.teams)

    def session(self) -> AsyncSession:
        return AsyncSession(self.engine, expire_on_commit=False)

    async def card_in(self, board_id: uuid.UUID, column_id: uuid.UUID, title: str) -> uuid.UUID:
        async with self.session() as db:
            card = await boards_api.create_card(
                board_id=board_id,
                request=CardCreateRequest(title=title, column_id=column_id),
                db=db,
                current_user=self.owner,
            )
            return card.id


class AutoAdvanceTests(KanbanPgCase):
    async def test_new_boards_advance_and_the_setting_round_trips(self) -> None:
        async with self.session() as db:
            created = await boards_api.create_board(
                request=BoardCreateRequest(name="Team", auto_advance=False),
                db=db,
                current_user=self.owner,
            )
            self.assertFalse(created.auto_advance)
            updated = await boards_api.update_board(
                board_id=created.id,
                request=BoardUpdateRequest(auto_advance=True),
                db=db,
                current_user=self.owner,
            )
            self.assertTrue(updated.auto_advance)
            state = await boards_api.get_board_state(
                board_id=created.id, db=db, current_user=self.owner
            )
            self.assertTrue(state.auto_advance)

    async def test_without_auto_advance_a_card_stays_in_an_empty_column(self) -> None:
        board, columns = await make_board(self.engine, self.owner, auto_advance=False)
        card_id = await self.card_in(board.id, columns[0].id, "Contract review")
        async with self.session() as db:
            await boards_api.move_card(
                board_id=board.id,
                card_id=card_id,
                request=CardMoveRequest(to_column_id=columns[2].id),
                db=db,
                current_user=self.owner,
            )
        async with self.session() as db:
            card = await db.get(BoardCard, card_id)
            self.assertEqual(card.column_id, columns[2].id)
            self.assertEqual(card.run_status, "idle")

    async def test_with_auto_advance_a_card_passes_empty_columns(self) -> None:
        board, columns = await make_board(self.engine, self.owner, auto_advance=True)
        card_id = await self.card_in(board.id, columns[0].id, "Contract review")
        async with self.session() as db:
            await boards_api.move_card(
                board_id=board.id,
                card_id=card_id,
                request=CardMoveRequest(to_column_id=columns[2].id),
                db=db,
                current_user=self.owner,
            )
        async with self.session() as db:
            card = await db.get(BoardCard, card_id)
            self.assertEqual(card.column_id, columns[3].id)


class CardFieldApiTests(KanbanPgCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.writer = await make_user(self.engine, "writer")
        self.reader = await make_user(self.engine, "reader")
        self.outsider = await make_user(self.engine, "outsider")
        self.users += [self.writer, self.reader, self.outsider]
        self.board, self.columns = await make_board(self.engine, self.owner, auto_advance=False)
        await share_board(self.engine, self.board, self.writer, "write")
        await share_board(self.engine, self.board, self.reader, "read")
        self.card_id = await self.card_in(self.board.id, self.columns[0].id, "NDA for Acme")

    async def update(self, user, **fields):
        async with self.session() as db:
            return await boards_api.update_card(
                board_id=self.board.id,
                card_id=self.card_id,
                request=CardUpdateRequest(**fields),
                db=db,
                current_user=user,
            )

    async def test_fields_round_trip_and_merge(self) -> None:
        card = await self.update(
            self.writer,
            assignee_user_id=self.writer.id,
            priority="high",
            due_date=date(2026, 11, 10),
            labels=["Acme", " acme ", "NDA"],
        )
        self.assertEqual(card.fields.assignee_user_id, self.writer.id)
        self.assertEqual(card.fields.labels, ["Acme", "NDA"])
        self.assertEqual(card.fields.due_date, date(2026, 11, 10))
        card = await self.update(self.writer, priority=None)
        self.assertIsNone(card.fields.priority)
        self.assertEqual(card.fields.assignee_user_id, self.writer.id)

    async def test_create_takes_fields(self) -> None:
        async with self.session() as db:
            card = await boards_api.create_card(
                board_id=self.board.id,
                request=CardCreateRequest(title="Brief", priority="urgent", labels=["Beta"]),
                db=db,
                current_user=self.writer,
            )
        self.assertEqual(card.fields.priority, "urgent")
        self.assertEqual(card.fields.labels, ["Beta"])

    async def test_raw_metadata_write_keeps_attachments_and_fields(self) -> None:
        async with self.session() as db:
            row = await db.get(BoardCard, self.card_id)
            row.card_metadata = {"attachments": [{"file_id": "f"}], "priority": "low"}
            await db.commit()
        card = await self.update(self.owner, card_metadata={"note": "x"})
        self.assertEqual(card.card_metadata["attachments"], [{"file_id": "f"}])
        self.assertEqual(card.fields.priority, "low")
        self.assertEqual(card.card_metadata["note"], "x")

    async def test_assignee_must_be_a_member(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self.update(self.owner, assignee_user_id=self.outsider.id)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_reader_cannot_write(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self.update(self.reader, priority="low")
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_stale_edit_version_conflicts_with_the_current_card(self) -> None:
        first = await self.update(self.owner, title="NDA for Acme v2")
        await self.update(self.writer, title="NDA for Acme v3")
        with self.assertRaises(HTTPException) as ctx:
            await self.update(self.owner, title="mine", expected_edit_version=first.edit_version)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["card"]["title"], "NDA for Acme v3")

    async def test_matching_edit_version_saves(self) -> None:
        first = await self.update(self.owner, title="v2")
        saved = await self.update(self.owner, title="v3", expected_edit_version=first.edit_version)
        self.assertEqual(saved.title, "v3")

    async def test_links_are_checked_on_write_and_hidden_without_access(self) -> None:
        async with self.session() as db:
            workflow = Workflow(name="Draft NDA", owner_id=self.owner.id, nodes=[], edges=[])
            db.add(workflow)
            await db.flush()
            run = ExecutionHistory(workflow_id=workflow.id, status="success")
            db.add(run)
            await db.commit()
        card = await self.update(
            self.owner, links=[CardLinkModel(workflow_id=workflow.id, execution_id=run.id)]
        )
        self.assertEqual(card.fields.links[0].workflow_name, "Draft NDA")
        self.assertEqual(card.fields.links[0].execution_status, "success")
        self.assertNotIn("links", card.card_metadata)
        with self.assertRaises(HTTPException):
            await self.update(self.writer, links=[CardLinkModel(workflow_id=workflow.id)])
        async with self.session() as db:
            state = await boards_api.get_board_state(
                board_id=self.board.id, db=db, current_user=self.reader
            )
        link = next(c for c in state.cards if c.id == self.card_id).fields.links[0]
        self.assertTrue(link.hidden)
        self.assertIsNone(link.workflow_id)

    async def test_a_writer_keeps_links_they_cannot_see(self) -> None:
        async with self.session() as db:
            private = Workflow(name="Owner only", owner_id=self.owner.id, nodes=[], edges=[])
            shared = Workflow(name="Writer's", owner_id=self.writer.id, nodes=[], edges=[])
            db.add_all([private, shared])
            await db.commit()
        await self.update(self.owner, links=[CardLinkModel(workflow_id=private.id)])
        card = await self.update(self.writer, links=[CardLinkModel(workflow_id=shared.id)])
        self.assertEqual(len(card.fields.links), 2)
        self.assertEqual(card.fields.links[0].workflow_name, "Writer's")
        self.assertTrue(card.fields.links[1].hidden)

    async def test_members_endpoint(self) -> None:
        async with self.session() as db:
            members = await boards_api.list_board_members(
                board_id=self.board.id, db=db, current_user=self.reader
            )
        self.assertEqual(
            {m.user_id for m in members}, {self.owner.id, self.writer.id, self.reader.id}
        )
        async with self.session() as db:
            with self.assertRaises(HTTPException) as ctx:
                await boards_api.list_board_members(
                    board_id=self.board.id, db=db, current_user=self.outsider
                )
        self.assertEqual(ctx.exception.status_code, 404)
