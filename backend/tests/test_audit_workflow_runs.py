"""Workflow runs started through the API reach the audit trail with who, how and the result."""

import ast
import asyncio
import contextlib
import logging
import pathlib
import unittest
import uuid
from collections.abc import Iterator
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request

from app.api import workflows as workflows_api
from app.api.workflow_run_audit import RunActor, audit_workflow_run
from app.api.workflows import (
    execute_workflow_endpoint,
    execute_workflow_stream,
    get_execution_history,
)
from app.services.workflow_executor import ExecutionResult, WorkflowCancelledError

API_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "api"
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _user() -> MagicMock:
    user = MagicMock()
    user.id = USER_ID
    user.email = "burak@example.com"
    return user


def _workflow(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "owner_id": uuid.uuid4(),
        "name": "Invoice triage",
        "nodes": [{"id": "n1", "type": "output"}],
        "edges": [],
        "rate_limit_requests": None,
        "rate_limit_window_seconds": None,
        "cache_ttl_seconds": None,
        "sse_enabled": True,
        "sse_node_config": {},
        "workflow_timeout_seconds": None,
        "concurrency_limit": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _request(query_string: bytes = b"") -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/workflows/test/execute",
        "headers": [],
        "query_string": query_string,
    }
    return Request(scope, receive)


@contextlib.contextmanager
def collect_audit_lines() -> Iterator[list[str]]:
    """Gather every audit line, including none at all (``assertLogs`` insists on one)."""
    lines: list[str] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(record.getMessage())

    handler = _Handler(level=logging.INFO)
    logger = logging.getLogger("winston.audit")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield lines
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _db_for(workflow: SimpleNamespace) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(workflow))
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _execute_patches(dispatch: AsyncMock) -> list:
    return [
        patch("app.api.workflows.validate_workflow_auth", AsyncMock(side_effect=_passthrough)),
        patch("app.api.workflows.enforce_workflow_http_method"),
        patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=True)),
        patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
        patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
        patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
        patch("app.api.workflows.register_execution", return_value=Event()),
        patch("app.api.workflows.clear_active_execution"),
        patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
        patch("app.api.workflows._persist_global_variables_from_execution", AsyncMock()),
        patch("app.api.workflows.dispatch_workflow", dispatch),
    ]


async def _passthrough(_workflow: object, _request: object, user: object, _db: object) -> object:
    return user


def _result(workflow: SimpleNamespace, status: str, execution_time_ms: float) -> ExecutionResult:
    return ExecutionResult(
        workflow_id=workflow.id,
        status=status,
        outputs={"ok": status == "success"},
        execution_time_ms=execution_time_ms,
        node_results=[],
        sub_workflow_executions=[],
    )


