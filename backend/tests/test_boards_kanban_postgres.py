"""Board API behavior for team kanban use, on a real PostgreSQL."""

import asyncio
import unittest
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import boards as boards_api
from app.db.models import Board, BoardCard, BoardColumn, BoardColumnWorkflow, Workflow
from app.models.board_schemas import (
    BoardCreateRequest,
    BoardUpdateRequest,
    CardCreateRequest,
    CardMoveRequest,
    CardUpdateRequest,
    ColumnUpdateRequest,
)
from app.services import board_run_service
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


class BoardListTests(KanbanPgCase):
    async def test_finds_parent_boards_by_column_or_card_with_board_permissions(self) -> None:
        board, columns = await make_board(self.engine, self.owner)
        another, _ = await make_board(self.engine, self.owner)
        card_id = await self.card_in(board.id, columns[0].id, "Saved picker target")
        reader = await make_user(self.engine, "reader")
        outsider = await make_user(self.engine, "outsider")
        self.users.extend([reader, outsider])
        await share_board(self.engine, board, reader, "read")

        async with self.session() as db:
            unfiltered = await boards_api.list_boards(db=db, current_user=self.owner)
            self.assertEqual({item.id for item in unfiltered}, {board.id, another.id})
            for filters in ({"column_id": columns[0].id}, {"card_id": card_id}):
                with self.subTest(filters=filters):
                    owned = await boards_api.list_boards(db=db, current_user=self.owner, **filters)
                    shared = await boards_api.list_boards(db=db, current_user=reader, **filters)
                    hidden = await boards_api.list_boards(db=db, current_user=outsider, **filters)
                    self.assertEqual(
                        [(item.id, item.permission) for item in owned], [(board.id, "owner")]
                    )
                    self.assertEqual(
                        [(item.id, item.permission) for item in shared], [(board.id, "read")]
                    )
                    self.assertEqual(hidden, [])
            unknown = await boards_api.list_boards(
                db=db, current_user=self.owner, card_id=uuid.uuid4()
            )
            self.assertEqual(unknown, [])


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

    async def test_user_moves_before_auto_advance_obtains_lock_is_preserved(
        self,
    ) -> None:
        col_names = ["Backlog", "Planning", "Development", "Staging", "QA", "Done"]
        async with self.session() as db:
            board = Board(owner_id=self.owner.id, name="Move Before Lock Board", auto_advance=True)
            db.add(board)
            await db.flush()
            columns = [
                BoardColumn(id=uuid.uuid4(), board_id=board.id, name=name, position=idx)
                for idx, name in enumerate(col_names)
            ]
            db.add_all(columns)
            await db.flush()
            card = BoardCard(
                board_id=board.id,
                column_id=columns[2].id,
                title="Task Pre-move",
                position=0,
                run_status="success",
            )
            db.add(card)
            await db.commit()
            card_id = card.id
            board_id = board.id
            development_id = columns[2].id
            backlog_id = columns[0].id

        async with self.session() as user_db:
            await boards_api.move_card(
                board_id=board_id,
                card_id=card_id,
                request=CardMoveRequest(to_column_id=backlog_id),
                db=user_db,
                current_user=self.owner,
            )

        async with self.session() as session:
            await board_run_service._auto_advance(
                card_id=card_id,
                board_id=board_id,
                from_column_id=development_id,
                actor_user_id=self.owner.id,
                session_factory=lambda: session,
            )

        async with self.session() as db:
            final_card = await db.get(BoardCard, card_id)
            self.assertIsNotNone(final_card)
            assert final_card is not None
            self.assertEqual(final_card.column_id, backlog_id)

    async def test_user_moves_while_auto_advance_holds_lock_waits_and_completes(
        self,
    ) -> None:
        col_names = ["Backlog", "Planning", "Development", "Staging", "QA", "Done"]
        async with self.session() as db:
            board = Board(owner_id=self.owner.id, name="Lock Race Board", auto_advance=True)
            db.add(board)
            await db.flush()
            columns = [
                BoardColumn(id=uuid.uuid4(), board_id=board.id, name=name, position=idx)
                for idx, name in enumerate(col_names)
            ]
            db.add_all(columns)
            await db.flush()
            card = BoardCard(
                board_id=board.id,
                column_id=columns[2].id,
                title="Task Lock Test",
                position=0,
                run_status="success",
            )
            db.add(card)
            await db.commit()
            card_id = card.id
            board_id = board.id
            development_id = columns[2].id
            backlog_id = columns[0].id

        lock_acquired_event = asyncio.Event()
        resume_advance_event = asyncio.Event()
        lock_hook_fired = False

        original_get = AsyncSession.get

        async def hook_get(session_self, entity, ident, *args, **kwargs):
            nonlocal lock_hook_fired
            result = await original_get(session_self, entity, ident, *args, **kwargs)
            if (
                not lock_hook_fired
                and kwargs.get("with_for_update")
                and entity is BoardCard
                and ident == card_id
            ):
                lock_hook_fired = True
                lock_acquired_event.set()
                await asyncio.wait_for(resume_advance_event.wait(), timeout=5)
            return result

        async def run_advance():
            session = AsyncSession(self.engine, expire_on_commit=False)
            session.get = lambda entity, ident, *a, **kw: hook_get(session, entity, ident, *a, **kw)
            try:
                await board_run_service._auto_advance(
                    card_id=card_id,
                    board_id=board_id,
                    from_column_id=development_id,
                    actor_user_id=self.owner.id,
                    session_factory=lambda: session,
                )
            finally:
                await session.close()

        advance_task = asyncio.create_task(run_advance())
        try:
            await asyncio.wait_for(lock_acquired_event.wait(), timeout=5)

            async def run_user_move():
                async with self.session() as user_db:
                    await boards_api.move_card(
                        board_id=board_id,
                        card_id=card_id,
                        request=CardMoveRequest(to_column_id=backlog_id),
                        db=user_db,
                        current_user=self.owner,
                    )

            user_move_task = asyncio.create_task(run_user_move())
            try:
                await asyncio.sleep(0.05)
                self.assertFalse(user_move_task.done())

                resume_advance_event.set()
                await asyncio.wait_for(user_move_task, timeout=5)
                await asyncio.wait_for(advance_task, timeout=5)
            finally:
                if not user_move_task.done():
                    user_move_task.cancel()
                    try:
                        await user_move_task
                    except (asyncio.CancelledError, Exception):
                        pass
        finally:
            resume_advance_event.set()
            if not advance_task.done():
                advance_task.cancel()
                try:
                    await advance_task
                except (asyncio.CancelledError, Exception):
                    pass

        async with self.session() as db:
            final_card = await db.get(BoardCard, card_id)
            self.assertIsNotNone(final_card)
            assert final_card is not None
            self.assertEqual(final_card.column_id, backlog_id)

    async def test_concurrent_user_move_during_empty_column_cascade_is_preserved(
        self,
    ) -> None:
        col_names = ["Backlog", "Planning", "Development", "Staging", "QA", "Done"]
        async with self.session() as db:
            board = Board(owner_id=self.owner.id, name="Auto-advance Race Board", auto_advance=True)
            db.add(board)
            await db.flush()
            columns = [
                BoardColumn(id=uuid.uuid4(), board_id=board.id, name=name, position=idx)
                for idx, name in enumerate(col_names)
            ]
            db.add_all(columns)
            await db.flush()
            card = BoardCard(
                board_id=board.id,
                column_id=columns[2].id,
                title="Task 1",
                position=0,
                run_status="success",
            )
            db.add(card)
            await db.commit()
            card_id = card.id
            board_id = board.id
            staging_id = columns[3].id
            backlog_id = columns[0].id

        paused_event = asyncio.Event()
        resume_event = asyncio.Event()
        first_empty_col_committed = False
        original_commit = AsyncSession.commit

        async def hook_commit(session_self):
            nonlocal first_empty_col_committed
            await original_commit(session_self)
            if not first_empty_col_committed:
                c = await session_self.get(BoardCard, card_id)
                if c is not None and c.column_id == staging_id:
                    first_empty_col_committed = True
                    paused_event.set()
                    await asyncio.wait_for(resume_event.wait(), timeout=5)

        async def run_advance():
            session = AsyncSession(self.engine, expire_on_commit=False)
            session.commit = lambda: hook_commit(session)
            try:
                await board_run_service._auto_advance(
                    card_id=card_id,
                    board_id=board_id,
                    from_column_id=columns[2].id,
                    actor_user_id=self.owner.id,
                    session_factory=lambda: session,
                )
            finally:
                await session.close()

        advance_task = asyncio.create_task(run_advance())
        try:
            await asyncio.wait_for(paused_event.wait(), timeout=5)

            async with self.session() as user_db:
                await boards_api.move_card(
                    board_id=board_id,
                    card_id=card_id,
                    request=CardMoveRequest(to_column_id=backlog_id),
                    db=user_db,
                    current_user=self.owner,
                )

            resume_event.set()
            await asyncio.wait_for(advance_task, timeout=5)
        finally:
            resume_event.set()
            if not advance_task.done():
                advance_task.cancel()
                try:
                    await advance_task
                except (asyncio.CancelledError, Exception):
                    pass

        async with self.session() as db:
            final_card = await db.get(BoardCard, card_id)
            self.assertIsNotNone(final_card)
            assert final_card is not None
            self.assertEqual(final_card.column_id, backlog_id)

    async def test_concurrent_column_deletion_during_empty_column_cascade_is_preserved(
        self,
    ) -> None:
        col_names = ["Backlog", "Planning", "Development", "Staging", "QA", "Done"]
        async with self.session() as db:
            board = Board(
                owner_id=self.owner.id, name="Column Delete Race Board", auto_advance=True
            )
            db.add(board)
            await db.flush()
            columns = [
                BoardColumn(id=uuid.uuid4(), board_id=board.id, name=name, position=idx)
                for idx, name in enumerate(col_names)
            ]
            db.add_all(columns)
            await db.flush()
            card = BoardCard(
                board_id=board.id,
                column_id=columns[2].id,
                title="Task 2",
                position=0,
                run_status="success",
            )
            db.add(card)
            await db.commit()
            card_id = card.id
            board_id = board.id
            staging_id = columns[3].id
            backlog_id = columns[0].id

        paused_event = asyncio.Event()
        resume_event = asyncio.Event()
        first_empty_col_committed = False
        original_commit = AsyncSession.commit

        async def hook_commit(session_self):
            nonlocal first_empty_col_committed
            await original_commit(session_self)
            if not first_empty_col_committed:
                c = await session_self.get(BoardCard, card_id)
                if c is not None and c.column_id == staging_id:
                    first_empty_col_committed = True
                    paused_event.set()
                    await asyncio.wait_for(resume_event.wait(), timeout=5)

        async def run_advance():
            session = AsyncSession(self.engine, expire_on_commit=False)
            session.commit = lambda: hook_commit(session)
            try:
                await board_run_service._auto_advance(
                    card_id=card_id,
                    board_id=board_id,
                    from_column_id=columns[2].id,
                    actor_user_id=self.owner.id,
                    session_factory=lambda: session,
                )
            finally:
                await session.close()

        advance_task = asyncio.create_task(run_advance())
        try:
            await asyncio.wait_for(paused_event.wait(), timeout=5)

            async with self.session() as user_db:
                await boards_api.delete_column(
                    board_id=board_id,
                    column_id=staging_id,
                    move_cards_to_column_id=backlog_id,
                    db=user_db,
                    current_user=self.owner,
                )

            resume_event.set()
            await asyncio.wait_for(advance_task, timeout=5)
        finally:
            resume_event.set()
            if not advance_task.done():
                advance_task.cancel()
                try:
                    await advance_task
                except (asyncio.CancelledError, Exception):
                    pass

        async with self.session() as db:
            final_card = await db.get(BoardCard, card_id)
            self.assertIsNotNone(final_card)
            assert final_card is not None
            self.assertEqual(final_card.column_id, backlog_id)

    async def test_mid_cascade_move_to_empty_column_settles_running_to_success(
        self,
    ) -> None:
        col_names = ["Backlog", "Planning", "Development", "Staging", "QA", "Done"]
        async with self.session() as db:
            board = Board(
                owner_id=self.owner.id,
                name="Settle Idle Mid Cascade Board",
                auto_advance=True,
            )
            db.add(board)
            await db.flush()
            columns = [
                BoardColumn(id=uuid.uuid4(), board_id=board.id, name=name, position=idx)
                for idx, name in enumerate(col_names)
            ]
            db.add_all(columns)
            await db.flush()
            card = BoardCard(
                board_id=board.id,
                column_id=columns[2].id,
                title="Task Settle Mid Cascade",
                position=0,
                run_status="running",
            )
            db.add(card)
            await db.commit()
            card_id = card.id
            board_id = board.id
            staging_id = columns[3].id
            backlog_id = columns[0].id

        paused_event = asyncio.Event()
        resume_event = asyncio.Event()
        first_empty_col_committed = False
        original_commit = AsyncSession.commit

        async def hook_commit(session_self):
            nonlocal first_empty_col_committed
            await original_commit(session_self)
            if not first_empty_col_committed:
                c = await session_self.get(BoardCard, card_id)
                if c is not None and c.column_id == staging_id:
                    first_empty_col_committed = True
                    paused_event.set()
                    await asyncio.wait_for(resume_event.wait(), timeout=5)

        async def run_advance():
            session = AsyncSession(self.engine, expire_on_commit=False)
            session.commit = lambda: hook_commit(session)
            try:
                await board_run_service._auto_advance(
                    card_id=card_id,
                    board_id=board_id,
                    from_column_id=columns[2].id,
                    actor_user_id=self.owner.id,
                    session_factory=lambda: session,
                )
            finally:
                await session.close()

        advance_task = asyncio.create_task(run_advance())
        try:
            await asyncio.wait_for(paused_event.wait(), timeout=5)

            async with self.session() as user_db:
                await boards_api.move_card(
                    board_id=board_id,
                    card_id=card_id,
                    request=CardMoveRequest(to_column_id=backlog_id),
                    db=user_db,
                    current_user=self.owner,
                )

            resume_event.set()
            await asyncio.wait_for(advance_task, timeout=5)
        finally:
            resume_event.set()
            if not advance_task.done():
                advance_task.cancel()
                try:
                    await advance_task
                except (asyncio.CancelledError, Exception):
                    pass

        async with self.session() as db:
            final_card = await db.get(BoardCard, card_id)
            self.assertIsNotNone(final_card)
            assert final_card is not None
            self.assertEqual(final_card.column_id, backlog_id)
            self.assertEqual(final_card.run_status, "success")

    async def test_mid_cascade_move_to_column_with_workflow_preserves_running_status(
        self,
    ) -> None:
        col_names = ["Backlog", "Planning", "Development", "Staging", "QA", "Done"]
        async with self.session() as db:
            board = Board(
                owner_id=self.owner.id,
                name="Preserve Running Mid Cascade Board",
                auto_advance=True,
            )
            db.add(board)
            await db.flush()
            columns = [
                BoardColumn(id=uuid.uuid4(), board_id=board.id, name=name, position=idx)
                for idx, name in enumerate(col_names)
            ]
            db.add_all(columns)
            workflow = Workflow(name="Backlog Triage", owner_id=self.owner.id, nodes=[], edges=[])
            db.add(workflow)
            await db.flush()
            link = BoardColumnWorkflow(column_id=columns[0].id, workflow_id=workflow.id, position=0)
            db.add(link)
            card = BoardCard(
                board_id=board.id,
                column_id=columns[2].id,
                title="Task Active Chain",
                position=0,
                run_status="running",
            )
            db.add(card)
            await db.commit()
            card_id = card.id
            board_id = board.id
            staging_id = columns[3].id
            backlog_id = columns[0].id

        paused_event = asyncio.Event()
        resume_event = asyncio.Event()
        first_empty_col_committed = False
        original_commit = AsyncSession.commit

        async def hook_commit(session_self):
            nonlocal first_empty_col_committed
            await original_commit(session_self)
            if not first_empty_col_committed:
                c = await session_self.get(BoardCard, card_id)
                if c is not None and c.column_id == staging_id:
                    first_empty_col_committed = True
                    paused_event.set()
                    await asyncio.wait_for(resume_event.wait(), timeout=5)

        async def run_advance():
            session = AsyncSession(self.engine, expire_on_commit=False)
            session.commit = lambda: hook_commit(session)
            try:
                await board_run_service._auto_advance(
                    card_id=card_id,
                    board_id=board_id,
                    from_column_id=columns[2].id,
                    actor_user_id=self.owner.id,
                    session_factory=lambda: session,
                )
            finally:
                await session.close()

        advance_task = asyncio.create_task(run_advance())
        try:
            await asyncio.wait_for(paused_event.wait(), timeout=5)

            with patch.object(board_run_service, "_spawn_chain", MagicMock()):
                async with self.session() as user_db:
                    await boards_api.move_card(
                        board_id=board_id,
                        card_id=card_id,
                        request=CardMoveRequest(to_column_id=backlog_id),
                        db=user_db,
                        current_user=self.owner,
                    )

            resume_event.set()
            await asyncio.wait_for(advance_task, timeout=5)
        finally:
            resume_event.set()
            if not advance_task.done():
                advance_task.cancel()
                try:
                    await advance_task
                except (asyncio.CancelledError, Exception):
                    pass

        async with self.session() as db:
            final_card = await db.get(BoardCard, card_id)
            self.assertIsNotNone(final_card)
            assert final_card is not None
            self.assertEqual(final_card.column_id, backlog_id)
            self.assertEqual(final_card.run_status, "running")

    async def test_mid_cascade_settle_success_before_enqueue_recovers_running_status(
        self,
    ) -> None:
        col_names = ["Backlog", "Planning", "Development", "Staging", "QA", "Done"]
        async with self.session() as db:
            board = Board(
                owner_id=self.owner.id,
                name="Settle Before Enqueue Race Board",
                auto_advance=True,
            )
            db.add(board)
            await db.flush()
            columns = [
                BoardColumn(id=uuid.uuid4(), board_id=board.id, name=name, position=idx)
                for idx, name in enumerate(col_names)
            ]
            db.add_all(columns)
            workflow = Workflow(name="Backlog Triage", owner_id=self.owner.id, nodes=[], edges=[])
            db.add(workflow)
            await db.flush()
            link = BoardColumnWorkflow(column_id=columns[0].id, workflow_id=workflow.id, position=0)
            db.add(link)
            card = BoardCard(
                board_id=board.id,
                column_id=columns[2].id,
                title="Task Active Chain Race",
                position=0,
                run_status="running",
            )
            db.add(card)
            await db.commit()
            card_id = card.id
            board_id = board.id
            development_id = columns[2].id
            staging_id = columns[3].id
            backlog_id = columns[0].id

        paused_advance_event = asyncio.Event()
        resume_advance_event = asyncio.Event()
        first_empty_col_committed = False
        original_commit = AsyncSession.commit

        async def hook_advance_commit(session_self):
            nonlocal first_empty_col_committed
            await original_commit(session_self)
            if not first_empty_col_committed:
                c = await session_self.get(BoardCard, card_id)
                if c is not None and c.column_id == staging_id:
                    first_empty_col_committed = True
                    paused_advance_event.set()
                    await asyncio.wait_for(resume_advance_event.wait(), timeout=5)

        async def run_advance():
            session = AsyncSession(self.engine, expire_on_commit=False)
            session.commit = lambda: hook_advance_commit(session)
            try:
                await board_run_service._auto_advance(
                    card_id=card_id,
                    board_id=board_id,
                    from_column_id=development_id,
                    actor_user_id=self.owner.id,
                    session_factory=lambda: session,
                )
            finally:
                await session.close()

        advance_task = asyncio.create_task(run_advance())
        try:
            await asyncio.wait_for(paused_advance_event.wait(), timeout=5)

            move_col_committed = False

            async def hook_user_commit(session_self):
                nonlocal move_col_committed
                await original_commit(session_self)
                if not move_col_committed:
                    move_col_committed = True
                    resume_advance_event.set()
                    await asyncio.wait_for(advance_task, timeout=5)

            with patch.object(board_run_service, "_spawn_chain", MagicMock()):
                async with self.session() as user_db:
                    user_db.commit = lambda: hook_user_commit(user_db)
                    await boards_api.move_card(
                        board_id=board_id,
                        card_id=card_id,
                        request=CardMoveRequest(to_column_id=backlog_id),
                        db=user_db,
                        current_user=self.owner,
                    )
        finally:
            resume_advance_event.set()
            if not advance_task.done():
                advance_task.cancel()
                try:
                    await advance_task
                except (asyncio.CancelledError, Exception):
                    pass

        async with self.session() as db:
            final_card = await db.get(BoardCard, card_id)
            self.assertIsNotNone(final_card)
            assert final_card is not None
            self.assertEqual(final_card.column_id, backlog_id)
            self.assertEqual(final_card.run_status, "running")

    async def test_pre_cascade_move_settles_stale_running_status_if_idle(
        self,
    ) -> None:
        col_names = ["Backlog", "Planning", "Development", "Staging", "QA", "Done"]
        async with self.session() as db:
            board = Board(
                owner_id=self.owner.id,
                name="Pre Cascade Settle Board",
                auto_advance=True,
            )
            db.add(board)
            await db.flush()
            columns = [
                BoardColumn(id=uuid.uuid4(), board_id=board.id, name=name, position=idx)
                for idx, name in enumerate(col_names)
            ]
            db.add_all(columns)
            await db.flush()
            # Card was marked running (e.g. by answer_card_comment) in Development
            card = BoardCard(
                board_id=board.id,
                column_id=columns[2].id,
                title="Task Pre Cascade",
                position=0,
                run_status="running",
            )
            db.add(card)
            await db.commit()
            card_id = card.id
            board_id = board.id
            development_id = columns[2].id
            backlog_id = columns[0].id

        # User moves the card to Backlog before auto-advance starts
        async with self.session() as user_db:
            await boards_api.move_card(
                board_id=board_id,
                card_id=card_id,
                request=CardMoveRequest(to_column_id=backlog_id),
                db=user_db,
                current_user=self.owner,
            )

        # Now auto-advance fires from Development
        async with self.session() as session:
            await board_run_service._auto_advance(
                card_id=card_id,
                board_id=board_id,
                from_column_id=development_id,
                actor_user_id=self.owner.id,
                session_factory=lambda: session,
            )

        async with self.session() as db:
            final_card = await db.get(BoardCard, card_id)
            self.assertIsNotNone(final_card)
            assert final_card is not None
            self.assertEqual(final_card.column_id, backlog_id)
            self.assertEqual(final_card.run_status, "success")


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


