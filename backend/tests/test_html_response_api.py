"""Deciding when a workflow run answers with text/html instead of JSON."""

import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Request

from app.api.workflows import execute_workflow_endpoint
from app.services.html_response import build_html_response, find_sole_html_terminal
from app.services.workflow_executor import ExecutionResult


def _html_node(node_id: str = "html1") -> dict:
    return {"id": node_id, "type": "htmlOutputMapper", "data": {"label": "page"}}


class FindSoleHtmlTerminalTests(unittest.TestCase):
    def test_finds_the_only_terminal(self) -> None:
        nodes = [{"id": "in1", "type": "textInput", "data": {}}, _html_node()]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertEqual(find_sole_html_terminal(nodes, edges), "html1")

    def test_none_when_there_is_no_html_node(self) -> None:
        nodes = [{"id": "in1", "type": "textInput", "data": {}}]
        self.assertIsNone(find_sole_html_terminal(nodes, []))

    def test_none_when_a_second_terminal_exists(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            _html_node(),
            {"id": "out1", "type": "output", "data": {"label": "out"}},
        ]
        edges = [{"source": "in1", "target": "html1"}, {"source": "in1", "target": "out1"}]
        self.assertIsNone(find_sole_html_terminal(nodes, edges))

    def test_none_when_the_html_node_is_deactivated(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            {"id": "html1", "type": "htmlOutputMapper", "data": {"active": False}},
        ]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertIsNone(find_sole_html_terminal(nodes, edges))

    def test_sticky_notes_do_not_count_as_a_second_terminal(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            _html_node(),
            {"id": "note", "type": "sticky", "data": {}},
        ]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertEqual(find_sole_html_terminal(nodes, edges), "html1")

    def test_error_handlers_do_not_count_as_a_second_terminal(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            _html_node(),
            {"id": "err", "type": "errorHandler", "data": {}},
        ]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertEqual(find_sole_html_terminal(nodes, edges), "html1")


class BuildHtmlResponseTests(unittest.TestCase):
    def test_builds_a_response_from_the_node_result(self) -> None:
        node_results = [
            {
                "node_id": "html1",
                "node_type": "htmlOutputMapper",
                "status": "success",
                "output": {
                    "html": "<h1>hi</h1>",
                    "statusCode": 201,
                    "contentType": "text/html; charset=utf-8",
                },
            }
        ]
        response = build_html_response(node_results, "html1")
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.body, b"<h1>hi</h1>")
        self.assertEqual(response.headers["content-type"], "text/html; charset=utf-8")

    def test_none_when_the_node_did_not_run(self) -> None:
        self.assertIsNone(build_html_response([], "html1"))

    def test_none_when_the_node_errored(self) -> None:
        node_results = [
            {
                "node_id": "html1",
                "node_type": "htmlOutputMapper",
                "status": "error",
                "output": {},
            }
        ]
        self.assertIsNone(build_html_response(node_results, "html1"))

    def test_none_when_the_output_is_not_the_expected_shape(self) -> None:
        node_results = [
            {
                "node_id": "html1",
                "node_type": "htmlOutputMapper",
                "status": "success",
                "output": "x",
            }
        ]
        self.assertIsNone(build_html_response(node_results, "html1"))


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def make_request(
    *,
    method: str = "POST",
    body: bytes = b"",
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": method,
        "path": "/api/workflows/test/execute",
        "headers": headers or [],
        "query_string": query_string,
    }
    return Request(scope, receive)


HTML_NODE = {
    "id": "html1",
    "type": "htmlOutputMapper",
    "data": {"label": "page", "html": "<h1>Hello Ada</h1>"},
}
INPUT_NODE = {
    "id": "in1",
    "type": "textInput",
    "data": {"label": "userInput", "inputFields": [{"key": "name"}]},
}


class ExecuteReturnsHtmlTests(unittest.IsolatedAsyncioTestCase):
    """The route-level contract: sole html terminal + simple response == text/html."""

    OUTPUT = {
        "html": "<h1>Hello Ada</h1>",
        "statusCode": 200,
        "contentType": "text/html; charset=utf-8",
    }
    EDGES = [{"id": "e1", "source": "in1", "target": "html1"}]

    def _workflow(self, nodes: list[dict], edges: list[dict]) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_enabled=False,
            http_method="POST",
            name="Page Workflow",
        )

    def _result(self, workflow_id: uuid.UUID, node_output: dict) -> ExecutionResult:
        return ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"page": node_output},
            node_results=[
                {
                    "node_id": "html1",
                    "node_label": "page",
                    "node_type": "htmlOutputMapper",
                    "status": "success",
                    "output": node_output,
                    "execution_time_ms": 1.0,
                    "error": None,
                }
            ],
            execution_time_ms=10.0,
        )

    async def _call(
        self,
        *,
        nodes: list[dict],
        edges: list[dict],
        node_output: dict,
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> object:
        workflow = self._workflow(nodes, edges)
        execution_result = self._result(workflow.id, node_output)
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
                request=make_request(body=b"{}", headers=headers),
                current_user=None,
                db=db,
            )

    async def test_sole_html_terminal_returns_text_html(self) -> None:
        response = await self._call(
            nodes=[INPUT_NODE, HTML_NODE], edges=self.EDGES, node_output=self.OUTPUT
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertEqual(response.body, b"<h1>Hello Ada</h1>")

    async def test_simple_response_false_still_returns_the_json_envelope(self) -> None:
        response = await self._call(
            nodes=[INPUT_NODE, HTML_NODE],
            edges=self.EDGES,
            node_output=self.OUTPUT,
            headers=[(b"x-simple-response", b"false")],
        )
        # The non-simple path returns the pydantic model, not a Response.
        self.assertTrue(hasattr(response, "node_results"))

    async def test_a_second_terminal_keeps_json(self) -> None:
        nodes = [
            INPUT_NODE,
            HTML_NODE,
            {"id": "out1", "type": "output", "data": {"label": "out", "message": "done"}},
        ]
        edges = [*self.EDGES, {"id": "e2", "source": "in1", "target": "out1"}]
        response = await self._call(nodes=nodes, edges=edges, node_output=self.OUTPUT)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))

    async def test_configured_status_code_reaches_the_response(self) -> None:
        output = {
            "html": "<p>nope</p>",
            "statusCode": 404,
            "contentType": "text/html; charset=utf-8",
        }
        response = await self._call(
            nodes=[INPUT_NODE, HTML_NODE], edges=self.EDGES, node_output=output
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.body, b"<p>nope</p>")


if __name__ == "__main__":
    unittest.main()
