"""Dashboard HITL inbox: owner-only reviews, and the widget does not cache them."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.hitl import get_hitl_inbox_link, list_hitl_inbox, submit_owned_hitl_decision
from app.db.models import HITLRequest
from app.models.schemas import HITLDecisionRequest, HITLInboxItem
from app.services.dashboard_data import compute_widget_data
from app.services.hitl_service import get_owned_hitl_request, list_pending_hitl_for_owner


def _make_request() -> HITLRequest:
    request_id = uuid.uuid4()
    return HITLRequest(
        id=request_id,
        workflow_id=uuid.uuid4(),
        execution_history_id=uuid.uuid4(),
        public_token=f"token-{request_id.hex}",
        workflow_name="Intake",
        agent_node_id="n1",
        agent_label="Reviewer",
        summary="Needs a look",
        original_draft_text="Draft body",
        original_agent_output={},
        resolved_output={},
        execution_snapshot={},
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        created_at=datetime.now(timezone.utc),
    )


def _user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


class HitlInboxQueryTest(IsolatedAsyncioTestCase):
    async def test_list_counts_and_returns_oldest_rows(self) -> None:
        request = _make_request()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 4
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [request]
        db = AsyncMock()
        db.execute.side_effect = [count_result, rows_result]

        total, rows = await list_pending_hitl_for_owner(db, uuid.uuid4())

        self.assertEqual(total, 4)
        self.assertEqual(rows, [request])
        count_sql = str(db.execute.await_args_list[0].args[0])
        rows_sql = str(db.execute.await_args_list[1].args[0])
        self.assertIn("workflows", count_sql)
        self.assertIn("hitl_requests", rows_sql)
        self.assertIn("created_at", rows_sql)

    async def test_unowned_request_is_not_found(self) -> None:
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        with self.assertRaises(HTTPException) as ctx:
            await get_owned_hitl_request(db, uuid.uuid4(), uuid.uuid4())

        self.assertEqual(ctx.exception.status_code, 404)


class HitlInboxApiTest(IsolatedAsyncioTestCase):
    async def test_inbox_payload_has_text_and_no_token(self) -> None:
        request = _make_request()
        user = _user()
        with patch(
            "app.api.hitl.list_pending_hitl_for_owner",
            new=AsyncMock(return_value=(2, [request])),
        ):
            response = await list_hitl_inbox(user, AsyncMock())

        self.assertEqual(response.pending_total, 2)
        self.assertEqual(response.items[0].text, "Draft body")
        self.assertEqual(response.items[0].workflow_id, request.workflow_id)
        self.assertEqual(response.items[0].execution_history_id, request.execution_history_id)
        self.assertNotIn("public_token", HITLInboxItem.model_fields)
        dumped = response.items[0].model_dump()
        self.assertNotIn(request.public_token, dumped.values())

    async def test_link_404_when_caller_does_not_own_the_review(self) -> None:
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        with self.assertRaises(HTTPException) as ctx:
            await get_hitl_inbox_link(uuid.uuid4(), _user(), db)

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_link_returns_review_url_for_the_owner(self) -> None:
        request = _make_request()
        with (
            patch(
                "app.api.hitl.get_owned_hitl_request",
                new=AsyncMock(return_value=request),
            ),
            patch(
                "app.api.hitl.build_default_public_base_url",
                return_value="https://heym.example",
            ),
        ):
            response = await get_hitl_inbox_link(request.id, _user(), AsyncMock())

        self.assertEqual(response.url, f"https://heym.example/review/{request.public_token}")

    async def test_owned_decision_uses_the_same_claim_path(self) -> None:
        request = _make_request()
        background = MagicMock()
        db = AsyncMock()
        with (
            patch(
                "app.api.hitl.get_owned_hitl_request",
                new=AsyncMock(return_value=request),
            ),
            patch("app.api.hitl.claim_hitl_request_for_decision", new=AsyncMock(return_value=True)),
            patch("app.api.hitl.resume_hitl_request_in_background"),
        ):
            response = await submit_owned_hitl_decision(
                request.id,
                HITLDecisionRequest(action="accept"),
                background,
                _user(),
                db,
            )

        self.assertEqual(response.status, "resolved")
        self.assertEqual(request.decision, "accept")
        background.add_task.assert_called_once()


class HitlWidgetDataTest(IsolatedAsyncioTestCase):
    async def test_hitl_widget_skips_the_workflow_and_does_not_cache_reviews(self) -> None:
        widget = MagicMock()
        widget.id = uuid.uuid4()
        widget.workflow_id = uuid.uuid4()
        workflow = MagicMock()
        workflow.nodes = [
            {"id": "c1", "type": "chartOutput", "data": {"chartType": "hitl", "label": "reviews"}}
        ]
        workflow.edges = []
        db = AsyncMock()
        found = MagicMock()
        found.scalar_one_or_none.return_value = workflow
        db.execute.return_value = found

        with patch("app.services.dashboard_data.dispatch_workflow", new=AsyncMock()) as dispatch:
            response = await compute_widget_data(db, widget, uuid.uuid4())

        dispatch.assert_not_awaited()
        db.commit.assert_not_awaited()
        self.assertEqual(response.payload, {"type": "hitl"})
        self.assertFalse(response.cached)
        self.assertIsNone(response.error)
