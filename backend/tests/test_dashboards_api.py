import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import dashboards as dash_api
from app.api import workflows as workflows_api
from app.models.dashboard_schemas import WidgetCreateRequest, WidgetLayout
from app.services.dashboard_widget_policy import DASHBOARD_WIDGET_BLOCKED_NODE_TYPES


class _User:
    def __init__(self):
        self.id = uuid.uuid4()


def _wire_db_inserts(db):
    """Make a mocked DB assign PKs on flush and column defaults on refresh,
    emulating what PostgreSQL would do for newly added ORM objects."""

    def fake_flush():
        for call in db.add.call_args_list:
            obj = call.args[0]
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def fake_flush_async():
        fake_flush()

    async def fake_refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "position", None) is None:
            obj.position = 0
        obj.updated_at = datetime.datetime.now()

    db.flush = AsyncMock(side_effect=fake_flush_async)
    db.refresh = AsyncMock(side_effect=fake_refresh)


class TestWorkflowListExcludesWidgets(unittest.TestCase):
    def test_list_query_filters_kind_workflow(self):
        # Guard: the source enforces kind == "workflow" on listing queries so that
        # hidden dashboard-widget workflows never appear in the normal workflow lists.
        src = workflows_api.__file__
        with open(src, "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn('Workflow.kind == "workflow"', content)


class TestIsDashboardWidgetWorkflow(unittest.TestCase):
    def test_detects_by_chart_output_node(self):
        from app.services.workflow_dsl_prompt import is_dashboard_widget_workflow

        wf = {"nodes": [{"type": "set"}, {"type": "chartOutput"}]}
        self.assertTrue(is_dashboard_widget_workflow(wf))

    def test_detects_by_kind_flag(self):
        from app.services.workflow_dsl_prompt import is_dashboard_widget_workflow

        self.assertTrue(is_dashboard_widget_workflow({"kind": "dashboard_widget", "nodes": []}))

    def test_normal_workflow_is_false(self):
        from app.services.workflow_dsl_prompt import is_dashboard_widget_workflow

        self.assertFalse(is_dashboard_widget_workflow({"nodes": [{"type": "llm"}]}))
        self.assertFalse(is_dashboard_widget_workflow(None))


class TestSeedWidgetNodes(unittest.TestCase):
    def test_seed_has_no_trigger_or_input_and_ends_in_chart(self):
        nodes, edges = dash_api._seed_widget_nodes("pie")
        types = [n["type"] for n in nodes]
        # Dashboard widgets must not start with a trigger or input node.
        for trigger in DASHBOARD_WIDGET_BLOCKED_NODE_TYPES:
            self.assertNotIn(trigger, types)
        self.assertIn("set", types)
        self.assertIn("chartOutput", types)
        self.assertEqual(nodes[1]["data"]["chartType"], "pie")
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["source"], nodes[0]["id"])
        self.assertEqual(edges[0]["target"], nodes[1]["id"])


class TestGenerateWidgetDsl(unittest.IsolatedAsyncioTestCase):
    async def test_generate_widget_dsl_passes_trace_context_to_llm(self):
        user = _User()
        credential_id = uuid.uuid4()
        credential = MagicMock()
        credential.id = credential_id
        from app.db.models import CredentialType

        credential.type = CredentialType.openai
        credential.encrypted_config = "enc"
        content = (
            '```json\n{"name": "Signups", "description": "Monthly signups", "nodes": ['
            '{"id": "chart", "type": "chartOutput", "data": {"chartType": "bar"}}], '
            '"edges": []}\n```'
        )
        execute_llm = AsyncMock(return_value={"text": content})

        with (
            patch.object(dash_api, "decrypt_config", return_value={"api_key": "x"}),
            patch.object(dash_api, "execute_llm", execute_llm),
        ):
            result = await dash_api.generate_widget_dsl(
                "show signups",
                credential=credential,
                model="gpt-4o-mini",
                user=user,
                node_label="AI Widget Create",
            )

        self.assertEqual(result["name"], "Signups")
        execute_llm.assert_awaited_once()
        kwargs = execute_llm.await_args.kwargs
        trace_context = kwargs["trace_context"]
        self.assertEqual(kwargs["model"], "gpt-4o-mini")
        self.assertEqual(trace_context.user_id, user.id)
        self.assertEqual(trace_context.credential_id, credential_id)
        self.assertEqual(trace_context.source, "dashboard_widget_ai")
        self.assertEqual(trace_context.node_label, "AI Widget Create")
        self.assertIsNone(trace_context.workflow_id)

    async def test_generate_widget_dsl_links_fine_tune_trace_to_workflow(self):
        user = _User()
        workflow_id = uuid.uuid4()
        credential = MagicMock()
        credential.id = uuid.uuid4()
        from app.db.models import CredentialType

        credential.type = CredentialType.openai
        credential.encrypted_config = "enc"
        execute_llm = AsyncMock(
            return_value={
                "text": (
                    '```json\n{"nodes": ['
                    '{"id": "chart", "type": "chartOutput", "data": {"chartType": "line"}}], '
                    '"edges": []}\n```'
                )
            }
        )

        with (
            patch.object(dash_api, "decrypt_config", return_value={"api_key": "x"}),
            patch.object(dash_api, "execute_llm", execute_llm),
        ):
            await dash_api.generate_widget_dsl(
                "make it line",
                credential=credential,
                model="gpt-4o-mini",
                user=user,
                current_workflow={"nodes": [], "edges": []},
                workflow_id=workflow_id,
                node_label="AI Widget Fine-tune",
            )

        trace_context = execute_llm.await_args.kwargs["trace_context"]
        self.assertEqual(trace_context.node_label, "AI Widget Fine-tune")
        self.assertEqual(trace_context.workflow_id, workflow_id)


