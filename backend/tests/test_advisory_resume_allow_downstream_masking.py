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

import json
import threading
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.workflow_executor import (
    ExecutionResult,
    SubWorkflowExecution,
    WorkflowExecutor,
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
