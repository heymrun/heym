"""Structured diagram widgets, from DSL execution to Work's planning previews."""

import json
import unittest
import uuid
from copy import deepcopy

from fastapi import HTTPException

from app.api.dashboards import _proposal_response, _seed_widget_nodes
from app.services.chart_payload import build_chart_payload
from app.services.dashboard_data import _unwrap_chart_payload
from app.services.dashboard_widget_plan import PLAN_SYSTEM_PROMPT, parse_widget_plan
from app.services.workflow_executor import execute_workflow

TASKS = [
    {"id": "design", "label": "Design", "start": "2026-10-01", "end": "2026-10-05"},
    {
        "id": "build",
        "label": "Build",
        "start": "2026-10-05T02:00:00+02:00",
        "end": "2026-10-14",
        "progress": 40,
        "dependencies": ["design"],
    },
]
GRAPH = {
    "entities": [
        {"id": "users", "label": "Users", "fields": [{"name": "id", "key": "PK"}]},
        {"id": "orders", "label": "Orders", "fields": [{"name": "user_id", "key": "FK"}]},
    ],
    "relations": [
        {
            "source": "users",
            "target": "orders",
            "sourceField": "id",
            "targetField": "user_id",
            "cardinality": "one-to-many",
        }
    ],
}


class DiagramWidgetTests(unittest.TestCase):
    def test_gantt_resolves_nested_table_rows_and_normalizes_dates(self) -> None:
        rows = [{"id": str(index), "data": task} for index, task in enumerate(TASKS)]
        payload = build_chart_payload(
            {"chartType": "gantt", "dataPath": "result.rows", "title": "Plan"},
            {"result": {"rows": rows}},
        )
        self.assertEqual(payload["tasks"][0]["start"], "2026-10-01T00:00:00+00:00")
        self.assertEqual(payload["tasks"][1]["start"], "2026-10-05T00:00:00+00:00")
        self.assertEqual(payload["tasks"][1]["dependencies"], ["design"])
        self.assertEqual(payload["title"], "Plan")
        self.assertEqual(_unwrap_chart_payload({"chart": payload}), payload)

    def test_gantt_rejects_invalid_dates_ranges_progress_and_references(self) -> None:
        for change in (
            {"start": "not-a-date"},
            {"end": "2026-09-01"},
            {"progress": 101},
            {"progress": float("nan")},
            {"dependencies": ["missing"]},
            {"dependencies": ["design"]},
        ):
            with self.subTest(change=change), self.assertRaises(HTTPException) as caught:
                build_chart_payload({"chartType": "gantt"}, [{**TASKS[0], **change}])
            self.assertEqual(caught.exception.status_code, 400)
        with self.assertRaises(HTTPException):
            build_chart_payload({"chartType": "gantt"}, [TASKS[0], TASKS[0]])

    def test_er_diagram_reads_an_object_and_preserves_field_connections(self) -> None:
        for config, source in (
            ({"dataPath": "result.graph"}, {"result": {"graph": GRAPH}}),
            ({}, GRAPH),
            ({}, {"graph": GRAPH}),
        ):
            with self.subTest(config=config):
                payload = build_chart_payload({"chartType": "erDiagram", **config}, source)
                self.assertEqual(payload["relations"][0]["sourceField"], "id")
                self.assertEqual(payload["entities"][1]["fields"][0]["key"], "FK")
                self.assertEqual(_unwrap_chart_payload({"diagram": payload}), payload)

    def test_er_diagram_rejects_dangling_entities_fields_and_duplicate_ids(self) -> None:
        for change in ({"target": "missing"}, {"targetField": "missing"}, {"cardinality": "all"}):
            source = deepcopy(GRAPH)
            source["relations"][0].update(change)
            with self.subTest(change=change), self.assertRaises(HTTPException):
                build_chart_payload({"chartType": "erDiagram"}, source)
        duplicate = deepcopy(GRAPH)
        duplicate["entities"].append(duplicate["entities"][0])
        with self.assertRaises(HTTPException):
            build_chart_payload({"chartType": "erDiagram"}, duplicate)

    def test_empty_diagrams_are_valid(self) -> None:
        self.assertEqual(build_chart_payload({"chartType": "gantt"}, {})["tasks"], [])
        self.assertEqual(build_chart_payload({"chartType": "erDiagram"}, {})["entities"], [])

    def test_real_set_node_dsl_runs_both_diagrams_and_seed_has_no_numeric_mapping(self) -> None:
        cases = (
            (
                "gantt",
                '$array(dict(id="task", label="Design", start="2026-10-01", end="2026-10-05"))',
                "tasks",
            ),
            (
                "erDiagram",
                '$dict(entities=array(dict(id="users", label="Users", fields=array(dict(name="id", key="PK")))), relations=array())',
                "entities",
            ),
        )
        for kind, expression, key in cases:
            with self.subTest(kind=kind):
                nodes, edges = _seed_widget_nodes(kind)
                self.assertNotIn("valueField", nodes[-1]["data"])
                nodes[0]["data"]["mappings"][0]["value"] = expression
                result = execute_workflow(
                    workflow_id=uuid.uuid4(), nodes=nodes, edges=edges, inputs={}, test_run=True
                )
                charts = [
                    node for node in result.node_results if node["node_type"] == "chartOutput"
                ]
                self.assertEqual(len(charts), 1)
                self.assertEqual(charts[0]["output"]["type"], kind)
                self.assertEqual(len(charts[0]["output"][key]), 1)

    def test_planner_returns_structured_previews_through_the_response_schema(self) -> None:
        for kind, example, key in (
            ("gantt", {"tasks": TASKS}, "tasks"),
            ("erDiagram", GRAPH, "entities"),
        ):
            with self.subTest(kind=kind):
                plan = parse_widget_plan(
                    json.dumps(
                        {
                            "widgets": [
                                {
                                    "title": "Plan",
                                    "chartType": kind,
                                    "prompt": "Show it",
                                    "example": example,
                                }
                            ]
                        }
                    )
                )
                self.assertEqual(plan[0].chart_type, kind)
                response = _proposal_response(plan[0]).model_dump(by_alias=True)
                self.assertEqual(len(response["example"][key]), 2)
                if kind == "erDiagram":
                    self.assertEqual(response["example"]["relations"][0]["sourceField"], "id")
                self.assertIn(kind, PLAN_SYSTEM_PROMPT)

    def test_planner_drops_invalid_or_oversized_sketches_without_losing_proposals(self) -> None:
        for example in ({"tasks": [TASKS[0]] * 9}, {"tasks": [{**TASKS[0], "end": "bad"}]}):
            plan = parse_widget_plan(
                json.dumps(
                    {
                        "widgets": [
                            {
                                "title": "Plan",
                                "chartType": "gantt",
                                "prompt": "Show it",
                                "example": example,
                            }
                        ]
                    }
                )
            )
            self.assertIsNone(plan[0].example)
            self.assertEqual(plan[0].chart_type, "gantt")
