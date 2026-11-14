"""Chat tools that create a dashboard and build or change several widgets at once, and the
``dashboard`` stream events that let a client redraw the dashboard while they run."""

import asyncio
import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import ai_assistant, chat_dashboard_builds, chat_dashboards
from app.api import dashboards as dashboards_api
from app.db.models import CredentialType, Dashboard
from app.models.dashboard_schemas import WidgetDataResponse
from app.services import mcp_chat_service
from app.services.chat_progress import ToolProgress, follow_tool
from app.services.dashboard_data import no_chart_error

BASE_URL = "https://heym.example"


def _rows(items):
    res = MagicMock()
    res.all.return_value = items
    return res


def _llm(session_id="conv-1"):
    credential = SimpleNamespace(id=uuid.uuid4(), type=CredentialType.openai)
    return chat_dashboard_builds.WidgetModel(
        credential=credential, model="gpt-4o-mini", session_id=session_id
    )


def _dsl(name, chart_type="bar"):
    return {
        "name": name,
        "nodes": [{"id": "c", "type": "chartOutput", "data": {"chartType": chart_type}}],
        "edges": [],
    }


def _data(payload=None, error=None):
    return WidgetDataResponse(
        widget_id=uuid.uuid4(), payload=payload, cached=False, computed_at=None, error=error
    )


class TestToolsRegistered(unittest.TestCase):
    def test_tools_are_offered_with_their_limits(self):
        tools = {t["function"]["name"]: t["function"] for t in ai_assistant.DASHBOARD_CHAT_TOOLS}
        self.assertEqual(tools["create_dashboard"]["parameters"]["required"], ["name"])
        build = tools["build_dashboard_widgets"]["parameters"]
        self.assertEqual(build["required"], ["dashboard_id", "widgets"])
        self.assertEqual(build["properties"]["widgets"]["maxItems"], 8)
        self.assertEqual(build["properties"]["widgets"]["items"]["required"], ["title", "prompt"])
        refine = tools["refine_dashboard_widgets"]["parameters"]
        self.assertEqual(refine["required"], ["changes"])
        self.assertEqual(refine["properties"]["changes"]["maxItems"], 10)

    def test_prompt_and_mcp_description_cover_pages_built_by_chat(self):
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        self.assertIn("call create_dashboard with a short name", prompt)
        self.assertIn("call build_dashboard_widgets once with every widget", prompt)
        self.assertIn("call refine_dashboard_widgets once with every change", prompt)
        self.assertIn("Heym Work's page view lists the user's notes", prompt)
        description = mcp_chat_service.MCP_CHAT_TOOL_DESCRIPTION
        self.assertIn("create a dashboard", description)
        self.assertIn("build several new widgets on a dashboard at once", description)


class TestCreateDashboardForChat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4(), email="ada@example.com")

    async def test_creates_an_owned_dashboard_and_audits_it(self):
        db = AsyncMock()
        db.add = MagicMock()

        async def _refresh(obj):
            obj.id = uuid.uuid4()

        db.refresh = AsyncMock(side_effect=_refresh)
        with patch.object(chat_dashboards, "audit") as audit:
            result = await chat_dashboards.create_dashboard_for_chat(
                db, self.user, {"name": "  Support  "}, BASE_URL, can_build=True
            )

        created = db.add.call_args.args[0]
        self.assertIsInstance(created, Dashboard)
        self.assertEqual(created.owner_id, self.user.id)
        self.assertEqual(created.name, "Support")
        db.commit.assert_awaited_once()
        self.assertTrue(result["created"])
        self.assertEqual(result["dashboard"]["name"], "Support")
        self.assertEqual(
            result["dashboard"]["url"], f"{BASE_URL}/?tab=dashboard&dashboard={created.id}"
        )
        self.assertIn("build_dashboard_widgets", result["next_step"])
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "dashboard.create")

    async def test_refuses_without_build_mode_or_a_name(self):
        db = AsyncMock()
        refused = await chat_dashboards.create_dashboard_for_chat(
            db, self.user, {"name": "Ops"}, BASE_URL, can_build=False
        )
        self.assertEqual(refused, {"error": chat_dashboards.CREATE_NEEDS_BUILD_ERROR})
        for name in ("", "   ", None, "x" * 256):
            result = await chat_dashboards.create_dashboard_for_chat(
                db, self.user, {"name": name}, BASE_URL, can_build=True
            )
            self.assertIn("name must be", result["error"])
        db.commit.assert_not_awaited()

    async def test_dispatch_passes_build_mode(self):
        db = AsyncMock()
        result = await chat_dashboards.call_dashboard_tool(
            db, self.user, "create_dashboard", {"name": "Ops"}, BASE_URL, can_build=False
        )
        self.assertEqual(result, {"error": chat_dashboards.CREATE_NEEDS_BUILD_ERROR})


