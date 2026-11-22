"""`test_run` is the editor's own test run, not a switch any caller can flip.

A test run skips the rate limit, the response cache and the HTTP method check, and uses pinned
node outputs in place of live ones. Both execute endpoints grant it only to a signed-in session
that can open the workflow; from anyone else the request runs as a production call.
"""

import json
import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request

from app.api.workflows import (
    execute_workflow_endpoint,
    execute_workflow_stream,
    persist_stream_execution_result,
)
from app.db.models import WorkflowAuthType
from app.services.workflow_executor import ExecutionResult, execute_workflow


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _request(
    *,
    method: str = "POST",
    query: bytes = b"",
    body: dict | None = None,
    path: str = "/api/workflows/x/execute",
) -> Request:
    payload = json.dumps(body).encode() if body is not None else b""

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "https",
            "server": ("heym.example", 443),
            "path": path,
            "headers": [(b"host", b"heym.example"), (b"content-type", b"application/json")],
            "query_string": query,
        },
        receive,
    )


def _workflow(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "owner_id": uuid.uuid4(),
        "name": "Public form",
        "nodes": [{"id": "o", "type": "output", "data": {"label": "out", "message": "ok"}}],
        "edges": [],
        "rate_limit_requests": None,
        "rate_limit_window_seconds": None,
        "cache_ttl_seconds": None,
        "sse_enabled": True,
        "sse_node_config": {},
        "http_method": "POST",
        "auth_type": WorkflowAuthType.anonymous,
        "auth_header_key": None,
        "concurrency_limit": None,
        "workflow_timeout_seconds": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _success() -> ExecutionResult:
    return ExecutionResult(
        workflow_id=uuid.uuid4(),
        status="success",
        outputs={"out": {"result": "ok"}},
        node_results=[],
        execution_time_ms=1.0,
    )


EDITOR = SimpleNamespace(id=uuid.uuid4(), email="editor@example.com")


class ExecuteEndpointTestRunTests(unittest.IsolatedAsyncioTestCase):
    async def _call(
        self,
        workflow: SimpleNamespace,
        *,
        request: Request,
        session_user: SimpleNamespace | None,
        has_access: bool = True,
        allowed: bool = True,
        cached: bool = False,
    ) -> tuple[object, AsyncMock, MagicMock, MagicMock, MagicMock]:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        db.add = MagicMock()
        dispatch = AsyncMock(return_value=_success())
        history = MagicMock(side_effect=lambda **kw: SimpleNamespace(**{"id": uuid.uuid4(), **kw}))
        limiter = MagicMock()
        limiter.is_allowed = MagicMock(return_value=(allowed, 0, 60))
        cache = MagicMock()
        cache.get = AsyncMock(return_value=(cached, {"outputs": {"out": {"result": "cached"}}}))
        cache.set = AsyncMock()
        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock(return_value=session_user)),
            patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=has_access)),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.workflows.dispatch_workflow", dispatch),
            patch("app.api.workflows.ExecutionHistory", history),
            patch("app.api.workflows.rate_limiter", limiter),
            patch("app.api.workflows.response_cache", cache),
        ):
            response = await execute_workflow_endpoint(
                workflow_id=workflow.id,
                request=request,
                current_user=session_user,
                db=db,
            )
        return response, dispatch, history, limiter, cache

    async def test_an_outside_test_run_executes_as_production(self) -> None:
        _, dispatch, history, _, _ = await self._call(
            _workflow(), request=_request(query=b"test_run=true"), session_user=None
        )
        self.assertFalse(dispatch.await_args.kwargs["test_run"])
        self.assertFalse(dispatch.await_args.kwargs["concurrency_exempt"])
        self.assertEqual(history.call_args.kwargs["status"], "success")

    async def test_a_wrapped_body_test_run_from_outside_is_ignored(self) -> None:
        request = _request(body={"inputs": {"text": "x"}, "test_run": True})
        _, dispatch, history, _, _ = await self._call(
            _workflow(), request=request, session_user=None
        )
        self.assertFalse(dispatch.await_args.kwargs["test_run"])
        history.assert_called_once()

    async def test_a_signed_in_user_without_access_gets_production(self) -> None:
        _, dispatch, history, _, _ = await self._call(
            _workflow(),
            request=_request(query=b"test_run=true"),
            session_user=SimpleNamespace(id=uuid.uuid4(), email="stranger@example.com"),
            has_access=False,
        )
        self.assertFalse(dispatch.await_args.kwargs["test_run"])
        history.assert_called_once()

    async def test_the_editor_keeps_its_test_run(self) -> None:
        _, dispatch, history, limiter, cache = await self._call(
            _workflow(rate_limit_requests=1, rate_limit_window_seconds=60, cache_ttl_seconds=60),
            request=_request(query=b"test_run=true"),
            session_user=EDITOR,
            allowed=False,
            cached=True,
        )
        self.assertTrue(dispatch.await_args.kwargs["test_run"])
        self.assertTrue(dispatch.await_args.kwargs["concurrency_exempt"])
        limiter.is_allowed.assert_not_called()
        cache.get.assert_not_awaited()
        history.assert_not_called()

    async def test_an_outside_test_run_is_rate_limited(self) -> None:
        workflow = _workflow(rate_limit_requests=1, rate_limit_window_seconds=60)
        with self.assertRaises(HTTPException) as ctx:
            await self._call(
                workflow,
                request=_request(query=b"test_run=true"),
                session_user=None,
                allowed=False,
            )
        self.assertEqual(ctx.exception.status_code, 429)

    async def test_an_outside_test_run_reads_the_cache(self) -> None:
        response, dispatch, _, _, _ = await self._call(
            _workflow(cache_ttl_seconds=60),
            request=_request(query=b"test_run=true"),
            session_user=None,
            cached=True,
        )
        self.assertEqual(json.loads(response.body), {"out": {"result": "cached"}})
        dispatch.assert_not_awaited()

    async def test_an_outside_test_run_is_held_to_the_http_method(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._call(
                _workflow(http_method="GET"),
                request=_request(query=b"test_run=true"),
                session_user=None,
            )
        self.assertEqual(ctx.exception.status_code, 405)

    async def test_the_editor_test_run_does_not_write_the_cache(self) -> None:
        _, _, _, _, cache = await self._call(
            _workflow(cache_ttl_seconds=60),
            request=_request(body={"inputs": {"text": "x"}, "test_run": True}),
            session_user=EDITOR,
        )
        cache.set.assert_not_awaited()

    async def test_a_production_run_still_writes_the_cache(self) -> None:
        _, _, _, _, cache = await self._call(
            _workflow(cache_ttl_seconds=60), request=_request(), session_user=None
        )
        cache.set.assert_awaited_once()


class StreamEndpointTestRunTests(unittest.IsolatedAsyncioTestCase):
    """The checks run before the stream opens, so an empty graph stops a run that passed them."""

    async def _call(
        self,
        workflow: SimpleNamespace,
        *,
        query: bytes,
        session_user: SimpleNamespace | None,
        has_access: bool = True,
    ) -> MagicMock:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        db.add = MagicMock()
        limiter = MagicMock()
        limiter.is_allowed = MagicMock(return_value=(False, 0, 60))
        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock(return_value=session_user)),
            patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=has_access)),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows.ExecutionHistory", MagicMock()),
            patch("app.api.workflows.rate_limiter", limiter),
        ):
            await execute_workflow_stream(
                workflow_id=workflow.id,
                request=_request(query=query, path="/api/workflows/x/execute/stream"),
                current_user=session_user,
                db=db,
                run_until_node_id=None,
            )
        return limiter

    async def test_an_outside_test_run_is_rate_limited(self) -> None:
        workflow = _workflow(nodes=[], rate_limit_requests=1, rate_limit_window_seconds=60)
        with self.assertRaises(HTTPException) as ctx:
            await self._call(workflow, query=b"test_run=true", session_user=None)
        self.assertEqual(ctx.exception.status_code, 429)

    async def test_a_signed_in_user_without_access_is_rate_limited(self) -> None:
        workflow = _workflow(nodes=[], rate_limit_requests=1, rate_limit_window_seconds=60)
        stranger = SimpleNamespace(id=uuid.uuid4(), email="stranger@example.com")
        with self.assertRaises(HTTPException) as ctx:
            await self._call(
                workflow, query=b"test_run=true", session_user=stranger, has_access=False
            )
        self.assertEqual(ctx.exception.status_code, 429)

    async def test_the_editor_skips_the_rate_limit(self) -> None:
        workflow = _workflow(nodes=[], rate_limit_requests=1, rate_limit_window_seconds=60)
        with self.assertRaises(HTTPException) as ctx:
            await self._call(workflow, query=b"test_run=true", session_user=EDITOR)
        self.assertEqual(ctx.exception.detail, "Workflow has no nodes")

    async def test_an_outside_test_run_is_held_to_the_http_method(self) -> None:
        workflow = _workflow(nodes=[], http_method="GET")
        with self.assertRaises(HTTPException) as ctx:
            await self._call(workflow, query=b"test_run=true", session_user=None)
        self.assertEqual(ctx.exception.status_code, 405)

    async def test_the_editor_skips_the_http_method(self) -> None:
        workflow = _workflow(nodes=[], http_method="GET")
        with self.assertRaises(HTTPException) as ctx:
            await self._call(workflow, query=b"test_run=true", session_user=EDITOR)
        self.assertEqual(ctx.exception.detail, "Workflow has no nodes")


