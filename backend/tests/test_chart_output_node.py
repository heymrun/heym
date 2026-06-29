import concurrent.futures
import threading
import unittest
import uuid
from unittest.mock import patch

from app.services.node_execution import registry as node_registry
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

        def blocking_wait_handler(_ctx):
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
        edges = [
            {"id": "e1", "source": "src", "target": "chart"},
            {"id": "e2", "source": "src", "target": "side"},
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
                try:
                    result = future.result(timeout=15)
                except concurrent.futures.TimeoutError as exc:
                    side_gate.set()
                    future.result(timeout=5)
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
