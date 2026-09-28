"""Regression tests: allowDownstream results and credentials masking on resume_workflow_execution.

When a workflow execution pauses (e.g. for HITL review or Codex followup) and is later resumed:
1. If the workflow has an output node with allowDownstream: True, resume_workflow_execution
   must populate allow_downstream_pending and allow_downstream_node_results, and preserve
   _credentials_context so that join_allow_downstream() masks appended credential rows.
2. Global variable nodes in allowDownstream must keep their unmasked values for persistence.
3. Background resume workers (resume_hitl_request_in_background and
   resume_codex_followup_in_background) must join allowDownstream pending work,
   persist sub_workflow_executions into ExecutionHistory, and update workflow analytics snapshots.
"""

from __future__ import annotations

import asyncio
import json
import threading
import unittest
import uuid
from concurrent.futures import Future
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.services.workflow_executor import (
    ExecutionResult,
    NodeResult,
    SubWorkflowExecution,
    WorkflowExecutor,
    execute_workflow,
    resume_workflow_execution,
)

_SECRET = "sk-live-SUPERSECRET-1234567890"
_MASKED = _SECRET[:7] + "**"


def _variable(node_id: str, value: str, is_global: bool = False) -> dict:
    return {
        "id": node_id,
        "type": "variable",
        "data": {
            "label": node_id,
            "variableName": node_id,
            "variableValue": value,
            "variableType": "string",
            "isGlobal": is_global,
        },
    }


_NODES = [
    {
        "id": "agent-1",
        "type": "agent",
        "data": {"label": "agent-1"},
    },
    _variable("pre", "$credentials.apiKey"),
    {
        "id": "out1",
        "type": "output",
        "data": {"label": "output", "message": "ok", "allowDownstream": True},
    },
    _variable("gate", "released"),
    _variable("post", "$credentials.apiKey"),
    _variable("post_global", "$credentials.apiKey", is_global=True),
]

_EDGES = [
    {"id": "e1", "source": "agent-1", "target": "pre"},
    {"id": "e2", "source": "pre", "target": "out1"},
    {"id": "e3", "source": "out1", "target": "gate"},
    {"id": "e4", "source": "gate", "target": "post"},
    {"id": "e5", "source": "post", "target": "post_global"},
]


def _build_snapshot(
    nodes: list[dict] = _NODES,
    edges: list[dict] = _EDGES,
    sub_workflow_executions: list[dict] | None = None,
) -> dict:
    wf_id = str(uuid.uuid4())
    return {
        "workflow_id": wf_id,
        "nodes": nodes,
        "edges": edges,
        "workflow_cache": {},
        "initial_inputs": {},
        "node_results": [
            {
                "node_id": "agent-1",
                "node_label": "agent-1",
                "node_type": "agent",
                "status": "pending",
                "output": {"summary": "paused"},
                "execution_time_ms": 100.0,
                "error": None,
                "metadata": {"sequence": 1},
            }
        ],
        "node_outputs": {},
        "node_execution_contexts": {},
        "label_to_output": {},
        "skipped_nodes": [],
        "inactive_nodes": [],
        "loop_states": {},
        "vars": {},
        "sub_workflow_executions": sub_workflow_executions or [],
        "completed_nodes": [],
        "pending_count": {"pre": 1, "out1": 1, "gate": 1, "post": 1, "post_global": 1},
        "paused_node_id": "agent-1",
        "paused_node_label": "agent-1",
        "hitl_resume_mode": "inject_output",
        "credentials_owner_id": str(uuid.uuid4()),
        "actor_user_id": str(uuid.uuid4()),
    }


