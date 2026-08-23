"""Per-workflow HTTP method: enforcement, defaults, and the test_run exemption."""

import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request

from app.api.workflows import execute_workflow_endpoint
from app.services.workflow_executor import ExecutionResult


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def make_request(*, method: str, query_string: bytes = b"") -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": method,
        "path": "/api/workflows/test/execute",
        "headers": [],
        "query_string": query_string,
    }
    return Request(scope, receive)


class WorkflowHttpMethodTests(unittest.IsolatedAsyncioTestCase):
    NODES = [
        {
            "id": "in1",
            "type": "textInput",
            "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
        },
        {"id": "out1", "type": "output", "data": {"label": "out", "message": "ok"}},
    ]
    EDGES = [{"id": "e1", "source": "in1", "target": "out1"}]

    def _workflow(self, http_method: str = "POST") -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=self.NODES,
            edges=self.EDGES,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_enabled=False,
            http_method=http_method,
            name="Method Workflow",
        )

    async def _call(self, workflow: SimpleNamespace, method: str, query: bytes = b"") -> object:
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={"out": {"result": "ok"}},
            node_results=[],
            execution_time_ms=5.0,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows.asyncio.to_thread", AsyncMock(return_value=execution_result)),
            patch(
                "app.api.workflows.ExecutionHistory",
                side_effect=lambda **kw: SimpleNamespace(id=uuid.uuid4()),
            ),
        ):
            return await execute_workflow_endpoint(
                workflow_id=workflow.id,
                request=make_request(method=method, query_string=query),
                current_user=None,
                db=db,
            )

    async def test_defaults_to_post_and_post_succeeds(self) -> None:
        response = await self._call(self._workflow(), "POST")
        self.assertEqual(response.status_code, 200)

    async def test_wrong_method_is_rejected_with_405_and_allow(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._call(self._workflow("GET"), "POST")
        self.assertEqual(ctx.exception.status_code, 405)
        self.assertEqual(ctx.exception.headers["Allow"], "GET")

    async def test_each_configured_method_succeeds(self) -> None:
        for method in ("GET", "POST", "PUT", "DELETE"):
            with self.subTest(method=method):
                response = await self._call(self._workflow(method), method)
                self.assertEqual(response.status_code, 200)

    async def test_test_run_bypasses_enforcement(self) -> None:
        """The editor's Run button must keep working whatever the dropdown says."""
        response = await self._call(self._workflow("GET"), "POST", query=b"test_run=true")
        self.assertEqual(response.status_code, 200)

    async def test_a_missing_column_value_is_treated_as_post(self) -> None:
        """Rows predating the migration must behave exactly as they do today."""
        workflow = self._workflow()
        workflow.http_method = None
        response = await self._call(workflow, "POST")
        self.assertEqual(response.status_code, 200)


class UpdateWorkflowHttpMethodTests(unittest.IsolatedAsyncioTestCase):
    """Persisting the choice. Enforcement is worthless if the dropdown never saves."""

    async def _update(self, value: str) -> SimpleNamespace:
        from app.api.workflows import update_workflow
        from app.models.schemas import WorkflowUpdate

        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="wf",
            nodes=[],
            edges=[],
            http_method="POST",
            sse_node_config=None,
            updated_at=None,
            auth_type=None,
            auth_header_key=None,
            auth_header_value=None,
            webhook_body_mode=None,
            description=None,
            folder_id=None,
            cache_ttl_seconds=None,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            sse_enabled=False,
            auto_recover_runs=True,
            error_workflow_id=None,
            minutes_saved_per_run=None,
            workflow_timeout_seconds=None,
            kind="workflow",
            portal_enabled=False,
            portal_slug=None,
            mcp_enabled=False,
            owner_id_=None,
        )
        db = AsyncMock()
        current_user = SimpleNamespace(id=workflow.owner_id)

        with (
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.workflows.publish_event", AsyncMock()),
            patch("app.api.workflows._build_workflow_response", lambda wf, uid: wf),
        ):
            await update_workflow(
                workflow_id=workflow.id,
                workflow_data=WorkflowUpdate(http_method=value),
                current_user=current_user,
                db=db,
            )
        return workflow

    async def test_a_valid_method_is_persisted(self) -> None:
        workflow = await self._update("GET")
        self.assertEqual(workflow.http_method, "GET")

    async def test_lowercase_is_normalised(self) -> None:
        workflow = await self._update("delete")
        self.assertEqual(workflow.http_method, "DELETE")

    async def test_an_unsupported_verb_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._update("PATCH")
        self.assertEqual(ctx.exception.status_code, 400)


class ExecuteRouteMethodsTests(unittest.TestCase):
    """The tests above call the endpoint directly, so they never touch the router.

    Without this case, opening the route to four verbs could be forgotten entirely and every
    enforcement test would still pass.
    """

    def _methods_for(self, path_suffix: str) -> set[str]:
        from app.api.workflows import router

        for route in router.routes:
            if getattr(route, "path", "") == path_suffix:
                return {m for m in route.methods if m not in ("HEAD", "OPTIONS")}
        raise AssertionError(f"route {path_suffix} not registered")

    def test_execute_accepts_all_four_verbs(self) -> None:
        self.assertEqual(
            self._methods_for("/{workflow_id}/execute"),
            {"GET", "POST", "PUT", "DELETE"},
        )

    def test_execute_stream_accepts_all_four_verbs(self) -> None:
        self.assertEqual(
            self._methods_for("/{workflow_id}/execute/stream"),
            {"GET", "POST", "PUT", "DELETE"},
        )


if __name__ == "__main__":
    unittest.main()
