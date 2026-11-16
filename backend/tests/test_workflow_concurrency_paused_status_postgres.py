"""The status URL follows a queued run that paused for review until the run finishes."""

import json
import uuid
from datetime import datetime, timedelta, timezone

from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.db.models import ExecutionHistory, Workflow, WorkflowRunQueue
from app.db.session import async_session_maker
from app.services import mcp_execution_status, workflow_concurrency

PAUSED_SUMMARY = {"status": "pending", "outputs": {"review_url": "https://heym.example/r/x"}}


class PausedQueuedRunStatusTests(ConcurrencyPostgresCase):
    async def _queued_run(self, queue_result: dict, history: tuple[str, dict] | None) -> uuid.UUID:
        """A queue row as the worker leaves it, and the history row as the review leaves it."""
        execution_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        async with async_session_maker() as db:
            db.add(
                WorkflowRunQueue(
                    workflow_id=self.workflow_id,
                    execution_id=execution_id,
                    placement="any",
                    status="done",
                    inputs={},
                    result=queue_result,
                    enqueued_at=now,
                    not_after=now + timedelta(minutes=5),
                    finished_at=now,
                )
            )
            if history is not None:
                db.add(
                    ExecutionHistory(
                        id=execution_id,
                        workflow_id=self.workflow_id,
                        inputs={},
                        outputs=history[1],
                        node_results=[],
                        status=history[0],
                        execution_time_ms=12.0,
                        trigger_source="API",
                    )
                )
            await db.commit()
        return execution_id

    async def _status(self, execution_id: uuid.UUID) -> dict:
        body = await workflow_concurrency.build_status_body(self.workflow_id, execution_id)
        assert body is not None
        return body

    async def test_a_decided_review_reports_the_finished_run(self) -> None:
        execution_id = await self._queued_run(
            PAUSED_SUMMARY, ("success", {"result": "refund sent"})
        )

        body = await self._status(execution_id)

        self.assertEqual(body["status"], "success")
        self.assertEqual(body["outputs"], {"result": "refund sent"})
        async with async_session_maker() as db:
            workflow = await db.get(Workflow, self.workflow_id)
        text, is_error = await mcp_execution_status.run_execution_status_tool(
            [workflow], {"execution_id": str(execution_id)}
        )
        self.assertFalse(is_error)
        self.assertEqual(json.loads(text)["status"], "success")

    async def test_a_review_still_open_stays_pending(self) -> None:
        execution_id = await self._queued_run(
            PAUSED_SUMMARY, ("pending", PAUSED_SUMMARY["outputs"])
        )

        self.assertEqual((await self._status(execution_id))["status"], "pending")

    async def test_a_pause_without_a_history_row_reads_the_queue_row(self) -> None:
        execution_id = await self._queued_run(PAUSED_SUMMARY, None)

        body = await self._status(execution_id)

        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["outputs"], PAUSED_SUMMARY["outputs"])

    async def test_a_finished_queue_row_still_answers_from_the_queue(self) -> None:
        summary = {"status": "success", "outputs": {"result": "from queue"}}
        execution_id = await self._queued_run(summary, ("success", {"result": "from history"}))

        self.assertEqual((await self._status(execution_id))["outputs"], {"result": "from queue"})
