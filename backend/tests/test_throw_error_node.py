from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request

from app.api.workflows import execute_workflow_endpoint
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import throw_error_node
from app.services.workflow_executor import execute_workflow


class ThrowErrorNodeTests(unittest.TestCase):
    def _create_context(self, node_data: dict) -> NodeExecutionContext:
        executor = MagicMock()
        executor.evaluate_message_template.side_effect = lambda t, *a, **k: t
        return NodeExecutionContext(
            executor=executor,
            node_id="throw_1",
            node_label="Throw Error",
            node_type="throwError",
            node_data=node_data,
            inputs={},
            start_time=0.0,
            allow_branch_skip=False,
            node={"id": "throw_1", "type": "throwError", "data": node_data},
        )

    def test_integer_status_code_is_preserved(self) -> None:
        ctx = self._create_context({"errorMessage": "Not found", "httpStatusCode": 404})
        result = throw_error_node.execute(ctx)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.output, {"httpStatusCode": 404})

    def test_string_status_code_is_coerced_to_integer(self) -> None:
        ctx = self._create_context({"errorMessage": "Bad request", "httpStatusCode": "400"})
        result = throw_error_node.execute(ctx)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.output, {"httpStatusCode": 400})
        self.assertIsInstance(result.output["httpStatusCode"], int)

    def test_fractional_and_boolean_status_codes_are_rejected(self) -> None:
        for invalid_status in [404.9, 599.9, "404.5", "599.9", True, False]:
            with self.subTest(invalid_status=invalid_status):
                ctx = self._create_context(
                    {"errorMessage": "Fail", "httpStatusCode": invalid_status}
                )
                result = throw_error_node.execute(ctx)
                self.assertEqual(result.output, {})

    def test_whole_float_status_code_is_accepted(self) -> None:
        ctx = self._create_context({"errorMessage": "Fail", "httpStatusCode": 404.0})
        result = throw_error_node.execute(ctx)
        self.assertEqual(result.output, {"httpStatusCode": 404})

    def test_out_of_range_status_code_is_omitted(self) -> None:
        ctx = self._create_context({"errorMessage": "Fail", "httpStatusCode": 999})
        result = throw_error_node.execute(ctx)
        self.assertEqual(result.output, {})

    def test_non_numeric_status_code_is_omitted(self) -> None:
        ctx = self._create_context({"errorMessage": "Fail", "httpStatusCode": "invalid"})
        result = throw_error_node.execute(ctx)
        self.assertEqual(result.output, {})

    def test_empty_status_code_is_omitted(self) -> None:
        ctx = self._create_context({"errorMessage": "Fail"})
        result = throw_error_node.execute(ctx)
        self.assertEqual(result.output, {})

    def test_workflow_execution_with_string_status_code_coerces_to_int(self) -> None:
        nodes = [
            {"id": "n1", "type": "textInput", "data": {"label": "in"}},
            {
                "id": "n2",
                "type": "throwError",
                "data": {"label": "throw", "errorMessage": "bad request", "httpStatusCode": "400"},
            },
        ]
        edges = [{"id": "e1", "source": "n1", "target": "n2"}]
        result = execute_workflow(uuid.uuid4(), nodes, edges, inputs={})
        self.assertEqual(result.status, "error")
        throw_res = next(r for r in result.node_results if r["node_type"] == "throwError")
        self.assertEqual(throw_res["output"]["httpStatusCode"], 400)
        self.assertIsInstance(throw_res["output"]["httpStatusCode"], int)


class ExecuteWorkflowThrowErrorEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_workflow_endpoint_with_throw_error_returns_integer_status_code(
        self,
    ) -> None:
        wf_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=wf_id,
            owner_id=uuid.uuid4(),
            name="Test Throw Error Workflow",
            nodes=[
                {"id": "n1", "type": "textInput", "data": {"label": "in"}},
                {
                    "id": "n2",
                    "type": "throwError",
                    "data": {
                        "label": "throw",
                        "errorMessage": "bad request",
                        "httpStatusCode": "400",
                    },
                },
            ],
            edges=[{"id": "e1", "source": "n1", "target": "n2"}],
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_enabled=False,
            concurrency_limit=None,
        )
        execution_result = execute_workflow(wf_id, workflow.nodes, workflow.edges, inputs={})

        db = AsyncMock()

        class _Scalar:
            def scalar_one_or_none(self) -> SimpleNamespace:
                return workflow

        db.execute = AsyncMock(return_value=_Scalar())
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        req = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/execute",
                "headers": [],
                "query_string": b"",
            },
            receive,
        )

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock(return_value=None)),
            patch("app.api.workflows.enforce_workflow_http_method"),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution"),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.dispatch_workflow", AsyncMock(return_value=execution_result)),
        ):
            response = await execute_workflow_endpoint(
                workflow_id=wf_id,
                request=req,
                current_user=None,
                db=db,
            )

        self.assertEqual(response.status_code, 400)
        self.assertIsInstance(response.status_code, int)


if __name__ == "__main__":
    unittest.main()
