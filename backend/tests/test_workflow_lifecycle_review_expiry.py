"""A review nobody can answer any more does not keep its workflow from being deleted."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.db.models import CodexFollowupRequest, ExecutionHistory, HITLRequest
from app.db.session import async_session_maker
from app.services.workflow_lifecycle import has_unfinished_workflow_executions


class ReviewExpiryDeletionTests(ConcurrencyPostgresCase):
    limit = None

    async def _paused_run(self, *, expires_in: timedelta, codex: bool = False) -> None:
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

    async def _blocked(self) -> bool:
        with patch("app.services.workflow_lifecycle.list_active_executions", return_value=[]):
            async with async_session_maker() as db:
                return await has_unfinished_workflow_executions(db, self.workflow_id)

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
