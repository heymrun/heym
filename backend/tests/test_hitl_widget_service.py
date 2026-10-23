"""A HITL widget's review filter at the read and write boundaries.

The filter is stored data, so it may only narrow what the viewer can already see: reads
re-check the viewer, and saves refuse a changed filter outside the saver's review scope.
"""

import datetime
import uuid
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import dashboards as dash_api
from app.api.workflows import update_workflow
from app.db.models import CredentialType, Workflow
from app.models.dashboard_schemas import (
    AiRefineRequest,
    AiWidgetRequest,
    HitlWidgetFilterModel,
    WidgetDataResponse,
    WidgetUpdateRequest,
)
from app.models.schemas import WebhookBodyMode, WorkflowAuthType, WorkflowUpdate
from app.services.chart_payload import build_chart_payload
from app.services.dashboard_data import compute_widget_data
from app.services.hitl_service import REVIEW_SOURCE_ERROR
from app.services.hitl_widget_filter import (
    HITL_FILTER_ACCESS_ERROR,
    ReviewSource,
    ReviewStep,
)
from app.services.hitl_widget_service import (
    AI_FILTER_ERROR,
    HIDDEN_WIDGET_DETAIL,
    apply_hitl_filter,
    check_hitl_filter_access,
    ensure_saved_filter_allowed,
    hidden_hitl_widgets,
    hitl_filters_for_widgets,
    hitl_sources_context,
)

SERVICE = "app.services.hitl_widget_service"


def _hitl_nodes(workflow_id: uuid.UUID | None = None, node_id: str | None = None) -> list:
    data: dict = {"label": "reviews", "chartType": "hitl"}
    if workflow_id is not None:
        data["hitlWorkflowId"] = str(workflow_id)
    if node_id is not None:
        data["hitlNodeId"] = node_id
    return [{"id": "chart", "type": "chartOutput", "position": {"x": 0, "y": 0}, "data": data}]


def _widget(chart_type: str = "hitl") -> MagicMock:
    widget = MagicMock()
    widget.id = uuid.uuid4()
    widget.workflow_id = uuid.uuid4()
    widget.chart_type = chart_type
    widget.title = "Reviews"
    widget.description = None
    widget.layout = {"x": 0, "y": 0, "w": 4, "h": 4}
    widget.cache_ttl_seconds = 300
    widget.position = 0
    widget.link_dashboard_id = None
    widget.link_record_field = None
    widget.link_label_field = None
    widget.updated_at = datetime.datetime.now(datetime.timezone.utc)
    return widget


def _widget_workflow(nodes: list) -> MagicMock:
    workflow = MagicMock()
    workflow.id = uuid.uuid4()
    workflow.nodes = nodes
    workflow.edges = []
    return workflow


def _found(value: object) -> MagicMock:
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


class HitlPayloadTest(IsolatedAsyncioTestCase):
    async def test_widget_data_carries_the_filter_and_still_skips_the_run(self) -> None:
        source = uuid.uuid4()
        widget = _widget()
        db = AsyncMock()
        db.execute.return_value = _found(_widget_workflow(_hitl_nodes(source, "a1")))

        with patch("app.services.dashboard_data.dispatch_workflow", new=AsyncMock()) as run:
            response = await compute_widget_data(db, widget, uuid.uuid4())

        run.assert_not_awaited()
        self.assertEqual(
            response.payload,
            {"type": "hitl", "filter": {"workflow_id": str(source), "node_id": "a1"}},
        )

    def test_canvas_chart_payload_carries_the_filter(self) -> None:
        source = uuid.uuid4()
        payload = build_chart_payload({"chartType": "hitl", "hitlWorkflowId": str(source)}, [])
        self.assertEqual(
            payload, {"type": "hitl", "filter": {"workflow_id": str(source), "node_id": None}}
        )


