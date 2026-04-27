import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.expressions import ExpressionEvaluateRequest, evaluate_expression


class ExpressionEvaluateApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = MagicMock()
        self.user.id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.current_node_id = "node-target"
        self.db = AsyncMock()

    def _workflow(
        self,
        *,
        nodes: list[dict] | None = None,
        edges: list[dict] | None = None,
    ) -> MagicMock:
        workflow = MagicMock()
        workflow.id = self.workflow_id
        workflow.owner_id = self.user.id
        workflow.nodes = nodes or []
        workflow.edges = edges or []
        return workflow

    def _request(self, **kwargs) -> ExpressionEvaluateRequest:
        payload = {
            "expression": "$myInput.text",
            "workflow_id": self.workflow_id,
            "current_node_id": self.current_node_id,
            "field_name": "message",
            "input_body": None,
            "selected_loop_iteration_index": None,
            "node_results": [],
        }
        payload.update(kwargs)
        return ExpressionEvaluateRequest(**payload)

    async def test_route_is_registered(self) -> None:
        from app.main import app

        paths = {route.path for route in app.router.routes}
        self.assertIn("/api/expressions/evaluate", paths)

    async def test_valid_request_returns_response(self) -> None:
        workflow = self._workflow(
            nodes=[
                {
                    "id": "node-upstream",
                    "type": "set",
                    "data": {"label": "myInput", "pinnedData": {"text": "pinned_value"}},
                },
                {"id": self.current_node_id, "type": "output", "data": {"label": "finalOutput"}},
            ],
            edges=[{"id": "e1", "source": "node-upstream", "target": self.current_node_id}],
        )
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(
                self._request(), db=self.db, current_user=self.user
            )

        self.assertEqual(response.result, "pinned_value")
        self.assertEqual(response.result_type, "string")
        self.assertTrue(response.preserved_type)
        self.assertIsNone(response.error)

    async def test_canvas_node_results_used_when_no_pinned(self) -> None:
        workflow = self._workflow(
            nodes=[
                {"id": "node-upstream", "type": "set", "data": {"label": "myLlm"}},
                {"id": self.current_node_id, "type": "output", "data": {"label": "finalOutput"}},
            ],
            edges=[{"id": "e1", "source": "node-upstream", "target": self.current_node_id}],
        )
        request = self._request(
            expression="$myLlm.text",
            node_results=[
                {"node_id": "node-upstream", "label": "myLlm", "output": {"text": "canvas_output"}}
            ],
        )
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertEqual(response.result, "canvas_output")

    async def test_pinned_wins_over_canvas(self) -> None:
        workflow = self._workflow(
            nodes=[
                {
                    "id": "node-upstream",
                    "type": "set",
                    "data": {"label": "myInput", "pinnedData": {"text": "pinned_value"}},
                },
                {"id": self.current_node_id, "type": "output", "data": {"label": "finalOutput"}},
            ],
            edges=[{"id": "e1", "source": "node-upstream", "target": self.current_node_id}],
        )
        request = self._request(
            node_results=[
                {"node_id": "node-upstream", "label": "myInput", "output": {"text": "canvas_value"}}
            ]
        )
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertEqual(response.result, "pinned_value")

    async def test_workflow_not_found_returns_404(self) -> None:
        with patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as context:
                await evaluate_expression(self._request(), db=self.db, current_user=self.user)

        self.assertEqual(context.exception.status_code, 404)

    async def test_invalid_expression_returns_error_field(self) -> None:
        workflow = self._workflow(
            nodes=[],
            edges=[],
        )
        request = self._request(expression="$@@broken@@")
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertIsNotNone(response.error)
        self.assertIsNone(response.result)

    async def test_result_type_array(self) -> None:
        workflow = self._workflow(
            nodes=[
                {
                    "id": "node-upstream",
                    "type": "set",
                    "data": {"label": "d", "pinnedData": {"items": [1, 2, 3]}},
                },
                {"id": self.current_node_id, "type": "output", "data": {"label": "finalOutput"}},
            ],
            edges=[{"id": "e1", "source": "node-upstream", "target": self.current_node_id}],
        )
        request = self._request(expression="$d.items")
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertEqual(response.result_type, "array")
        self.assertTrue(response.preserved_type)
        self.assertEqual(response.result, [1, 2, 3])

    async def test_loop_child_response_includes_selected_loop_total(self) -> None:
        workflow = self._workflow(
            nodes=[
                {"id": "node-input", "type": "textInput", "data": {"label": "input"}},
                {
                    "id": "node-loop",
                    "type": "loop",
                    "data": {"label": "loop", "arrayExpression": "$input.items"},
                },
                {"id": "node-child", "type": "set", "data": {"label": "child"}},
            ],
            edges=[
                {"id": "e1", "source": "node-input", "target": "node-loop"},
                {
                    "id": "e2",
                    "source": "node-loop",
                    "target": "node-child",
                    "sourceHandle": "loop",
                },
            ],
        )
        request = self._request(
            current_node_id="node-child",
            expression="$loop.item.text",
            input_body={
                "body": {
                    "items": [
                        {"text": "Hello"},
                        {"text": "World"},
                    ]
                }
            },
            selected_loop_iteration_index=1,
        )
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertEqual(response.result, "World")
        self.assertEqual(response.selected_loop_total, 2)

    async def test_loop_child_can_preview_upstream_set_output_without_run(self) -> None:
        workflow = self._workflow(
            nodes=[
                {
                    "id": "node-llm",
                    "type": "set",
                    "data": {
                        "label": "llm",
                        "pinnedData": {
                            "results": [
                                {"text": "Hello"},
                                {"text": "World"},
                            ]
                        },
                    },
                },
                {
                    "id": "node-loop",
                    "type": "loop",
                    "data": {"label": "loop", "arrayExpression": "$llm.results"},
                },
                {
                    "id": "node-set",
                    "type": "set",
                    "data": {
                        "label": "set",
                        "mappings": [{"key": "text", "value": "$loop.item.text"}],
                    },
                },
                {
                    "id": "node-log",
                    "type": "consoleLog",
                    "data": {"label": "consoleLog"},
                },
            ],
            edges=[
                {"id": "e1", "source": "node-llm", "target": "node-loop"},
                {
                    "id": "e2",
                    "source": "node-loop",
                    "target": "node-set",
                    "sourceHandle": "loop",
                },
                {"id": "e3", "source": "node-set", "target": "node-log"},
                {"id": "e4", "source": "node-log", "target": "node-loop", "targetHandle": "loop"},
            ],
        )
        request = self._request(
            current_node_id="node-log",
            expression="$set.text",
        )
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertEqual(response.result, "Hello")
        self.assertEqual(response.result_type, "string")
        self.assertTrue(response.preserved_type)

    async def test_loop_node_response_includes_selected_loop_total_for_object_items(self) -> None:
        workflow = self._workflow(
            nodes=[
                {"id": "node-input", "type": "textInput", "data": {"label": "input"}},
                {
                    "id": "node-loop",
                    "type": "loop",
                    "data": {"label": "loop", "arrayExpression": "$input.items"},
                },
            ],
            edges=[
                {"id": "e1", "source": "node-input", "target": "node-loop"},
            ],
        )
        request = self._request(
            current_node_id="node-loop",
            expression="$input.items",
            input_body={
                "body": {
                    "items": [
                        {"text": "Hello"},
                        {"text": "World"},
                    ]
                }
            },
        )
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertEqual(
            response.result,
            [
                {"text": "Hello"},
                {"text": "World"},
            ],
        )
        self.assertEqual(response.selected_loop_total, 2)

    async def test_preserved_type_false_for_template(self) -> None:
        workflow = self._workflow(
            nodes=[
                {
                    "id": "node-upstream",
                    "type": "set",
                    "data": {"label": "d", "pinnedData": {"name": "Ali"}},
                },
                {"id": self.current_node_id, "type": "output", "data": {"label": "finalOutput"}},
            ],
            edges=[{"id": "e1", "source": "node-upstream", "target": self.current_node_id}],
        )
        request = self._request(expression="Hello $d.name")
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertFalse(response.preserved_type)
        self.assertEqual(response.result, "Hello Ali")

    async def test_multi_ref_condition_with_js_double_ampersand(self) -> None:
        workflow = self._workflow(
            nodes=[
                {
                    "id": "n-a",
                    "type": "set",
                    "data": {"label": "alpha", "pinnedData": {"ok": True}},
                },
                {
                    "id": "n-b",
                    "type": "set",
                    "data": {"label": "beta", "pinnedData": {"ok": True}},
                },
                {"id": self.current_node_id, "type": "output", "data": {"label": "finalOutput"}},
            ],
            edges=[
                {"id": "e1", "source": "n-a", "target": self.current_node_id},
                {"id": "e2", "source": "n-b", "target": self.current_node_id},
            ],
        )
        request = self._request(expression="$alpha.ok == true && $beta.ok == true")
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertIsNone(response.error)
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")
        self.assertTrue(response.preserved_type)

    async def test_global_arithmetic_subtraction_preserved_number(self) -> None:
        workflow = self._workflow(
            nodes=[
                {"id": self.current_node_id, "type": "output", "data": {"label": "finalOutput"}},
            ],
            edges=[],
        )
        request = self._request(expression="$global.units - 3")
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={"units": 10}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertIsNone(response.error)
        self.assertEqual(response.result, 7)
        self.assertEqual(response.result_type, "number")
        self.assertTrue(response.preserved_type)

    async def test_uses_vars_and_global_context(self) -> None:
        workflow = self._workflow(
            nodes=[
                {
                    "id": "var-node",
                    "type": "variable",
                    "data": {
                        "label": "saveName",
                        "variableName": "savedName",
                        "pinnedData": {"value": "Ada"},
                    },
                },
                {"id": self.current_node_id, "type": "output", "data": {"label": "finalOutput"}},
            ],
            edges=[{"id": "e1", "source": "var-node", "target": self.current_node_id}],
        )
        request = self._request(expression="$vars.savedName")
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={"baseUrl": "https://api.example.com"}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertEqual(response.result, "Ada")

    async def test_upstream_filtering_ignores_unrelated_nodes(self) -> None:
        workflow = self._workflow(
            nodes=[
                {
                    "id": "allowed",
                    "type": "set",
                    "data": {"label": "allowedNode", "pinnedData": {"text": "ok"}},
                },
                {
                    "id": "blocked",
                    "type": "set",
                    "data": {"label": "blockedNode", "pinnedData": {"text": "secret"}},
                },
                {"id": self.current_node_id, "type": "output", "data": {"label": "finalOutput"}},
            ],
            edges=[{"id": "e1", "source": "allowed", "target": self.current_node_id}],
        )
        request = self._request(expression="$blockedNode.text")
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertIsNone(response.result)
        self.assertEqual(response.result_type, "null")

    async def test_input_body_populates_text_input_preview_without_run(self) -> None:
        workflow = self._workflow(
            nodes=[
                {"id": "input-node", "type": "textInput", "data": {"label": "input"}},
                {"id": self.current_node_id, "type": "output", "data": {"label": "finalOutput"}},
            ],
            edges=[{"id": "e1", "source": "input-node", "target": self.current_node_id}],
        )
        request = self._request(
            expression="$input.items",
            input_body={"body": {"items": ["a", "b"]}},
        )
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertEqual(response.result, ["a", "b"])
        self.assertEqual(response.result_type, "array")

    async def test_selected_loop_iteration_index_updates_loop_preview(self) -> None:
        loop_id = "loop-node"
        body_id = "body-node"
        workflow = self._workflow(
            nodes=[
                {"id": "input-node", "type": "textInput", "data": {"label": "input"}},
                {
                    "id": loop_id,
                    "type": "loop",
                    "data": {"label": "loop", "arrayExpression": "$input.items"},
                },
                {"id": body_id, "type": "set", "data": {"label": "body"}},
            ],
            edges=[
                {"id": "e1", "source": "input-node", "target": loop_id},
                {"id": "e2", "source": loop_id, "target": body_id, "sourceHandle": "loop"},
                {"id": "e3", "source": body_id, "target": loop_id, "targetHandle": "loop"},
            ],
        )
        request = self._request(
            current_node_id=body_id,
            expression="$loop.item",
            input_body={"body": {"items": ["first", "second"]}},
            selected_loop_iteration_index=1,
        )
        with (
            patch("app.api.expressions.get_workflow_by_id", AsyncMock(return_value=workflow)),
            patch("app.api.expressions.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.expressions.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            response = await evaluate_expression(request, db=self.db, current_user=self.user)

        self.assertEqual(response.result, "second")
        self.assertEqual(response.result_type, "string")

    def test_request_rejects_expression_over_max_length(self) -> None:
        with self.assertRaises(ValidationError):
            ExpressionEvaluateRequest(
                expression="$" + ("x" * 10001),
                workflow_id=self.workflow_id,
                current_node_id=self.current_node_id,
                node_results=[],
            )


if __name__ == "__main__":
    unittest.main()