class ResumeAllowDownstreamMaskingTests(unittest.TestCase):
    def _run_resume(
        self,
        credentials_context: dict[str, str] | None,
        nodes: list[dict] = _NODES,
        edges: list[dict] = _EDGES,
    ) -> tuple[ExecutionResult, list[str]]:
        release = threading.Event()
        real_logic = WorkflowExecutor._execute_node_logic

        def gated_logic(executor: WorkflowExecutor, node_id: str, *args, **kwargs):
            if node_id == "gate" and not release.wait(timeout=5):
                raise AssertionError("downstream gate was never released")
            return real_logic(executor, node_id, *args, **kwargs)

        snapshot = _build_snapshot(nodes, edges)

        with patch.object(WorkflowExecutor, "_execute_node_logic", gated_logic):
            result = resume_workflow_execution(
                snapshot=snapshot,
                resolved_output={"decision": "accepted", "text": "approved"},
                credentials_context=credentials_context,
            )
            self.assertTrue(result.allow_downstream_pending)
            early_ids = [row["node_id"] for row in result.node_results]
            release.set()
            result.join_allow_downstream()

        return result, early_ids

    def test_resume_sets_credentials_context_and_masks_joined_rows(self) -> None:
        result, early_ids = self._run_resume({"apiKey": _SECRET})

        self.assertNotIn("post", early_ids)
        self.assertNotIn("post_global", early_ids)
        self.assertEqual(result._credentials_context, {"apiKey": _SECRET})

        rows = {row["node_id"]: row for row in result.node_results}
        self.assertIn("post", rows)
        self.assertEqual(rows["post"]["output"]["value"], _MASKED)

        # Global variable keeps raw value for callers to persist
        self.assertIn("post_global", rows)
        self.assertEqual(rows["post_global"]["output"]["value"], _SECRET)

        # Verify raw secret does not leak in any non-global node result
        non_global_results = [r for r in result.node_results if r["node_id"] != "post_global"]
        self.assertNotIn(_SECRET, json.dumps(non_global_results))

    def test_resume_without_credentials_still_joins_downstream_rows(self) -> None:
        result, early_ids = self._run_resume(None)

        self.assertNotIn("post", early_ids)
        self.assertEqual(result._credentials_context, {})
        rows = {row["node_id"]: row for row in result.node_results}
        self.assertIn("post", rows)
        self.assertIn("post_global", rows)

    def test_parent_progress_while_background_child_is_running(self) -> None:
        """executeDoNotWait background child must not hold up later nodes in resumed downstream branch."""
        bg_started = threading.Event()
        bg_can_finish = threading.Event()
        node_after_executed = threading.Event()

        class FakeBgFuture:
            def __init__(self):
                self._done = False

            def result(self, timeout=None):
                bg_started.set()
                if not bg_can_finish.wait(timeout=5):
                    raise TimeoutError(
                        "Background future was drained prematurely while downstream nodes were waiting to execute!"
                    )
                self._done = True
                return None

            def done(self):
                return self._done

            def cancel(self):
                return False

        fake_fut = FakeBgFuture()

        nodes = [
            {"id": "agent-1", "type": "agent", "data": {"label": "agent-1"}},
            {
                "id": "out1",
                "type": "output",
                "data": {"label": "output", "message": "ok", "allowDownstream": True},
            },
            _variable("launcher", "dispatched"),
            _variable("after_launcher", "progress_made"),
        ]
        edges = [
            {"id": "e1", "source": "agent-1", "target": "out1"},
            {"id": "e2", "source": "out1", "target": "launcher"},
            {"id": "e3", "source": "launcher", "target": "after_launcher"},
        ]

        snapshot = _build_snapshot(nodes, edges)
        snapshot["pending_count"] = {"out1": 1, "launcher": 1, "after_launcher": 1}

        real_logic = WorkflowExecutor._execute_node_logic

        def mock_execute_node(executor: WorkflowExecutor, node_id: str, *args, **kwargs):
            if node_id == "launcher":
                with executor._bg_futures_lock:
                    executor._bg_futures.append((fake_fut, None, "child-wf", "child", {}))
                return NodeResult(
                    node_id="launcher",
                    node_label="launcher",
                    node_type="variable",
                    status="success",
                    output={"status": "dispatched"},
                    execution_time_ms=10.0,
                )
            elif node_id == "after_launcher":
                if fake_fut.done():
                    raise AssertionError(
                        "Child future was already drained before after_launcher executed!"
                    )
                node_after_executed.set()
                bg_can_finish.set()
                return NodeResult(
                    node_id="after_launcher",
                    node_label="after_launcher",
                    node_type="variable",
                    status="success",
                    output={"value": "progress_made"},
                    execution_time_ms=10.0,
                )
            return real_logic(executor, node_id, *args, **kwargs)

        with patch.object(WorkflowExecutor, "_execute_node_logic", mock_execute_node):
            result = resume_workflow_execution(
                snapshot=snapshot,
                resolved_output={"decision": "accepted"},
                credentials_context=None,
            )
            self.assertTrue(result.allow_downstream_pending)
            result.join_allow_downstream()

        self.assertTrue(node_after_executed.is_set(), "after_launcher node should have executed")
        self.assertTrue(fake_fut.done(), "fake background future should be drained upon completion")


class BackgroundResumeHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_hitl_background_resume_joins_downstream_and_persists_sub_workflows(
        self,
    ) -> None:
        from app.services import hitl_service

        request_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        history_id = uuid.uuid4()
        owner_id = uuid.uuid4()

        sub_wf_id = str(uuid.uuid4())
        mock_sub_exec = SubWorkflowExecution(
            workflow_id=sub_wf_id,
            inputs={"x": 1},
            outputs={"y": 2},
            status="success",
            execution_time_ms=50.0,
            node_results=[],
            workflow_name="Child Workflow",
            trigger_source="SUB_WORKFLOW",
        )

        hitl_req = MagicMock()
        hitl_req.id = request_id
        hitl_req.workflow_id = workflow_id
        hitl_req.execution_history_id = history_id
        hitl_req.status = "resolved"
        hitl_req.decision = "accepted"
        hitl_req.execution_snapshot = _build_snapshot()

        mock_wf = MagicMock()
        mock_wf.id = workflow_id
        mock_wf.owner_id = owner_id
        mock_wf.name = "Parent Workflow"

        mock_history = MagicMock()
        mock_history.id = history_id
        mock_history.outputs = {}
        mock_history.node_results = []
        mock_history.status = "pending"
        mock_history.execution_time_ms = 0.0
        mock_history.started_at = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)

        resumed_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"output": {"msg": "done"}},
            execution_time_ms=120.0,
            node_results=[{"node_id": "out1", "status": "success"}],
            sub_workflow_executions=[mock_sub_exec],
        )
        resumed_result._allow_downstream_pending = [MagicMock()]
        resumed_result.join_allow_downstream = MagicMock()

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=hitl_req))
        )
        mock_db.get = AsyncMock(
            side_effect=lambda model, mid: mock_wf if mid == workflow_id else mock_history
        )
        mock_db_context = MagicMock()
        mock_db_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_context.__aexit__ = AsyncMock(return_value=None)

        upsert_analytics = AsyncMock()
        persist_globals = AsyncMock()

        with (
            patch.object(hitl_service, "async_session_maker", return_value=mock_db_context),
            patch.object(hitl_service, "resume_workflow_execution", return_value=resumed_result),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch("app.api.workflows._persist_global_variables_from_execution", persist_globals),
            patch.object(hitl_service, "_resume_board_chain", AsyncMock()),
            patch("app.services.hitl_service.upsert_workflow_analytics_snapshot", upsert_analytics),
        ):
            await hitl_service.resume_hitl_request_in_background(request_id)

        # Assert allowDownstream was joined
        resumed_result.join_allow_downstream.assert_called_once()

        # Assert sub_workflow was persisted to DB
        added_entities = [call.args[0] for call in mock_db.add.call_args_list]
        sub_histories = [
            e for e in added_entities if getattr(e, "workflow_id", None) == uuid.UUID(sub_wf_id)
        ]
        self.assertEqual(len(sub_histories), 1)
        self.assertEqual(sub_histories[0].status, "success")

        # Assert upsert_workflow_analytics_snapshot was called for sub_workflow and main workflow
        analytics_wf_ids = {
            call.kwargs.get("workflow_id") for call in upsert_analytics.await_args_list
        }
        self.assertIn(uuid.UUID(sub_wf_id), analytics_wf_ids)
        self.assertIn(workflow_id, analytics_wf_ids)

        parent_call = next(
            call
            for call in upsert_analytics.await_args_list
            if call.kwargs.get("workflow_id") == workflow_id
        )
        self.assertIs(parent_call.kwargs.get("count_execution"), False)
        self.assertEqual(parent_call.kwargs.get("started_at"), mock_history.started_at)

    async def test_hitl_background_resume_marks_error_when_downstream_fails(
        self,
    ) -> None:
        from app.services import hitl_service

        request_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        history_id = uuid.uuid4()
        owner_id = uuid.uuid4()

        hitl_req = MagicMock()
        hitl_req.id = request_id
        hitl_req.workflow_id = workflow_id
        hitl_req.execution_history_id = history_id
        hitl_req.status = "resolved"
        hitl_req.decision = "accepted"
        hitl_req.execution_snapshot = _build_snapshot()

        mock_wf = MagicMock(id=workflow_id, owner_id=owner_id, name="Parent Workflow")
        mock_history = MagicMock(
            id=history_id, outputs={}, node_results=[], status="pending", execution_time_ms=0.0
        )

        resumed_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"output": {"msg": "done"}},
            execution_time_ms=120.0,
            node_results=[{"node_id": "out1", "status": "success"}],
            sub_workflow_executions=[],
        )
        resumed_result._allow_downstream_pending = [MagicMock()]

        def append_failing_downstream():
            resumed_result.node_results.append(
                {"node_id": "fail_node", "status": "error", "error": "failed"}
            )

        resumed_result.join_allow_downstream = MagicMock(side_effect=append_failing_downstream)

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=hitl_req))
        )
        mock_db.get = AsyncMock(
            side_effect=lambda model, mid: mock_wf if mid == workflow_id else mock_history
        )
        mock_db_context = MagicMock()
        mock_db_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_context.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.object(hitl_service, "async_session_maker", return_value=mock_db_context),
            patch.object(hitl_service, "resume_workflow_execution", return_value=resumed_result),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch("app.api.workflows._persist_global_variables_from_execution", AsyncMock()),
            patch.object(hitl_service, "_resume_board_chain", AsyncMock()),
            patch("app.services.hitl_service.upsert_workflow_analytics_snapshot", AsyncMock()),
        ):
            await hitl_service.resume_hitl_request_in_background(request_id)

        self.assertEqual(resumed_result.status, "error")
        self.assertEqual(mock_history.status, "error")

    async def test_codex_background_resume_joins_downstream_and_persists_sub_workflows(
        self,
    ) -> None:
        from app.services import codex_followup_service

        request_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        history_id = uuid.uuid4()
        owner_id = uuid.uuid4()

        sub_wf_id = str(uuid.uuid4())
        mock_sub_exec = SubWorkflowExecution(
            workflow_id=sub_wf_id,
            inputs={"q": "ping"},
            outputs={"a": "pong"},
            status="success",
            execution_time_ms=45.0,
            node_results=[],
            workflow_name="Child Workflow",
            trigger_source="SUB_WORKFLOW",
        )

        followup = MagicMock()
        followup.id = request_id
        followup.workflow_id = workflow_id
        followup.execution_history_id = history_id
        followup.status = "answered"
        followup.answer_text = "42"
        followup.execution_snapshot = _build_snapshot()

        mock_wf = MagicMock()
        mock_wf.id = workflow_id
        mock_wf.owner_id = owner_id
        mock_wf.name = "Codex Parent Workflow"

        mock_history = MagicMock()
        mock_history.id = history_id
        mock_history.outputs = {}
        mock_history.node_results = []
        mock_history.status = "pending"
        mock_history.execution_time_ms = 0.0
        mock_history.started_at = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)

        resumed_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"output": {"msg": "done"}},
            execution_time_ms=150.0,
            node_results=[{"node_id": "out1", "status": "success"}],
            sub_workflow_executions=[mock_sub_exec],
        )
        resumed_result._allow_downstream_pending = [MagicMock()]
        resumed_result.join_allow_downstream = MagicMock()

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=followup))
        )
        mock_db.get = AsyncMock(
            side_effect=lambda model, mid: mock_wf if mid == workflow_id else mock_history
        )
        mock_db_context = MagicMock()
        mock_db_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_context.__aexit__ = AsyncMock(return_value=None)

        upsert_analytics = AsyncMock()
        persist_globals = AsyncMock()

        with (
            patch.object(
                codex_followup_service, "async_session_maker", return_value=mock_db_context
            ),
            patch.object(
                codex_followup_service, "resume_workflow_execution", return_value=resumed_result
            ),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch("app.api.workflows._persist_global_variables_from_execution", persist_globals),
            patch.object(codex_followup_service, "_resume_board_chain", AsyncMock()),
            patch(
                "app.services.codex_followup_service.upsert_workflow_analytics_snapshot",
                upsert_analytics,
            ),
        ):
            await codex_followup_service.resume_codex_followup_in_background(request_id)

        # Assert allowDownstream was joined
        resumed_result.join_allow_downstream.assert_called_once()

        # Assert sub_workflow was persisted to DB
        added_entities = [call.args[0] for call in mock_db.add.call_args_list]
        sub_histories = [
            e for e in added_entities if getattr(e, "workflow_id", None) == uuid.UUID(sub_wf_id)
        ]
        self.assertEqual(len(sub_histories), 1)

        # Assert upsert_workflow_analytics_snapshot was called for sub_workflow and main workflow
        analytics_wf_ids = {
            call.kwargs.get("workflow_id") for call in upsert_analytics.await_args_list
        }
        self.assertIn(uuid.UUID(sub_wf_id), analytics_wf_ids)
        self.assertIn(workflow_id, analytics_wf_ids)

        parent_call = next(
            call
            for call in upsert_analytics.await_args_list
            if call.kwargs.get("workflow_id") == workflow_id
        )
        self.assertIs(parent_call.kwargs.get("count_execution"), False)
        self.assertEqual(parent_call.kwargs.get("started_at"), mock_history.started_at)


class SingleAnalyticsCountAfterResumeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from app.db.session import engine

        await engine.dispose()
        self.users_to_clean: list[uuid.UUID] = []
        self.workflows_to_clean: list[uuid.UUID] = []

    async def asyncTearDown(self) -> None:
        from sqlalchemy import delete

        from app.db.models import User, Workflow, WorkflowAnalyticsSnapshot
        from app.db.session import async_session_maker, engine

        async with async_session_maker() as db:
            if self.workflows_to_clean:
                await db.execute(
                    delete(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id.in_(self.workflows_to_clean)
                    )
                )
                await db.execute(delete(Workflow).where(Workflow.id.in_(self.workflows_to_clean)))
            if self.users_to_clean:
                await db.execute(delete(User).where(User.id.in_(self.users_to_clean)))
            await db.commit()

        await engine.dispose()

    async def test_analytics_snapshot_counts_execution_once_across_pause_and_resume(self) -> None:
        """Pausing records 1 execution; resuming records outcome with count_execution=False without incrementing."""
        from sqlalchemy import select

        from app.db.models import User, Workflow, WorkflowAnalyticsSnapshot
        from app.db.session import async_session_maker

        async with async_session_maker() as db:
            user = User(
                id=uuid.uuid4(),
                email=f"test-{uuid.uuid4()}@example.com",
                hashed_password="pw",
                name="Test User",
            )
            workflow = Workflow(
                id=uuid.uuid4(),
                owner_id=user.id,
                name="Analytics Test WF",
                nodes=[],
                edges=[],
            )
            self.users_to_clean.append(user.id)
            self.workflows_to_clean.append(workflow.id)
            db.add(user)
            db.add(workflow)
            await db.commit()

            t0 = datetime(2026, 4, 1, 10, 15, tzinfo=timezone.utc)

            # 1. Workflow pauses: records total_executions = 1, success_count = 0, error_count = 0
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=workflow.id,
                owner_id=user.id,
                workflow_name_snapshot=workflow.name,
                status="pending",
                execution_time_ms=100.0,
                started_at=t0,
            )
            await db.commit()

            stmt = select(WorkflowAnalyticsSnapshot).where(
                WorkflowAnalyticsSnapshot.workflow_id == workflow.id
            )
            res = (await db.execute(stmt)).scalar_one()
            self.assertEqual(res.total_executions, 1)
            self.assertEqual(res.success_count, 0)
            self.assertEqual(res.error_count, 0)
            self.assertEqual(res.latency_sample_count, 1)

            # 2. Workflow resumes and succeeds: updates final outcome without counting execution again
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=workflow.id,
                owner_id=user.id,
                workflow_name_snapshot=workflow.name,
                status="success",
                execution_time_ms=250.0,
                started_at=t0,
                count_execution=False,
            )
            await db.commit()
            await db.refresh(res)
            self.assertEqual(res.total_executions, 1, "Total executions must remain 1 after resume")
            self.assertEqual(res.success_count, 1, "Success count must be updated to 1")
            self.assertEqual(res.error_count, 0)
            self.assertEqual(
                res.latency_sample_count, 1, "Latency sample count must not be incremented again"
            )

    async def test_analytics_snapshot_records_error_outcome_without_double_counting(self) -> None:
        """When a resumed workflow encounters an error, error_count is incremented without incrementing total_executions."""
        from sqlalchemy import select

        from app.db.models import User, Workflow, WorkflowAnalyticsSnapshot
        from app.db.session import async_session_maker

        async with async_session_maker() as db:
            user = User(
                id=uuid.uuid4(),
                email=f"test-{uuid.uuid4()}@example.com",
                hashed_password="pw",
                name="Test User",
            )
            workflow = Workflow(
                id=uuid.uuid4(),
                owner_id=user.id,
                name="Analytics Error Test WF",
                nodes=[],
                edges=[],
            )
            self.users_to_clean.append(user.id)
            self.workflows_to_clean.append(workflow.id)
            db.add(user)
            db.add(workflow)
            await db.commit()

            t0 = datetime(2026, 4, 1, 10, 15, tzinfo=timezone.utc)

            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=workflow.id,
                owner_id=user.id,
                workflow_name_snapshot=workflow.name,
                status="pending",
                execution_time_ms=50.0,
                started_at=t0,
            )
            await db.commit()

            # Resumed workflow errors out
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=workflow.id,
                owner_id=user.id,
                workflow_name_snapshot=workflow.name,
                status="error",
                execution_time_ms=120.0,
                started_at=t0,
                count_execution=False,
            )
            await db.commit()

            stmt = select(WorkflowAnalyticsSnapshot).where(
                WorkflowAnalyticsSnapshot.workflow_id == workflow.id
            )
            res = (await db.execute(stmt)).scalar_one()
            self.assertEqual(res.total_executions, 1)
            self.assertEqual(res.success_count, 0)
            self.assertEqual(res.error_count, 1)