class OrderTests(KanbanPgCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.board, self.columns = await make_board(self.engine, self.owner, auto_advance=False)

    async def order(self, column_id: uuid.UUID) -> list[str]:
        async with self.session() as db:
            rows = await db.execute(
                select(BoardCard.title)
                .where(BoardCard.column_id == column_id)
                .order_by(BoardCard.position)
            )
            return list(rows.scalars().all())

    async def move(self, card_id: uuid.UUID, column_id: uuid.UUID, position: int | None = None):
        async with self.session() as db:
            return await boards_api.move_card(
                board_id=self.board.id,
                card_id=card_id,
                request=CardMoveRequest(to_column_id=column_id, position=position),
                db=db,
                current_user=self.owner,
            )

    async def test_new_cards_go_on_top(self) -> None:
        await self.card_in(self.board.id, self.columns[0].id, "a")
        await self.card_in(self.board.id, self.columns[0].id, "b")
        self.assertEqual(await self.order(self.columns[0].id), ["b", "a"])

    async def test_moved_card_goes_on_top_or_to_the_given_index(self) -> None:
        a = await self.card_in(self.board.id, self.columns[0].id, "a")
        b = await self.card_in(self.board.id, self.columns[0].id, "b")
        c = await self.card_in(self.board.id, self.columns[1].id, "c")
        await self.move(a, self.columns[1].id)
        self.assertEqual(await self.order(self.columns[1].id), ["a", "c"])
        await self.move(b, self.columns[1].id, position=2)
        self.assertEqual(await self.order(self.columns[1].id), ["a", "c", "b"])
        await self.move(c, self.columns[1].id, position=0)
        self.assertEqual(await self.order(self.columns[1].id), ["c", "a", "b"])
        self.assertEqual(await self.order(self.columns[0].id), [])

    async def test_same_column_move_without_position_keeps_the_place(self) -> None:
        a = await self.card_in(self.board.id, self.columns[0].id, "a")
        await self.card_in(self.board.id, self.columns[0].id, "b")
        await self.move(a, self.columns[0].id)
        self.assertEqual(await self.order(self.columns[0].id), ["b", "a"])

    async def test_reorder_in_place_through_update(self) -> None:
        ids = {}
        for title in ("a", "b", "c"):
            ids[title] = await self.card_in(self.board.id, self.columns[0].id, title)
        async with self.session() as db:
            await boards_api.update_card(
                board_id=self.board.id,
                card_id=ids["a"],
                request=CardUpdateRequest(position=0),
                db=db,
                current_user=self.owner,
            )
        self.assertEqual(await self.order(self.columns[0].id), ["a", "c", "b"])


class ColumnDeleteTests(KanbanPgCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.board, self.columns = await make_board(self.engine, self.owner, auto_advance=False)
        self.a = await self.card_in(self.board.id, self.columns[1].id, "a")
        self.b = await self.card_in(self.board.id, self.columns[1].id, "b")
        await self.card_in(self.board.id, self.columns[0].id, "z")

    async def delete(self, move_to: uuid.UUID | None):
        async with self.session() as db:
            await boards_api.delete_column(
                board_id=self.board.id,
                column_id=self.columns[1].id,
                move_cards_to_column_id=move_to,
                db=db,
                current_user=self.owner,
            )

    async def test_refuses_without_a_target(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self.delete(None)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_moves_cards_on_top_of_the_target_without_running_chains(self) -> None:
        await self.delete(self.columns[0].id)
        async with self.session() as db:
            rows = await db.execute(
                select(BoardCard.title, BoardCard.run_status)
                .where(BoardCard.column_id == self.columns[0].id)
                .order_by(BoardCard.position)
            )
            self.assertEqual(
                [tuple(r) for r in rows.all()], [("b", "idle"), ("a", "idle"), ("z", "idle")]
            )

    async def test_refuses_while_a_card_waits_for_a_review(self) -> None:
        async with self.session() as db:
            card = await db.get(BoardCard, self.a)
            card.run_status = "pending"
            await db.commit()
        with self.assertRaises(HTTPException) as ctx:
            await self.delete(self.columns[0].id)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_target_must_be_another_column_of_the_board(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self.delete(self.columns[1].id)
        self.assertEqual(ctx.exception.status_code, 400)


class RevisionTests(KanbanPgCase):
    async def revision(self, board_id: uuid.UUID) -> str:
        async with self.session() as db:
            response = await boards_api.get_board_revision(
                board_id=board_id, db=db, current_user=self.owner
            )
            return response.revision

    async def test_every_kind_of_change_moves_the_revision(self) -> None:
        board, columns = await make_board(self.engine, self.owner, auto_advance=False)
        first = await self.revision(board.id)
        self.assertEqual(await self.revision(board.id), first)
        seen = {first}

        card_id = await self.card_in(board.id, columns[0].id, "a")
        seen.add(await self.revision(board.id))
        async with self.session() as db:
            await boards_api.update_card(
                board_id=board.id,
                card_id=card_id,
                request=CardUpdateRequest(priority="high"),
                db=db,
                current_user=self.owner,
            )
        seen.add(await self.revision(board.id))
        async with self.session() as db:
            await boards_api.update_column(
                board_id=board.id,
                column_id=columns[1].id,
                request=ColumnUpdateRequest(name="Review"),
                db=db,
                current_user=self.owner,
            )
        seen.add(await self.revision(board.id))
        async with self.session() as db:
            await boards_api.delete_card(
                board_id=board.id, card_id=card_id, db=db, current_user=self.owner
            )
        seen.add(await self.revision(board.id))
        async with self.session() as db:
            await boards_api.update_board(
                board_id=board.id,
                request=BoardUpdateRequest(name="Legal 2"),
                db=db,
                current_user=self.owner,
            )
        seen.add(await self.revision(board.id))
        self.assertEqual(len(seen), 6)

    async def test_a_chain_change_moves_the_revision(self) -> None:
        board, columns = await make_board(self.engine, self.owner)
        async with self.session() as db:
            workflow = Workflow(name="Draft", owner_id=self.owner.id, nodes=[], edges=[])
            db.add(workflow)
            await db.commit()
        before = await self.revision(board.id)
        async with self.session() as db:
            await boards_api.update_column(
                board_id=board.id,
                column_id=columns[1].id,
                request=ColumnUpdateRequest(workflow_ids=[workflow.id]),
                db=db,
                current_user=self.owner,
            )
        self.assertNotEqual(await self.revision(board.id), before)

    async def test_outsider_cannot_read_the_revision(self) -> None:
        board, _ = await make_board(self.engine, self.owner)
        outsider = await make_user(self.engine, "outsider")
        self.users.append(outsider)
        async with self.session() as db:
            with self.assertRaises(HTTPException) as ctx:
                await boards_api.get_board_revision(board_id=board.id, db=db, current_user=outsider)
        self.assertEqual(ctx.exception.status_code, 404)
