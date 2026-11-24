import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api import dashboards
from app.models.dashboard_schemas import WidgetActionRequest
from app.services.dashboard_data import run_html_widget_action
from app.services.widget_actions import WidgetAction, WidgetActionGraph
from app.services.workflow_executor import (
    ExecutionResult,
    execute_workflow,
    execute_workflow_streaming,
)


def _graph() -> WidgetActionGraph:
    return WidgetActionGraph(
        [
            {"id": "load", "type": "set", "data": {"label": "load"}},
            {
                "id": "card",
                "type": "chartOutput",
                "data": {
                    "label": "colorChanger",
                    "chartType": "html",
                    "html": "<button>Start</button>",
                },
            },
            {
                "id": "handle",
                "type": "set",
                "data": {
                    "label": "handler",
                    "mappings": [
                        {"key": "color", "value": "$colorChanger.data.color"},
                        {"key": "message", "value": "$colorChanger.message"},
                        {"key": "record", "value": "$page.record"},
                    ],
                },
            },
            {
                "id": "reply",
                "type": "chartOutput",
                "data": {
                    "label": "reply",
                    "chartType": "html",
                    "html": "<p>$handler.message / $handler.color / $handler.record</p>",
                },
            },
        ],
        [
            {"source": "load", "target": "card"},
            {"source": "card", "target": "handle", "sourceHandle": "action"},
            {"source": "handle", "target": "reply"},
        ],
    )


class TestWidgetActionGraph(unittest.TestCase):
    def test_initial_render_only_runs_render_nodes(self) -> None:
        graph = _graph()
        result = execute_workflow(
            uuid.uuid4(), graph.nodes, graph.edges, {}, return_on_chart_output=True
        )
        self.assertEqual(result.status, "success")
        self.assertEqual({row["node_id"] for row in result.node_results}, {"load", "card"})
        self.assertEqual(
            result.outputs["colorChanger"],
            {
                "type": "html",
                "html": "<button>Start</button>",
                "html_action_node_id": "card",
            },
        )

    def test_action_runs_only_branch_with_typed_event_and_page_record(self) -> None:
        graph = _graph()
        action = WidgetAction("card", "color_change", {"color": "blue", "count": 2, "ok": False})
        result = execute_workflow(
            uuid.uuid4(),
            graph.nodes,
            graph.edges,
            {
                **action.inputs(),
                "__heym_page": {"record": "item-1"},
            },
            return_on_chart_output=True,
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(
            {row["node_id"] for row in result.node_results}, {"card", "handle", "reply"}
        )
        self.assertEqual(result.node_results[0]["output"], action.output())
        self.assertEqual(
            result.outputs["reply"],
            {
                "type": "html",
                "html": "<p>color_change / blue / item-1</p>",
                "html_action_node_id": "card",
            },
        )

    def test_streaming_editor_test_run_does_not_start_the_action(self) -> None:
        graph = _graph()
        events = list(
            execute_workflow_streaming(
                workflow_id=uuid.uuid4(),
                nodes=graph.nodes,
                edges=graph.edges,
                inputs={},
                test_run=True,
            )
        )
        self.assertEqual(
            {event["node_id"] for event in events if event["type"] == "node_start"},
            {"load", "card"},
        )

    def test_two_connections_cannot_be_activated(self) -> None:
        graph = _graph()
        graph.edges.append({"source": "card", "target": "reply", "sourceHandle": "action"})
        self.assertEqual(graph.sources(), set())
        self.assertEqual(graph.branch("card"), ([], []))
        self.assertEqual([node["id"] for node in graph.render()[0]], ["load", "card"])

    def test_data_only_and_invalid_payload(self) -> None:
        self.assertIs(WidgetActionRequest(node_id="card", data=False).data, False)
        with self.assertRaises(ValidationError):
            WidgetActionRequest(node_id="card")
        with self.assertRaises(ValidationError):
            WidgetActionRequest(node_id="card", data="x" * 65_537)


class TestWidgetActionRoute(unittest.IsolatedAsyncioTestCase):
    async def test_viewer_runs_as_owner_and_cannot_select_another_node(self) -> None:
        graph = _graph()
        owner = uuid.uuid4()
        dashboard = SimpleNamespace(owner_id=owner, record_format="id")
        widget = SimpleNamespace(id=uuid.uuid4(), workflow_id=uuid.uuid4(), chart_type="html")
        workflow = SimpleNamespace(nodes=graph.nodes, edges=graph.edges)
        db, user = AsyncMock(), SimpleNamespace(id=uuid.uuid4())
        with (
            patch.object(
                dashboards,
                "_load_widget_for_user",
                AsyncMock(return_value=(widget, dashboard, "read")),
            ) as load,
            patch.object(dashboards, "get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch.object(dashboards, "run_html_widget_action", AsyncMock()) as run,
        ):
            await dashboards.widget_action(
                widget.id,
                WidgetActionRequest(
                    node_id="card",
                    message="color_change",
                    data={"color": "blue"},
                    record="item-1",
                ),
                user,
                db,
            )
            load.assert_awaited_once_with(db, widget.id, user, write=False)
            run.assert_awaited_once_with(
                db,
                widget,
                workflow,
                owner,
                WidgetAction("card", "color_change", {"color": "blue"}),
                "item-1",
            )
            with self.assertRaises(HTTPException) as rejected:
                await dashboards.widget_action(
                    widget.id, WidgetActionRequest(node_id="reply", data=0), user, db
                )
            self.assertEqual(rejected.exception.status_code, 404)
            self.assertEqual(run.await_count, 1)

    async def test_action_does_not_write_shared_cache(self) -> None:
        widget = SimpleNamespace(
            id=uuid.uuid4(), cached_payload={"type": "html", "html": "Original"}
        )
        result = ExecutionResult(
            uuid.uuid4(),
            "success",
            {
                "reply": {"type": "html", "html": "For one viewer", "html_action_node_id": "card"},
            },
            0.0,
        )
        with patch(
            "app.services.dashboard_data.run_widget_workflow",
            AsyncMock(return_value=(result, None)),
        ):
            response = await run_html_widget_action(
                AsyncMock(),
                widget,
                SimpleNamespace(),
                uuid.uuid4(),
                WidgetAction("card", "click", None),
                None,
            )
        self.assertEqual(response.payload["html"], "For one viewer")
        self.assertEqual(widget.cached_payload["html"], "Original")
