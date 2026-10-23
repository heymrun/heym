"""Dashboard HITL inbox: owner-only reviews, and the widget does not cache them."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.hitl import (
    count_hitl_dashboard_reviews,
    get_hitl_inbox_link,
    list_hitl_inbox,
    list_hitl_review_sources,
    submit_owned_hitl_decision,
)
from app.db.models import HITLRequest
from app.models.schemas import HITLDecisionRequest, HITLInboxItem
from app.services.dashboard_data import compute_widget_data
from app.services.hitl_service import (
    REVIEW_SOURCE_ERROR,
    count_pending_by_step,
    count_pending_in_workflows,
    ensure_review_source,
    filter_reachable,
    get_decidable_hitl_request,
    get_owned_hitl_request,
    list_pending_hitl_for_owner,
    list_review_sources,
)
from app.services.hitl_widget_filter import (
    HITL_FILTER_ACCESS_ERROR,
    HitlWidgetFilter,
    ReviewSource,
    ReviewStep,
)


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


def _rows(*rows: object) -> MagicMock:
    result = MagicMock()
    result.all.return_value = list(rows)
    return result


def _workflow_row(name: str, nodes: list) -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.name = name
    row.nodes = nodes
    return row


_APPROVER = {"id": "a1", "type": "agent", "data": {"label": "Approver", "hitlEnabled": True}}
_ASK = {
    "id": "s1",
    "type": "slack",
    "data": {"label": "Ask finance", "slackOperation": "requestApproval"},
}


class HitlInboxFilterQueryTest(IsolatedAsyncioTestCase):
    async def test_workflow_and_step_narrow_the_count_and_the_rows(self) -> None:
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        db = AsyncMock()
        db.execute.side_effect = [count_result, rows_result]
        workflow_id = uuid.uuid4()

        await list_pending_hitl_for_owner(db, uuid.uuid4(), workflow_id=workflow_id, node_id="a1")

        for call in db.execute.await_args_list:
            sql = str(call.args[0])
            self.assertIn("hitl_requests.workflow_id =", sql)
            self.assertIn("hitl_requests.agent_node_id =", sql)
            # Anyone who can open the workflow sees its queue, not only its owner.
            self.assertIn("workflow_shares", sql)
            self.assertIn("workflow_team_shares", sql)

    async def test_without_a_filter_the_queue_is_not_narrowed(self) -> None:
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        db = AsyncMock()
        db.execute.side_effect = [count_result, rows_result]

        await list_pending_hitl_for_owner(db, uuid.uuid4())

        sql = str(db.execute.await_args_list[0].args[0])
        self.assertNotIn("hitl_requests.workflow_id =", sql)
        # The unfiltered queue stays the user's own workflows.
        self.assertIn("workflows.owner_id =", sql)
        self.assertNotIn("workflow_shares", sql)

    async def test_counts_group_by_workflow_and_step_within_the_owner_scope(self) -> None:
        workflow_id = uuid.uuid4()
        db = AsyncMock()
        db.execute.return_value = _rows((workflow_id, "a1", 3))

        counts = await count_pending_by_step(db, uuid.uuid4())

        self.assertEqual(counts, {(workflow_id, "a1"): 3})
        sql = str(db.execute.await_args.args[0])
        self.assertIn("GROUP BY", sql)
        self.assertIn("workflows.owner_id", sql)
        self.assertNotIn("workflow_shares", sql)

    async def test_chosen_workflows_count_for_anyone_who_can_open_them(self) -> None:
        shared = uuid.uuid4()
        db = AsyncMock()
        db.execute.return_value = _rows((shared, "legal", 6))

        counts = await count_pending_in_workflows(db, uuid.uuid4(), [shared])

        self.assertEqual(counts, {(shared, "legal"): 6})
        sql = str(db.execute.await_args.args[0])
        self.assertIn("hitl_requests.workflow_id IN", sql)
        self.assertIn("workflow_shares", sql)

    async def test_no_chosen_workflows_cost_no_query(self) -> None:
        db = AsyncMock()
        self.assertEqual(await count_pending_in_workflows(db, uuid.uuid4(), []), {})
        db.execute.assert_not_awaited()

    async def test_reach_check_uses_workflow_access(self) -> None:
        db = AsyncMock()
        found = MagicMock()
        found.scalars.return_value.all.return_value = []
        db.execute.return_value = found

        allowed = await filter_reachable(db, uuid.uuid4(), HitlWidgetFilter(uuid.uuid4()))

        self.assertFalse(allowed)
        sql = str(db.execute.await_args.args[0])
        self.assertIn("workflows.id IN", sql)
        self.assertIn("workflows.owner_id =", sql)
        self.assertIn("workflow_shares", sql)

    async def test_deciding_reaches_reviews_of_workflows_the_caller_can_open(self) -> None:
        db = AsyncMock()
        found = MagicMock()
        found.scalar_one_or_none.return_value = None
        db.execute.return_value = found

        with self.assertRaises(HTTPException) as ctx:
            await get_decidable_hitl_request(db, uuid.uuid4(), uuid.uuid4())

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("workflow_shares", str(db.execute.await_args.args[0]))

    async def test_the_review_link_stays_with_the_owner(self) -> None:
        db = AsyncMock()
        found = MagicMock()
        found.scalar_one_or_none.return_value = None
        db.execute.return_value = found

        with self.assertRaises(HTTPException):
            await get_owned_hitl_request(db, uuid.uuid4(), uuid.uuid4())

        self.assertNotIn("workflow_shares", str(db.execute.await_args.args[0]))


class ReviewSourcesTest(IsolatedAsyncioTestCase):
    async def test_only_workflows_with_waiting_steps_are_sources(self) -> None:
        invoices = _workflow_row("Invoices", [_APPROVER, _ASK])
        notes = _workflow_row("Notes", [{"id": "c1", "type": "codex", "data": {"label": "Fix"}}])
        db = AsyncMock()
        db.execute.return_value = _rows(invoices, notes)

        sources = await list_review_sources(db, uuid.uuid4())

        self.assertEqual(
            sources,
            [
                ReviewSource(
                    workflow_id=invoices.id,
                    workflow_name="Invoices",
                    steps=(
                        ReviewStep("a1", "Approver", "agent"),
                        ReviewStep("s1", "Ask finance", "slack"),
                    ),
                )
            ],
        )
        sql = str(db.execute.await_args.args[0])
        self.assertIn("workflows.owner_id =", sql)
        self.assertIn("workflow_shares", sql)
        self.assertIn("workflows.kind !=", sql)

    async def test_a_new_filter_must_name_a_source_and_one_of_its_steps(self) -> None:
        workflow_id = uuid.uuid4()
        found = MagicMock()
        found.one_or_none.return_value = MagicMock(nodes=[_APPROVER])
        db = AsyncMock()
        db.execute.return_value = found

        await ensure_review_source(db, uuid.uuid4(), HitlWidgetFilter(workflow_id, "a1"))
        await ensure_review_source(db, uuid.uuid4(), HitlWidgetFilter(workflow_id))
        with self.assertRaises(HTTPException) as ctx:
            await ensure_review_source(db, uuid.uuid4(), HitlWidgetFilter(workflow_id, "s9"))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, REVIEW_SOURCE_ERROR)

    async def test_a_workflow_outside_the_scope_is_refused(self) -> None:
        missing = MagicMock()
        missing.one_or_none.return_value = None
        db = AsyncMock()
        db.execute.return_value = missing

        with self.assertRaises(HTTPException) as ctx:
            await ensure_review_source(db, uuid.uuid4(), HitlWidgetFilter(uuid.uuid4()))

        self.assertEqual(ctx.exception.status_code, 422)

    async def test_sources_route_returns_steps_with_their_kind(self) -> None:
        source = ReviewSource(
            workflow_id=uuid.uuid4(),
            workflow_name="Invoices",
            steps=(ReviewStep("s1", "Ask finance", "slack"),),
        )
        with patch("app.api.hitl.list_review_sources", new=AsyncMock(return_value=[source])):
            response = await list_hitl_review_sources(_user(), AsyncMock())

        self.assertEqual(response.sources[0].workflow_name, "Invoices")
        self.assertEqual(response.sources[0].steps[0].kind, "slack")


class HitlInboxApiTest(IsolatedAsyncioTestCase):
    async def test_filtered_inbox_passes_workflow_and_step(self) -> None:
        workflow_id = uuid.uuid4()
        with (
            patch("app.api.hitl.filter_reachable", new=AsyncMock(return_value=True)),
            patch(
                "app.api.hitl.list_pending_hitl_for_owner",
                new=AsyncMock(return_value=(0, [])),
            ) as listing,
        ):
            await list_hitl_inbox(_user(), AsyncMock(), workflow_id=workflow_id, node_id=" a1 ")

        self.assertEqual(listing.await_args.kwargs, {"workflow_id": workflow_id, "node_id": "a1"})

    async def test_a_workflow_outside_the_scope_is_403_and_lists_nothing(self) -> None:
        with (
            patch("app.api.hitl.filter_reachable", new=AsyncMock(return_value=False)),
            patch("app.api.hitl.list_pending_hitl_for_owner", new=AsyncMock()) as listing,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await list_hitl_inbox(_user(), AsyncMock(), workflow_id=uuid.uuid4())

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, HITL_FILTER_ACCESS_ERROR)
        listing.assert_not_awaited()

    async def test_a_step_without_its_workflow_is_422(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await list_hitl_inbox(_user(), AsyncMock(), node_id="a1")

        self.assertEqual(ctx.exception.status_code, 422)

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

    async def test_inbox_decision_reaches_any_workflow_the_caller_can_open(self) -> None:
        request = _make_request()
        background = MagicMock()
        db = AsyncMock()
        with (
            patch(
                "app.api.hitl.get_decidable_hitl_request",
                new=AsyncMock(return_value=request),
            ) as load,
            patch("app.api.hitl.get_owned_hitl_request", new=AsyncMock()) as owned,
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
        load.assert_awaited_once()
        owned.assert_not_awaited()


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


class HitlDashboardCountsTest(IsolatedAsyncioTestCase):
    async def test_each_dashboard_counts_what_its_widgets_show(self) -> None:
        invoices = uuid.uuid4()
        approvals, overview, everything = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        filtered = [
            {
                "id": "chart",
                "type": "chartOutput",
                "data": {"chartType": "hitl", "hitlWorkflowId": str(invoices)},
            }
        ]
        plain = [{"id": "chart", "type": "chartOutput", "data": {"chartType": "hitl"}}]
        widgets = _rows(
            MagicMock(dashboard_id=approvals, nodes=filtered),
            MagicMock(dashboard_id=everything, nodes=plain),
        )
        db = AsyncMock()
        db.execute.return_value = widgets
        # invoices is shared with the caller: it is not in their own queue.
        own = {(uuid.uuid4(), "b1"): 5}
        chosen = {(invoices, "a1"): 2}
        with (
            patch(
                "app.api.hitl.reachable_dashboard_ids",
                new=AsyncMock(return_value={approvals, overview, everything}),
            ),
            patch("app.api.hitl.count_pending_by_step", new=AsyncMock(return_value=own)),
            patch(
                "app.api.hitl.count_pending_in_workflows", new=AsyncMock(return_value=chosen)
            ) as counting,
        ):
            response = await count_hitl_dashboard_reviews(
                _user(), db, dashboard_id=[approvals, overview, everything]
            )

        self.assertEqual(response.counts, {str(approvals): 2, str(everything): 5})
        self.assertEqual(counting.await_args.args[2], {invoices})

    async def test_unreachable_dashboards_are_not_counted(self) -> None:
        db = AsyncMock()
        with (
            patch("app.api.hitl.reachable_dashboard_ids", new=AsyncMock(return_value=set())),
            patch("app.api.hitl.count_pending_by_step", new=AsyncMock()) as counting,
        ):
            response = await count_hitl_dashboard_reviews(_user(), db, dashboard_id=[uuid.uuid4()])

        self.assertEqual(response.counts, {})
        counting.assert_not_awaited()
        db.execute.assert_not_awaited()

    async def test_too_many_dashboards_are_refused(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await count_hitl_dashboard_reviews(
                _user(), AsyncMock(), dashboard_id=[uuid.uuid4() for _ in range(101)]
            )

        self.assertEqual(ctx.exception.status_code, 422)
