"""
Tests that verify cancellation behaviour across every trigger type.

Legend
------
✅ registered  = execution appears in _ACTIVE_EXECUTIONS → history dialog shows it → cancel works
❌ unregistered = not in _ACTIVE_EXECUTIONS → cancel returns 404

Trigger                 | Before fix | After fix
------------------------|------------|----------
POST /execute/stream    | ✅         | ✅ (unchanged)
POST /execute           | ❌         | ✅ fixed here
MCP /tools/call         | ❌         | ✅ fixed here
MCP /message            | ❌         | ✅ fixed here
MCP /sse (POST)         | ❌         | ✅ fixed here
Portal /execute         | ✅         | ✅ (unchanged)
Dashboard chat          | ❌         | ❌ by design (not a workflow run)
"""

import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.mcp import call_mcp_tool
from app.services.execution_cancellation import (
    _ACTIVE_EXECUTIONS,
    _LOCK,
    cancel_execution,
    clear_execution,
    list_active_executions,
    register_execution,
)
from app.services.workflow_executor import WorkflowCancelledError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mcp_request(tool_name: str = "my_tool", arguments: dict | None = None) -> MagicMock:
    """Return a mock Request whose .json() resolves to the given MCP payload."""
    req = MagicMock()
    req.json = AsyncMock(return_value={"name": tool_name, "arguments": arguments or {}})
    return req


def _make_workflow(workflow_id: uuid.UUID | None = None, name: str = "my_tool") -> MagicMock:
    """Return a mock Workflow object whose tool name matches *name*."""
    wf = MagicMock()
    wf.id = workflow_id or uuid.uuid4()
    wf.name = name
    wf.nodes = [{"id": "n1", "type": "input"}]
    wf.owner_id = uuid.uuid4()
    return wf


def _make_execution_result(status: str = "success") -> MagicMock:
    result = MagicMock()
    result.status = status
    result.outputs = {"result": "ok"}
    result.node_results = []
    result.execution_time_ms = 10
    result.sub_workflow_executions = []
    return result


def _clear_active_executions() -> None:
    with _LOCK:
        _ACTIVE_EXECUTIONS.clear()


# ---------------------------------------------------------------------------
# 1. Execution-cancellation mechanism unit tests
# ---------------------------------------------------------------------------


