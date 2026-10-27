"""Chat tools for dashboards: the dashboard to widget map, placing a workflow as a widget,
renaming and deleting widgets, and tidying a dashboard."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import ai_assistant, chat_dashboards
from app.api import dashboards as dashboards_api
from app.db.models import DashboardWidget, Workflow
from app.models.dashboard_schemas import HitlWidgetFilterModel
from app.services import dashboard_tidy, mcp_chat_service

BASE_URL = "https://heym.example"


def _rows(items):
    res = MagicMock()
    res.all.return_value = items
    return res


def _scalars(items):
    res = MagicMock()
    res.scalars.return_value.all.return_value = items
    return res


def _widget(dashboard_id, *, title, chart_type="bar", position=0, x=0, y=0):
    return SimpleNamespace(
        id=uuid.uuid4(),
        dashboard_id=dashboard_id,
        workflow_id=uuid.uuid4(),
        title=title,
        description=None,
        chart_type=chart_type,
        position=position,
        layout={"x": x, "y": y, "w": 4, "h": 4},
    )


def _session():
    """An AsyncSession double that gives added rows the ids a flush would."""
    db = AsyncMock()
    added = []

    def _add(obj):
        added.append(obj)

    async def _assign_ids(*_args):
        for obj in added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock(side_effect=_assign_ids)
    db.refresh = AsyncMock(side_effect=_assign_ids)
    return db, added


class TestDashboardToolsRegistered(unittest.TestCase):
    def test_tools_present_on_every_chat_surface(self):
        names = {t["function"]["name"] for t in ai_assistant.DASHBOARD_CHAT_TOOLS}
        for name in (
            "list_dashboards",
            "add_dashboard_widget",
            "rename_dashboard_widget",
            "delete_dashboard_widget",
            "tidy_dashboard",
        ):
            self.assertIn(name, names)

    def test_add_needs_only_a_dashboard(self):
        tool = next(
            item
            for item in ai_assistant.DASHBOARD_CHAT_TOOLS
            if item["function"]["name"] == "add_dashboard_widget"
        )
        parameters = tool["function"]["parameters"]
        self.assertEqual(parameters["required"], ["dashboard_id"])
        self.assertIn("hitl", parameters["properties"]["chart_type"]["enum"])

    def test_rename_delete_and_tidy_parameters(self):
        tools = {t["function"]["name"]: t["function"] for t in ai_assistant.DASHBOARD_CHAT_TOOLS}
        self.assertEqual(
            tools["rename_dashboard_widget"]["parameters"]["required"], ["widget_id", "title"]
        )
        self.assertEqual(tools["delete_dashboard_widget"]["parameters"]["required"], ["widget_id"])
        tidy = tools["tidy_dashboard"]["parameters"]
        self.assertEqual(tidy["required"], ["dashboard_id"])
        self.assertEqual(tidy["properties"]["per_row"]["minimum"], 1)
        self.assertEqual(tidy["properties"]["per_row"]["maximum"], 4)

    def test_prompt_and_mcp_description_cover_dashboards(self):
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        self.assertIn("list_dashboards", prompt)
        self.assertIn("add_dashboard_widget", prompt)
        self.assertIn("Heym Work shows each dashboard as a page", prompt)
        self.assertIn("call add_dashboard_widget without workflow_id", prompt)
        self.assertIn("Never build a separate workflow to copy onto a dashboard", prompt)
        self.assertIn("dashboards", mcp_chat_service.MCP_CHAT_TOOL_DESCRIPTION)
        self.assertIn("as a widget", mcp_chat_service.MCP_CHAT_TOOL_DESCRIPTION)

    def test_prompt_and_mcp_description_cover_renaming_deleting_and_tidying(self):
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        self.assertIn("call rename_dashboard_widget", prompt)
        self.assertIn("Call delete_dashboard_widget only when the user asked", prompt)
        self.assertIn("call tidy_dashboard once the widgets are added", prompt)
        self.assertIn("A Heym Work page keeps its own arrangement", prompt)
        description = mcp_chat_service.MCP_CHAT_TOOL_DESCRIPTION
        self.assertIn("rename or delete a widget", description)
        self.assertIn("tidy a dashboard's layout", description)


class TestListDashboardsForChat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.owner_id = uuid.uuid4()
        self.shared = SimpleNamespace(id=uuid.uuid4(), name="Sales", owner_id=self.owner_id)
        self.own = SimpleNamespace(id=uuid.uuid4(), name="Ops", owner_id=self.user.id)

    async def _list(self, db, args, *, shared=None, filters=None, hidden=None):
        with (
            patch.object(
                chat_dashboards,
                "shared_dashboard_permissions",
                AsyncMock(return_value=shared or {}),
            ),
            patch.object(
                chat_dashboards, "hitl_filters_for_widgets", AsyncMock(return_value=filters or {})
            ),
            patch.object(
                chat_dashboards, "hidden_hitl_widgets", AsyncMock(return_value=hidden or set())
            ) as hidden_mock,
        ):
            result = await chat_dashboards.list_dashboards_for_chat(db, self.user, args, BASE_URL)
        return result, hidden_mock

    async def test_maps_each_dashboard_to_its_widgets_owned_first(self):
        later = _widget(self.own.id, title="Revenue", position=1)
        first = _widget(self.own.id, title="Open cases", position=0, y=4)
        run = _widget(self.shared.id, title="Import invoices", chart_type="fileRun")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _rows([(self.shared, "ada@example.com"), (self.own, "me@example.com")]),
                _scalars([later, run, first]),
            ]
        )

        result, _ = await self._list(db, {}, shared={self.shared.id: "write"})

        self.assertEqual(result["count"], 2)
        own, shared = result["dashboards"]
        self.assertEqual(own["name"], "Ops")
        self.assertEqual(own["permission"], "owner")
        self.assertIsNone(own["shared_by"])
        self.assertEqual(own["url"], f"{BASE_URL}/?tab=dashboard&dashboard={self.own.id}")
        self.assertEqual([w["title"] for w in own["widgets"]], ["Open cases", "Revenue"])
        self.assertEqual(own["widgets"][0]["kind"], "chart")
        self.assertEqual(own["widgets"][0]["workflow_id"], str(first.workflow_id))
        self.assertEqual(shared["permission"], "write")
        self.assertEqual(shared["shared_by"], "ada@example.com")
        self.assertEqual(shared["widget_count"], 1)
        self.assertEqual(shared["widgets"][0]["kind"], "run")

    async def test_hides_a_hitl_widget_the_viewer_cannot_open(self):
        inbox = _widget(self.shared.id, title="Reviews", chart_type="hitl")
        chart = _widget(self.shared.id, title="Pipeline")
        review_filter = HitlWidgetFilterModel(workflow_id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_rows([(self.shared, "ada@example.com")]), _scalars([inbox, chart])]
        )

        result, hidden_mock = await self._list(
            db,
            {},
            shared={self.shared.id: "read"},
            filters={inbox.id: review_filter},
            hidden={inbox.id},
        )

        hidden_mock.assert_awaited_once_with(
            db, {inbox.id: review_filter}, self.user.id, self.owner_id
        )
        self.assertEqual([w["title"] for w in result["dashboards"][0]["widgets"]], ["Pipeline"])

    async def test_workflow_filter_keeps_only_dashboards_that_show_it(self):
        placed = _widget(self.own.id, title="Revenue")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _rows([(self.shared, "ada@example.com"), (self.own, "me@example.com")]),
                _scalars([placed]),
            ]
        )

        result, _ = await self._list(
            db, {"workflow_id": str(placed.workflow_id)}, shared={self.shared.id: "read"}
        )

        widgets_query = str(db.execute.await_args_list[1].args[0])
        self.assertIn("dashboard_widgets.workflow_id", widgets_query)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["dashboards"][0]["name"], "Ops")

    async def test_unreachable_dashboard_is_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows([]))

        result, _ = await self._list(db, {"dashboard_id": str(uuid.uuid4())})

        self.assertEqual(result, {"error": "Dashboard not found"})
        db.execute.assert_awaited_once()

    async def test_invalid_ids_are_refused(self):
        db = AsyncMock()
        result, _ = await self._list(db, {"dashboard_id": "sales"})
        self.assertEqual(result, {"error": "Invalid dashboard_id"})
        result, _ = await self._list(db, {"workflow_id": "revenue"})
        self.assertEqual(result, {"error": "Invalid workflow_id"})
        db.execute.assert_not_awaited()


CHART_NODES = [
    {
        "id": "source",
        "type": "set",
        "position": {"x": 0, "y": 0},
        "data": {"label": "data", "mappings": [{"key": "rows", "value": "$array(1, 2)"}]},
    },
    {
        "id": "chart",
        "type": "chartOutput",
        "position": {"x": 320, "y": 0},
        "data": {"label": "chart", "chartType": "line", "dataPath": "rows"},
    },
]
CHART_EDGES = [{"id": "e1", "source": "source", "target": "chart"}]


class TestAddDashboardWidgetForChat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4(), email="me@example.com")
        self.dashboard = SimpleNamespace(id=uuid.uuid4(), name="Ops", owner_id=self.user.id)

    def _source(self, nodes, edges=None, *, name="Revenue trend"):
        return SimpleNamespace(
            id=uuid.uuid4(),
            name=name,
            description="Monthly revenue",
            kind="workflow",
            nodes=nodes,
            edges=edges or [],
        )

    async def _add(
        self,
        db,
        args,
        *,
        workflows=None,
        placed=(),
        permission="owner",
        filter_check=None,
        can_build=True,
    ):
        """Run the tool with the real dashboard checks over mocked lookups."""
        workflows = workflows or {}
        lookup = AsyncMock(side_effect=lambda _db, workflow_id, user_id: workflows.get(user_id))
        dashboard_row = MagicMock()
        dashboard_row.scalar_one_or_none.return_value = self.dashboard
        db.execute = AsyncMock(side_effect=[dashboard_row, _rows(list(placed))])
        with (
            patch.object(
                dashboards_api, "dashboard_permission", AsyncMock(return_value=permission)
            ),
            patch.object(chat_dashboards, "get_workflow_for_user", lookup),
            patch.object(dashboards_api, "get_workflow_for_user", lookup),
            patch.object(
                chat_dashboards, "ensure_saved_filter_allowed", filter_check or AsyncMock()
            ),
            patch.object(chat_dashboards, "audit") as audit,
        ):
            result = await chat_dashboards.add_dashboard_widget_for_chat(
                db, self.user, args, BASE_URL, can_build=can_build
            )
        return result, audit

    async def test_new_widget_starts_empty_for_the_chat_to_fill(self):
        self.dashboard.owner_id = uuid.uuid4()
        db, added = _session()

        result, audit = await self._add(
            db,
            {"dashboard_id": str(self.dashboard.id), "title": "Open cases", "chart_type": "table"},
            placed=[({"x": 0, "y": 0, "w": 4, "h": 4}, 0)],
            permission="write",
        )

        workflow, widget = added
        self.assertEqual(workflow.kind, "dashboard_widget")
        self.assertEqual(workflow.owner_id, self.dashboard.owner_id)
        self.assertEqual(workflow.name, "Open cases")
        self.assertEqual([n["type"] for n in workflow.nodes], ["set", "chartOutput"])
        self.assertEqual(workflow.nodes[1]["data"]["chartType"], "table")
        self.assertEqual(widget.workflow_id, workflow.id)
        self.assertEqual(widget.chart_type, "table")
        self.assertEqual(widget.layout["y"], 4)
        self.assertEqual(widget.position, 1)
        self.assertEqual(result["widget"]["workflow_id"], str(workflow.id))
        self.assertIn(f"save_workflow and workflow_id {workflow.id}", result["next_step"])
        self.assertIn("'Open cases'", result["next_step"])
        self.assertIn("chartOutput", result["widget_rules"])
        self.assertIsNone(audit.call_args.kwargs["source_workflow_id"])

    async def test_new_hitl_widget_needs_no_graph(self):
        db, added = _session()

        result, _ = await self._add(
            db, {"dashboard_id": str(self.dashboard.id), "title": "Reviews", "chart_type": "hitl"}
        )

        workflow, widget = added
        self.assertEqual([n["type"] for n in workflow.nodes], ["chartOutput"])
        self.assertEqual(widget.chart_type, "hitl")
        self.assertIn("do not save a graph", result["next_step"])

    async def test_new_widget_defaults_to_a_bar_chart_named_widget(self):
        db, added = _session()

        await self._add(db, {"dashboard_id": str(self.dashboard.id)})

        workflow, widget = added
        self.assertEqual((widget.title, widget.chart_type), ("Widget", "bar"))
        self.assertEqual(workflow.name, "Widget")

    async def test_new_widget_needs_a_turn_that_can_build(self):
        db, added = _session()

        result, _ = await self._add(
            db, {"dashboard_id": str(self.dashboard.id), "title": "Revenue"}, can_build=False
        )

        self.assertEqual(result, {"error": chat_dashboards.EMPTY_WIDGET_NEEDS_BUILD_ERROR})
        self.assertEqual(added, [])

    async def test_new_widget_needs_a_known_chart_type(self):
        db, added = _session()

        result, _ = await self._add(
            db, {"dashboard_id": str(self.dashboard.id), "chart_type": "donut"}
        )

        self.assertIn("chart_type must be one of", result["error"])
        self.assertEqual(added, [])

    async def test_chart_workflow_becomes_a_widget_on_its_own_copy(self):
        source = self._source(CHART_NODES, CHART_EDGES)
        db, added = _session()

        result, audit = await self._add(
            db,
            {"dashboard_id": str(self.dashboard.id), "workflow_id": str(source.id)},
            workflows={self.user.id: source},
            placed=[({"x": 0, "y": 0, "w": 4, "h": 4}, 0), ({"y": 2, "h": 6}, 3)],
        )

        copy, widget = added
        self.assertIsInstance(copy, Workflow)
        self.assertEqual(copy.kind, "dashboard_widget")
        self.assertEqual(copy.owner_id, self.dashboard.owner_id)
        self.assertEqual([n["type"] for n in copy.nodes], ["set", "chartOutput"])
        self.assertNotIn("chart", {n["id"] for n in copy.nodes})
        self.assertEqual(copy.edges[0]["target"], copy.nodes[1]["id"])
        self.assertEqual(source.nodes[1]["id"], "chart")
        self.assertIsInstance(widget, DashboardWidget)
        self.assertEqual(widget.workflow_id, copy.id)
        self.assertEqual(widget.chart_type, "line")
        self.assertEqual(widget.title, "Revenue trend")
        self.assertEqual(widget.description, "Monthly revenue")
        self.assertEqual(widget.layout, {"x": 0, "y": 8, "w": 4, "h": 4})
        self.assertEqual(widget.position, 4)
        self.assertTrue(result["created"])
        self.assertEqual(result["widget"]["kind"], "chart")
        self.assertEqual(result["widget"]["workflow_id"], str(copy.id))
        self.assertEqual(
            result["dashboard"]["url"], f"{BASE_URL}/?tab=dashboard&dashboard={self.dashboard.id}"
        )
        db.commit.assert_awaited_once()
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "dashboard.widget_create")
        self.assertEqual(audit.call_args.kwargs["source_workflow_id"], source.id)

    async def test_explicit_title_names_the_widget_and_its_copy(self):
        source = self._source(CHART_NODES, CHART_EDGES)
        db, added = _session()

        result, _ = await self._add(
            db,
            {
                "dashboard_id": str(self.dashboard.id),
                "workflow_id": str(source.id),
                "title": "  Revenue  ",
            },
            workflows={self.user.id: source},
        )

        copy, widget = added
        self.assertEqual((copy.name, widget.title), ("Revenue", "Revenue"))
        self.assertEqual(widget.layout["y"], 0)
        self.assertEqual(widget.position, 0)
        self.assertEqual(result["widget"]["title"], "Revenue")

    async def test_chart_workflow_with_a_trigger_is_refused(self):
        cron = {"id": "cron", "type": "cron", "data": {"label": "every hour"}}
        source = self._source([cron, *CHART_NODES], CHART_EDGES)
        db, added = _session()

        result, audit = await self._add(
            db,
            {"dashboard_id": str(self.dashboard.id), "workflow_id": str(source.id)},
            workflows={self.user.id: source},
        )

        self.assertIn("every hour (cron)", result["error"])
        self.assertEqual(added, [])
        db.commit.assert_not_awaited()
        audit.assert_not_called()

    async def test_other_workflow_becomes_a_run_widget_on_the_workflow_itself(self):
        source = self._source([{"id": "llm", "type": "llm", "data": {"label": "summarize"}}])
        db, added = _session()

        result, _ = await self._add(
            db,
            {"dashboard_id": str(self.dashboard.id), "workflow_id": str(source.id)},
            workflows={self.user.id: source},
        )

        (widget,) = added
        self.assertEqual(widget.workflow_id, source.id)
        self.assertEqual(widget.chart_type, "fileRun")
        self.assertEqual(result["widget"]["kind"], "run")

    async def test_run_widget_needs_a_workflow_the_owner_can_run(self):
        self.dashboard.owner_id = uuid.uuid4()
        source = self._source([{"id": "llm", "type": "llm", "data": {"label": "summarize"}}])
        db, added = _session()

        result, _ = await self._add(
            db,
            {"dashboard_id": str(self.dashboard.id), "workflow_id": str(source.id)},
            workflows={self.user.id: source},
            permission="write",
        )

        self.assertEqual(result, {"error": "The dashboard owner cannot run this workflow"})
        self.assertEqual(added, [])

    async def test_read_only_dashboard_takes_no_widget(self):
        source = self._source(CHART_NODES, CHART_EDGES)
        db, added = _session()

        result, _ = await self._add(
            db,
            {"dashboard_id": str(self.dashboard.id), "workflow_id": str(source.id)},
            workflows={self.user.id: source},
            permission="read",
        )

        self.assertEqual(result, {"error": "Read-only access to this dashboard"})
        self.assertEqual(added, [])

    async def test_workflow_the_user_cannot_open_is_not_found(self):
        db, added = _session()

        result, _ = await self._add(
            db,
            {"dashboard_id": str(self.dashboard.id), "workflow_id": str(uuid.uuid4())},
            workflows={},
        )

        self.assertEqual(result, {"error": "Workflow not found"})
        self.assertEqual(added, [])

    async def test_ids_are_checked_before_any_lookup(self):
        db, _ = _session()
        result = await chat_dashboards.add_dashboard_widget_for_chat(
            db,
            self.user,
            {"dashboard_id": "Ops", "workflow_id": str(uuid.uuid4())},
            BASE_URL,
            can_build=True,
        )
        self.assertIn("dashboard_id", result["error"])
        result = await chat_dashboards.add_dashboard_widget_for_chat(
            db,
            self.user,
            {"dashboard_id": str(uuid.uuid4()), "workflow_id": "revenue"},
            BASE_URL,
            can_build=True,
        )
        self.assertIn("workflow_id", result["error"])
        db.execute.assert_not_awaited()

    async def test_hitl_filter_outside_the_users_reach_is_refused(self):
        source = self._source(CHART_NODES, CHART_EDGES)
        db, added = _session()
        refuse = AsyncMock(side_effect=HTTPException(status_code=404, detail="Workflow not found"))

        result, _ = await self._add(
            db,
            {"dashboard_id": str(self.dashboard.id), "workflow_id": str(source.id)},
            workflows={self.user.id: source},
            filter_check=refuse,
        )

        refuse.assert_awaited_once_with(db, self.user.id, [], source.nodes)
        self.assertEqual(result, {"error": "Workflow not found"})
        self.assertEqual(added, [])


def _widget_row(widget, dashboard):
    res = MagicMock()
    res.one_or_none.return_value = (widget, dashboard)
    return res


def _one(item):
    res = MagicMock()
    res.scalar_one_or_none.return_value = item
    return res


class TestRenameDashboardWidgetForChat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.dashboard = SimpleNamespace(id=uuid.uuid4(), name="Ops", owner_id=self.user.id)
        self.widget = _widget(self.dashboard.id, title="Revenue")
        self.widget.description = "Old"

    async def _rename(self, args, *, workflow=None, permission="write"):
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_widget_row(self.widget, self.dashboard), _one(workflow)]
        )
        with patch.object(
            dashboards_api, "dashboard_permission", AsyncMock(return_value=permission)
        ):
            result = await chat_dashboards.rename_dashboard_widget_for_chat(
                db, self.user, args, BASE_URL
            )
        return db, result

    async def test_chart_widget_and_its_workflow_take_the_new_name(self):
        workflow = SimpleNamespace(kind="dashboard_widget", name="Revenue", description="Old")

        db, result = await self._rename(
            {"widget_id": str(self.widget.id), "title": " Sales ", "description": "Per month"},
            workflow=workflow,
        )

        self.assertEqual((self.widget.title, self.widget.description), ("Sales", "Per month"))
        self.assertEqual((workflow.name, workflow.description), ("Sales", "Per month"))
        db.commit.assert_awaited_once()
        self.assertTrue(result["renamed"])
        self.assertEqual(result["widget"]["title"], "Sales")
        self.assertEqual(result["dashboard"]["name"], "Ops")

    async def test_rename_without_description_keeps_it(self):
        workflow = SimpleNamespace(kind="dashboard_widget", name="Revenue", description="Old")

        await self._rename({"widget_id": str(self.widget.id), "title": "Sales"}, workflow=workflow)

        self.assertEqual(self.widget.description, "Old")
        self.assertEqual(workflow.description, "Old")

    async def test_run_widget_workflow_keeps_its_own_name(self):
        self.widget.chart_type = "fileRun"
        workflow = SimpleNamespace(kind="workflow", name="Import invoices", description="Mine")

        _, result = await self._rename(
            {"widget_id": str(self.widget.id), "title": "Upload", "description": "Drop files"},
            workflow=workflow,
        )

        self.assertEqual(self.widget.title, "Upload")
        self.assertEqual((workflow.name, workflow.description), ("Import invoices", "Mine"))
        self.assertEqual(result["widget"]["kind"], "run")

    async def test_read_only_dashboard_refuses_the_rename(self):
        db, result = await self._rename(
            {"widget_id": str(self.widget.id), "title": "Sales"}, permission="read"
        )

        self.assertEqual(result, {"error": "Read-only access to this dashboard"})
        self.assertEqual(self.widget.title, "Revenue")
        db.commit.assert_not_awaited()

    async def test_bad_arguments_are_refused_before_any_lookup(self):
        db = AsyncMock()
        bad = [
            ({"widget_id": "nope", "title": "Sales"}, chat_dashboards.WIDGET_ID_ERROR),
            ({"widget_id": str(self.widget.id), "title": "  "}, "title must not be empty"),
        ]
        for args, error in bad:
            result = await chat_dashboards.rename_dashboard_widget_for_chat(
                db, self.user, args, BASE_URL
            )
            self.assertEqual(result, {"error": error})
        db.execute.assert_not_awaited()


class TestDeleteDashboardWidgetForChat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.dashboard = SimpleNamespace(id=uuid.uuid4(), name="Ops", owner_id=self.user.id)
        self.widget = _widget(self.dashboard.id, title="Revenue")

    async def _delete(self, *, workflow=None, permission="owner"):
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_widget_row(self.widget, self.dashboard), _one(workflow)]
        )
        with (
            patch.object(
                dashboards_api, "dashboard_permission", AsyncMock(return_value=permission)
            ),
            patch.object(chat_dashboards, "audit") as audit,
        ):
            result = await chat_dashboards.delete_dashboard_widget_for_chat(
                db, self.user, {"widget_id": str(self.widget.id)}, BASE_URL
            )
        return db, result, audit

    async def test_chart_widget_goes_with_its_workflow(self):
        workflow = SimpleNamespace(kind="dashboard_widget")

        db, result, audit = await self._delete(workflow=workflow)

        self.assertEqual(
            [call.args[0] for call in db.delete.await_args_list], [self.widget, workflow]
        )
        db.commit.assert_awaited_once()
        self.assertTrue(result["deleted"])
        self.assertTrue(result["workflow_deleted"])
        self.assertEqual(result["widget"]["title"], "Revenue")
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "dashboard.widget_delete")
        self.assertEqual(audit.call_args.kwargs["widget_id"], self.widget.id)

    async def test_run_widget_workflow_stays(self):
        self.widget.chart_type = "fileRun"

        db, result, _ = await self._delete(workflow=SimpleNamespace(kind="workflow"))

        self.assertEqual([call.args[0] for call in db.delete.await_args_list], [self.widget])
        self.assertFalse(result["workflow_deleted"])

    async def test_read_only_dashboard_keeps_its_widget(self):
        db, result, audit = await self._delete(permission="read")

        self.assertEqual(result, {"error": "Read-only access to this dashboard"})
        db.delete.assert_not_awaited()
        db.commit.assert_not_awaited()
        audit.assert_not_called()

    async def test_invalid_widget_id_is_refused(self):
        result = await chat_dashboards.delete_dashboard_widget_for_chat(
            AsyncMock(), self.user, {"widget_id": "nope"}, BASE_URL
        )
        self.assertEqual(result, {"error": chat_dashboards.WIDGET_ID_ERROR})


class TestTidyDashboardForChat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.dashboard = SimpleNamespace(id=uuid.uuid4(), name="Ops", owner_id=self.user.id)

    async def _tidy(self, args, widgets, *, permission="owner", hidden=None, rand=None):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_one(self.dashboard), _scalars(widgets)])

        def _tidy_layouts(current, per_row):
            return dashboard_tidy.tidy_layouts(current, per_row, rand or (lambda: 0.0))

        with (
            patch.object(
                dashboards_api, "dashboard_permission", AsyncMock(return_value=permission)
            ),
            patch.object(chat_dashboards, "hitl_filters_for_widgets", AsyncMock(return_value={})),
            patch.object(
                chat_dashboards, "hidden_hitl_widgets", AsyncMock(return_value=hidden or set())
            ),
            patch.object(chat_dashboards, "tidy_layouts", side_effect=_tidy_layouts),
        ):
            result = await chat_dashboards.tidy_dashboard_for_chat(db, self.user, args, BASE_URL)
        return db, result

    async def test_widgets_fill_rows_in_their_order(self):
        third = _widget(self.dashboard.id, title="C", position=2)
        first = _widget(self.dashboard.id, title="A", position=0)
        second = _widget(self.dashboard.id, title="B", position=1)

        db, result = await self._tidy(
            {"dashboard_id": str(self.dashboard.id)}, [third, first, second]
        )

        self.assertEqual(first.layout, {"x": 0, "y": 0, "w": 6, "h": 5})
        self.assertEqual(second.layout, {"x": 6, "y": 0, "w": 6, "h": 5})
        self.assertEqual(third.layout, {"x": 0, "y": 5, "w": 12, "h": 5})
        db.commit.assert_awaited_once()
        self.assertEqual(result["rows"], [2, 1])
        self.assertEqual(result["widget_count"], 3)
        self.assertEqual(result["dashboard"]["name"], "Ops")

    async def test_per_row_gives_every_row_the_same_width(self):
        widgets = [_widget(self.dashboard.id, title=str(i), position=i) for i in range(4)]

        _, result = await self._tidy(
            {"dashboard_id": str(self.dashboard.id), "per_row": 3}, widgets
        )

        self.assertEqual([w.layout["w"] for w in widgets], [4, 4, 4, 4])
        self.assertEqual([(w.layout["x"], w.layout["y"]) for w in widgets][3], (0, 5))
        self.assertEqual(result["rows"], [3, 1])

    async def test_widget_hidden_from_the_user_keeps_its_place(self):
        shown = _widget(self.dashboard.id, title="Shown", position=0, x=4, y=8)
        hidden = _widget(self.dashboard.id, title="Hidden", chart_type="hitl", position=1)
        before = dict(hidden.layout)

        _, result = await self._tidy(
            {"dashboard_id": str(self.dashboard.id)}, [shown, hidden], hidden={hidden.id}
        )

        self.assertEqual(shown.layout, {"x": 0, "y": 0, "w": 12, "h": 5})
        self.assertEqual(hidden.layout, before)
        self.assertEqual(result["widget_count"], 1)

    async def test_empty_and_read_only_dashboards_are_refused(self):
        db, result = await self._tidy({"dashboard_id": str(self.dashboard.id)}, [])
        self.assertEqual(result, {"error": "This dashboard has no widgets to tidy"})
        db.commit.assert_not_awaited()

        widgets = [_widget(self.dashboard.id, title="A")]
        db, result = await self._tidy(
            {"dashboard_id": str(self.dashboard.id)}, widgets, permission="read"
        )
        self.assertEqual(result, {"error": "Read-only access to this dashboard"})
        db.commit.assert_not_awaited()

    async def test_bad_arguments_are_refused_before_any_lookup(self):
        db = AsyncMock()
        for args, error in [
            ({"dashboard_id": "nope"}, chat_dashboards.DASHBOARD_ID_ERROR),
            (
                {"dashboard_id": str(self.dashboard.id), "per_row": 5},
                "per_row must be a whole number from 1 to 4",
            ),
            (
                {"dashboard_id": str(self.dashboard.id), "per_row": "two"},
                "per_row must be a whole number from 1 to 4",
            ),
        ]:
            result = await chat_dashboards.tidy_dashboard_for_chat(db, self.user, args, BASE_URL)
            self.assertEqual(result, {"error": error})
        db.execute.assert_not_awaited()


class TestDashboardToolSummaries(unittest.TestCase):
    def test_summaries(self):
        listed = {"count": 2, "dashboards": [{"widgets": [{}, {}]}, {"widgets": [{}]}]}
        self.assertEqual(
            ai_assistant._summarize_tool_result("list_dashboards", json.dumps(listed)),
            "2 dashboard(s), 3 widget(s) listed",
        )
        added = {"widget": {"kind": "run", "title": "Import"}, "dashboard": {"name": "Ops"}}
        self.assertEqual(
            ai_assistant._summarize_tool_result("add_dashboard_widget", json.dumps(added)),
            "Added run widget 'Import' to dashboard 'Ops'",
        )
        self.assertEqual(
            ai_assistant._summarize_tool_result(
                "add_dashboard_widget", json.dumps({"error": "Workflow not found"})
            ),
            "Error: Workflow not found",
        )
        renamed = {"widget": {"title": "Sales"}, "dashboard": {"name": "Ops"}}
        self.assertEqual(
            ai_assistant._summarize_tool_result("rename_dashboard_widget", json.dumps(renamed)),
            "Renamed widget to 'Sales' on dashboard 'Ops'",
        )
        self.assertEqual(
            ai_assistant._summarize_tool_result("delete_dashboard_widget", json.dumps(renamed)),
            "Deleted widget 'Sales' from dashboard 'Ops'",
        )
        tidied = {"widget_count": 5, "rows": [3, 2], "dashboard": {"name": "Ops"}}
        self.assertEqual(
            ai_assistant._summarize_tool_result("tidy_dashboard", json.dumps(tidied)),
            "Tidied 5 widget(s) on dashboard 'Ops' into rows of 3, 2",
        )


class TestDashboardToolDispatch(unittest.IsolatedAsyncioTestCase):
    async def test_stream_dispatches_dashboard_tools(self):
        user = SimpleNamespace(id=uuid.uuid4())
        tool_message = MagicMock(content=None)
        tool_call = MagicMock()
        tool_call.id = "dash-call"
        tool_call.function.name = "list_dashboards"
        tool_call.function.arguments = "{}"
        tool_message.tool_calls = [tool_call]
        final_message = MagicMock(content="You have one dashboard.", tool_calls=None)
        usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=tool_message)], usage=usage),
            MagicMock(choices=[MagicMock(message=final_message)], usage=usage),
        ]
        db = AsyncMock()

        with (
            patch.object(ai_assistant, "record_run_history"),
            patch.object(
                ai_assistant,
                "call_dashboard_tool",
                AsyncMock(return_value={"count": 1, "dashboards": [{"widgets": [{}]}]}),
            ) as call_tool,
        ):
            chunks = [
                chunk
                async for chunk in ai_assistant.stream_dashboard_chat(
                    client,
                    "gpt-4o-mini",
                    "system",
                    [{"role": "user", "content": "which pages do I have?"}],
                    db,
                    user,
                    "OpenAI",
                    BASE_URL,
                )
            ]

        call_tool.assert_awaited_once_with(
            db, user, "list_dashboards", {}, BASE_URL, can_build=False
        )
        joined = "".join(chunks)
        self.assertIn("Reading dashboards...", joined)
        self.assertIn("1 dashboard(s), 1 widget(s) listed", joined)


if __name__ == "__main__":
    unittest.main()
