from __future__ import annotations

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.workflows import execute_workflow_endpoint
from app.models.schemas import WorkflowExecuteResponse
from app.services.cluster.run_history import OffloadedRun, throw_error_http_status_code
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
    def _create_workflow(self, wf_id: uuid.UUID) -> SimpleNamespace:
        return SimpleNamespace(
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

    async def _execute_endpoint(
        self,
        workflow: SimpleNamespace,
        execution_result: object,
        *,
        simple_response: bool = True,
        query_string: bytes = b"",
    ) -> object:
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

        headers = [(b"x-simple-response", b"true" if simple_response else b"false")]
        req = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/execute",
                "headers": headers,
                "query_string": query_string,
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
            return await execute_workflow_endpoint(
                workflow_id=workflow.id,
                request=req,
                current_user=None,
                db=db,
            )

    async def test_execute_workflow_endpoint_with_throw_error_returns_integer_status_code(
        self,
    ) -> None:
        wf_id = uuid.uuid4()
        workflow = self._create_workflow(wf_id)
        execution_result = execute_workflow(wf_id, workflow.nodes, workflow.edges, inputs={})

        response = await self._execute_endpoint(workflow, execution_result)

        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(response.status_code, 400)
        self.assertIsInstance(response.status_code, int)
        body = json.loads(response.body.decode())
        self.assertEqual(body, execution_result.outputs)

    async def test_execute_workflow_endpoint_local_throw_error_full_response(
        self,
    ) -> None:
        wf_id = uuid.uuid4()
        workflow = self._create_workflow(wf_id)
        execution_result = execute_workflow(wf_id, workflow.nodes, workflow.edges, inputs={})

        response = await self._execute_endpoint(workflow, execution_result, simple_response=False)

        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(response.status_code, 400)
        self.assertIsInstance(response.status_code, int)
        body = json.loads(response.body.decode())
        self.assertEqual(body["workflow_id"], str(wf_id))
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["outputs"], execution_result.outputs)

    async def test_execute_workflow_endpoint_offloaded_throw_error_returns_custom_status_code(
        self,
    ) -> None:
        wf_id = uuid.uuid4()
        workflow = self._create_workflow(wf_id)
        offloaded = OffloadedRun(
            workflow_id=str(wf_id),
            status="error",
            outputs={"error": "bad request"},
            http_status_code=400,
            history_written=True,
        )

        response = await self._execute_endpoint(workflow, offloaded, simple_response=False)

        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(response.status_code, 400)
        self.assertIsInstance(response.status_code, int)
        body = json.loads(response.body.decode())
        self.assertEqual(body["workflow_id"], str(wf_id))
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["outputs"], {"error": "bad request"})
        self.assertEqual(body["node_results"], [])

    async def test_execute_workflow_endpoint_offloaded_throw_error_simple_response(
        self,
    ) -> None:
        wf_id = uuid.uuid4()
        workflow = self._create_workflow(wf_id)
        offloaded = OffloadedRun(
            workflow_id=str(wf_id),
            status="error",
            outputs={"error": "bad request"},
            http_status_code=400,
            history_written=True,
        )

        response = await self._execute_endpoint(workflow, offloaded, simple_response=True)

        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(response.status_code, 400)
        self.assertIsInstance(response.status_code, int)
        body = json.loads(response.body.decode())
        self.assertEqual(body, {"error": "bad request"})

    async def test_execute_workflow_endpoint_older_offloaded_run_without_status_code_retains_200(
        self,
    ) -> None:
        wf_id = uuid.uuid4()
        workflow = self._create_workflow(wf_id)
        old_offloaded = OffloadedRun(
            workflow_id=str(wf_id),
            status="error",
            outputs={"error": "older error"},
            http_status_code=None,
            history_written=True,
        )

        # Full response shape returns WorkflowExecuteResponse (defaults to HTTP 200)
        full_response = await self._execute_endpoint(workflow, old_offloaded, simple_response=False)
        self.assertIsInstance(full_response, WorkflowExecuteResponse)
        self.assertEqual(full_response.status, "error")
        self.assertEqual(full_response.outputs, {"error": "older error"})

        # Simple response shape returns JSONResponse with status_code=200
        simple_response = await self._execute_endpoint(
            workflow, old_offloaded, simple_response=True
        )
        self.assertIsInstance(simple_response, JSONResponse)
        self.assertEqual(simple_response.status_code, 200)
        body = json.loads(simple_response.body.decode())
        self.assertEqual(body, {"error": "older error"})


class ThrowErrorHttpStatusCodeExtractionTests(unittest.TestCase):
    def test_extracts_from_local_node_results(self) -> None:
        result = SimpleNamespace(
            node_results=[
                {
                    "node_type": "throwError",
                    "status": "error",
                    "output": {"httpStatusCode": 422},
                }
            ],
            http_status_code=None,
        )
        self.assertEqual(throw_error_http_status_code(result), 422)

    def test_extracts_from_offloaded_run(self) -> None:
        run = OffloadedRun(status="error", outputs={}, http_status_code=403)
        self.assertEqual(throw_error_http_status_code(run), 403)

    def test_prefers_node_results_over_offloaded_status_code(self) -> None:
        result = SimpleNamespace(
            node_results=[
                {
                    "node_type": "throwError",
                    "status": "error",
                    "output": {"httpStatusCode": 401},
                }
            ],
            http_status_code=500,
        )
        self.assertEqual(throw_error_http_status_code(result), 401)

    def test_coerces_valid_formats(self) -> None:
        res_str = SimpleNamespace(
            node_results=[
                {
                    "node_type": "throwError",
                    "status": "error",
                    "output": {"httpStatusCode": "404"},
                }
            ]
        )
        self.assertEqual(throw_error_http_status_code(res_str), 404)

        res_float = SimpleNamespace(
            node_results=[
                {
                    "node_type": "throwError",
                    "status": "error",
                    "output": {"httpStatusCode": 400.0},
                }
            ]
        )
        self.assertEqual(throw_error_http_status_code(res_float), 400)

    def test_returns_none_for_missing_or_invalid(self) -> None:
        self.assertIsNone(throw_error_http_status_code(None))
        self.assertIsNone(throw_error_http_status_code(OffloadedRun(status="error", outputs={})))
        self.assertIsNone(
            throw_error_http_status_code(
                SimpleNamespace(
                    node_results=[
                        {
                            "node_type": "throwError",
                            "status": "error",
                            "output": {"httpStatusCode": True},
                        }
                    ]
                )
            )
        )
        self.assertIsNone(
            throw_error_http_status_code(
                SimpleNamespace(
                    node_results=[
                        {
                            "node_type": "throwError",
                            "status": "error",
                            "output": {"httpStatusCode": 999},
                        }
                    ]
                )
            )
        )
        self.assertIsNone(
            throw_error_http_status_code(
                SimpleNamespace(
                    node_results=[
                        {
                            "node_type": "throwError",
                            "status": "error",
                            "output": {"httpStatusCode": "invalid"},
                        }
                    ]
                )
            )
        )
        self.assertIsNone(
            throw_error_http_status_code(
                SimpleNamespace(
                    node_results=[
                        {
                            "node_type": "code",
                            "status": "error",
                            "output": {"httpStatusCode": 500},
                        }
                    ]
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