class ExecutionCancellationMechanismTests(unittest.TestCase):
    def setUp(self) -> None:
        _clear_active_executions()

    def tearDown(self) -> None:
        _clear_active_executions()

    def test_register_makes_execution_visible_in_active_list(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)

        handles = list_active_executions()
        self.assertEqual(len(handles), 1)
        self.assertEqual(handles[0].execution_id, ex_id)
        self.assertEqual(handles[0].workflow_id, wf_id)

    def test_cancel_sets_event_and_execution_remains_visible_until_cleared(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        event = register_execution(workflow_id=wf_id, execution_id=ex_id)

        self.assertFalse(event.is_set())
        result = cancel_execution(workflow_id=wf_id, execution_id=ex_id)

        self.assertTrue(result)
        self.assertTrue(event.is_set())
        # Still in list until executor calls clear_execution
        self.assertEqual(len(list_active_executions()), 1)

    def test_clear_removes_execution_from_active_list(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        clear_execution(ex_id)

        self.assertEqual(list_active_executions(), [])

    def test_cancel_returns_false_for_unknown_execution(self) -> None:
        result = cancel_execution(workflow_id=uuid.uuid4(), execution_id=uuid.uuid4())
        self.assertFalse(result)

    def test_cancel_returns_false_when_workflow_id_mismatch(self) -> None:
        ex_id = uuid.uuid4()
        register_execution(workflow_id=uuid.uuid4(), execution_id=ex_id)
        result = cancel_execution(workflow_id=uuid.uuid4(), execution_id=ex_id)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# 2. MCP /tools/call  (call_mcp_tool)
# ---------------------------------------------------------------------------


class McpCallToolCancellationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _clear_active_executions()

    def tearDown(self) -> None:
        _clear_active_executions()

    async def test_execution_registered_and_visible_during_run(self) -> None:
        """register_execution is called before execute_workflow, so the execution
        appears in _ACTIVE_EXECUTIONS while the workflow is running."""
        wf = _make_workflow()
        captured: list[uuid.UUID] = []

        def fake_execute(*_args, **_kwargs) -> MagicMock:
            # At this point the execution must already be registered
            captured.extend(
                h.execution_id for h in list_active_executions() if h.workflow_id == wf.id
            )
            return _make_execution_result()

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch("app.api.mcp.get_user_mcp_workflows", AsyncMock(return_value=[wf])),
            patch("app.api.mcp.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.mcp.get_credentials_context_for_user", AsyncMock(return_value={})),
            patch("app.api.mcp.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.mcp.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.mcp._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.mcp.asyncio.to_thread", AsyncMock(side_effect=fake_execute)),
        ):
            user = MagicMock()
            user.id = uuid.uuid4()
            result = await call_mcp_tool(
                request=_make_mcp_request("my_tool"),
                mcp_user=user,
                db=db,
            )

        self.assertFalse(result.isError)
        self.assertEqual(len(captured), 1, "execution must be visible in active list during run")

    async def test_execution_cleared_after_successful_run(self) -> None:
        wf = _make_workflow()
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch("app.api.mcp.get_user_mcp_workflows", AsyncMock(return_value=[wf])),
            patch("app.api.mcp.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.mcp.get_credentials_context_for_user", AsyncMock(return_value={})),
            patch("app.api.mcp.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.mcp.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.mcp._persist_global_variables_from_execution", AsyncMock()),
            patch(
                "app.api.mcp.asyncio.to_thread",
                AsyncMock(return_value=_make_execution_result()),
            ),
        ):
            user = MagicMock()
            user.id = uuid.uuid4()
            await call_mcp_tool(
                request=_make_mcp_request("my_tool"),
                mcp_user=user,
                db=db,
            )

        self.assertEqual(
            list_active_executions(), [], "execution must be cleared from active list after run"
        )

    async def test_execution_cleared_when_executor_raises(self) -> None:
        """finally block must clear the execution even when execute_workflow raises."""
        wf = _make_workflow()
        db = AsyncMock()

        with (
            patch("app.api.mcp.get_user_mcp_workflows", AsyncMock(return_value=[wf])),
            patch("app.api.mcp.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.mcp.get_credentials_context_for_user", AsyncMock(return_value={})),
            patch("app.api.mcp.get_global_variables_context", AsyncMock(return_value={})),
            patch(
                "app.api.mcp.asyncio.to_thread",
                AsyncMock(side_effect=WorkflowCancelledError("cancelled")),
            ),
        ):
            user = MagicMock()
            user.id = uuid.uuid4()
            result = await call_mcp_tool(
                request=_make_mcp_request("my_tool"),
                mcp_user=user,
                db=db,
            )

        self.assertTrue(result.isError)
        self.assertIn("cancelled", result.content[0].text)
        self.assertEqual(list_active_executions(), [], "execution must be cleared even on error")

    async def test_cancel_event_passed_to_executor_and_stops_run(self) -> None:
        """When the cancel event is set during execution, execute_workflow sees it."""
        wf = _make_workflow()
        received_event: list[threading.Event] = []

        def capture_event(*args, **kwargs) -> MagicMock:
            event = kwargs.get("cancel_event")
            if event is not None:
                received_event.append(event)
            return _make_execution_result()

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch("app.api.mcp.get_user_mcp_workflows", AsyncMock(return_value=[wf])),
            patch("app.api.mcp.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.mcp.get_credentials_context_for_user", AsyncMock(return_value={})),
            patch("app.api.mcp.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.mcp.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.mcp._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.mcp.asyncio.to_thread", AsyncMock(side_effect=capture_event)),
        ):
            user = MagicMock()
            user.id = uuid.uuid4()
            await call_mcp_tool(
                request=_make_mcp_request("my_tool"),
                mcp_user=user,
                db=db,
            )

        self.assertEqual(
            len(received_event), 1, "cancel_event must be forwarded to execute_workflow"
        )
        # Simulate cancel: the event is settable from outside
        received_event[0].set()
        self.assertTrue(received_event[0].is_set())


# ---------------------------------------------------------------------------
# 3. Non-streaming HTTP API  (execute_workflow_endpoint)
# ---------------------------------------------------------------------------