class TestDashboardChangeEvents(unittest.TestCase):
    def test_each_change_names_its_dashboard_and_widget(self):
        dashboard = {"id": "d1", "name": "Ops"}
        widget = {"id": "w1", "title": "Open cases"}
        events = chat_dashboards.dashboard_change_events
        self.assertEqual(
            events("create_dashboard", {"created": True, "dashboard": dashboard}),
            [{"type": "dashboard", "action": "created", "dashboard_id": "d1", "title": "Ops"}],
        )
        for name, action in (
            ("add_dashboard_widget", "widget_added"),
            ("rename_dashboard_widget", "widget_updated"),
            ("delete_dashboard_widget", "widget_removed"),
        ):
            self.assertEqual(
                events(name, {"widget": widget, "dashboard": dashboard}),
                [
                    {
                        "type": "dashboard",
                        "action": action,
                        "dashboard_id": "d1",
                        "widget_id": "w1",
                        "title": "Open cases",
                    }
                ],
            )
        self.assertEqual(
            events("tidy_dashboard", {"tidied": True, "dashboard": dashboard}),
            [{"type": "dashboard", "action": "arranged", "dashboard_id": "d1"}],
        )

    def test_a_revertible_change_names_the_snapshot_before_it(self):
        event = chat_dashboards.dashboard_event(
            "widget_updated", "d1", widget_id="w1", title="Open cases", previous_version=7
        )
        self.assertEqual(event["previous_version"], 7)
        plain = chat_dashboards.dashboard_event("widget_updated", "d1", widget_id="w1")
        self.assertNotIn("previous_version", plain)

    def test_reads_and_errors_change_nothing(self):
        events = chat_dashboards.dashboard_change_events
        self.assertEqual(events("list_dashboards", {"count": 0, "dashboards": []}), [])
        self.assertEqual(events("add_dashboard_widget", {"error": "Dashboard not found"}), [])
        self.assertEqual(events("add_dashboard_widget", "not a dict"), [])


class TestEmptyReason(unittest.TestCase):
    def test_reasons_mirror_the_page_wizard(self):
        reason = chat_dashboard_builds.empty_reason
        self.assertEqual(reason(_data(error="boom")), "The widget's workflow failed: boom")
        self.assertEqual(reason(_data()), "The widget returned no data.")
        self.assertIsNone(reason(_data({"type": "hitl"})))
        self.assertIsNone(reason(_data({"type": "fileRun"})))
        self.assertEqual(
            reason(_data({"type": "text", "text": " "})), "The widget's text is empty."
        )
        self.assertIsNone(reason(_data({"type": "text", "text": "Hi"})))
        self.assertEqual(
            reason(_data({"type": "numeric", "value": ""})), "The widget's value is empty."
        )
        self.assertIsNone(reason(_data({"type": "gauge", "value": 0})))
        self.assertEqual(
            reason(_data({"type": "table", "rows": []})), "The widget's table has no rows."
        )
        self.assertEqual(
            reason(_data({"type": "bar", "series": [{"data": []}]})),
            "The widget's chart has no values.",
        )
        self.assertEqual(
            reason(_data({"type": "bar", "series": [{"data": [0, "0", [0, 0]]}]})),
            "Every value in the widget's chart is 0.",
        )
        self.assertIsNone(reason(_data({"type": "line", "series": [{"data": [0, 3]}]})))

    def test_fix_prompt_carries_the_reason_and_a_short_payload(self):
        prompt = chat_dashboard_builds.fix_prompt(
            "The widget's chart has no values.", _data({"type": "bar", "rows": ["x" * 900]})
        )
        self.assertTrue(prompt.startswith("The widget's chart has no values. It returned: "))
        self.assertIn("...", prompt)
        self.assertIn("Keep the chart type", prompt)


class TestNoChartError(unittest.TestCase):
    def test_names_the_node_that_failed(self):
        result = SimpleNamespace(
            node_results=[
                {"node_label": "leadRows", "node_type": "dataTable", "status": "success"},
                SimpleNamespace(
                    node_label="dailyLeadCounts",
                    node_type="code",
                    status="error",
                    error="The Code node sandbox image could not be resolved.",
                ),
            ],
            outputs={},
        )
        self.assertEqual(
            no_chart_error(result),
            "Workflow produced no chartOutput: dailyLeadCounts failed: "
            "The Code node sandbox image could not be resolved.",
        )

    def test_falls_back_to_the_run_error_then_to_the_plain_message(self):
        self.assertEqual(
            no_chart_error(SimpleNamespace(node_results=[], outputs={"error": "Timed out"})),
            "Workflow produced no chartOutput: Timed out",
        )
        self.assertEqual(
            no_chart_error(SimpleNamespace(node_results=[], outputs={})),
            "Workflow produced no chartOutput",
        )