class WorkflowRunLineTests(unittest.TestCase):
    def test_line_says_who_ran_what_how_and_with_what_result(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()

        with self.assertLogs("winston.audit", level="INFO") as captured:
            audit_workflow_run(
                workflow_id=workflow_id,
                workflow_name="Invoice triage",
                status="success",
                execution_time_ms=1234.6,
                trigger_source="Canvas",
                execution_id=execution_id,
                actor=RunActor.of(_user()),
                test_run=True,
            )

        line = captured.records[0].getMessage()
        self.assertIn("action=workflow.run", line)
        self.assertIn("outcome=success", line)
        self.assertIn(f"actor_id={USER_ID}", line)
        self.assertIn("actor_email=burak@example.com", line)
        self.assertIn(f"target=workflow:{workflow_id}", line)
        self.assertIn('target_name="Invoice triage"', line)
        self.assertIn("status=success", line)
        self.assertIn("trigger_source=Canvas", line)
        self.assertIn(f"execution_id={execution_id}", line)
        self.assertIn("duration_ms=1235", line)
        self.assertIn("test_run=true", line)

    def test_caller_without_a_user_carries_no_identity(self) -> None:
        with self.assertLogs("winston.audit", level="INFO") as captured:
            audit_workflow_run(
                workflow_id=uuid.uuid4(),
                workflow_name="Webhook",
                status="success",
                execution_time_ms=1,
                trigger_source="API",
            )

        line = captured.records[0].getMessage()
        self.assertNotIn("actor_id=", line)
        self.assertNotIn("actor_email=", line)

    def test_only_runs_that_did_not_finish_well_are_failures(self) -> None:
        expected = {
            "success": "success",
            "pending": "success",
            "queued": "success",
            "error": "failure",
            "cancelled": "failure",
            "timeout": "failure",
        }
        for status, outcome in expected.items():
            with self.subTest(status=status):
                with self.assertLogs("winston.audit", level="INFO") as captured:
                    audit_workflow_run(
                        workflow_id=uuid.uuid4(),
                        workflow_name="w",
                        status=status,
                        execution_time_ms=None,
                        trigger_source="API",
                    )
                line = captured.records[0].getMessage()
                self.assertIn(f"outcome={outcome}", line)
                self.assertNotIn("duration_ms=", line)

    def test_actor_is_a_copy_that_survives_the_user_row(self) -> None:
        user = _user()
        actor = RunActor.of(user)
        user.id = None
        user.email = None

        self.assertEqual((actor.id, actor.email), (USER_ID, "burak@example.com"))


class ExecuteEndpointAuditTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self, dispatch: AsyncMock, workflow: SimpleNamespace, user: object, query: bytes = b""
    ) -> list[str]:
        patches = _execute_patches(dispatch)
        for item in patches:
            item.start()
        self.addCleanup(patch.stopall)
        with self.assertLogs("winston.audit", level="INFO") as captured:
            try:
                await execute_workflow_endpoint(
                    workflow_id=workflow.id,
                    request=_request(query),
                    background_tasks=None,
                    current_user=user,
                    db=_db_for(workflow),
                )
            except HTTPException:
                pass
        return [record.getMessage() for record in captured.records]

    async def test_a_finished_run_is_audited_with_actor_and_result(self) -> None:
        workflow = _workflow()
        dispatch = AsyncMock(return_value=_result(workflow, "success", 42.0))

        lines = await self._run(dispatch, workflow, _user(), b"trigger_source=API")

        self.assertEqual(len(lines), 1)
        self.assertIn("action=workflow.run", lines[0])
        self.assertIn("outcome=success", lines[0])
        self.assertIn("actor_email=burak@example.com", lines[0])
        self.assertIn("status=success", lines[0])
        self.assertIn("trigger_source=API", lines[0])
        self.assertIn("test_run=false", lines[0])
        self.assertIn(f"target=workflow:{workflow.id}", lines[0])

    async def test_a_failed_run_is_a_failure_line(self) -> None:
        workflow = _workflow()
        dispatch = AsyncMock(return_value=_result(workflow, "error", 7.0))

        lines = await self._run(dispatch, workflow, _user())

        self.assertEqual(len(lines), 1)
        self.assertIn("outcome=failure", lines[0])
        self.assertIn("status=error", lines[0])

    async def test_an_editor_test_run_is_marked(self) -> None:
        workflow = _workflow()
        dispatch = AsyncMock(return_value=_result(workflow, "success", 3.0))

        lines = await self._run(dispatch, workflow, _user(), b"test_run=true")

        self.assertIn("test_run=true", lines[0])

    async def test_an_anonymous_webhook_call_is_audited_without_an_actor(self) -> None:
        workflow = _workflow()
        dispatch = AsyncMock(return_value=_result(workflow, "success", 3.0))

        lines = await self._run(dispatch, workflow, None)

        self.assertEqual(len(lines), 1)
        self.assertNotIn("actor_id=", lines[0])

    async def test_a_cancelled_run_is_audited_before_the_409(self) -> None:
        workflow = _workflow()
        dispatch = AsyncMock(side_effect=WorkflowCancelledError())

        lines = await self._run(dispatch, workflow, _user())

        self.assertEqual(len(lines), 1)
        self.assertIn("outcome=failure", lines[0])
        self.assertIn("status=cancelled", lines[0])

    async def test_the_request_body_never_reaches_the_line(self) -> None:
        workflow = _workflow()
        dispatch = AsyncMock(return_value=_result(workflow, "success", 3.0))

        lines = await self._run(dispatch, workflow, _user(), b"api_key=hunter2&note=private")

        self.assertNotIn("hunter2", lines[0])
        self.assertNotIn("private", lines[0])


