"""A review planted on a workflow without running it."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app.db.models import ExecutionHistory, HITLRequest
from app.services.hitl_service import _close_seeded_review, seed_pending_workflow_review


def _workflow() -> MagicMock:
    workflow = MagicMock()
    workflow.id = uuid.uuid4()
    workflow.name = "Client update approval"
    workflow.nodes = [
        {
            "id": "agent-1",
            "type": "agent",
            "data": {"label": "DraftClientUpdate", "hitlEnabled": True},
        }
    ]
    return workflow


def _db_with(existing: HITLRequest | None) -> tuple[AsyncMock, list]:
    added: list = []
    db = AsyncMock()
    db.add = MagicMock(side_effect=added.append)

    async def flush() -> None:
        for obj in added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    db.flush = AsyncMock(side_effect=flush)
    found = MagicMock()
    found.scalar_one_or_none.return_value = existing
    db.execute = AsyncMock(return_value=found)
    return db, added


class SeedPendingReviewTests(IsolatedAsyncioTestCase):
    async def test_plants_one_pending_run_on_the_review_step(self) -> None:
        db, added = _db_with(None)

        review, created = await seed_pending_workflow_review(
            db,
            _workflow(),
            owner_id=uuid.uuid4(),
            summary="Client update approval",
            draft_text="The hearing moved.",
            trigger_source="Heym Work demo",
            inputs={"matter_id": "M-2041"},
        )

        self.assertTrue(created)
        history = next(obj for obj in added if isinstance(obj, ExecutionHistory))
        self.assertIs(review, next(obj for obj in added if isinstance(obj, HITLRequest)))
        self.assertEqual(history.status, "pending")
        self.assertEqual(history.trigger_source, "Heym Work demo")
        self.assertEqual(history.inputs, {"matter_id": "M-2041"})
        pending = history.outputs["DraftClientUpdate"]
        self.assertIsNone(pending["decision"])
        self.assertEqual(pending["draftText"], "The hearing moved.")
        self.assertEqual(pending["requestId"], str(review.id))
        self.assertEqual(review.agent_label, "DraftClientUpdate")
        self.assertTrue(review.execution_snapshot["seeded_review"])
        self.assertEqual(history.node_results[0]["status"], "pending")

    async def test_a_review_already_waiting_is_left_as_it_is(self) -> None:
        existing = HITLRequest(
            id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            execution_history_id=uuid.uuid4(),
            public_token="token",
            workflow_name="Client update approval",
            agent_node_id="agent-1",
            agent_label="DraftClientUpdate",
            summary="Already waiting",
            original_draft_text="Draft",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db, added = _db_with(existing)

        review, created = await seed_pending_workflow_review(
            db,
            _workflow(),
            owner_id=uuid.uuid4(),
            summary="Client update approval",
            draft_text="The hearing moved.",
            trigger_source="Heym Work demo",
            inputs={},
        )

        self.assertFalse(created)
        self.assertIs(review, existing)
        self.assertEqual(added, [])

    async def test_a_workflow_without_a_review_step_is_refused(self) -> None:
        workflow = _workflow()
        workflow.nodes = [{"id": "n1", "type": "llm", "data": {"label": "Draft"}}]
        db, _added = _db_with(None)

        with self.assertRaises(HTTPException) as caught:
            await seed_pending_workflow_review(
                db,
                workflow,
                owner_id=uuid.uuid4(),
                summary="Client update approval",
                draft_text="The hearing moved.",
                trigger_source="Heym Work demo",
                inputs={},
            )

        self.assertEqual(caught.exception.status_code, 422)

    def test_deciding_a_planted_review_finishes_the_run(self) -> None:
        history = ExecutionHistory(
            workflow_id=uuid.uuid4(),
            status="pending",
            outputs={},
            node_results=[],
        )
        review = HITLRequest(
            workflow_id=history.workflow_id,
            execution_history_id=uuid.uuid4(),
            public_token="token",
            workflow_name="Client update approval",
            agent_node_id="agent-1",
            agent_label="DraftClientUpdate",
            summary="Client update approval",
            original_draft_text="The hearing moved.",
            decision="accept",
            status="resolved",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        _close_seeded_review(
            history, review, {"seeded_review": True, "paused_node_label": "DraftClientUpdate"}
        )

        self.assertEqual(history.status, "success")
        self.assertEqual(history.outputs, {"DraftClientUpdate": {"text": "The hearing moved."}})