class _BuildHarness:
    """Patches for build_dashboard_widgets: the dashboard, its context, saving and data checks."""

    def __init__(self, dashboard, *, generate, data=None, detail=""):
        self.dashboard = dashboard
        self.saved = []
        self.applied = []
        self.snapshots = []
        self.generate = generate
        self.data = data or {}

        async def _save(_db, _dashboard, _user, dsl, *, prompt, title, layout, position):
            widget = SimpleNamespace(
                id=uuid.uuid4(),
                dashboard_id=dashboard.id,
                workflow_id=uuid.uuid4(),
                title=title or dsl["name"],
                description=None,
                chart_type="bar",
                layout=layout,
                position=position,
            )
            self.saved.append((widget, prompt))
            return widget

        async def _compute(_db, widget, _owner, force):
            answers = self.data.get(widget.title)
            if not answers:
                return _data({"type": "bar", "series": [{"data": [1]}]})
            return answers.pop(0) if len(answers) > 1 else answers[0]

        async def _apply(_db, widget, workflow, _user, dsl, *, snapshot=True):
            self.applied.append((widget.title, dsl))
            self.snapshots.append(snapshot)
            return 3 if snapshot else None

        self.patches = [
            patch.object(
                dashboards_api,
                "_get_dashboard_for_user",
                AsyncMock(return_value=(dashboard, "owner")),
            ),
            patch.object(
                dashboards_api,
                "widget_create_prompt",
                AsyncMock(side_effect=lambda _db, _d, _u, prompt, _ids: f"CTX {prompt}"),
            ),
            patch.object(dashboards_api, "_detail_page_context", AsyncMock(return_value=detail)),
            patch.object(dashboards_api, "save_generated_widget", AsyncMock(side_effect=_save)),
            patch.object(
                dashboards_api,
                "_load_widget_workflow",
                AsyncMock(
                    side_effect=lambda _db, widget: SimpleNamespace(
                        id=widget.workflow_id,
                        name=widget.title,
                        description=None,
                        nodes=[],
                        edges=[],
                    )
                ),
            ),
            patch.object(
                dashboards_api,
                "widget_refine_prompt",
                AsyncMock(side_effect=lambda _db, _w, _d, _u, prompt, _ids, _kind: f"FIX {prompt}"),
            ),
            patch.object(dashboards_api, "apply_refined_widget", AsyncMock(side_effect=_apply)),
            patch.object(dashboards_api, "generate_widget_dsl", AsyncMock(side_effect=generate)),
            patch.object(
                chat_dashboard_builds, "compute_widget_data", AsyncMock(side_effect=_compute)
            ),
        ]

    def __enter__(self):
        self.mocks = [item.start() for item in self.patches]
        return self

    def __exit__(self, *_exc):
        for item in self.patches:
            item.stop()


