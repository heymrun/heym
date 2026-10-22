"""A count card counts one value of a data table column; the widget's title names the value."""

import json
import unittest
import uuid
from typing import Any

from app.services.chart_payload import build_chart_payload
from app.services.count_card_widget import (
    COUNT_NODE_LABEL,
    count_card_html,
    count_card_nodes,
    countable_value,
)
from app.services.dashboard_widget_policy import DASHBOARD_WIDGET_BLOCKED_NODE_TYPES
from app.services.workflow_executor import execute_workflow


def _run_card(value: str, count: int) -> dict[str, Any]:
    """The card's chart output, with a set node standing in for the dataTable count."""
    nodes, edges = count_card_nodes(uuid.uuid4(), "status", value)
    nodes[0] = {
        "id": nodes[0]["id"],
        "type": "set",
        "data": {
            "label": COUNT_NODE_LABEL,
            "mappings": [{"key": "count", "value": f'$int("{count}")'}],
        },
    }
    result = execute_workflow(
        workflow_id=uuid.uuid4(), nodes=nodes, edges=edges, inputs={}, test_run=True
    )
    for node_result in result.node_results:
        row = node_result if isinstance(node_result, dict) else node_result.__dict__
        if row["node_label"] == "chart":
            return row["output"]
    raise AssertionError(f"no chart output, run status {result.status}")


class TestCountCardNodes(unittest.TestCase):
    def test_counts_the_rows_whose_column_is_the_value(self) -> None:
        table_id = uuid.uuid4()
        nodes, edges = count_card_nodes(table_id, "status", "Active")

        count, card, chart = nodes
        self.assertEqual(count["type"], "dataTable")
        self.assertEqual(count["data"]["label"], COUNT_NODE_LABEL)
        self.assertEqual(count["data"]["dataTableId"], str(table_id))
        self.assertEqual(count["data"]["dataTableOperation"], "count")
        self.assertEqual(json.loads(count["data"]["dataTableFilter"]), {"status": "Active"})
        self.assertEqual(card["type"], "set")
        self.assertEqual(chart["type"], "chartOutput")
        self.assertEqual(chart["data"]["chartType"], "text")
        self.assertEqual(
            [(edge["source"], edge["target"]) for edge in edges],
            [(count["id"], card["id"]), (card["id"], chart["id"])],
        )
        for blocked in DASHBOARD_WIDGET_BLOCKED_NODE_TYPES:
            self.assertNotIn(blocked, [node["type"] for node in nodes])

    def test_a_value_with_quotes_stays_valid_json(self) -> None:
        nodes, _ = count_card_nodes(uuid.uuid4(), "status", 'On "hold"')

        self.assertEqual(json.loads(nodes[0]["data"]["dataTableFilter"]), {"status": 'On "hold"'})


class TestCountCardRun(unittest.TestCase):
    def test_the_card_shows_only_the_count(self) -> None:
        output = _run_card("Active", 34)

        self.assertEqual(output["type"], "text")
        self.assertFalse(output["text_interactive"])
        self.assertIn(">34<", output["text"])
        self.assertNotIn("Active", output["text"])

    def test_the_card_reads_the_theme_colors_in_one_html_block(self) -> None:
        text = count_card_html()

        self.assertIn("hsl(var(--foreground))", text)
        self.assertTrue(text.startswith("<div") and text.endswith("</div>"))
        self.assertNotIn("\n", text)

    def test_the_payload_takes_the_card_from_the_set_node(self) -> None:
        payload = build_chart_payload(
            {"chartType": "text", "valueField": "html"}, {"html": "<div>3</div>"}
        )

        self.assertEqual(payload["text"], "<div>3</div>")


class TestCountableValue(unittest.TestCase):
    def test_a_name_after_a_dollar_sign_would_be_resolved(self) -> None:
        self.assertFalse(countable_value("$vip"))
        self.assertFalse(countable_value("Paid $_x"))

    def test_other_values_are_counted(self) -> None:
        self.assertTrue(countable_value("Active"))
        self.assertTrue(countable_value("$100 plan"))
        self.assertTrue(countable_value("Ödendi"))

    def test_a_countable_value_reaches_the_filter_as_it_is(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor(nodes=[], edges=[], test_mode=True)
        for value in ("$100 plan", "Ödendi", 'On "hold"', "50% (promo)"):
            with self.subTest(value=value):
                nodes, _ = count_card_nodes(uuid.uuid4(), "status", value)
                resolved = executor.evaluate_message_template(
                    nodes[0]["data"]["dataTableFilter"], {}
                )
                self.assertEqual(json.loads(resolved), {"status": value})


if __name__ == "__main__":
    unittest.main()
