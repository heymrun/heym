"""The html widget type: a chartOutput html template that resolves like an htmlOutputMapper."""

import json
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.api import chat_dashboard_builds
from app.api import dashboards as dash_api
from app.models.dashboard_schemas import WidgetDataResponse
from app.services.chart_payload import build_chart_payload
from app.services.dashboard_data import _extract_chart_payload
from app.services.dashboard_widget_plan import (
    PLAN_SYSTEM_PROMPT,
    WIDGET_CHART_TYPES,
    parse_widget_plan,
)
from app.services.workflow_executor import WorkflowExecutor


def _outputs(nodes: list[dict], edges: list[dict], body: dict) -> dict:
    result = WorkflowExecutor(nodes=nodes, edges=edges).execute(
        workflow_id=uuid.uuid4(),
        initial_inputs={"headers": {}, "query": {}, "body": body},
    )
    assert result.status == "success", result.node_results
    return {row["node_id"]: row["output"] for row in result.node_results}


def _graph(terminal: dict) -> tuple[list[dict], list[dict]]:
    nodes = [
        {
            "id": "in1",
            "type": "textInput",
            "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
        },
        {"id": "out1", **terminal},
    ]
    return nodes, [{"id": "e1", "source": "in1", "target": "out1"}]


def _data(payload: dict | None) -> WidgetDataResponse:
    return WidgetDataResponse(
        widget_id=uuid.uuid4(),
        payload=payload,
        cached=False,
        computed_at=datetime.now(timezone.utc),
    )


class HtmlChartPayloadTests(unittest.TestCase):
    def test_static_template_becomes_the_payload(self) -> None:
        payload = build_chart_payload({"chartType": "html", "html": "<b>Hi</b>"}, {})
        self.assertEqual(payload, {"type": "html", "html": "<b>Hi</b>"})

    def test_value_field_reads_html_built_upstream(self) -> None:
        payload = build_chart_payload(
            {"chartType": "html", "dataPath": "rows", "valueField": "html"},
            {"rows": [{"html": "<p>up</p>"}]},
        )
        self.assertEqual(payload["html"], "<p>up</p>")

    def test_template_wins_over_value_field(self) -> None:
        payload = build_chart_payload(
            {"chartType": "html", "html": "<p>tpl</p>", "valueField": "html"},
            [{"html": "<p>up</p>"}],
        )
        self.assertEqual(payload["html"], "<p>tpl</p>")

    def test_nothing_to_show_is_empty_not_the_first_string(self) -> None:
        payload = build_chart_payload({"chartType": "html"}, [{"note": "<script>x</script>"}])
        self.assertEqual(payload["html"], "")

    def test_title_and_url_pass_through(self) -> None:
        payload = build_chart_payload(
            {"chartType": "html", "html": "<p>x</p>", "title": "Card", "url": " https://a.b "},
            {},
        )
        self.assertEqual(payload["title"], "Card")
        self.assertEqual(payload["url"], "https://a.b")


class HtmlWidgetExecutionTests(unittest.TestCase):
    TEMPLATE = "<h1>$userInput.text</h1><p>$userInput.text!</p>"

    def test_widget_and_html_output_node_render_the_same_html(self) -> None:
        widget_nodes, edges = _graph(
            {
                "type": "chartOutput",
                "data": {"label": "card", "chartType": "html", "html": self.TEMPLATE},
            }
        )
        page_nodes, _ = _graph(
            {"type": "htmlOutputMapper", "data": {"label": "page", "html": self.TEMPLATE}}
        )
        widget = _outputs(widget_nodes, edges, {"text": "Hello"})["out1"]
        page = _outputs(page_nodes, edges, {"text": "Hello"})["out1"]
        self.assertEqual(widget, {"type": "html", "html": "<h1>Hello</h1><p>Hello!</p>"})
        self.assertEqual(widget["html"], page["html"])

    def test_other_chart_types_carry_no_html(self) -> None:
        nodes, edges = _graph(
            {
                "type": "chartOutput",
                "data": {"label": "card", "chartType": "text", "text": "$userInput.text"},
            }
        )
        output = _outputs(nodes, edges, {"text": "Hello"})["out1"]
        self.assertEqual(output["type"], "text")
        self.assertNotIn("html", output)

    def test_dashboard_reads_the_html_payload_from_the_run(self) -> None:
        result = SimpleNamespace(
            outputs={},
            node_results=[
                {"node_type": "chartOutput", "output": {"type": "html", "html": "<p>x</p>"}}
            ],
        )
        self.assertEqual(_extract_chart_payload(result), {"type": "html", "html": "<p>x</p>"})


class HtmlWidgetBuildTests(unittest.TestCase):
    def test_planner_offers_and_keeps_the_html_type(self) -> None:
        self.assertIn("html", WIDGET_CHART_TYPES)
        self.assertIn("Use html for", PLAN_SYSTEM_PROMPT)
        text = json.dumps(
            {"widgets": [{"title": "Summary", "chartType": "html", "prompt": "A styled card."}]}
        )
        self.assertEqual(parse_widget_plan(text)[0].chart_type, "html")

    def test_empty_html_widget_reads_upstream_html(self) -> None:
        nodes, edges = dash_api._seed_widget_nodes("html")
        chart = nodes[-1]["data"]
        self.assertEqual(chart["chartType"], "html")
        self.assertEqual(chart["valueField"], "html")
        self.assertEqual(len(edges), 1)

    def test_generator_is_told_about_the_sandbox(self) -> None:
        self.assertIn("chartType html", dash_api._AI_WIDGET_SUFFIX)
        self.assertIn("without network access", dash_api._AI_WIDGET_SUFFIX)

    def test_blank_html_is_sent_back_to_be_fixed(self) -> None:
        reason = chat_dashboard_builds.empty_reason
        self.assertEqual(
            reason(_data({"type": "html", "html": "  "})), "The widget's HTML is empty."
        )
        self.assertIsNone(reason(_data({"type": "html", "html": "<p>ok</p>"})))


if __name__ == "__main__":
    unittest.main()