class TestBuildDashboardWidgetsForChat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4(), user_rules=None)
        self.dashboard = SimpleNamespace(id=uuid.uuid4(), name="Support", owner_id=self.user.id)
        self.db = AsyncMock()
        # Two widgets already sit on the dashboard, the lowest ending on row 9.
        self.db.execute = AsyncMock(
            return_value=_rows([({"x": 0, "y": 0, "w": 6, "h": 5}, 0), ({"y": 5, "h": 4}, 1)])
        )
        self.widgets = [
            {"title": "Open tickets", "prompt": "Open tickets by priority", "chart_type": "pie"},
            {"title": "Weekly volume", "prompt": "Tickets per week"},
            {"title": "Backlog", "prompt": "Backlog size", "data_table_ids": [str(uuid.uuid4())]},
        ]

    async def _build(self, args, *, llm=None, can_build=True, progress=None):
        return await chat_dashboard_builds.build_dashboard_widgets_for_chat(
            self.db,
            self.user,
            args,
            BASE_URL,
            can_build=can_build,
            llm=llm or _llm(),
            progress=progress or ToolProgress(),
        )

    async def test_builds_every_widget_in_order_below_the_existing_ones(self):
        async def generate(prompt, **kwargs):
            return _dsl(prompt.split("Widget title: ")[1].split(".")[0])

        progress = ToolProgress()
        with _BuildHarness(self.dashboard, generate=generate) as harness:
            result = await self._build(
                {"dashboard_id": str(self.dashboard.id), "widgets": self.widgets},
                progress=progress,
            )

        self.assertEqual(
            [entry["title"] for entry in result["built"]], [w["title"] for w in self.widgets]
        )
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["dashboard"]["id"], str(self.dashboard.id))
        self.assertIn("refine_dashboard_widgets", result["next_step"])
        positions = sorted(widget.position for widget, _ in harness.saved)
        self.assertEqual(positions, [2, 3, 4])
        self.assertTrue(all(widget.layout["y"] >= 9 for widget, _ in harness.saved))
        prompts = {widget.title: prompt for widget, prompt in harness.saved}
        self.assertIn("Draw it as a pie chart.", prompts["Open tickets"])
        self.assertNotIn("Draw it as", prompts["Weekly volume"])
        events = progress.drain()
        self.assertEqual([event["action"] for event in events], ["widget_added"] * 3)
        self.assertTrue(all(event["dashboard_id"] == str(self.dashboard.id) for event in events))
        generate_mock = harness.mocks[7]
        for call in generate_mock.await_args_list:
            self.assertEqual(call.kwargs["session_id"], "conv-1")
            self.assertEqual(call.kwargs["model"], "gpt-4o-mini")
            self.assertTrue(call.args[0].startswith("CTX "))

    async def test_generates_in_parallel(self):
        running = 0
        most = 0

        async def generate(prompt, **kwargs):
            nonlocal running, most
            running += 1
            most = max(most, running)
            await asyncio.sleep(0.02)
            running -= 1
            return _dsl("Chart")

        widgets = [{"title": f"W{i}", "prompt": f"Metric {i}"} for i in range(6)]
        with _BuildHarness(self.dashboard, generate=generate):
            result = await self._build({"dashboard_id": str(self.dashboard.id), "widgets": widgets})

        self.assertEqual(len(result["built"]), 6)
        self.assertEqual(most, chat_dashboard_builds.MAX_PARALLEL_GENERATIONS)

    async def test_a_widget_without_data_is_fixed_and_checked_again(self):
        async def generate(prompt, **kwargs):
            return _dsl("Weekly volume" if "Tickets per week" in prompt else "Other")

        zeros = _data({"type": "bar", "series": [{"data": [0, 0]}]})
        empty = {"Weekly volume": [zeros, _data({"type": "bar", "series": [{"data": [4, 2]}]})]}
        progress = ToolProgress()
        with _BuildHarness(self.dashboard, generate=generate, data=empty) as harness:
            result = await self._build(
                {"dashboard_id": str(self.dashboard.id), "widgets": self.widgets},
                progress=progress,
            )

        fixes = {entry["title"]: entry["data_fixes"] for entry in result["built"]}
        self.assertEqual(fixes, {"Open tickets": 0, "Weekly volume": 1, "Backlog": 0})
        self.assertTrue(all(entry["data_problem"] is None for entry in result["built"]))
        self.assertNotIn("still_failing", result)
        self.assertEqual([title for title, _ in harness.applied], ["Weekly volume"])
        fix_call = next(
            call for call in harness.mocks[7].await_args_list if call.args[0].startswith("FIX ")
        )
        self.assertIn("The widget should show: Widget title: Weekly volume.", fix_call.args[0])
        self.assertIn("Every value in the widget's chart is 0.", fix_call.args[0])
        self.assertIsNotNone(fix_call.kwargs["current_workflow"])
        events = progress.drain()
        self.assertEqual([event["action"] for event in events].count("widget_updated"), 1)
        # A widget the call built has nothing to go back to.
        self.assertTrue(all("previous_version" not in event for event in events))

    async def test_a_widget_that_stays_broken_is_fixed_twice_then_reported(self):
        async def generate(prompt, **kwargs):
            return _dsl("Weekly volume" if "Tickets per week" in prompt else "Other")

        broken = _data(
            error="Workflow produced no chartOutput: dailyLeadCounts failed: The Code node "
            "sandbox image could not be resolved."
        )
        with _BuildHarness(
            self.dashboard, generate=generate, data={"Weekly volume": [broken]}
        ) as harness:
            result = await self._build(
                {"dashboard_id": str(self.dashboard.id), "widgets": self.widgets[:2]}
            )

        self.assertEqual(len(harness.applied), chat_dashboard_builds.MAX_DATA_FIXES)
        self.assertEqual(harness.snapshots, [True, False])
        fix_prompts = [
            call.args[0]
            for call in harness.mocks[7].await_args_list
            if call.args[0].startswith("FIX ")
        ]
        self.assertEqual(len(fix_prompts), 2)
        self.assertIn("Code node sandbox image could not be resolved", fix_prompts[0])
        self.assertIn("instead of the same node again", fix_prompts[0])
        weekly = next(entry for entry in result["built"] if entry["title"] == "Weekly volume")
        self.assertEqual(weekly["data_fixes"], 2)
        self.assertIn("sandbox image", weekly["data_problem"])
        self.assertEqual(
            result["still_failing"],
            [
                {
                    "widget_id": weekly["id"],
                    "title": "Weekly volume",
                    "error": weekly["data_problem"],
                }
            ],
        )
        self.assertIn(
            "Call refine_dashboard_widgets once for them", result["still_failing_next_step"]
        )

    async def test_a_fix_the_model_cannot_write_leaves_the_widget_reported(self):
        async def generate(prompt, **kwargs):
            if prompt.startswith("FIX "):
                raise HTTPException(status_code=422, detail="The model did not answer")
            return _dsl("Weekly volume")

        empty = {"Weekly volume": [_data({"type": "table", "rows": []})]}
        with _BuildHarness(self.dashboard, generate=generate, data=empty) as harness:
            result = await self._build(
                {"dashboard_id": str(self.dashboard.id), "widgets": self.widgets[1:2]}
            )

        self.assertEqual(harness.applied, [])
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["still_failing"][0]["error"], "The widget's table has no rows.")

    async def test_detail_pages_are_not_checked(self):
        async def generate(prompt, **kwargs):
            return _dsl("Chart")

        with _BuildHarness(self.dashboard, generate=generate, detail="This is a detail page"):
            result = await self._build(
                {"dashboard_id": str(self.dashboard.id), "widgets": self.widgets[:1]}
            )
            chat_dashboard_builds.compute_widget_data.assert_not_awaited()
        self.assertEqual(len(result["built"]), 1)

    async def test_failed_widgets_are_reported_and_the_rest_built(self):
        async def generate(prompt, **kwargs):
            if "Backlog" in prompt:
                raise HTTPException(status_code=422, detail="The model did not answer")
            if "Weekly" in prompt:
                raise RuntimeError("provider down")
            return _dsl("Open tickets")

        with _BuildHarness(self.dashboard, generate=generate):
            result = await self._build(
                {"dashboard_id": str(self.dashboard.id), "widgets": self.widgets}
            )

        self.assertEqual([entry["title"] for entry in result["built"]], ["Open tickets"])
        failed = {item["title"]: item["error"] for item in result["failed"]}
        self.assertEqual(failed["Backlog"], "The model did not answer")
        self.assertIn("could not build this widget", failed["Weekly volume"])
        self.assertNotIn("error", result)
        self.assertEqual(
            chat_dashboard_builds.summarize_dashboard_build_tool("build_dashboard_widgets", result),
            "Built 1 widget(s) on dashboard 'Support', 2 failed",
        )

    async def test_nothing_built_is_an_error(self):
        async def generate(prompt, **kwargs):
            raise HTTPException(status_code=422, detail="AI did not produce a chartOutput node")

        with _BuildHarness(self.dashboard, generate=generate):
            result = await self._build(
                {"dashboard_id": str(self.dashboard.id), "widgets": self.widgets[:1]}
            )
        self.assertIn("None of the widgets could be built", result["error"])
        self.assertEqual(len(result["failed"]), 1)

    async def test_refusals_before_any_model_call(self):
        dashboard_id = str(self.dashboard.id)
        llm_types = SimpleNamespace(id=uuid.uuid4(), type="slack")
        cases = [
            (
                {"dashboard_id": dashboard_id, "widgets": self.widgets},
                {"can_build": False},
                "cannot build widgets",
            ),
            ({"dashboard_id": "nope", "widgets": self.widgets}, {}, "dashboard_id must be"),
            ({"dashboard_id": dashboard_id, "widgets": []}, {}, "widgets must list 1 to 8"),
            (
                {"dashboard_id": dashboard_id, "widgets": [{"title": "x", "prompt": "y"}] * 9},
                {},
                "at most 8",
            ),
            ({"dashboard_id": dashboard_id, "widgets": [{"title": "x"}]}, {}, "prompt must say"),
            (
                {
                    "dashboard_id": dashboard_id,
                    "widgets": [{"title": "x", "prompt": "y", "chart_type": "radar"}],
                },
                {},
                "chart_type must be one of",
            ),
            (
                {
                    "dashboard_id": dashboard_id,
                    "widgets": [{"title": "x", "prompt": "y", "data_table_ids": ["no"]}],
                },
                {},
                "data_table_ids must be",
            ),
            (
                {"dashboard_id": dashboard_id, "widgets": self.widgets},
                {"llm": chat_dashboard_builds.WidgetModel(credential=None, model="m")},
                "OpenAI, Google or Custom",
            ),
            (
                {"dashboard_id": dashboard_id, "widgets": self.widgets},
                {"llm": chat_dashboard_builds.WidgetModel(credential=llm_types, model="m")},
                "OpenAI, Google or Custom",
            ),
        ]
        generate = AsyncMock()
        with patch.object(dashboards_api, "generate_widget_dsl", generate):
            for args, options, error in cases:
                result = await self._build(args, **options)
                self.assertIn(error, result["error"])
        generate.assert_not_awaited()

    async def test_a_dashboard_out_of_reach_is_refused(self):
        with patch.object(
            dashboards_api,
            "_get_dashboard_for_user",
            AsyncMock(side_effect=HTTPException(status_code=403, detail="Read-only access")),
        ):
            result = await self._build(
                {"dashboard_id": str(self.dashboard.id), "widgets": self.widgets}
            )
        self.assertEqual(result, {"error": "Read-only access"})