class ReadAccessTest(IsolatedAsyncioTestCase):
    """A owns a workflow and shares it with B; B's dashboard is shared with C, who cannot open it."""

    def _response(self, source: uuid.UUID) -> WidgetDataResponse:
        return WidgetDataResponse(
            widget_id=uuid.uuid4(),
            payload={"type": "hitl", "filter": {"workflow_id": str(source), "node_id": None}},
            cached=False,
            computed_at=None,
        )

    def _reach(self, *workflow_ids: uuid.UUID) -> AsyncMock:
        return AsyncMock(return_value=set(workflow_ids))

    async def test_a_viewer_who_can_open_the_workflow_gets_the_chart(self) -> None:
        source = uuid.uuid4()
        response = self._response(source)
        with patch(f"{SERVICE}.reachable_review_workflows", new=self._reach(source)):
            checked = await check_hitl_filter_access(
                AsyncMock(), response, uuid.uuid4(), dashboard_owner=False
            )
        self.assertIs(checked, response)

    async def test_the_dashboard_owner_without_access_is_told_to_pick_another(self) -> None:
        with patch(f"{SERVICE}.reachable_review_workflows", new=self._reach()):
            checked = await check_hitl_filter_access(
                AsyncMock(), self._response(uuid.uuid4()), uuid.uuid4(), dashboard_owner=True
            )
        self.assertIsNone(checked.payload)
        self.assertEqual(checked.error, HITL_FILTER_ACCESS_ERROR)

    async def test_anyone_else_without_access_does_not_see_the_widget(self) -> None:
        with patch(f"{SERVICE}.reachable_review_workflows", new=self._reach()):
            with self.assertRaises(HTTPException) as ctx:
                await check_hitl_filter_access(
                    AsyncMock(), self._response(uuid.uuid4()), uuid.uuid4(), dashboard_owner=False
                )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, HIDDEN_WIDGET_DETAIL)

    async def test_an_unfiltered_widget_is_not_checked(self) -> None:
        response = WidgetDataResponse(
            widget_id=uuid.uuid4(), payload={"type": "hitl"}, cached=False, computed_at=None
        )
        with patch(f"{SERVICE}.reachable_review_workflows", new=AsyncMock()) as reach:
            checked = await check_hitl_filter_access(
                AsyncMock(), response, uuid.uuid4(), dashboard_owner=False
            )
        reach.assert_not_awaited()
        self.assertIs(checked, response)

    async def _widget_data(self, viewer: MagicMock, owner_id: uuid.UUID) -> WidgetDataResponse:
        widget = _widget()
        dashboard = MagicMock(owner_id=owner_id)
        with (
            patch.object(
                dash_api,
                "_load_widget_for_user",
                AsyncMock(return_value=(widget, dashboard, "read")),
            ),
            patch.object(
                dash_api,
                "compute_widget_data",
                AsyncMock(return_value=self._response(uuid.uuid4())),
            ),
            patch(f"{SERVICE}.reachable_review_workflows", new=self._reach()) as reach,
        ):
            data = await dash_api.get_widget_data(
                widget.id, force=False, record=None, current_user=viewer, db=AsyncMock()
            )
        self.assertEqual(reach.await_args.args[1], viewer.id)
        return data

    async def test_widget_data_route_hides_the_widget_from_a_viewer_without_access(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._widget_data(_user(), owner_id=uuid.uuid4())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_widget_data_route_shows_the_owner_the_access_error(self) -> None:
        owner = _user()
        data = await self._widget_data(owner, owner_id=owner.id)
        self.assertEqual(data.error, HITL_FILTER_ACCESS_ERROR)
        self.assertIsNone(data.payload)

    async def test_hidden_widgets_are_those_filtered_on_workflows_the_viewer_cannot_open(
        self,
    ) -> None:
        shared, foreign = uuid.uuid4(), uuid.uuid4()
        open_widget, closed_widget = uuid.uuid4(), uuid.uuid4()
        filters = {
            open_widget: HitlWidgetFilterModel(workflow_id=shared),
            closed_widget: HitlWidgetFilterModel(workflow_id=foreign, node_id="a1"),
        }
        with patch(f"{SERVICE}.reachable_review_workflows", new=self._reach(shared)):
            hidden = await hidden_hitl_widgets(AsyncMock(), filters, uuid.uuid4(), uuid.uuid4())
        self.assertEqual(hidden, {closed_widget})

    async def test_the_dashboard_owner_keeps_every_widget(self) -> None:
        owner = uuid.uuid4()
        filters = {uuid.uuid4(): HitlWidgetFilterModel(workflow_id=uuid.uuid4())}
        with patch(f"{SERVICE}.reachable_review_workflows", new=AsyncMock()) as reach:
            hidden = await hidden_hitl_widgets(AsyncMock(), filters, owner, owner)
        self.assertEqual(hidden, set())
        reach.assert_not_awaited()

    async def test_dashboard_route_leaves_hidden_widgets_out(self) -> None:
        viewer = _user()
        dashboard = MagicMock(id=uuid.uuid4(), owner_id=uuid.uuid4())
        dashboard.name = "Approvals"
        dashboard.record_format = "id"
        dashboard.updated_at = datetime.datetime.now(datetime.timezone.utc)
        shown, hidden = _widget("bar"), _widget()
        widgets = MagicMock()
        widgets.scalars.return_value.all.return_value = [shown, hidden]
        owner_row = MagicMock()
        owner = MagicMock(email="b@x.test")
        owner.name = "B"
        owner_row.scalar_one.return_value = owner
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[owner_row, widgets])
        filters = {hidden.id: HitlWidgetFilterModel(workflow_id=uuid.uuid4())}
        with (
            patch.object(
                dash_api, "_get_dashboard_for_user", AsyncMock(return_value=(dashboard, "read"))
            ),
            patch.object(dash_api, "hitl_filters_for_widgets", AsyncMock(return_value=filters)),
            patch.object(dash_api, "_reachable_links", AsyncMock(return_value=set())),
            patch(f"{SERVICE}.reachable_review_workflows", new=self._reach()),
        ):
            response = await dash_api.get_dashboard(dashboard.id, viewer, db)

        self.assertEqual([widget.id for widget in response.widgets], [shown.id])


