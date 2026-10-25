"""Held runs show up as queued with their position, and Cancel removes them."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.workflow_concurrency import HeldRunRecord


class ActiveOverviewQueuedTests(unittest.IsolatedAsyncioTestCase):
    async def test_held_runs_are_listed_as_queued(self) -> None:
        from app.services import active_execution_overview

        record = HeldRunRecord(
            execution_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            workflow_name="wf",
            enqueued_at=datetime.now(timezone.utc),
            inputs={},
            position=2,
            size=3,
        )
        with (
            patch.object(
                active_execution_overview,
                "list_persisted_active_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch.object(active_execution_overview, "list_active_executions", return_value=[]),
            patch.object(
                active_execution_overview,
                "list_pending_review_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                active_execution_overview.workflow_concurrency,
                "list_held_runs_for_user",
                AsyncMock(return_value=[record]),
            ),
        ):
            items = await active_execution_overview.collect_active_executions_for_user(
                AsyncMock(), uuid.uuid4()
            )
        (item,) = items
        self.assertEqual((item.status, item.queue_position, item.queue_size), ("queued", 2, 3))


class CancelHeldEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_finds_a_held_run_first(self) -> None:
        from app.api.workflows import cancel_workflow_execution

        workflow = SimpleNamespace(id=uuid.uuid4(), name="wf", owner_id=uuid.uuid4())
        with (
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch(
                "app.api.workflows.cancel_pending_review_execution",
                AsyncMock(return_value=False),
            ),
            patch(
                "app.api.workflows.workflow_concurrency.cancel_held",
                AsyncMock(return_value=True),
            ) as cancel_held,
            patch("app.api.workflows.cancel_active_execution") as cancel_local,
        ):
            result = await cancel_workflow_execution(
                workflow_id=workflow.id,
                execution_id=uuid.uuid4(),
                current_user=SimpleNamespace(id=uuid.uuid4(), email="a@b.c"),
                db=AsyncMock(),
            )
        self.assertEqual(result, {"status": "cancel_requested"})
        cancel_held.assert_awaited_once()
        cancel_local.assert_not_called()