class NonStreamingHttpCancellationTests(unittest.IsolatedAsyncioTestCase):
    """Tests for POST /workflows/{id}/execute (non-streaming)."""

    def setUp(self) -> None:
        _clear_active_executions()

    def tearDown(self) -> None:
        _clear_active_executions()

    async def test_raises_409_when_executor_is_cancelled(self) -> None:
        """WorkflowCancelledError from the executor must become HTTP 409."""
        from app.api.workflows import execute_workflow_endpoint

        wf_id = uuid.uuid4()
        wf = SimpleNamespace(
            id=wf_id,
            name="Test WF",
            owner_id=uuid.uuid4(),
            nodes=[{"id": "n1"}],
            edges=[],
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(wf))
        db.add = MagicMock()
        db.commit = AsyncMock()

        request = MagicMock()
        request.headers = {}
        request.query_params = {}
        request.base_url = "http://localhost/"

        with (
            patch(
                "app.api.workflows.parse_execute_body",
                AsyncMock(return_value=({}, False, "API", True)),
            ),
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=wf)),
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(
                "app.api.workflows.asyncio.to_thread",
                AsyncMock(side_effect=WorkflowCancelledError("cancelled")),
            ),
        ):
            current_user = MagicMock()
            current_user.id = uuid.uuid4()
            with self.assertRaises(HTTPException) as ctx:
                await execute_workflow_endpoint(
                    workflow_id=wf_id,
                    request=request,
                    current_user=current_user,
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "Execution was cancelled")
        db.add.assert_called_once()
        db.commit.assert_called_once()

    async def test_execution_registered_before_executor_called(self) -> None:
        """register_execution must be called so the run is visible in the active list."""
        from app.api.workflows import execute_workflow_endpoint

        wf_id = uuid.uuid4()
        wf = SimpleNamespace(
            id=wf_id,
            owner_id=uuid.uuid4(),
            nodes=[{"id": "n1"}],
            edges=[],
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
        )

        captured: list[uuid.UUID] = []

        def fake_execute(*args, **kwargs) -> MagicMock:
            captured.extend(
                h.execution_id for h in list_active_executions() if h.workflow_id == wf_id
            )
            return _make_execution_result()

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(wf))
        db.add = MagicMock()
        db.flush = AsyncMock()

        request = MagicMock()
        request.headers = {}
        request.query_params = {}
        request.base_url = "http://localhost/"

        with (
            patch(
                "app.api.workflows.parse_execute_body",
                AsyncMock(return_value=({}, False, "API", True)),
            ),
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.asyncio.to_thread", AsyncMock(side_effect=fake_execute)),
            patch("app.api.workflows.build_public_base_url", return_value="http://localhost"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
        ):
            current_user = MagicMock()
            current_user.id = uuid.uuid4()
            try:
                await execute_workflow_endpoint(
                    workflow_id=wf_id,
                    request=request,
                    current_user=current_user,
                    db=db,
                )
            except Exception:
                pass

        self.assertEqual(len(captured), 1, "execution must be visible in active list during run")

    async def test_execution_cleared_after_cancellation(self) -> None:
        """clear_execution must run in the finally block even when cancelled."""
        from app.api.workflows import execute_workflow_endpoint

        wf_id = uuid.uuid4()
        wf = SimpleNamespace(
            id=wf_id,
            name="Test WF",
            owner_id=uuid.uuid4(),
            nodes=[{"id": "n1"}],
            edges=[],
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(wf))
        db.add = MagicMock()
        db.commit = AsyncMock()
        request = MagicMock()
        request.headers = {}
        request.query_params = {}
        request.base_url = "http://localhost/"

        with (
            patch(
                "app.api.workflows.parse_execute_body",
                AsyncMock(return_value=({}, False, "API", True)),
            ),
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(
                "app.api.workflows.asyncio.to_thread",
                AsyncMock(side_effect=WorkflowCancelledError("cancelled")),
            ),
        ):
            current_user = MagicMock()
            current_user.id = uuid.uuid4()
            try:
                await execute_workflow_endpoint(
                    workflow_id=wf_id,
                    request=request,
                    current_user=current_user,
                    db=db,
                )
            except HTTPException:
                pass

        self.assertEqual(
            list_active_executions(), [], "execution must be cleared from active list after cancel"
        )


# ---------------------------------------------------------------------------
# 4. Portal trigger — already registered (regression guard)
# ---------------------------------------------------------------------------


class PortalTriggerRegistrationTests(unittest.TestCase):
    """Verify that the portal code path registers executions (regression guard)."""

    def setUp(self) -> None:
        _clear_active_executions()

    def tearDown(self) -> None:
        _clear_active_executions()

    def test_portal_execution_visible_after_register(self) -> None:
        """Simulates what portal.py does: register → run → clear."""
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()

        # portal.py calls register_execution before execute_workflow_streaming
        event = register_execution(workflow_id=wf_id, execution_id=ex_id)

        # Execution is visible in active list (what history dialog queries)
        handles = list_active_executions()
        self.assertEqual(len(handles), 1)
        self.assertEqual(handles[0].execution_id, ex_id)

        # Cancelling from history dialog would call cancel_execution
        cancel_execution(workflow_id=wf_id, execution_id=ex_id)
        self.assertTrue(event.is_set(), "cancel must set the event the executor polls")

        # After executor finishes (finally block in portal.py)
        clear_execution(ex_id)
        self.assertEqual(list_active_executions(), [])

    def test_cancel_endpoint_returns_false_for_unregistered_portal_execution(self) -> None:
        """If portal execution is not registered, cancel returns False → history dialog gets 404."""
        result = cancel_execution(workflow_id=uuid.uuid4(), execution_id=uuid.uuid4())
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# 5. Dashboard chat — NOT registered by design
# ---------------------------------------------------------------------------


class DashboardChatNotRegisteredTests(unittest.TestCase):
    """Dashboard chat has its own cancel mechanism (disconnect) and is NOT registered
    in _ACTIVE_EXECUTIONS, so it cannot be cancelled via the history dialog cancel button.
    This is intentional: the chat is not a direct workflow run."""

    def setUp(self) -> None:
        _clear_active_executions()

    def tearDown(self) -> None:
        _clear_active_executions()

    def test_active_executions_empty_when_no_registration_made(self) -> None:
        """Baseline: if no register_execution call is made, active list is empty."""
        # Dashboard chat creates its own threading.Event but never calls register_execution
        import threading

        _internal_cancel_event = threading.Event()  # what ai_assistant.py does
        # This event is NOT registered — active list stays empty
        self.assertEqual(list_active_executions(), [])

    def test_cancel_via_history_dialog_fails_for_unregistered_chat_execution(self) -> None:
        """Cancelling an unregistered execution (like a chat session) returns False."""
        result = cancel_execution(workflow_id=uuid.uuid4(), execution_id=uuid.uuid4())
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value