class SettingsSaveTest(IsolatedAsyncioTestCase):
    async def test_only_a_hitl_widget_takes_a_filter(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await apply_hitl_filter(
                AsyncMock(),
                _widget("bar"),
                HitlWidgetFilterModel(workflow_id=uuid.uuid4()),
                uuid.uuid4(),
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_a_workflow_outside_the_scope_is_refused_and_nothing_changes(self) -> None:
        nodes = _hitl_nodes()
        workflow = _widget_workflow(nodes)
        db = AsyncMock()
        db.execute.return_value = _found(workflow)
        refusal = HTTPException(status_code=422, detail=REVIEW_SOURCE_ERROR)
        with (
            patch(f"{SERVICE}.ensure_review_source", new=AsyncMock(side_effect=refusal)),
            patch(f"{SERVICE}.add_workflow_version", new=AsyncMock()) as version,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await apply_hitl_filter(
                    db, _widget(), HitlWidgetFilterModel(workflow_id=uuid.uuid4()), uuid.uuid4()
                )

        self.assertEqual(ctx.exception.status_code, 422)
        version.assert_not_awaited()
        self.assertEqual(workflow.nodes, nodes)

    async def test_a_valid_choice_is_a_versioned_edit_that_reloads_the_card(self) -> None:
        source = uuid.uuid4()
        workflow = _widget_workflow(_hitl_nodes())
        widget = _widget()
        before = widget.updated_at
        db = AsyncMock()
        db.execute.return_value = _found(workflow)
        actor = uuid.uuid4()
        with (
            patch(f"{SERVICE}.ensure_review_source", new=AsyncMock()) as check,
            patch(f"{SERVICE}.add_workflow_version", new=AsyncMock()) as version,
        ):
            await apply_hitl_filter(
                db, widget, HitlWidgetFilterModel(workflow_id=source, node_id=" a1 "), actor
            )

        self.assertEqual(check.await_args.args[1], actor)
        version.assert_awaited_once()
        self.assertEqual(version.await_args.args[2].nodes, _hitl_nodes())
        self.assertEqual(workflow.nodes, _hitl_nodes(source, "a1"))
        self.assertGreater(widget.updated_at, before)

    async def test_null_shows_every_review_again_without_a_scope_check(self) -> None:
        workflow = _widget_workflow(_hitl_nodes(uuid.uuid4(), "a1"))
        db = AsyncMock()
        db.execute.return_value = _found(workflow)
        with (
            patch(f"{SERVICE}.ensure_review_source", new=AsyncMock()) as check,
            patch(f"{SERVICE}.add_workflow_version", new=AsyncMock()) as version,
        ):
            await apply_hitl_filter(db, _widget(), None, uuid.uuid4())

        check.assert_not_awaited()
        version.assert_awaited_once()
        self.assertEqual(workflow.nodes, _hitl_nodes())

    async def test_the_same_choice_is_not_a_new_version(self) -> None:
        source = uuid.uuid4()
        workflow = _widget_workflow(_hitl_nodes(source))
        db = AsyncMock()
        db.execute.return_value = _found(workflow)
        with patch(f"{SERVICE}.add_workflow_version", new=AsyncMock()) as version:
            await apply_hitl_filter(
                db, _widget(), HitlWidgetFilterModel(workflow_id=source), uuid.uuid4()
            )
        version.assert_not_awaited()

    async def test_update_route_applies_the_filter_only_when_it_is_sent(self) -> None:
        widget = _widget()
        db = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        with (
            patch.object(
                dash_api, "_load_widget_for_user", AsyncMock(return_value=(widget, None, "write"))
            ),
            patch.object(dash_api, "_reachable_links", AsyncMock(return_value=set())),
            patch.object(dash_api, "apply_hitl_filter", AsyncMock()) as apply,
            patch.object(dash_api, "hitl_filters_for_widgets", AsyncMock(return_value={})),
        ):
            await dash_api.update_widget(
                widget.id, WidgetUpdateRequest(cache_ttl_seconds=60), _user(), db
            )
            apply.assert_not_awaited()
            await dash_api.update_widget(
                widget.id, WidgetUpdateRequest(hitl_filter=None), _user(), db
            )

        self.assertIsNone(apply.await_args.args[2])

    async def test_responses_carry_each_hitl_widgets_filter(self) -> None:
        source = uuid.uuid4()
        hitl = _widget()
        chart = _widget("bar")
        rows = MagicMock()
        rows.all.return_value = [MagicMock(id=hitl.workflow_id, nodes=_hitl_nodes(source, "a1"))]
        db = AsyncMock()
        db.execute.return_value = rows

        filters = await hitl_filters_for_widgets(db, [hitl, chart])

        self.assertEqual(
            filters, {hitl.id: HitlWidgetFilterModel(workflow_id=source, node_id="a1")}
        )
        self.assertEqual(db.execute.await_count, 1)

    async def test_a_page_without_hitl_widgets_costs_no_query(self) -> None:
        db = AsyncMock()
        self.assertEqual(await hitl_filters_for_widgets(db, [_widget("bar")]), {})
        db.execute.assert_not_awaited()


class SavedGraphTest(IsolatedAsyncioTestCase):
    async def test_an_unchanged_filter_is_not_checked_again(self) -> None:
        nodes = _hitl_nodes(uuid.uuid4())
        moved = [{**nodes[0], "position": {"x": 80, "y": 0}}]
        with patch(f"{SERVICE}.ensure_review_source", new=AsyncMock()) as check:
            await ensure_saved_filter_allowed(AsyncMock(), uuid.uuid4(), nodes, moved)
        check.assert_not_awaited()

    async def test_clearing_the_filter_needs_no_check(self) -> None:
        with patch(f"{SERVICE}.ensure_review_source", new=AsyncMock()) as check:
            await ensure_saved_filter_allowed(
                AsyncMock(), uuid.uuid4(), _hitl_nodes(uuid.uuid4()), _hitl_nodes()
            )
        check.assert_not_awaited()

    async def test_a_new_filter_outside_the_scope_is_refused_with_the_callers_words(self) -> None:
        refusal = HTTPException(status_code=422, detail=REVIEW_SOURCE_ERROR)
        with patch(f"{SERVICE}.ensure_review_source", new=AsyncMock(side_effect=refusal)):
            with self.assertRaises(HTTPException) as ctx:
                await ensure_saved_filter_allowed(
                    AsyncMock(),
                    uuid.uuid4(),
                    _hitl_nodes(),
                    _hitl_nodes(uuid.uuid4()),
                    detail=AI_FILTER_ERROR,
                )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, AI_FILTER_ERROR)


class AiTest(IsolatedAsyncioTestCase):
    def test_sources_context_names_ids_steps_and_kinds(self) -> None:
        source = ReviewSource(
            workflow_id=uuid.UUID(int=1),
            workflow_name="Invoice\napproval",
            steps=(
                ReviewStep("a1", "Approver", "agent"),
                ReviewStep("s1", "Ask finance", "slack"),
            ),
        )
        context = hitl_sources_context([source])
        self.assertIn("hitlWorkflowId", context)
        self.assertIn(
            f"- Invoice approval (hitlWorkflowId {uuid.UUID(int=1)}): "
            "Approver (hitlNodeId a1, agent); Ask finance (hitlNodeId s1, Slack)",
            context,
        )

    def test_without_sources_the_model_is_told_to_show_every_review(self) -> None:
        self.assertIn("Leave hitlWorkflowId and hitlNodeId out", hitl_sources_context([]))

    async def _create(
        self, generated: list, sources: list[ReviewSource], prompt: str
    ) -> tuple[AsyncMock, MagicMock]:
        user = _user()
        dashboard = MagicMock(id=uuid.uuid4(), owner_id=user.id, name="Dashboard")
        db = MagicMock()
        db.execute = AsyncMock(return_value=_found(dashboard))
        db.add = MagicMock()
        db.commit = AsyncMock()

        async def flush() -> None:
            for call in db.add.call_args_list:
                if getattr(call.args[0], "id", None) is None:
                    call.args[0].id = uuid.uuid4()

        async def refresh(obj: object) -> None:
            await flush()
            obj.position = 0
            obj.updated_at = datetime.datetime.now(datetime.timezone.utc)

        db.flush = AsyncMock(side_effect=flush)
        db.refresh = AsyncMock(side_effect=refresh)
        generate = AsyncMock(return_value={"nodes": generated, "edges": []})
        with (
            patch.object(dash_api, "generate_widget_dsl", generate),
            patch.object(
                dash_api,
                "get_credential_for_user",
                AsyncMock(return_value=MagicMock(type=CredentialType.openai)),
            ),
            patch.object(dash_api, "list_review_sources", AsyncMock(return_value=sources)),
        ):
            await dash_api.ai_generate_widget(
                dashboard_id=dashboard.id,
                body=AiWidgetRequest(prompt=prompt, credential_id=uuid.uuid4(), model="m"),
                current_user=user,
                db=db,
            )
        workflow = next(
            call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], Workflow)
        )
        return generate, workflow

    async def test_a_new_widget_may_show_a_workflow_the_request_names(self) -> None:
        source = ReviewSource(
            workflow_id=uuid.uuid4(),
            workflow_name="Discount approval",
            steps=(ReviewStep("a1", "Approver", "agent"),),
        )
        chosen = _hitl_nodes(source.workflow_id, "a1")
        with patch(f"{SERVICE}.ensure_review_source", new=AsyncMock()) as check:
            generate, workflow = await self._create(
                chosen, [source], "pending reviews of Discount approval"
            )

        self.assertIn(f"hitlWorkflowId {source.workflow_id}", generate.await_args.args[0])
        self.assertEqual(check.await_args.args[2].workflow_id, source.workflow_id)
        self.assertEqual(workflow.nodes, chosen)

    async def test_a_new_widget_without_a_named_workflow_shows_every_review(self) -> None:
        with patch(f"{SERVICE}.ensure_review_source", new=AsyncMock()) as check:
            generate, workflow = await self._create(_hitl_nodes(), [], "pending reviews")

        check.assert_not_awaited()
        self.assertNotIn("hitlWorkflowId", generate.await_args.args[0])
        self.assertEqual(workflow.nodes, _hitl_nodes())

    async def test_a_new_widget_on_an_invented_workflow_is_refused(self) -> None:
        refusal = HTTPException(status_code=422, detail=REVIEW_SOURCE_ERROR)
        with patch(f"{SERVICE}.ensure_review_source", new=AsyncMock(side_effect=refusal)):
            with self.assertRaises(HTTPException) as ctx:
                await self._create(_hitl_nodes(uuid.uuid4()), [], "reviews of Payroll")

        self.assertEqual(ctx.exception.detail, AI_FILTER_ERROR)

    async def _refine(
        self, current: list, generated: list, sources: list[ReviewSource]
    ) -> tuple[AsyncMock, MagicMock]:
        user = _user()
        widget = _widget()
        workflow = _widget_workflow(current)
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(
                    one_or_none=MagicMock(
                        return_value=(widget, MagicMock(id=uuid.uuid4(), owner_id=user.id))
                    )
                ),
                _found(workflow),
            ]
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        generate = AsyncMock(return_value={"nodes": generated, "edges": []})
        with (
            patch.object(dash_api, "generate_widget_dsl", generate),
            patch.object(
                dash_api,
                "get_credential_for_user",
                AsyncMock(return_value=MagicMock(type=CredentialType.openai)),
            ),
            patch.object(dash_api, "_record_chat_workflow_edit_version", AsyncMock()),
            patch.object(dash_api, "list_review_sources", AsyncMock(return_value=sources)),
        ):
            await dash_api.ai_refine_widget(
                widget_id=widget.id,
                body=AiRefineRequest(
                    prompt="only the invoice approvals",
                    credential_id=uuid.uuid4(),
                    model="m",
                    page_kind="listing",
                ),
                current_user=user,
                db=db,
            )
        return generate, workflow

    async def test_fine_tune_is_told_the_sources_and_may_pick_one(self) -> None:
        source = ReviewSource(
            workflow_id=uuid.uuid4(),
            workflow_name="Invoices",
            steps=(ReviewStep("a1", "Approver", "agent"),),
        )
        chosen = _hitl_nodes(source.workflow_id, "a1")
        with patch(f"{SERVICE}.ensure_review_source", new=AsyncMock()):
            generate, workflow = await self._refine(_hitl_nodes(), chosen, [source])

        self.assertIn(f"hitlWorkflowId {source.workflow_id}", generate.await_args.args[0])
        self.assertEqual(workflow.nodes, chosen)

    async def test_fine_tune_refuses_an_invented_workflow(self) -> None:
        refusal = HTTPException(status_code=422, detail=REVIEW_SOURCE_ERROR)
        with patch(f"{SERVICE}.ensure_review_source", new=AsyncMock(side_effect=refusal)):
            with self.assertRaises(HTTPException) as ctx:
                await self._refine(_hitl_nodes(), _hitl_nodes(uuid.uuid4()), [])

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, AI_FILTER_ERROR)

    async def test_fine_tune_keeps_a_filter_the_editor_cannot_see(self) -> None:
        current = _hitl_nodes(uuid.uuid4(), "a1")
        with patch(f"{SERVICE}.ensure_review_source", new=AsyncMock()) as check:
            _, workflow = await self._refine(current, current, [])

        check.assert_not_awaited()
        self.assertEqual(workflow.nodes, current)


