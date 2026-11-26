import concurrent.futures
import threading
import unittest
import uuid
from unittest.mock import patch

from app.services.node_execution import registry as node_registry
from app.services.page_params import page_inputs
from app.services.workflow_executor import execute_workflow


def _chart_output_node_result(result):
    for nr in result.node_results:
        nr_type = nr["node_type"] if isinstance(nr, dict) else nr.node_type
        if nr_type == "chartOutput":
            return nr["output"] if isinstance(nr, dict) else nr.output
    return None


class TestChartOutputNode(unittest.TestCase):
    def test_chart_output_transforms_upstream_rows(self):
        nodes = [
            {
                "id": "src",
                "type": "textInput",
                "data": {"label": "Source"},
            },
            {
                "id": "chart",
                "type": "chartOutput",
                "data": {
                    "label": "Chart",
                    "chartType": "bar",
                    "orientation": "vertical",
                    "dataPath": "data",
                    "labelField": "month",
                    "valueField": "revenue",
                },
            },
        ]
        edges = [{"id": "e1", "source": "src", "target": "chart"}]

        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            inputs={
                "headers": {},
                "query": {},
                "body": {
                    "data": [
                        {"month": "Jan", "revenue": 120},
                        {"month": "Feb", "revenue": 150},
                    ]
                },
            },
            test_run=True,
        )

        payload = _chart_output_node_result(result)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["type"], "bar")
        self.assertEqual(payload["labels"], ["Jan", "Feb"])
        self.assertEqual(payload["series"], [{"name": "revenue", "data": [120, 150]}])

    def test_return_on_chart_output_does_not_wait_for_side_branch(self):
        side_gate = threading.Event()
        side_started = threading.Event()

        def blocking_wait_handler(_ctx):
            side_started.set()
            side_gate.wait()
            return {"value": "side-complete"}

        nodes = [
            {
                "id": "src",
                "type": "set",
                "data": {
                    "label": "source",
                    "mappings": [
                        {
                            "key": "rows",
                            "value": '$array(dict(label="A", value=1))',
                        }
                    ],
                },
            },
            {
                "id": "chart",
                "type": "chartOutput",
                "data": {
                    "label": "chart",
                    "chartType": "bar",
                    "dataPath": "rows",
                    "labelField": "label",
                    "valueField": "value",
                },
            },
            {
                "id": "side",
                "type": "wait",
                "data": {"label": "sideEffect", "duration": 350},
            },
        ]
        # Side edge first: previously this could starve chartOutput on a saturated
        # shared pool and prevent return_on_chart_output from completing early.
        edges = [
            {"id": "e2", "source": "src", "target": "side"},
            {"id": "e1", "source": "src", "target": "chart"},
        ]

        with patch.dict(node_registry._HANDLER_CACHE, {"wait": blocking_wait_handler}):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    execute_workflow,
                    workflow_id=uuid.uuid4(),
                    nodes=nodes,
                    edges=edges,
                    inputs={},
                    test_run=True,
                    return_on_chart_output=True,
                )
                self.assertTrue(
                    side_started.wait(timeout=30),
                    "side branch should start while chart early-return is pending",
                )
                try:
                    result = future.result(timeout=30)
                except concurrent.futures.TimeoutError as exc:
                    side_gate.set()
                    future.result(timeout=10)
                    raise AssertionError(
                        "chart output should return while downstream side branch is still pending"
                    ) from exc

        try:
            self.assertTrue(result.allow_downstream_pending)
            self.assertEqual(result.outputs["chart"]["type"], "bar")
            self.assertFalse(any(nr["node_id"] == "side" for nr in result.node_results))
        finally:
            side_gate.set()
            result.join_allow_downstream()
        self.assertTrue(any(nr["node_id"] == "side" for nr in result.node_results))


class TestChartOutputExpressionFields(unittest.TestCase):
    """The fields the panel offers as expressions are filled in at run time, as html is.

    The runs are shaped like a widget's: no trigger, an upstream Set node, and the detail
    page's record as ``$page.record``.
    """

    def _payload(self, chart: dict, values: dict, record: str | None = None) -> dict:
        nodes = [
            {
                "id": "src",
                "type": "set",
                "data": {
                    "label": "cfg",
                    "mappings": [{"key": key, "value": value} for key, value in values.items()],
                },
            },
            {"id": "chart", "type": "chartOutput", "data": {"label": "Chart", **chart}},
        ]
        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=[{"id": "e1", "source": "src", "target": "chart"}],
            inputs=page_inputs(record),
            test_run=True,
        )
        return _chart_output_node_result(result)

    def test_fields_resolve_from_the_run(self) -> None:
        values = {
            "rows": '$array(dict(month="Jan", revenue=120), dict(month="Feb", revenue=150))',
            "path": "rows",
            "label": "month",
            "field": "revenue",
            "site": "https://example.com/acme",
        }
        payload = self._payload(
            {
                "chartType": "bar",
                "dataPath": "$cfg.path",
                "labelField": "$cfg.label",
                "valueField": "$cfg.field",
                "title": "Orders for $page.record",
                "url": "$cfg.site",
            },
            values,
            record="ACME-1",
        )
        self.assertEqual(payload["title"], "Orders for ACME-1")
        self.assertEqual(payload["labels"], ["Jan", "Feb"])
        self.assertEqual(payload["series"][0]["data"], [120, 150])
        self.assertEqual(payload["url"], "https://example.com/acme")

    def test_gauge_range_stays_numeric(self) -> None:
        payload = self._payload(
            {
                "chartType": "gauge",
                "dataPath": "$cfg.path",
                "valueField": "v",
                "min": "$cfg.low",
                "max": "$cfg.high",
            },
            {"rows": "$array(dict(v=40))", "path": "rows", "low": "10", "high": "250"},
        )
        self.assertEqual((payload["min"], payload["max"]), (10, 250))

    def test_text_that_is_not_a_reference_stays(self) -> None:
        for unit in ("$", "US$", "$PATH"):
            with self.subTest(unit=unit):
                payload = self._payload(
                    {
                        "chartType": "numeric",
                        "dataPath": "rows",
                        "valueField": "v",
                        "unit": unit,
                        "title": "Costs $5 each",
                    },
                    {"rows": "$array(dict(v=40))"},
                )
                self.assertEqual(payload["unit"], unit)
                self.assertEqual(payload["title"], "Costs $5 each")

    def test_text_stays_static(self) -> None:
        payload = self._payload(
            {"chartType": "text", "text": "Hello $page.record"}, {}, record="ACME-1"
        )
        self.assertEqual(payload["text"], "Hello $page.record")