class StreamEndpointAuditTests(unittest.IsolatedAsyncioTestCase):
    async def _stream(self, final_status: str, user: object, query: bytes) -> list[str]:
        workflow = _workflow()

        def fake_streaming_executor(**_kwargs: object):
            yield {
                "type": "execution_complete",
                "workflow_id": str(workflow.id),
                "status": final_status,
                "outputs": {},
                "node_results": [],
                "sub_workflow_executions": [],
                "execution_time_ms": 12.4,
            }

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.get = AsyncMock(return_value=workflow)
        session.commit = AsyncMock()

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock(side_effect=_passthrough)),
            patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=True)),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.complete_active_execution"),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.execute_workflow_streaming", fake_streaming_executor),
            patch("app.api.workflows.async_session_maker", return_value=session),
            patch(
                "app.api.workflows.persist_stream_execution_result", AsyncMock(return_value=False)
            ),
            self.assertLogs("winston.audit", level="INFO") as captured,
        ):
            response = await execute_workflow_stream(
                workflow_id=workflow.id,
                request=_request(query),
                current_user=user,
                db=_db_for(workflow),
            )
            async for _chunk in response.body_iterator:
                pass
            await asyncio.gather(*list(workflows_api._DETACHED_TASKS))

        return [record.getMessage() for record in captured.records]

    async def test_a_streamed_run_is_audited_once_it_ends(self) -> None:
        lines = await self._stream("success", _user(), b"test_run=true&trigger_source=Canvas")

        self.assertEqual(len(lines), 1)
        self.assertIn("action=workflow.run", lines[0])
        self.assertIn("actor_email=burak@example.com", lines[0])
        self.assertIn("status=success", lines[0])
        self.assertIn("trigger_source=Canvas", lines[0])
        self.assertIn("duration_ms=12", lines[0])
        self.assertIn("test_run=true", lines[0])

    async def test_a_streamed_failure_is_a_failure_line(self) -> None:
        lines = await self._stream("error", _user(), b"test_run=true")

        self.assertIn("outcome=failure", lines[0])
        self.assertIn("status=error", lines[0])


class HistoryViewAuditTests(unittest.IsolatedAsyncioTestCase):
    async def _list(self, *, latest_only: bool, search: str | None) -> tuple[list[str], list[str]]:
        workflow = _workflow()
        statements: list[str] = []

        async def fake_execute(statement: object) -> MagicMock:
            statements.append(
                str(statement.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[attr-defined]
            )
            result = MagicMock()
            result.scalar.return_value = 0
            result.scalars.return_value.all.return_value = []
            return result

        db = MagicMock()
        db.execute = fake_execute

        with (
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)),
            collect_audit_lines() as lines,
        ):
            await get_execution_history(
                workflow_id=workflow.id,
                current_user=_user(),
                db=db,
                limit=50,
                offset=10,
                search=search,
                trigger_source=None,
                instance_id=None,
                execution_status=None,
                latest_only=latest_only,
            )

        return lines, statements

    async def test_opening_the_history_view_is_audited(self) -> None:
        lines, _ = await self._list(latest_only=False, search=None)

        self.assertEqual(len(lines), 1)
        self.assertIn("action=workflow.history_view", lines[0])

    async def test_the_latest_run_lookup_is_not_a_history_view(self) -> None:
        lines, _ = await self._list(latest_only=True, search=None)

        self.assertEqual(lines, [])

    async def test_the_latest_run_lookup_cannot_search_run_contents(self) -> None:
        _, statements = await self._list(latest_only=True, search="needle")

        for sql in statements:
            self.assertNotIn("needle", sql)
        self.assertTrue(any("LIMIT 1" in sql for sql in statements))


class CallSiteCoverageTests(unittest.TestCase):
    """A router that starts a run for a caller keeps its audit call."""

    def test_every_api_entry_point_audits_its_runs(self) -> None:
        for module in ("workflows", "mcp", "mcp_servers", "portal"):
            with self.subTest(module=module):
                tree = ast.parse((API_DIR / f"{module}.py").read_text())
                calls = [
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "audit_workflow_run"
                ]
                self.assertTrue(calls, f"{module}.py no longer audits the runs it starts")

    def test_runs_are_audited_from_routers_only(self) -> None:
        """audit() writes to the stdout of the instance that ran it, so keep it off the run queue."""
        services = API_DIR.parent / "services"
        offenders = [
            str(path.relative_to(API_DIR.parent))
            for path in services.rglob("*.py")
            if path.name != "audit_log.py" and "audit_workflow_run" in path.read_text()
        ]

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