class TestCreateWidget(unittest.IsolatedAsyncioTestCase):
    async def test_create_widget_creates_hidden_workflow(self):
        user = _User()
        db = MagicMock()
        # _get_or_create_dashboard: first query returns an existing dashboard
        dashboard = MagicMock(id=uuid.uuid4())
        existing = MagicMock()
        existing.scalars.return_value.first.return_value = dashboard
        db.execute = AsyncMock(return_value=existing)
        db.add = MagicMock()
        db.commit = AsyncMock()
        _wire_db_inserts(db)

        body = WidgetCreateRequest(title="Sales", chart_type="bar", layout=WidgetLayout())
        resp = await dash_api.create_widget(body=body, current_user=user, db=db)

        self.assertEqual(resp.title, "Sales")
        self.assertEqual(resp.chart_type, "bar")
        added_kinds = [getattr(c.args[0], "kind", None) for c in db.add.call_args_list]
        self.assertIn("dashboard_widget", added_kinds)


class TestAiGenerateWidget(unittest.IsolatedAsyncioTestCase):
    async def test_ai_generate_extracts_chart_type(self):
        user = _User()
        db = MagicMock()
        dashboard = MagicMock(id=uuid.uuid4())
        existing = MagicMock()
        existing.scalars.return_value.first.return_value = dashboard
        db.execute = AsyncMock(return_value=existing)
        db.add = MagicMock()
        db.commit = AsyncMock()
        _wire_db_inserts(db)

        fake_dsl = {
            "nodes": [
                {"id": "a", "type": "set", "data": {}},
                {"id": "b", "type": "chartOutput", "data": {"chartType": "pie"}},
            ],
            "edges": [{"id": "e", "source": "a", "target": "b"}],
        }

        from app.db.models import CredentialType
        from app.models.dashboard_schemas import AiWidgetRequest

        credential = MagicMock(type=CredentialType.openai)

        with (
            patch.object(dash_api, "generate_widget_dsl", AsyncMock(return_value=fake_dsl)),
            patch.object(dash_api, "get_credential_for_user", AsyncMock(return_value=credential)),
        ):
            resp = await dash_api.ai_generate_widget(
                body=AiWidgetRequest(
                    prompt="show signups by month",
                    credential_id=uuid.uuid4(),
                    model="gpt-4o",
                ),
                current_user=user,
                db=db,
            )
        self.assertEqual(resp.chart_type, "pie")

    async def test_ai_generate_rejects_trigger_nodes(self):
        user = _User()
        db = MagicMock()
        dashboard = MagicMock(id=uuid.uuid4())
        existing = MagicMock()
        existing.scalars.return_value.first.return_value = dashboard
        db.execute = AsyncMock(return_value=existing)
        db.add = MagicMock()
        db.commit = AsyncMock()
        _wire_db_inserts(db)

        fake_dsl = {
            "nodes": [
                {"id": "a", "type": "textInput", "data": {"label": "input"}},
                {"id": "b", "type": "chartOutput", "data": {"chartType": "pie"}},
            ],
            "edges": [{"id": "e", "source": "a", "target": "b"}],
        }

        from app.db.models import CredentialType
        from app.models.dashboard_schemas import AiWidgetRequest

        credential = MagicMock(type=CredentialType.openai)
        with (
            patch.object(dash_api, "generate_widget_dsl", AsyncMock(return_value=fake_dsl)),
            patch.object(dash_api, "get_credential_for_user", AsyncMock(return_value=credential)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await dash_api.ai_generate_widget(
                    body=AiWidgetRequest(prompt="anything", credential_id=uuid.uuid4(), model="m"),
                    current_user=user,
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("input (textInput)", ctx.exception.detail)

    async def test_ai_generate_uses_dsl_name_and_description(self):
        user = _User()
        db = MagicMock()
        dashboard = MagicMock(id=uuid.uuid4())
        existing = MagicMock()
        existing.scalars.return_value.first.return_value = dashboard
        db.execute = AsyncMock(return_value=existing)
        added: list = []
        db.add = MagicMock(side_effect=lambda obj: added.append(obj))
        db.commit = AsyncMock()
        _wire_db_inserts(db)

        fake_dsl = {
            "name": "Signups by month",
            "description": "Monthly signups bar chart",
            "nodes": [{"id": "b", "type": "chartOutput", "data": {"chartType": "bar"}}],
            "edges": [],
        }

        from app.db.models import CredentialType
        from app.models.dashboard_schemas import AiWidgetRequest

        credential = MagicMock(type=CredentialType.openai)
        with (
            patch.object(dash_api, "generate_widget_dsl", AsyncMock(return_value=fake_dsl)),
            patch.object(dash_api, "get_credential_for_user", AsyncMock(return_value=credential)),
        ):
            resp = await dash_api.ai_generate_widget(
                body=AiWidgetRequest(prompt="anything", credential_id=uuid.uuid4(), model="m"),
                current_user=user,
                db=db,
            )
        self.assertEqual(resp.title, "Signups by month")
        self.assertEqual(resp.description, "Monthly signups bar chart")
        # the hidden workflow inherits the AI name/description
        workflows = [o for o in added if getattr(o, "kind", None) == "dashboard_widget"]
        self.assertTrue(workflows)
        self.assertEqual(workflows[0].name, "Signups by month")
        self.assertEqual(workflows[0].description, "Monthly signups bar chart")


class TestUpdateWidgetSync(unittest.IsolatedAsyncioTestCase):
    async def test_title_change_syncs_to_workflow(self):
        user = _User()
        widget = MagicMock()
        widget.id = uuid.uuid4()
        widget.workflow_id = uuid.uuid4()
        widget.title = "Old"
        widget.description = None
        widget.position = 0
        widget.layout = {"x": 0, "y": 0, "w": 4, "h": 4}
        widget.cache_ttl_seconds = 300
        widget.chart_type = "bar"
        workflow = MagicMock()

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=widget)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )
        db.commit = AsyncMock()

        async def fake_refresh(obj):
            obj.updated_at = datetime.datetime.now()

        db.refresh = AsyncMock(side_effect=fake_refresh)

        from app.models.dashboard_schemas import WidgetUpdateRequest

        resp = await dash_api.update_widget(
            widget_id=widget.id,
            body=WidgetUpdateRequest(title="New", description="Desc"),
            current_user=user,
            db=db,
        )
        self.assertEqual(resp.title, "New")
        self.assertEqual(workflow.name, "New")
        self.assertEqual(workflow.description, "Desc")


class TestAiRefineWidget(unittest.IsolatedAsyncioTestCase):
    async def test_refine_updates_workflow_and_invalidates_cache(self):
        user = _User()
        widget = MagicMock()
        widget.id = uuid.uuid4()
        widget.workflow_id = uuid.uuid4()
        widget.chart_type = "bar"
        widget.position = 0
        widget.title = "W"
        widget.description = None
        widget.layout = {"x": 0, "y": 0, "w": 4, "h": 4}
        widget.cache_ttl_seconds = 300
        widget.cached_payload = {"old": True}
        widget.cached_at = datetime.datetime.now()
        widget.cached_workflow_version = "v"
        workflow = MagicMock()

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=widget)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )
        db.commit = AsyncMock()

        async def fake_refresh(obj):
            obj.updated_at = datetime.datetime.now()

        db.refresh = AsyncMock(side_effect=fake_refresh)

        fake_dsl = {
            "nodes": [{"id": "c", "type": "chartOutput", "data": {"chartType": "line"}}],
            "edges": [],
        }

        from app.db.models import CredentialType
        from app.models.dashboard_schemas import AiRefineRequest

        credential = MagicMock(type=CredentialType.openai)
        record_version = AsyncMock()
        generate_dsl = AsyncMock(return_value=fake_dsl)
        with (
            patch.object(dash_api, "generate_widget_dsl", generate_dsl),
            patch.object(dash_api, "get_credential_for_user", AsyncMock(return_value=credential)),
            patch.object(dash_api, "_record_chat_workflow_edit_version", record_version),
        ):
            resp = await dash_api.ai_refine_widget(
                widget_id=widget.id,
                body=AiRefineRequest(
                    prompt="make it a line chart", credential_id=uuid.uuid4(), model="m"
                ),
                current_user=user,
                db=db,
            )
        self.assertEqual(resp.chart_type, "line")
        self.assertEqual(workflow.nodes, fake_dsl["nodes"])
        self.assertIsNone(widget.cached_payload)
        self.assertIsNone(widget.cached_at)
        # AI fine-tune records a pre-edit snapshot so it appears in Edit History.
        record_version.assert_awaited_once()
        self.assertEqual(generate_dsl.await_args.kwargs["workflow_id"], widget.workflow_id)
        self.assertEqual(generate_dsl.await_args.kwargs["node_label"], "AI Widget Fine-tune")

    async def test_refine_rejects_trigger_nodes(self):
        user = _User()
        widget = MagicMock()
        widget.id = uuid.uuid4()
        widget.workflow_id = uuid.uuid4()
        widget.chart_type = "bar"
        widget.position = 0
        widget.title = "W"
        widget.description = None
        widget.layout = {"x": 0, "y": 0, "w": 4, "h": 4}
        widget.cache_ttl_seconds = 300
        workflow = MagicMock()
        workflow.nodes = [{"id": "c", "type": "chartOutput", "data": {"chartType": "bar"}}]
        workflow.edges = []

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=widget)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )
        db.commit = AsyncMock()

        fake_dsl = {
            "nodes": [
                {"id": "cron", "type": "cron", "data": {"label": "hourly"}},
                {"id": "c", "type": "chartOutput", "data": {"chartType": "line"}},
            ],
            "edges": [{"id": "e", "source": "cron", "target": "c"}],
        }

        from app.db.models import CredentialType
        from app.models.dashboard_schemas import AiRefineRequest

        credential = MagicMock(type=CredentialType.openai)
        record_version = AsyncMock()
        with (
            patch.object(dash_api, "generate_widget_dsl", AsyncMock(return_value=fake_dsl)),
            patch.object(dash_api, "get_credential_for_user", AsyncMock(return_value=credential)),
            patch.object(dash_api, "_record_chat_workflow_edit_version", record_version),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await dash_api.ai_refine_widget(
                    widget_id=widget.id,
                    body=AiRefineRequest(prompt="line it", credential_id=uuid.uuid4(), model="m"),
                    current_user=user,
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("hourly (cron)", ctx.exception.detail)
        record_version.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_refine_records_change_history_snapshot(self):
        user = _User()
        widget = MagicMock()
        widget.id = uuid.uuid4()
        widget.workflow_id = uuid.uuid4()
        widget.chart_type = "bar"
        widget.position = 0
        widget.title = "W"
        widget.description = None
        widget.layout = {"x": 0, "y": 0, "w": 4, "h": 4}
        widget.cache_ttl_seconds = 300
        widget.cached_payload = None
        widget.cached_at = None
        workflow = MagicMock()
        workflow.nodes = [{"id": "old", "type": "chartOutput", "data": {"chartType": "bar"}}]
        workflow.edges = []

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=widget)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )
        db.commit = AsyncMock()

        async def fake_refresh(obj):
            obj.updated_at = datetime.datetime.now()

        db.refresh = AsyncMock(side_effect=fake_refresh)

        fake_dsl = {
            "nodes": [{"id": "c", "type": "chartOutput", "data": {"chartType": "line"}}],
            "edges": [],
        }

        from app.db.models import CredentialType
        from app.models.dashboard_schemas import AiRefineRequest

        credential = MagicMock(type=CredentialType.openai)
        record_version = AsyncMock()
        with (
            patch.object(dash_api, "generate_widget_dsl", AsyncMock(return_value=fake_dsl)),
            patch.object(dash_api, "get_credential_for_user", AsyncMock(return_value=credential)),
            patch.object(dash_api, "_record_chat_workflow_edit_version", record_version),
        ):
            await dash_api.ai_refine_widget(
                widget_id=widget.id,
                body=AiRefineRequest(prompt="line it", credential_id=uuid.uuid4(), model="m"),
                current_user=user,
                db=db,
            )
        # The snapshot must capture the OLD nodes (before the overwrite).
        record_version.assert_awaited_once()
        _, kwargs = record_version.await_args
        self.assertEqual(
            kwargs["old_nodes"],
            [{"id": "old", "type": "chartOutput", "data": {"chartType": "bar"}}],
        )
        self.assertIs(kwargs["workflow"], workflow)