class TestRefineDashboardWidgetsForChat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=uuid.uuid4(), user_rules=None)
        self.dashboard = SimpleNamespace(id=uuid.uuid4(), name="Support", owner_id=self.user.id)
        self.chart = self._widget("Open tickets")
        self.other = self._widget("Backlog")
        self.run = self._widget("Import", chart_type="fileRun")
        self.widgets = {w.id: w for w in (self.chart, self.other, self.run)}

    def _widget(self, title, chart_type="bar"):
        return SimpleNamespace(
            id=uuid.uuid4(),
            dashboard_id=self.dashboard.id if hasattr(self, "dashboard") else None,
            workflow_id=uuid.uuid4(),
            title=title,
            description=None,
            chart_type=chart_type,
        )

    async def _refine(self, changes, *, generate, load=None, progress=None, data=None):
        answers = data or {}

        async def _compute(_db, widget, _owner, force):
            queue = answers.get(widget.title)
            if not queue:
                return _data({"type": "bar", "series": [{"data": [1]}]})
            return queue.pop(0) if len(queue) > 1 else queue[0]

        async def _load(_db, widget_id, _user, write):
            if widget_id not in self.widgets:
                raise HTTPException(status_code=404, detail="Widget not found")
            return self.widgets[widget_id], self.dashboard, "owner"

        applied = []
        self.snapshots = []

        async def _apply(_db, widget, _workflow, _user, dsl, *, snapshot=True):
            applied.append((widget.title, dsl["name"]))
            self.snapshots.append(snapshot)
            return 7 if snapshot else None

        with (
            patch.object(
                dashboards_api, "_load_widget_for_user", AsyncMock(side_effect=load or _load)
            ),
            patch.object(
                dashboards_api,
                "_load_widget_workflow",
                AsyncMock(
                    side_effect=lambda _db, widget: SimpleNamespace(
                        id=widget.workflow_id,
                        name=widget.title,
                        description=None,
                        nodes=[{"id": "n"}],
                        edges=[],
                    )
                ),
            ),
            patch.object(
                dashboards_api,
                "widget_refine_prompt",
                AsyncMock(side_effect=lambda _db, _w, _d, _u, prompt, _ids, _kind: f"CTX {prompt}"),
            ),
            patch.object(dashboards_api, "apply_refined_widget", AsyncMock(side_effect=_apply)),
            patch.object(dashboards_api, "_detail_page_context", AsyncMock(return_value="")),
            patch.object(
                chat_dashboard_builds, "compute_widget_data", AsyncMock(side_effect=_compute)
            ),
            patch.object(
                dashboards_api, "generate_widget_dsl", AsyncMock(side_effect=generate)
            ) as gen,
        ):
            result = await chat_dashboard_builds.refine_dashboard_widgets_for_chat(
                AsyncMock(),
                self.user,
                {"changes": changes},
                BASE_URL,
                can_build=True,
                llm=_llm(),
                progress=progress or ToolProgress(),
            )
        return result, applied, gen

    async def test_applies_every_note_and_merges_notes_on_one_widget(self):
        async def generate(prompt, **kwargs):
            return _dsl(kwargs["current_workflow"]["name"])

        progress = ToolProgress()
        result, applied, gen = await self._refine(
            [
                {"widget_id": str(self.chart.id), "instruction": "Make it a line chart"},
                {"widget_id": str(self.other.id), "instruction": "Only last 30 days"},
                {"widget_id": str(self.chart.id), "instruction": "Sort by count"},
            ],
            generate=generate,
            progress=progress,
        )

        self.assertEqual(
            sorted(applied), [("Backlog", "Backlog"), ("Open tickets", "Open tickets")]
        )
        self.assertEqual(gen.await_count, 2)
        chart_prompt = next(c.args[0] for c in gen.await_args_list if "line chart" in c.args[0])
        self.assertEqual(chart_prompt, "CTX Make it a line chart\nSort by count")
        for call in gen.await_args_list:
            self.assertEqual(call.kwargs["node_label"], "AI Widget Fine-tune")
            self.assertEqual(call.kwargs["session_id"], "conv-1")
        self.assertEqual([entry["previous_version"] for entry in result["changed"]], [7, 7])
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["dashboards"][0]["id"], str(self.dashboard.id))
        events = progress.drain()
        self.assertEqual(sorted(event["title"] for event in events), ["Backlog", "Open tickets"])
        self.assertEqual([event["previous_version"] for event in events], [7, 7])

    async def test_a_change_that_breaks_a_widget_is_fixed_and_checked_again(self):
        async def generate(prompt, **kwargs):
            return _dsl(kwargs["current_workflow"]["name"])

        broken = _data(error="Workflow produced no chartOutput: sumByDay failed: no column day")
        progress = ToolProgress()
        result, applied, gen = await self._refine(
            [{"widget_id": str(self.chart.id), "instruction": "Group it by day"}],
            generate=generate,
            data={"Open tickets": [broken, _data({"type": "bar", "series": [{"data": [3]}]})]},
            progress=progress,
        )

        self.assertEqual(
            applied, [("Open tickets", "Open tickets"), ("Open tickets", "Open tickets")]
        )
        # The fix is part of the change: only the change stores a snapshot, so reverting to it
        # undoes both, and both events offer that snapshot.
        self.assertEqual(self.snapshots, [True, False])
        self.assertEqual(
            [(event["action"], event["previous_version"]) for event in progress.drain()],
            [("widget_updated", 7), ("widget_updated", 7)],
        )
        fix_prompt = gen.await_args_list[1].args[0]
        self.assertTrue(fix_prompt.startswith("CTX The widget should show: Group it by day"))
        self.assertIn("no column day", fix_prompt)
        entry = result["changed"][0]
        self.assertEqual((entry["previous_version"], entry["data_fixes"]), (7, 1))
        self.assertIsNone(entry["data_problem"])
        self.assertNotIn("still_failing", result)

    async def test_run_widgets_missing_widgets_and_model_failures_are_reported(self):
        async def generate(prompt, **kwargs):
            raise HTTPException(status_code=422, detail="AI did not produce a chartOutput node")

        missing = uuid.uuid4()
        result, applied, _ = await self._refine(
            [
                {"widget_id": str(self.run.id), "instruction": "Change it"},
                {"widget_id": str(missing), "instruction": "Change it"},
                {"widget_id": str(self.chart.id), "instruction": "Change it"},
            ],
            generate=generate,
        )
        failed = {item["title"]: item["error"] for item in result["failed"]}
        self.assertIn("file-run widget", failed["Import"])
        self.assertEqual(failed[str(missing)], "Widget not found")
        self.assertEqual(failed["Open tickets"], "AI did not produce a chartOutput node")
        self.assertEqual(applied, [])
        self.assertIn("None of the widgets could be changed", result["error"])
        self.assertEqual(
            chat_dashboard_builds.summarize_dashboard_build_tool(
                "refine_dashboard_widgets", result
            ),
            "Changed 0 widget(s), 3 failed",
        )

    async def test_bad_arguments_are_refused(self):
        generate = AsyncMock()
        for changes, error in (
            ([], "changes must list 1 to 10"),
            ([{"widget_id": "x", "instruction": "y"}], "widget_id must be"),
            ([{"widget_id": str(self.chart.id)}], "instruction must say"),
            (
                [{"widget_id": str(uuid.uuid4()), "instruction": "y"} for _ in range(11)],
                "change at most 10",
            ),
        ):
            result, _, _ = await self._refine(changes, generate=generate)
            self.assertIn(error, result["error"])
        generate.assert_not_awaited()


