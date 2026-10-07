"""Page parameters: `$page.record` in widget runs and in the expression dialog alike."""

import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import dashboards, expressions
from app.services.expression_evaluator import ExpressionEvaluatorService
from app.services.page_params import (
    PAGE_INPUT_KEY,
    page_inputs,
    page_params_from_inputs,
    preview_page_params,
)
from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT
from app.services.workflow_executor import (
    execute_workflow,
    execute_workflow_streaming,
    resume_workflow_execution,
)

LOOKUP = {
    "id": "lookup",
    "type": "set",
    "data": {
        "label": "lookup",
        "mappings": [
            {"key": "record", "value": "$page.record"},
            {"key": "query", "value": "Customer $page.record"},
            {"key": "notes", "value": '$page.record + "-notes"'},
        ],
    },
}


def _outputs(nodes: list[dict], edges: list[dict], inputs: dict) -> dict[str, Any]:
    result = execute_workflow(
        workflow_id=uuid.uuid4(), nodes=nodes, edges=edges, inputs=inputs, test_run=True
    )
    assert result.status == "success", result.outputs
    return {
        (row["node_label"] if isinstance(row, dict) else row.node_label): (
            row["output"] if isinstance(row, dict) else row.output
        )
        for row in result.node_results
    }


class PageInputsTests(unittest.TestCase):
    def test_inputs_round_trip(self) -> None:
        self.assertEqual(page_inputs("ACME-1"), {PAGE_INPUT_KEY: {"record": "ACME-1"}})
        self.assertEqual(page_params_from_inputs(page_inputs("ACME-1")), {"record": "ACME-1"})

    def test_a_run_outside_a_page_has_no_parameters(self) -> None:
        self.assertIsNone(page_params_from_inputs({}))
        self.assertIsNone(page_params_from_inputs({PAGE_INPUT_KEY: "ACME-1"}))
        self.assertIsNone(page_params_from_inputs(None))

    def test_only_widget_workflows_preview_page(self) -> None:
        self.assertEqual(preview_page_params("dashboard_widget"), {"record": None})
        self.assertIsNone(preview_page_params("workflow"))


class PageRunTests(unittest.TestCase):
    def test_a_widget_run_reads_the_record(self) -> None:
        outputs = _outputs([LOOKUP], [], page_inputs("ACME-1"))

        self.assertEqual(
            outputs["lookup"],
            {"record": "ACME-1", "query": "Customer ACME-1", "notes": "ACME-1-notes"},
        )

    def test_a_page_without_a_record_gives_null(self) -> None:
        self.assertIsNone(_outputs([LOOKUP], [], page_inputs(None))["lookup"]["record"])

    def test_a_node_labelled_page_keeps_its_name(self) -> None:
        page_node = {
            "id": "page",
            "type": "set",
            "data": {"label": "page", "mappings": [{"key": "record", "value": "from the node"}]},
        }
        reader = {
            "id": "reader",
            "type": "set",
            "data": {"label": "reader", "mappings": [{"key": "record", "value": "$page.record"}]},
        }
        outputs = _outputs(
            [page_node, reader],
            [{"id": "e1", "source": "page", "target": "reader"}],
            page_inputs("ACME-1"),
        )

        self.assertEqual(outputs["reader"], {"record": "from the node"})

    def test_a_streamed_run_reads_the_record(self) -> None:
        events = list(
            execute_workflow_streaming(
                workflow_id=uuid.uuid4(),
                nodes=[LOOKUP],
                edges=[],
                inputs=page_inputs("ACME-2"),
                test_run=True,
            )
        )

        complete = next(e for e in events if e.get("type") == "execution_complete")
        self.assertEqual(complete["outputs"]["lookup"]["record"], "ACME-2")

    def test_a_run_resumed_after_review_still_reads_the_record(self) -> None:
        snapshot = {
            "workflow_id": str(uuid.uuid4()),
            "nodes": [{"id": "agent-1", "type": "agent", "data": {"label": "Agent"}}, LOOKUP],
            "edges": [{"id": "e1", "source": "agent-1", "target": "lookup"}],
            "workflow_cache": {},
            "initial_inputs": page_inputs("ACME-3"),
            "node_results": [],
            "node_outputs": {},
            "node_execution_contexts": {},
            "label_to_output": {},
            "skipped_nodes": [],
            "inactive_nodes": [],
            "loop_states": {},
            "vars": {},
            "sub_workflow_executions": [],
            "completed_nodes": [],
            "pending_count": {"lookup": 1},
            "paused_node_id": "agent-1",
            "paused_node_label": "Agent",
            "hitl_resume_mode": "inject_output",
            "test_mode": True,
        }

        result = resume_workflow_execution(
            snapshot=snapshot, resolved_output={"decision": "accepted", "text": "ok"}
        )

        lookup = next(row for row in result.node_results if row["node_label"] == "lookup")
        self.assertEqual(lookup["output"]["record"], "ACME-3")


class PageDialogTests(unittest.TestCase):
    def test_the_dialog_answers_what_the_run_produced(self) -> None:
        service = ExpressionEvaluatorService(page_params={"record": "ACME-1"})
        run = _outputs([LOOKUP], [], page_inputs("ACME-1"))["lookup"]

        for mapping in LOOKUP["data"]["mappings"]:
            with self.subTest(expression=mapping["value"]):
                response = service.evaluate(mapping["value"], {})
                self.assertIsNone(response.error)
                self.assertEqual(response.result, run[mapping["key"]])

    def test_the_dialog_previews_a_widget_record_as_null(self) -> None:
        response = ExpressionEvaluatorService(page_params={"record": None}).evaluate(
            "$page.record", {}
        )

        self.assertIsNone(response.result)
        self.assertIsNone(response.error)


class EvaluationSetupPageTests(unittest.IsolatedAsyncioTestCase):
    async def _setup(self, kind: str) -> expressions.EvaluationSetup:
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            kind=kind,
            nodes=[LOOKUP],
            edges=[],
            owner_id=uuid.uuid4(),
            name="Customer notes",
            description="",
        )
        request = expressions.ExpressionContextRequest(
            workflow_id=workflow.id, current_node_id="lookup"
        )
        with (
            patch.object(expressions, "get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch.object(expressions, "get_credentials_context", AsyncMock(return_value={})),
            patch.object(expressions, "get_global_variables_context", AsyncMock(return_value={})),
            patch.object(expressions, "build_public_base_url", return_value="http://localhost"),
        ):
            return await expressions.build_evaluation_setup(
                request, MagicMock(), AsyncMock(), SimpleNamespace(id=uuid.uuid4())
            )

    async def test_a_widget_workflow_gets_page_in_the_dialog(self) -> None:
        setup = await self._setup("dashboard_widget")

        self.assertEqual(setup.service.page_params, {"record": None})

    async def test_an_ordinary_workflow_does_not(self) -> None:
        setup = await self._setup("workflow")

        self.assertIsNone(setup.service.page_params)


class PageDocumentationTests(unittest.TestCase):
    def test_the_dsl_prompt_and_the_widget_builder_know_page(self) -> None:
        self.assertIn("#### Detail pages: `$page.record`", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("$page.record", dashboards._AI_WIDGET_SUFFIX)


if __name__ == "__main__":
    unittest.main()