class DownstreamGlobalPersistenceTimingTests(unittest.TestCase):
    """Verify that downstream globals keep raw values while pre-output globals stay masked,
    consistently across both fast and delayed completion in normal and resumed execution."""

    def _setup_workflow(self, paused: bool = False) -> tuple[list[dict], list[dict]]:
        first_node = (
            {"id": "agent-1", "type": "agent", "data": {"label": "agent-1"}}
            if paused
            else {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            }
        )
        nodes = [
            first_node,
            _variable("pre_global", "$credentials.apiKey", is_global=True),
            {
                "id": "out1",
                "type": "output",
                "data": {"label": "output", "message": "ok", "allowDownstream": True},
            },
            _variable("gate", "released"),
            _variable("post_global", "$credentials.apiKey", is_global=True),
            _variable("post_non_global", "$credentials.apiKey", is_global=False),
        ]
        first_id = first_node["id"]
        edges = [
            {"id": "e1", "source": first_id, "target": "pre_global"},
            {"id": "e2", "source": "pre_global", "target": "out1"},
            {"id": "e3", "source": "out1", "target": "gate"},
            {"id": "e4", "source": "gate", "target": "post_global"},
            {"id": "e5", "source": "post_global", "target": "post_non_global"},
        ]
        return nodes, edges

    def _sync_submit(self, work):
        fut = Future()
        work()
        fut.set_result(None)
        return fut

    def _persist(self, nodes: list[dict], result: ExecutionResult) -> dict[str, str]:
        from app.api.workflows import _persist_global_variables_from_execution

        upsert = AsyncMock()
        with patch("app.api.workflows.upsert_global_variable", upsert):
            asyncio.run(
                _persist_global_variables_from_execution(
                    MagicMock(),
                    uuid.uuid4(),
                    nodes,
                    {},
                    result.node_results,
                    result.sub_workflow_executions,
                )
            )
        return {call.args[2]: call.args[3] for call in upsert.await_args_list}

    def test_normal_execution_fast_downstream_global_keeps_raw_value(self) -> None:
        """When downstream finishes fast, execute_workflow's initial masking pass must not mask downstream globals."""
        nodes, edges = self._setup_workflow(paused=False)

        with patch(
            "app.services.workflow_executor._submit_allow_downstream_work",
            side_effect=self._sync_submit,
        ):
            result = execute_workflow(
                workflow_id=uuid.uuid4(),
                nodes=nodes,
                edges=edges,
                inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
                credentials_context={"apiKey": _SECRET},
            )

        rows = {r["node_id"]: r for r in result.node_results if isinstance(r, dict)}
        self.assertIn("pre_global", rows)
        self.assertIn("post_global", rows)
        self.assertIn("post_non_global", rows)

        # Pre-output global is masked
        self.assertEqual(rows["pre_global"]["output"]["value"], _MASKED)
        # Downstream global keeps raw secret
        self.assertEqual(rows["post_global"]["output"]["value"], _SECRET)
        # Downstream non-global is masked
        self.assertEqual(rows["post_non_global"]["output"]["value"], _MASKED)

        # Global persistence stores raw value for downstream global, masked for pre-output global
        persisted = self._persist(nodes, result)
        self.assertEqual(persisted.get("pre_global"), _MASKED)
        self.assertEqual(persisted.get("post_global"), _SECRET)

    def test_normal_execution_delayed_downstream_global_keeps_raw_value(self) -> None:
        """When downstream finishes delayed, join_allow_downstream must preserve downstream global raw value."""
        nodes, edges = self._setup_workflow(paused=False)
        release = threading.Event()
        real_logic = WorkflowExecutor._execute_node_logic

        def gated_logic(executor: WorkflowExecutor, node_id: str, *args, **kwargs):
            if node_id == "gate" and not release.wait(timeout=5):
                raise AssertionError("gate was never released")
            return real_logic(executor, node_id, *args, **kwargs)

        with patch.object(WorkflowExecutor, "_execute_node_logic", gated_logic):
            result = execute_workflow(
                workflow_id=uuid.uuid4(),
                nodes=nodes,
                edges=edges,
                inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
                credentials_context={"apiKey": _SECRET},
            )
            early_ids = [r["node_id"] for r in result.node_results if isinstance(r, dict)]
            self.assertIn("pre_global", early_ids)
            self.assertNotIn("post_global", early_ids)

            release.set()
            result.join_allow_downstream()

        rows = {r["node_id"]: r for r in result.node_results if isinstance(r, dict)}
        self.assertEqual(rows["pre_global"]["output"]["value"], _MASKED)
        self.assertEqual(rows["post_global"]["output"]["value"], _SECRET)
        self.assertEqual(rows["post_non_global"]["output"]["value"], _MASKED)

        persisted = self._persist(nodes, result)
        self.assertEqual(persisted.get("pre_global"), _MASKED)
        self.assertEqual(persisted.get("post_global"), _SECRET)

    def test_resume_execution_fast_downstream_global_keeps_raw_value(self) -> None:
        """When resumed downstream finishes fast, initial masking pass in resume_workflow_execution preserves downstream globals."""
        nodes, edges = self._setup_workflow(paused=True)
        snapshot = _build_snapshot(nodes, edges)
        snapshot["pending_count"] = {
            "pre_global": 1,
            "out1": 1,
            "gate": 1,
            "post_global": 1,
            "post_non_global": 1,
        }

        with patch(
            "app.services.workflow_executor._submit_allow_downstream_work",
            side_effect=self._sync_submit,
        ):
            result = resume_workflow_execution(
                snapshot=snapshot,
                resolved_output={"decision": "accepted"},
                credentials_context={"apiKey": _SECRET},
            )

        rows = {r["node_id"]: r for r in result.node_results if isinstance(r, dict)}
        self.assertEqual(rows["pre_global"]["output"]["value"], _MASKED)
        self.assertEqual(rows["post_global"]["output"]["value"], _SECRET)
        self.assertEqual(rows["post_non_global"]["output"]["value"], _MASKED)

        persisted = self._persist(nodes, result)
        self.assertEqual(persisted.get("pre_global"), _MASKED)
        self.assertEqual(persisted.get("post_global"), _SECRET)

    def test_resume_execution_delayed_downstream_global_keeps_raw_value(self) -> None:
        """When resumed downstream finishes delayed, join_allow_downstream preserves downstream global raw value."""
        nodes, edges = self._setup_workflow(paused=True)
        snapshot = _build_snapshot(nodes, edges)
        snapshot["pending_count"] = {
            "pre_global": 1,
            "out1": 1,
            "gate": 1,
            "post_global": 1,
            "post_non_global": 1,
        }
        release = threading.Event()
        real_logic = WorkflowExecutor._execute_node_logic

        def gated_logic(executor: WorkflowExecutor, node_id: str, *args, **kwargs):
            if node_id == "gate" and not release.wait(timeout=5):
                raise AssertionError("gate was never released")
            return real_logic(executor, node_id, *args, **kwargs)

        with patch.object(WorkflowExecutor, "_execute_node_logic", gated_logic):
            result = resume_workflow_execution(
                snapshot=snapshot,
                resolved_output={"decision": "accepted"},
                credentials_context={"apiKey": _SECRET},
            )
            early_ids = [r["node_id"] for r in result.node_results if isinstance(r, dict)]
            self.assertIn("pre_global", early_ids)
            self.assertNotIn("post_global", early_ids)

            release.set()
            result.join_allow_downstream()

        rows = {r["node_id"]: r for r in result.node_results if isinstance(r, dict)}
        self.assertEqual(rows["pre_global"]["output"]["value"], _MASKED)
        self.assertEqual(rows["post_global"]["output"]["value"], _SECRET)
        self.assertEqual(rows["post_non_global"]["output"]["value"], _MASKED)

        persisted = self._persist(nodes, result)
        self.assertEqual(persisted.get("pre_global"), _MASKED)
        self.assertEqual(persisted.get("post_global"), _SECRET)

    def test_pre_output_global_remains_masked_in_normal_and_resumed_execution(self) -> None:
        """Top-level globals written before the output node must stay masked upon persistence."""
        nodes, edges = self._setup_workflow(paused=False)

        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
            credentials_context={"apiKey": _SECRET},
        )
        result.join_allow_downstream()

        persisted = self._persist(nodes, result)
        self.assertEqual(persisted["pre_global"], _MASKED)
        self.assertEqual(persisted["post_global"], _SECRET)