class TestMarkdownTaskToggle(unittest.IsolatedAsyncioTestCase):
    async def test_toggle_updates_static_text_and_returns_payload(self):
        user = _User()
        chart_id = str(uuid.uuid4())
        markdown = "- [ ] Seçenek 2\n- [ ] Seçenek 3"
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.nodes = [
            {
                "id": chart_id,
                "type": "chartOutput",
                "data": {"chartType": "text", "text": markdown},
            }
        ]

        widget = MagicMock()
        widget.id = uuid.uuid4()
        widget.workflow_id = workflow.id
        widget.cached_payload = {"type": "text", "text": markdown, "text_interactive": True}
        widget.cached_at = datetime.datetime.now()
        widget.cached_workflow_version = "v"

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=widget)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        updated_payload = {
            "type": "text",
            "text": "- [x] Seçenek 2\n- [ ] Seçenek 3",
            "text_interactive": True,
        }
        compute = AsyncMock(
            side_effect=[
                MagicMock(payload={"type": "text", "text": markdown, "text_interactive": True}),
                MagicMock(
                    widget_id=widget.id,
                    payload=updated_payload,
                    cached=False,
                    computed_at=datetime.datetime.now(),
                    error=None,
                ),
            ]
        )

        from app.models.dashboard_schemas import MarkdownTaskToggleRequest

        with patch.object(dash_api, "compute_widget_data", compute):
            resp = await dash_api.toggle_markdown_task(
                widget_id=widget.id,
                body=MarkdownTaskToggleRequest(line_index=0),
                current_user=user,
                db=db,
            )

        self.assertEqual(resp.payload, updated_payload)
        chart_node = workflow.nodes[0]
        self.assertIn("[x]", chart_node["data"]["text"])
        self.assertIsNone(widget.cached_payload)

    async def test_toggle_rejects_plain_dynamic_text(self):
        user = _User()
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.nodes = [
            {
                "id": "c",
                "type": "chartOutput",
                "data": {
                    "chartType": "text",
                    "valueField": "message",
                },
            }
        ]

        widget = MagicMock()
        widget.id = uuid.uuid4()
        widget.workflow_id = workflow.id

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=widget)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )

        compute = AsyncMock(
            return_value=MagicMock(
                payload={
                    "type": "text",
                    "text": "Last run at 19:47",
                    "text_interactive": False,
                }
            )
        )

        from app.models.dashboard_schemas import MarkdownTaskToggleRequest

        with patch.object(dash_api, "compute_widget_data", compute):
            with self.assertRaises(Exception) as ctx:
                await dash_api.toggle_markdown_task(
                    widget_id=widget.id,
                    body=MarkdownTaskToggleRequest(line_index=0),
                    current_user=user,
                    db=db,
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_toggle_value_field_checklist_promotes_to_static_text(self):
        user = _User()
        checklist = "- [ ] Option 1\n- [ ] Option 2\n- [ ] Option 3"
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.nodes = [
            {
                "id": "c",
                "type": "chartOutput",
                "data": {
                    "chartType": "text",
                    "valueField": "text",
                },
            }
        ]

        widget = MagicMock()
        widget.id = uuid.uuid4()
        widget.workflow_id = workflow.id
        widget.cached_payload = None
        widget.cached_at = None
        widget.cached_workflow_version = None

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=widget)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        updated = "- [x] Option 1\n- [ ] Option 2\n- [ ] Option 3"
        compute = AsyncMock(
            side_effect=[
                MagicMock(
                    payload={
                        "type": "text",
                        "text": checklist,
                        "text_interactive": True,
                    }
                ),
                MagicMock(
                    widget_id=widget.id,
                    payload={"type": "text", "text": updated, "text_interactive": True},
                    cached=False,
                    computed_at=datetime.datetime.now(),
                    error=None,
                ),
            ]
        )

        from app.models.dashboard_schemas import MarkdownTaskToggleRequest

        with patch.object(dash_api, "compute_widget_data", compute):
            await dash_api.toggle_markdown_task(
                widget_id=widget.id,
                body=MarkdownTaskToggleRequest(line_index=0),
                current_user=user,
                db=db,
            )

        chart_data = workflow.nodes[0]["data"]
        self.assertEqual(chart_data["text"], updated)
        self.assertNotIn("valueField", chart_data)