class TestFollowToolSendsQueuedEvents(unittest.IsolatedAsyncioTestCase):
    async def test_events_emitted_while_running_and_at_the_end_are_sent(self):
        progress = ToolProgress()

        async def tool():
            progress.emit({"type": "dashboard", "action": "widget_added", "dashboard_id": "d"})
            await asyncio.sleep(0.6)
            progress.emit({"type": "dashboard", "action": "widget_updated", "dashboard_id": "d"})
            return "done"

        task = asyncio.ensure_future(tool())
        chunks = [chunk async for chunk in follow_tool(task, "call-1", progress)]
        actions = [json.loads(chunk[6:])["action"] for chunk in chunks if '"dashboard"' in chunk]
        self.assertEqual(actions, ["widget_added", "widget_updated"])
        self.assertEqual(task.result(), "done")


class TestBuildToolDispatch(unittest.IsolatedAsyncioTestCase):
    async def _stream(self, tool_name, arguments, *, build, tool_result, emitted=()):
        user = SimpleNamespace(id=uuid.uuid4())
        tool_message = MagicMock(content=None)
        tool_call = MagicMock()
        tool_call.id = "build-call"
        tool_call.function.name = tool_name
        tool_call.function.arguments = json.dumps(arguments)
        tool_message.tool_calls = [tool_call]
        final_message = MagicMock(content="Done.", tool_calls=None)
        usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=tool_message)], usage=usage),
            MagicMock(choices=[MagicMock(message=final_message)], usage=usage),
        ]
        credential = SimpleNamespace(id=uuid.uuid4(), type=CredentialType.openai)

        async def _call(*_args, progress, **_kwargs):
            for event in emitted:
                progress.emit(event)
            return tool_result

        call = AsyncMock(side_effect=_call)
        with (
            patch.object(ai_assistant, "record_run_history"),
            patch.object(ai_assistant, "call_dashboard_build_tool", call),
        ):
            chunks = [
                chunk
                async for chunk in ai_assistant.stream_dashboard_chat(
                    client,
                    "gpt-4o-mini",
                    "system",
                    [{"role": "user", "content": "build my page"}],
                    AsyncMock(),
                    user,
                    "OpenAI",
                    BASE_URL,
                    selected_credential=credential,
                    build=build,
                )
            ]
        return "".join(chunks), call, credential

    async def test_build_streams_widget_events_before_the_tool_ends(self):
        build = SimpleNamespace(
            request=SimpleNamespace(skill_only=False, target_workflow_id=None),
            llm_session_id="conv-9",
            handles=lambda _name: False,
            tools=lambda tools: tools,
        )
        event = {
            "type": "dashboard",
            "action": "widget_added",
            "dashboard_id": "d1",
            "widget_id": "w1",
        }
        joined, call, credential = await self._stream(
            "build_dashboard_widgets",
            {"dashboard_id": "d1", "widgets": []},
            build=build,
            tool_result={"built": [{}], "failed": [], "dashboard": {"name": "Ops"}},
            emitted=[event],
        )
        kwargs = call.await_args.kwargs
        self.assertTrue(kwargs["can_build"])
        self.assertIs(kwargs["llm"].credential, credential)
        self.assertEqual(kwargs["llm"].model, "gpt-4o-mini")
        self.assertEqual(kwargs["llm"].session_id, "conv-9")
        self.assertIn("Building widgets...", joined)
        self.assertLess(joined.index('"widget_added"'), joined.index('"tool_end"'))
        self.assertIn("Built 1 widget(s) on dashboard 'Ops'", joined)

    async def test_an_ai_edit_turn_cannot_build_widgets(self):
        build = SimpleNamespace(
            request=SimpleNamespace(skill_only=False, target_workflow_id=uuid.uuid4()),
            llm_session_id="conv-9",
            handles=lambda _name: False,
            tools=lambda tools: tools,
        )
        _, call, _ = await self._stream(
            "refine_dashboard_widgets",
            {"changes": []},
            build=build,
            tool_result={"error": "x", "failed": []},
        )
        self.assertFalse(call.await_args.kwargs["can_build"])

    async def test_create_dashboard_streams_a_created_event(self):
        user = SimpleNamespace(id=uuid.uuid4())
        tool_message = MagicMock(content=None)
        tool_call = MagicMock()
        tool_call.id = "create-call"
        tool_call.function.name = "create_dashboard"
        tool_call.function.arguments = json.dumps({"name": "Ops"})
        tool_message.tool_calls = [tool_call]
        final_message = MagicMock(content="Created.", tool_calls=None)
        usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=tool_message)], usage=usage),
            MagicMock(choices=[MagicMock(message=final_message)], usage=usage),
        ]
        result = {"created": True, "dashboard": {"id": "d7", "name": "Ops", "url": "u"}}
        with (
            patch.object(ai_assistant, "record_run_history"),
            patch.object(ai_assistant, "call_dashboard_tool", AsyncMock(return_value=result)),
        ):
            chunks = [
                chunk
                async for chunk in ai_assistant.stream_dashboard_chat(
                    client,
                    "gpt-4o-mini",
                    "system",
                    [{"role": "user", "content": "new page"}],
                    AsyncMock(),
                    user,
                    "OpenAI",
                    BASE_URL,
                )
            ]
        events = [
            json.loads(c[6:]) for c in chunks if c.startswith("data: ") and '"dashboard"' in c
        ]
        created = [e for e in events if e.get("type") == "dashboard"]
        self.assertEqual(
            created,
            [{"type": "dashboard", "action": "created", "dashboard_id": "d7", "title": "Ops"}],
        )


if __name__ == "__main__":
    unittest.main()
