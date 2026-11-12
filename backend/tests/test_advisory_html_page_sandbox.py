"""HTML page workflows must not run with the visitor's session (GHSA-hhvf-v27f-g7c7).

A workflow whose sole terminal is an htmlOutputMapper answers ``/execute`` with the
author's document on the instance's own origin. Without a sandbox the page's script
could call the Heym API as whoever opened the link. Every page response therefore
carries ``Content-Security-Policy: sandbox ...`` (without ``allow-same-origin``) and
``X-Content-Type-Options: nosniff``, whatever content type the node sets.
"""

import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Request

from app.api.workflows import execute_workflow_endpoint
from app.services.html_response import (
    PAGE_CONTENT_SECURITY_POLICY,
    PAGE_SECURITY_HEADERS,
    build_html_response,
)
from app.services.workflow_executor import ExecutionResult

_INPUT_NODE = {
    "id": "in1",
    "type": "textInput",
    "data": {"label": "userInput", "inputFields": [{"key": "name"}]},
}
_HTML_NODE = {"id": "html1", "type": "htmlOutputMapper", "data": {"label": "page"}}
_EDGES = [{"id": "e1", "source": "in1", "target": "html1"}]
_SCRIPT_PAGE = "<script>fetch('/api/auth/me')</script>"
_SVG_PAGE = '<svg xmlns="http://www.w3.org/2000/svg"><script>fetch("/api/auth/me")</script></svg>'


def _node_results(output: dict) -> list[dict]:
    return [
        {
            "node_id": "html1",
            "node_label": "page",
            "node_type": "htmlOutputMapper",
            "status": "success",
            "output": output,
            "execution_time_ms": 1.0,
            "error": None,
        }
    ]


def _assert_sandboxed(test: unittest.TestCase, response: object) -> None:
    headers = response.headers  # type: ignore[attr-defined]
    csp = headers.get("content-security-policy")
    test.assertIsNotNone(csp, "page response has no Content-Security-Policy")
    assert csp is not None
    directives = [part.strip() for part in csp.split(";")]
    sandbox = next((d for d in directives if d.split(" ")[0] == "sandbox"), None)
    test.assertIsNotNone(sandbox, f"no sandbox directive in {csp!r}")
    assert sandbox is not None
    test.assertNotIn("allow-same-origin", sandbox.split())
    test.assertEqual(headers.get("x-content-type-options"), "nosniff")


class PageSecurityHeadersTests(unittest.TestCase):
    def test_policy_sandboxes_without_same_origin(self) -> None:
        tokens = PAGE_CONTENT_SECURITY_POLICY.split()
        self.assertEqual(tokens[0], "sandbox")
        self.assertIn("allow-scripts", tokens)
        self.assertNotIn("allow-same-origin", tokens)

    def test_headers_cover_csp_and_nosniff(self) -> None:
        self.assertEqual(
            PAGE_SECURITY_HEADERS["Content-Security-Policy"], PAGE_CONTENT_SECURITY_POLICY
        )
        self.assertEqual(PAGE_SECURITY_HEADERS["X-Content-Type-Options"], "nosniff")

    def test_builder_sends_the_headers_for_html(self) -> None:
        response = build_html_response(
            _node_results({"html": _SCRIPT_PAGE, "contentType": "text/html; charset=utf-8"}),
            "html1",
        )
        self.assertIsNotNone(response)
        _assert_sandboxed(self, response)

    def test_builder_sends_the_headers_for_svg(self) -> None:
        response = build_html_response(
            _node_results({"html": _SVG_PAGE, "contentType": "image/svg+xml"}), "html1"
        )
        self.assertIsNotNone(response)
        assert response is not None
        self.assertTrue(response.headers["content-type"].startswith("image/svg+xml"))
        _assert_sandboxed(self, response)

    def test_builder_sends_the_headers_for_any_content_type(self) -> None:
        for content_type in ("text/plain", "application/xhtml+xml", "text/xml", "x/unknown"):
            with self.subTest(content_type=content_type):
                response = build_html_response(
                    _node_results({"html": _SCRIPT_PAGE, "contentType": content_type}), "html1"
                )
                _assert_sandboxed(self, response)

    def test_builder_does_not_share_one_header_dict(self) -> None:
        output = {"html": _SCRIPT_PAGE, "contentType": "text/html; charset=utf-8"}
        first = build_html_response(_node_results(output), "html1")
        assert first is not None
        first.headers["x-extra"] = "1"
        self.assertNotIn("x-extra", PAGE_SECURITY_HEADERS)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _make_request(method: str) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"" if method == "GET" else b"{}"}

    scope = {
        "type": "http",
        "method": method,
        "path": "/api/workflows/test/execute",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope, receive)


class ExecuteEndpointPageSandboxTests(unittest.IsolatedAsyncioTestCase):
    """The headers reach the client through the execute endpoint itself."""

    async def _execute(self, output: dict, *, method: str = "POST") -> object:
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[_INPUT_NODE, _HTML_NODE],
            edges=_EDGES,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_enabled=False,
            http_method=method,
            name="Page Workflow",
        )
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={"page": output},
            node_results=_node_results(output),
            execution_time_ms=10.0,
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
                request=_make_request(method),
                current_user=None,
                db=db,
            )

    async def test_html_page_is_sandboxed(self) -> None:
        response = await self._execute(
            {"html": _SCRIPT_PAGE, "statusCode": 200, "contentType": "text/html; charset=utf-8"}
        )
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        _assert_sandboxed(self, response)

    async def test_svg_page_is_sandboxed(self) -> None:
        response = await self._execute(
            {"html": _SVG_PAGE, "statusCode": 200, "contentType": "image/svg+xml"}
        )
        self.assertTrue(response.headers["content-type"].startswith("image/svg+xml"))
        _assert_sandboxed(self, response)

    async def test_page_served_to_a_get_request_is_sandboxed(self) -> None:
        response = await self._execute(
            {"html": _SCRIPT_PAGE, "statusCode": 200, "contentType": "text/html; charset=utf-8"},
            method="GET",
        )
        _assert_sandboxed(self, response)

    async def test_custom_status_page_is_sandboxed(self) -> None:
        response = await self._execute(
            {"html": "<p>nope</p>", "statusCode": 404, "contentType": "text/html; charset=utf-8"}
        )
        self.assertEqual(response.status_code, 404)
        _assert_sandboxed(self, response)


if __name__ == "__main__":
    unittest.main()