class CanvasSaveTest(IsolatedAsyncioTestCase):
    async def _save(self, current: list, saved: list) -> AsyncMock:
        owner_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            kind="dashboard_widget",
            name="Reviews",
            description=None,
            nodes=current,
            edges=[],
            auth_type=WorkflowAuthType.anonymous,
            auth_header_key=None,
            auth_header_value=None,
            webhook_body_mode=WebhookBodyMode.generic,
            cache_ttl_seconds=None,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            sse_enabled=False,
            sse_node_config=None,
            allow_anonymous=True,
            owner_id=owner_id,
            folder_id=None,
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: None, scalar=lambda: 0)
        )
        db.add = lambda _row: None
        with (
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.workflows._build_workflow_response", return_value={"ok": True}),
            patch("app.services.websocket_trigger_service.websocket_trigger_manager.request_sync"),
        ):
            await update_workflow(
                workflow_id=workflow.id,
                workflow_data=WorkflowUpdate(nodes=saved, edges=[]),
                current_user=SimpleNamespace(id=owner_id),
                db=db,
            )
        return db

    async def test_a_new_filter_outside_the_scope_is_refused(self) -> None:
        refusal = HTTPException(status_code=422, detail=REVIEW_SOURCE_ERROR)
        with patch(f"{SERVICE}.ensure_review_source", new=AsyncMock(side_effect=refusal)):
            with self.assertRaises(HTTPException) as ctx:
                await self._save(_hitl_nodes(), _hitl_nodes(uuid.uuid4(), "a1"))

        self.assertEqual(ctx.exception.status_code, 422)

    async def test_moving_the_chart_keeps_a_filter_without_a_check(self) -> None:
        current = _hitl_nodes(uuid.uuid4(), "a1")
        moved = [{**current[0], "position": {"x": 120, "y": 40}}]
        with patch(f"{SERVICE}.ensure_review_source", new=AsyncMock()) as check:
            db = await self._save(current, moved)

        check.assert_not_awaited()
        db.commit.assert_awaited()
