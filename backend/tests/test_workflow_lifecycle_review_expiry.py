"""A review nobody can answer any more does not keep its workflow from being deleted."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
from sqlalchemy import delete, select
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.db.models import (
    Board,
    BoardCard,
    BoardCardRun,
    BoardColumn,
    BoardColumnWorkflow,
    CodexFollowupRequest,
    ExecutionHistory,
    HITLRequest,
    Workflow,
)
from app.db.session import async_session_maker
from app.main import app
from app.services.auth import create_access_token
from app.services.cron_scheduler import CronScheduler
from app.services.workflow_lifecycle import has_unfinished_workflow_executions


class _ReviewFixture(ConcurrencyPostgresCase):
    limit = None

    async def _paused_run(self, *, expires_in: timedelta, codex: bool = False) -> uuid.UUID:
        """A run parked on a pending review that expires `expires_in` from now."""
        execution_id = uuid.uuid4()
        expires_at = datetime.now(timezone.utc) + expires_in
        async with async_session_maker() as db:
            db.add(
                ExecutionHistory(
                    id=execution_id,
                    workflow_id=self.workflow_id,
                    inputs={},
                    outputs={},
                    node_results=[],
                    status="pending",
                    execution_time_ms=1.0,
                    trigger_source="API",
                )
            )
            await db.flush()
            common = {
                "workflow_id": self.workflow_id,
                "execution_history_id": execution_id,
                "public_token": uuid.uuid4().hex,
                "workflow_name": "Review fixture",
                "status": "pending",
                "expires_at": expires_at,
            }
            if codex:
                db.add(CodexFollowupRequest(codex_node_id="codex", codex_label="Codex", **common))
            else:
                db.add(HITLRequest(agent_node_id="agent", agent_label="Agent", **common))
            await db.commit()
        return execution_id

    async def _blocked(self) -> bool:
        with patch("app.services.workflow_lifecycle.list_active_executions", return_value=[]):
            async with async_session_maker() as db:
                return await has_unfinished_workflow_executions(db, self.workflow_id)


class ReviewExpiryDeletionTests(_ReviewFixture):
    async def test_an_answerable_review_blocks_deletion(self) -> None:
        await self._paused_run(expires_in=timedelta(hours=1))
        self.assertTrue(await self._blocked())

    async def test_an_expired_review_does_not_block_deletion(self) -> None:
        await self._paused_run(expires_in=-timedelta(minutes=1))
        self.assertFalse(await self._blocked())

    async def test_an_answerable_codex_question_blocks_deletion(self) -> None:
        await self._paused_run(expires_in=timedelta(hours=1), codex=True)
        self.assertTrue(await self._blocked())

    async def test_an_expired_codex_question_does_not_block_deletion(self) -> None:
        await self._paused_run(expires_in=-timedelta(minutes=1), codex=True)
        self.assertFalse(await self._blocked())


class ExpiredReviewBoardCardTests(_ReviewFixture):
    """A board card parked on an expired review is released when its workflow goes."""

    async def _board_with_parked_card(self, execution_id: uuid.UUID) -> dict[str, uuid.UUID]:
        ids = {name: uuid.uuid4() for name in ("board", "todo", "done", "card", "run")}
        async with async_session_maker() as db:
            db.add(Board(id=ids["board"], owner_id=self.user_id, name="Review board"))
            await db.flush()
            db.add_all(
                [
                    BoardColumn(id=ids["todo"], board_id=ids["board"], name="Todo", position=0),
                    BoardColumn(id=ids["done"], board_id=ids["board"], name="Done", position=1),
                ]
            )
            await db.flush()
            db.add(BoardColumnWorkflow(column_id=ids["todo"], workflow_id=self.workflow_id))
            db.add(
                BoardCard(
                    id=ids["card"],
                    board_id=ids["board"],
                    column_id=ids["todo"],
                    title="Card",
                    run_status="pending",
                )
            )
            await db.flush()
            db.add(
                BoardCardRun(
                    id=ids["run"],
                    card_id=ids["card"],
                    column_id=ids["todo"],
                    workflow_id=self.workflow_id,
                    workflow_name="Review fixture",
                    status="pending",
                    execution_history_id=execution_id,
                )
            )
            await db.commit()
        self.addAsyncCleanup(self._remove_board, ids["board"])
        return ids

    async def _remove_board(self, board_id: uuid.UUID) -> None:
        async with async_session_maker() as db:
            await db.execute(delete(Board).where(Board.id == board_id))
            await db.commit()

    async def test_deleting_the_workflow_releases_a_card_parked_on_an_expired_review(
        self,
    ) -> None:
        execution_id = await self._paused_run(expires_in=-timedelta(minutes=1))
        ids = await self._board_with_parked_card(execution_id)
        headers = {"Authorization": f"Bearer {create_access_token(self.user_id)}"}
        transport = httpx.ASGITransport(app=app)

        with patch("app.services.workflow_lifecycle.list_active_executions", return_value=[]):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver", headers=headers
            ) as client:
                deleted = await client.delete(f"/api/workflows/{self.workflow_id}")
                async with async_session_maker() as db:
                    run_status = (
                        await db.execute(
                            select(BoardCardRun.status).where(BoardCardRun.id == ids["run"])
                        )
                    ).scalar_one()
                column = await client.delete(
                    f"/api/boards/{ids['board']}/columns/{ids['todo']}",
                    params={"move_cards_to_column_id": str(ids["done"])},
                )

        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertNotEqual(run_status, "pending")
        self.assertEqual(column.status_code, 204, column.text)

    async def test_an_answerable_review_still_blocks_and_stays_pending(self) -> None:
        execution_id = await self._paused_run(expires_in=timedelta(hours=1))
        ids = await self._board_with_parked_card(execution_id)
        headers = {"Authorization": f"Bearer {create_access_token(self.user_id)}"}
        transport = httpx.ASGITransport(app=app)

        with patch("app.services.workflow_lifecycle.list_active_executions", return_value=[]):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver", headers=headers
            ) as client:
                deleted = await client.delete(f"/api/workflows/{self.workflow_id}")

        async with async_session_maker() as db:
            run_status = (
                await db.execute(select(BoardCardRun.status).where(BoardCardRun.id == ids["run"]))
            ).scalar_one()
            history_status = (
                await db.execute(
                    select(ExecutionHistory.status).where(ExecutionHistory.id == execution_id)
                )
            ).scalar_one()
        self.assertEqual(deleted.status_code, 409)
        self.assertEqual((run_status, history_status), ("pending", "pending"))

    async def test_scheduled_deletion_releases_a_card_parked_on_an_expired_review(
        self,
    ) -> None:
        execution_id = await self._paused_run(expires_in=-timedelta(minutes=1))
        ids = await self._board_with_parked_card(execution_id)
        async with async_session_maker() as db:
            workflow = await db.get(Workflow, self.workflow_id)
            workflow.scheduled_for_deletion = datetime.now(timezone.utc)
            await db.commit()

        with patch("app.services.workflow_lifecycle.list_active_executions", return_value=[]):
            await CronScheduler()._cleanup_scheduled_workflows()

        async with async_session_maker() as db:
            run_status = (
                await db.execute(select(BoardCardRun.status).where(BoardCardRun.id == ids["run"]))
            ).scalar_one()
            remaining = await db.get(Workflow, self.workflow_id)
        self.assertIsNone(remaining)
        self.assertNotEqual(run_status, "pending")