class StreamPersistenceCacheTests(unittest.IsolatedAsyncioTestCase):
    async def _persist(self, *, test_run: bool) -> AsyncMock:
        db = AsyncMock()
        db.add = MagicMock()
        cache = MagicMock()
        cache.set = AsyncMock()
        workflow = _workflow(cache_ttl_seconds=60)
        with (
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.workflows.response_cache", cache),
        ):
            await persist_stream_execution_result(
                db,
                workflow=workflow,
                execution_id=uuid.uuid4(),
                enriched_inputs={"body": {}},
                trigger_source="Canvas",
                raw_body={},
                query_params={},
                workflow_cache={},
                credentials_owner_id=uuid.uuid4(),
                final_result={"status": "success", "outputs": {"out": 1}, "node_results": []},
                was_cancelled=False,
                test_run=test_run,
            )
        return cache.set

    async def test_a_test_run_does_not_write_the_cache(self) -> None:
        (await self._persist(test_run=True)).assert_not_awaited()

    async def test_a_production_run_writes_the_cache(self) -> None:
        (await self._persist(test_run=False)).assert_awaited_once()


class PinnedOutputsTests(unittest.TestCase):
    """Why the flag matters: a test run returns what the editor pinned, not a live result."""

    NODES = [
        {
            "id": "in_1",
            "type": "textInput",
            "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "s",
            "type": "set",
            "data": {
                "label": "lookup",
                "mappings": [{"key": "customer", "value": "$userInput.body.text"}],
                "pinnedData": {"customer": "pinned sample from an earlier run"},
            },
        },
        {"id": "o", "type": "output", "data": {"label": "out", "message": "$lookup.customer"}},
    ]
    EDGES = [
        {"id": "e1", "source": "in_1", "target": "s"},
        {"id": "e2", "source": "s", "target": "o"},
    ]

    def _run(self, *, test_run: bool) -> object:
        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=self.NODES,
            edges=self.EDGES,
            inputs={"headers": {}, "query": {}, "body": {"text": "live input"}},
            test_run=test_run,
        )
        return result.outputs["out"]["result"]

    def test_a_production_run_ignores_pinned_outputs(self) -> None:
        self.assertEqual(self._run(test_run=False), "live input")

    def test_a_test_run_uses_pinned_outputs(self) -> None:
        self.assertEqual(self._run(test_run=True), "pinned sample from an earlier run")


if __name__ == "__main__":
    unittest.main()
