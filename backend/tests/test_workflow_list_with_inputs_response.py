"""Payload shape for GET /workflows/with-inputs (quick drawer, assistants, debug)."""

import unittest
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.workflows import extract_input_fields_from_workflow, extract_output_node_from_workflow
from app.models.schemas import WorkflowListWithInputsResponse


def _workflow_row(
    *,
    nodes: list | None = None,
    edges: list | None = None,
    wf_id: uuid.UUID | None = None,
    name: str = "Demo",
    description: str | None = "d",
) -> SimpleNamespace:
    now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=wf_id or uuid.uuid4(),
        name=name,
        description=description,
        nodes=nodes or [],
        edges=edges or [],
        created_at=now,
        updated_at=now,
    )


class WorkflowListWithInputsResponseShapeTests(unittest.TestCase):
    """Mirrors list_workflows_with_inputs response construction (no DB)."""

    def test_text_input_default_value_round_trip(self) -> None:
        wf = _workflow_row(
            nodes=[
                {
                    "id": "in1",
                    "type": "textInput",
                    "data": {
                        "active": True,
                        "label": "User",
                        "inputFields": [{"key": "city", "defaultValue": "Paris"}],
                    },
                },
            ],
            edges=[],
        )
        row = WorkflowListWithInputsResponse(
            id=wf.id,
            name=wf.name,
            description=wf.description,
            input_fields=extract_input_fields_from_workflow(wf),
            output_node=extract_output_node_from_workflow(wf),
            created_at=wf.created_at,
            updated_at=wf.updated_at,
        )
        self.assertEqual(len(row.input_fields), 1)
        self.assertEqual(row.input_fields[0].key, "city")
        self.assertEqual(row.input_fields[0].default_value, "Paris")
        # Lone root textInput is both the entry input and the graph end node.
        self.assertIsNotNone(row.output_node)
        assert row.output_node is not None
        self.assertEqual(row.output_node.node_type, "textInput")
        self.assertEqual(row.output_node.output_expression, "$User.city")

    def test_linear_chain_end_node_is_output_schema(self) -> None:
        wf = _workflow_row(
            nodes=[
                {
                    "id": "in1",
                    "type": "textInput",
                    "data": {"active": True, "label": "In", "inputFields": [{"key": "q"}]},
                },
                {
                    "id": "n2",
                    "type": "llm",
                    "data": {"label": "LLM", "active": True, "outputType": "text"},
                },
            ],
            edges=[{"source": "in1", "target": "n2"}],
        )
        row = WorkflowListWithInputsResponse(
            id=wf.id,
            name=wf.name,
            description=wf.description,
            input_fields=extract_input_fields_from_workflow(wf),
            output_node=extract_output_node_from_workflow(wf),
            created_at=wf.created_at,
            updated_at=wf.updated_at,
        )
        self.assertEqual([f.key for f in row.input_fields], ["q"])
        self.assertIsNotNone(row.output_node)
        assert row.output_node is not None
        self.assertEqual(row.output_node.node_type, "llm")
        self.assertEqual(row.output_node.label, "LLM")
        self.assertEqual(row.output_node.output_expression, "$LLM.text")

    def test_explicit_output_node_preferred_over_last_llm(self) -> None:
        wf = _workflow_row(
            nodes=[
                {
                    "id": "in1",
                    "type": "textInput",
                    "data": {"active": True, "label": "In", "inputFields": [{"key": "x"}]},
                },
                {"id": "n2", "type": "llm", "data": {"label": "L", "active": True}},
                {
                    "id": "out1",
                    "type": "output",
                    "data": {"label": "Final", "message": "$L.text", "active": True},
                },
            ],
            edges=[
                {"source": "in1", "target": "n2"},
                {"source": "n2", "target": "out1"},
            ],
        )
        row = WorkflowListWithInputsResponse(
            id=wf.id,
            name=wf.name,
            description=wf.description,
            input_fields=extract_input_fields_from_workflow(wf),
            output_node=extract_output_node_from_workflow(wf),
            created_at=wf.created_at,
            updated_at=wf.updated_at,
        )
        self.assertIsNotNone(row.output_node)
        assert row.output_node is not None
        self.assertEqual(row.output_node.node_type, "output")
        self.assertEqual(row.output_node.output_expression, "$L.text")

    def test_json_serialization_uses_default_value_alias(self) -> None:
        wf = _workflow_row(
            nodes=[
                {
                    "id": "in1",
                    "type": "textInput",
                    "data": {
                        "active": True,
                        "inputFields": [{"key": "k", "defaultValue": "v"}],
                    },
                },
            ],
            edges=[],
        )
        row = WorkflowListWithInputsResponse(
            id=wf.id,
            name=wf.name,
            description=wf.description,
            input_fields=extract_input_fields_from_workflow(wf),
            output_node=extract_output_node_from_workflow(wf),
            created_at=wf.created_at,
            updated_at=wf.updated_at,
        )
        dumped = row.model_dump(mode="json", by_alias=True)
        self.assertIn("input_fields", dumped)
        self.assertEqual(len(dumped["input_fields"]), 1)
        field0 = dumped["input_fields"][0]
        self.assertEqual(field0["key"], "k")
        self.assertEqual(field0["defaultValue"], "v")
