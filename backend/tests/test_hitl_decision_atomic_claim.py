"""Regression test: HITL decisions must be claimed atomically.

Concurrent submissions for the same review request used to both pass the
pending check (read-check-write race), both commit, and both schedule a
background resume — so the paused workflow ran twice and one reviewer's
decision silently overwrote the other's while both received a success
response. The claim now happens in a single conditional UPDATE.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks, HTTPException

from app.api.hitl import submit_hitl_decision
from app.db.models import HITLRequest
from app.models.schemas import HITLDecisionRequest


def _make_request(status: str = "pending") -> HITLRequest:
    request_id = uuid.uuid4()
    return HITLRequest(
        id=request_id,
        workflow_id=uuid.uuid4(),
        execution_history_id=uuid.uuid4(),
        public_token=f"token-{request_id.hex}",
        workflow_name="wf",
        agent_node_id="n1",
        agent_label="agent",
        summary="summary",
        original_draft_text="draft",
        original_agent_output={},
        resolved_output={},
        execution_snapshot={},
        status=status,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _result(rowcount: int | None = None, scalar: object = None) -> MagicMock:
    result = MagicMock()
    if rowcount is not None:
        result.rowcount = rowcount
    result.scalar_one_or_none.return_value = scalar
    return result


class SubmitHitlDecisionAtomicClaimTest(IsolatedAsyncioTestCase):
    async def test_winner_claims_once_and_schedules_single_resume(self) -> None:
        request = _make_request()
        db = AsyncMock()
        db.execute.return_value = _result(rowcount=1)
        background_tasks = MagicMock(spec=BackgroundTasks)

        with (
            patch("app.api.hitl.get_hitl_request_by_token", new=AsyncMock(return_value=request)),
            patch("app.api.hitl.resume_hitl_request_in_background"),
        ):
            response = await submit_hitl_decision(
                request.public_token,
                HITLDecisionRequest(action="accept"),
                background_tasks,
                db,
            )

        self.assertEqual(response.status, "resolved")
        background_tasks.add_task.assert_called_once()

    async def test_lost_claim_returns_409_and_never_schedules_resume(self) -> None:
        request = _make_request()
        db = AsyncMock()
        db.execute.side_effect = [
            _result(rowcount=0),  # atomic claim loses
            _result(scalar=_make_request(status="resolved")),  # re-read shows the winner
        ]
        background_tasks = MagicMock(spec=BackgroundTasks)

        with patch("app.api.hitl.get_hitl_request_by_token", new=AsyncMock(return_value=request)):
            with self.assertRaises(HTTPException) as ctx:
                await submit_hitl_decision(
                    request.public_token,
                    HITLDecisionRequest(action="refuse"),
                    background_tasks,
                    db,
                )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "Review request has already been resolved")
        background_tasks.add_task.assert_not_called()

    async def test_lost_claim_returns_410_when_request_expired_in_flight(self) -> None:
        request = _make_request()
        expired = _make_request(status="expired")
        db = AsyncMock()
        db.execute.side_effect = [
            _result(rowcount=0),  # atomic claim loses on the expiry predicate
            _result(scalar=expired),
        ]
        background_tasks = MagicMock(spec=BackgroundTasks)

        with patch("app.api.hitl.get_hitl_request_by_token", new=AsyncMock(return_value=request)):
            with self.assertRaises(HTTPException) as ctx:
                await submit_hitl_decision(
                    request.public_token,
                    HITLDecisionRequest(action="accept"),
                    background_tasks,
                    db,
                )

        self.assertEqual(ctx.exception.status_code, 410)
        background_tasks.add_task.assert_not_called()


class ClaimHitlRequestForDecisionTest(IsolatedAsyncioTestCase):
    async def test_claim_predicates_include_status_and_expiry(self) -> None:
        from app.services.hitl_service import claim_hitl_request_for_decision

        db = AsyncMock()
        db.execute.return_value = _result(rowcount=1)
        request = _make_request()

        claimed = await claim_hitl_request_for_decision(
            db, request, decision="accept", edited_text=None, refusal_reason=None
        )

        self.assertTrue(claimed)
        statement = db.execute.call_args.args[0]
        sql = str(statement)
        self.assertIn("hitl_requests", sql)
        self.assertIn("status", sql)
        self.assertIn("expires_at", sql)

    async def test_claim_reports_loss_when_rowcount_is_zero(self) -> None:
        from app.services.hitl_service import claim_hitl_request_for_decision

        db = AsyncMock()
        db.execute.return_value = _result(rowcount=0)
        request = _make_request()

        claimed = await claim_hitl_request_for_decision(
            db, request, decision="accept", edited_text=None, refusal_reason=None
        )

        self.assertFalse(claimed)


class ResolveHitlReviewToolAtomicClaimTest(IsolatedAsyncioTestCase):
    async def _run_tool(self, claim_rowcount: int) -> tuple[dict, MagicMock]:
        from app.api.ai_assistant import resolve_hitl_review_tool

        request = _make_request()
        db = AsyncMock()
        db.execute.side_effect = [
            _result(scalar=request),  # request_id lookup
            _result(rowcount=claim_rowcount),  # atomic claim
            _result(scalar=_make_request(status="resolved")),  # re-read after loss
        ]
        with (
            patch(
                "app.api.ai_assistant.get_hitl_request_by_token",
                new=AsyncMock(return_value=request),
            ),
            patch(
                "app.api.ai_assistant.get_workflow_for_user",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch("app.api.ai_assistant.resume_hitl_request_in_background"),
            patch("app.api.ai_assistant.asyncio.create_task") as create_task,
        ):
            output = await resolve_hitl_review_tool(
                db,
                uuid.uuid4(),
                action="accept",
                request_id=str(request.id),
            )
        return json.loads(output), create_task

    async def test_lost_claim_reports_error_instead_of_overwriting(self) -> None:
        data, create_task = await self._run_tool(claim_rowcount=0)
        self.assertEqual(data["status"], "error")
        self.assertIn("already been resolved", data["error"])
        create_task.assert_not_called()

    async def test_winner_resumes_exactly_once(self) -> None:
        data, create_task = await self._run_tool(claim_rowcount=1)
        self.assertEqual(data["status"], "resolved")
        create_task.assert_called_once()
