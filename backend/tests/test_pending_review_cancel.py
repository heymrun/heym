import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.workflows import cancel_workflow_execution
from app.services.pending_review_cancel import cancel_pending_review_execution


def _update_result(rowcount: int) -> MagicMock:
    result = MagicMock()
    result.rowcount = rowcount
    return result


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_history(status: str = "pending") -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        outputs={"Review": {"status": "pending"}},
        node_results=[
            {"node_id": "a", "status": "success"},
            {"node_id": "b", "status": "pending"},
        ],
    )


class CancelPendingReviewExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancels_pending_hitl_review_and_history(self) -> None:
        history = _make_history()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_update_result(1), _update_result(0), _scalar_result(history)]
        )

        with patch("app.services.board_run_service.resume_card_chain", AsyncMock()) as resume:
            cancelled = await cancel_pending_review_execution(
                db, workflow_id=uuid.uuid4(), execution_id=uuid.uuid4()
            )

        self.assertTrue(cancelled)
        self.assertEqual(history.status, "cancelled")
        self.assertEqual(history.outputs, {"error": "Execution was cancelled"})
        self.assertEqual(
            [item["status"] for item in history.node_results], ["success", "cancelled"]
        )
        db.commit.assert_awaited_once()
        resume.assert_awaited_once()

    async def test_cancels_pending_codex_followup(self) -> None:
        history = _make_history()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_update_result(0), _update_result(1), _scalar_result(history)]
        )

        with patch("app.services.board_run_service.resume_card_chain", AsyncMock()):
            cancelled = await cancel_pending_review_execution(
                db, workflow_id=uuid.uuid4(), execution_id=uuid.uuid4()
            )

        self.assertTrue(cancelled)
        self.assertEqual(history.status, "cancelled")

    async def test_returns_false_and_touches_nothing_without_pending_review(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_update_result(0), _update_result(0)])

        with patch("app.services.board_run_service.resume_card_chain", AsyncMock()) as resume:
            cancelled = await cancel_pending_review_execution(
                db, workflow_id=uuid.uuid4(), execution_id=uuid.uuid4()
            )

        self.assertFalse(cancelled)
        self.assertEqual(db.execute.await_count, 2)
        db.commit.assert_not_awaited()
        resume.assert_not_awaited()

    async def test_does_not_rewrite_history_that_already_finished(self) -> None:
        history = _make_history(status="success")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_update_result(1), _update_result(0), _scalar_result(history)]
        )

        with patch("app.services.board_run_service.resume_card_chain", AsyncMock()):
            await cancel_pending_review_execution(
                db, workflow_id=uuid.uuid4(), execution_id=uuid.uuid4()
            )

        self.assertEqual(history.status, "success")
        self.assertEqual(history.outputs, {"Review": {"status": "pending"}})


class CancelWorkflowExecutionEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # No run here is waiting for a concurrency slot.
        held = patch(
            "app.api.workflows.workflow_concurrency.cancel_held", AsyncMock(return_value=False)
        )
        held.start()
        self.addCleanup(held.stop)

    async def _call(
        self,
        *,
        pending: bool,
        local: bool,
        persisted: bool,
    ) -> tuple[object, MagicMock, AsyncMock]:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        cancel_local = MagicMock(return_value=local)
        cancel_persisted = AsyncMock(return_value=persisted)
        with (
            patch(
                "app.api.workflows.get_workflow_for_user",
                AsyncMock(
                    return_value=SimpleNamespace(
                        id=workflow_id, owner_id=uuid.uuid4(), name="Review workflow"
                    )
                ),
            ),
            patch(
                "app.api.workflows.cancel_pending_review_execution",
                AsyncMock(return_value=pending),
            ),
            patch("app.api.workflows.cancel_active_execution", cancel_local),
            patch("app.api.workflows.request_persisted_execution_cancel", cancel_persisted),
        ):
            result = await cancel_workflow_execution(
                workflow_id=workflow_id,
                execution_id=execution_id,
                current_user=SimpleNamespace(id=uuid.uuid4()),
                db=AsyncMock(),
            )
        return result, cancel_local, cancel_persisted

    async def test_pending_review_cancel_short_circuits_running_paths(self) -> None:
        result, cancel_local, cancel_persisted = await self._call(
            pending=True, local=False, persisted=False
        )

        self.assertEqual(result, {"status": "cancel_requested"})
        cancel_local.assert_not_called()
        cancel_persisted.assert_not_awaited()

    async def test_running_execution_still_uses_existing_cancel_paths(self) -> None:
        result, cancel_local, cancel_persisted = await self._call(
            pending=False, local=True, persisted=False
        )

        self.assertEqual(result, {"status": "cancel_requested"})
        cancel_local.assert_called_once()
        cancel_persisted.assert_awaited_once()

    async def test_unknown_execution_is_still_not_found(self) -> None:
        with self.assertRaises(HTTPException) as context:
            await self._call(pending=False, local=False, persisted=False)

        self.assertEqual(context.exception.status_code, 404)