class TestMarkdownTaskUpdate(unittest.IsolatedAsyncioTestCase):
    async def test_update_text_persists_to_workflow(self):
        user = _User()
        markdown = "- [ ] Option 1\n- [ ] Option 2"
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.nodes = [
            {
                "id": "c",
                "type": "chartOutput",
                "data": {"chartType": "text", "text": markdown},
            }
        ]

        widget = MagicMock()
        widget.id = uuid.uuid4()
        widget.workflow_id = workflow.id
        widget.cached_payload = None
        widget.cached_at = None
        widget.cached_workflow_version = None

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=widget)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        updated_text = "- [ ] Renamed\n- [ ] Option 2"
        compute = AsyncMock(
            side_effect=[
                MagicMock(payload={"type": "text", "text": markdown, "text_interactive": True}),
                MagicMock(
                    widget_id=widget.id,
                    payload={"type": "text", "text": updated_text, "text_interactive": True},
                    cached=False,
                    computed_at=datetime.datetime.now(),
                    error=None,
                ),
            ]
        )

        from app.models.dashboard_schemas import MarkdownTaskUpdateRequest

        with patch.object(dash_api, "compute_widget_data", compute):
            resp = await dash_api.update_markdown_task(
                widget_id=widget.id,
                body=MarkdownTaskUpdateRequest(line_index=0, text="Renamed"),
                current_user=user,
                db=db,
            )

        self.assertEqual(resp.payload["text"], updated_text)
        self.assertEqual(workflow.nodes[0]["data"]["text"], updated_text)

    async def test_update_blank_text_removes_line(self):
        user = _User()
        markdown = "- [ ] One\n- [ ] Two"
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.nodes = [
            {
                "id": "c",
                "type": "chartOutput",
                "data": {"chartType": "text", "text": markdown},
            }
        ]

        widget = MagicMock()
        widget.id = uuid.uuid4()
        widget.workflow_id = workflow.id
        widget.cached_payload = None
        widget.cached_at = None
        widget.cached_workflow_version = None

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=widget)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        updated_text = "- [ ] Two"
        compute = AsyncMock(
            side_effect=[
                MagicMock(payload={"type": "text", "text": markdown, "text_interactive": True}),
                MagicMock(
                    widget_id=widget.id,
                    payload={"type": "text", "text": updated_text, "text_interactive": True},
                    cached=False,
                    computed_at=datetime.datetime.now(),
                    error=None,
                ),
            ]
        )

        from app.models.dashboard_schemas import MarkdownTaskUpdateRequest

        with patch.object(dash_api, "compute_widget_data", compute):
            await dash_api.update_markdown_task(
                widget_id=widget.id,
                body=MarkdownTaskUpdateRequest(line_index=0, text=""),
                current_user=user,
                db=db,
            )

        self.assertEqual(workflow.nodes[0]["data"]["text"], updated_text)

    async def test_update_rejects_non_interactive_text(self):
        user = _User()
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.nodes = [
            {
                "id": "c",
                "type": "chartOutput",
                "data": {"chartType": "text", "valueField": "message"},
            }
        ]

        widget = MagicMock()
        widget.id = uuid.uuid4()
        widget.workflow_id = workflow.id

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=widget)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )

        compute = AsyncMock(
            return_value=MagicMock(
                payload={
                    "type": "text",
                    "text": "Last run at 19:47",
                    "text_interactive": False,
                }
            )
        )

        from app.models.dashboard_schemas import MarkdownTaskUpdateRequest

        with patch.object(dash_api, "compute_widget_data", compute):
            with self.assertRaises(Exception) as ctx:
                await dash_api.update_markdown_task(
                    widget_id=widget.id,
                    body=MarkdownTaskUpdateRequest(line_index=0, text="New"),
                    current_user=user,
                    db=db,
                )
        self.assertEqual(ctx.exception.status_code, 400)
