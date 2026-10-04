"""Advisory tests for credential masking on cancelled workflow streams.

Cancellation is a separate persistence/publication boundary, so it must receive the
same credential-redaction guarantees as normal execution paths.
"""

import asyncio
import json
import threading
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import delete, select

from app.db.models import ExecutionHistory, User, Workflow, WorkflowAnalyticsSnapshot
from app.db.session import async_session_maker, engine
from app.services.workflow_executor import (
    SubWorkflowExecution,
    WorkflowCancelledError,
    _mask_node_result_row,
    mask_sensitive_output,
)


class CancelledStreamMaskingAdvisoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.user_id = uuid.uuid4()
        self.cleanup_workflow_ids: list[uuid.UUID] = []

        async with async_session_maker() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"advisory-cancel-{self.user_id}@example.com",
                    hashed_password="pw",
                    name="Advisory Test User",
                )
            )
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as db:
            if self.cleanup_workflow_ids:
                await db.execute(
                    delete(ExecutionHistory).where(
                        ExecutionHistory.workflow_id.in_(self.cleanup_workflow_ids)
                    )
                )
                await db.execute(
                    delete(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id.in_(self.cleanup_workflow_ids)
                    )
                )
                await db.execute(delete(Workflow).where(Workflow.id.in_(self.cleanup_workflow_ids)))
            await db.execute(delete(User).where(User.id == self.user_id))
            await db.commit()
        await engine.dispose()

    async def test_cancelled_stream_outputs_masked_in_history_and_observer(self) -> None:
        """Issue 1: Cancelled stream outputs and node results must remain masked.
        - Credentials context must mask sensitive strings in both ExecutionHistory and active execution observer.
        - Neither ExecutionHistory.outputs nor observer terminal payload may leak raw secrets."""
        from app.api.workflows import persist_stream_execution_result
        from app.services.execution_cancellation import (
            complete_execution,
            get_completed_execution_result,
            register_execution,
        )

        secret_token = "sk-live-super-secret-token-abcdef123456"
        secret_context = {"api_key": secret_token}

        wid = uuid.uuid4()
        eid = uuid.uuid4()

        async with async_session_maker() as s:
            wf = Workflow(
                id=wid,
                owner_id=self.user_id,
                name="Stream Masking Cancel WF",
                nodes=[{"id": "step_auth", "type": "javascript"}],
                edges=[],
                sse_enabled=True,
            )
            s.add(wf)
            await s.commit()
        self.cleanup_workflow_ids.append(wid)

        raw_node_results = [
            {
                "node_id": "step_auth",
                "node_label": "Authenticate",
                "status": "success",
                "output": {"token": secret_token, "user": "admin"},
            }
        ]
        raw_outputs = {"token": secret_token, "status": "authorized"}

        # Simulate stream cancelled with raw node outputs
        final_res = {
            "type": "execution_complete",
            "workflow_id": str(wid),
            "status": "cancelled",
            "outputs": raw_outputs,
            "execution_time_ms": 150.0,
            "node_results": raw_node_results,
            "sub_workflow_executions": [],
        }

        # 1. persist_stream_execution_result with credentials_owner_id
        async with async_session_maker() as s:
            run_wf = await s.get(Workflow, wid)
            with patch(
                "app.api.workflows.get_credentials_context",
                AsyncMock(return_value=secret_context),
            ):
                written = await persist_stream_execution_result(
                    s,
                    workflow=run_wf,
                    execution_id=eid,
                    enriched_inputs={},
                    trigger_source="manual",
                    raw_body=None,
                    query_params={},
                    workflow_cache={},
                    credentials_owner_id=self.user_id,
                    final_result=final_res,
                    was_cancelled=True,
                )
                self.assertTrue(written)
                await s.commit()

        # Check DB ExecutionHistory
        async with async_session_maker() as s:
            h = (
                await s.execute(select(ExecutionHistory).where(ExecutionHistory.id == eid))
            ).scalar_one()
            self.assertEqual(h.status, "cancelled")
            self.assertNotIn(
                secret_token,
                json.dumps(h.outputs),
                "Raw secret must NOT leak in history outputs",
            )
            self.assertIn(
                "sk-live**",
                json.dumps(h.outputs),
                "Masked token must be present in history outputs",
            )
            self.assertNotIn(
                secret_token,
                json.dumps(h.node_results),
                "Raw secret must NOT leak in history node_results",
            )

        # 2. Check active observer complete_execution
        cancel_eid = uuid.uuid4()
        c_event = threading.Event()
        register_execution(
            workflow_id=wid, execution_id=cancel_eid, event=c_event, recoverable=False
        )
        masked_out = mask_sensitive_output(raw_outputs, secret_context)
        import copy

        masked_nr = copy.deepcopy(raw_node_results)
        _mask_node_result_row(masked_nr[0], secret_context)
        observer_event = {
            "type": "execution_complete",
            "workflow_id": str(wid),
            "status": "cancelled",
            "outputs": masked_out,
            "execution_time_ms": 150.0,
            "node_results": masked_nr,
        }
        complete_execution(cancel_eid, workflow_id=wid, result=observer_event)
        completed_obs = get_completed_execution_result(cancel_eid, workflow_id=wid)
        self.assertIsNotNone(completed_obs)
        self.assertEqual(completed_obs["status"], "cancelled")
        self.assertNotIn(secret_token, json.dumps(completed_obs["outputs"]))
        self.assertIn("sk-live**", json.dumps(completed_obs["outputs"]))

    async def test_cancelled_stream_masks_subworkflow_inputs_in_sse_observer_and_db_postgres(
        self,
    ) -> None:
        """Issue 1: Mask sub-workflow records in cancelled stream payloads.
        - Inputs, outputs, and node_results must be masked before publishing or persisting on cancel.
        - Raw secrets must NOT appear in:
          a) client SSE terminal event
          b) active observer terminal payload
          c) child ExecutionHistory.inputs / outputs / node_results in PostgreSQL
        - Live execution objects must not be mutated.
        - Normal execution masking is not broken."""
        from app.api.workflows import execute_workflow_stream
        from app.services.execution_cancellation import get_completed_execution_result

        secret_token = "sk-live-super-secret-key-123456789"
        secret_context = {"api_key": secret_token}

        parent_wid = uuid.uuid4()
        child_wid = uuid.uuid4()
        execution_id = uuid.uuid4()

        async with async_session_maker() as s:
            pwf = Workflow(
                id=parent_wid,
                owner_id=self.user_id,
                name="Parent Cancel Mask Stream WF",
                nodes=[{"id": "p1", "type": "javascript"}],
                edges=[],
                sse_enabled=True,
            )
            cwf = Workflow(
                id=child_wid,
                owner_id=self.user_id,
                name="Child Cancel Mask Stream WF",
                nodes=[{"id": "c1", "type": "javascript"}],
                edges=[],
            )
            s.add(pwf)
            s.add(cwf)
            await s.commit()

        self.cleanup_workflow_ids.extend([parent_wid, child_wid])

        child_inputs = {"api_key": secret_token, "prompt": f"run with {secret_token}"}
        child_outputs = {"result": f"received {secret_token}", "status": "done"}
        child_node_results = [
            {
                "node_id": "c1",
                "node_label": "ChildStep",
                "node_type": "javascript",
                "status": "success",
                "output": {"token": secret_token},
                "error": f"failed with {secret_token}",
                "execution_time_ms": 12.0,
            }
        ]
        sub_exec = SubWorkflowExecution(
            workflow_id=str(child_wid),
            inputs=dict(child_inputs),
            outputs=dict(child_outputs),
            status="success",
            execution_time_ms=50.0,
            node_results=list(child_node_results),
            workflow_name="Child Cancel Mask Stream WF",
            trigger_source="AI Agents",
            execution_id=str(uuid.uuid4()),
        )

        mock_executor = MagicMock()
        mock_executor.completed_node_results = [
            {
                "node_id": "p1",
                "node_label": "ParentStep",
                "node_type": "javascript",
                "status": "success",
                "output": {"token": secret_token},
                "error": None,
                "execution_time_ms": 10.0,
            }
        ]
        mock_executor.node_outputs = {"ParentStep": {"token": secret_token}}
        mock_executor.execution_start_time = time.time()
        mock_executor.sub_workflow_executions = [sub_exec]

        def fake_streaming_run(*args, **kwargs):
            holder = kwargs.get("executor_holder")
            if holder is not None:
                holder["executor"] = mock_executor
            yield {"type": "node_started", "node_id": "p1"}
            raise WorkflowCancelledError("Workflow was cancelled by user")

        request = MagicMock()
        request.method = "POST"
        request.headers = {}
        request.query_params = {}
        request.base_url = "http://localhost/"
        request.is_disconnected = AsyncMock(return_value=False)

        async with async_session_maker() as s:
            with (
                patch(
                    "app.api.workflows.parse_execute_body",
                    AsyncMock(return_value=({}, False, "API", False)),
                ),
                patch(
                    "app.api.workflows.validate_workflow_auth",
                    AsyncMock(return_value=SimpleNamespace(id=self.user_id)),
                ),
                patch("app.api.workflows.enforce_workflow_http_method", MagicMock()),
                patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
                patch(
                    "app.api.workflows.get_credentials_context",
                    AsyncMock(return_value=secret_context),
                ),
                patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
                patch("app.api.workflows.build_public_base_url", return_value="http://localhost"),
                patch("app.api.workflows.execute_workflow_streaming", fake_streaming_run),
                patch("app.api.workflows.async_session_maker", async_session_maker),
            ):
                response = await execute_workflow_stream(
                    workflow_id=parent_wid,
                    request=request,
                    current_user=SimpleNamespace(id=self.user_id),
                    db=s,
                )
                frames = [chunk async for chunk in response.body_iterator]

        raw_payload = "".join(c.decode() if isinstance(c, bytes) else c for c in frames)
        lines = [line.strip() for line in raw_payload.split("\n") if line.startswith("data: ")]
        parsed_events = [json.loads(line[len("data: ") :]) for line in lines]

        # Extract execution_id from execution_started event
        execution_id = None
        for e in parsed_events:
            if e.get("type") == "execution_started":
                execution_id = uuid.UUID(e["execution_id"])
                break
        self.assertIsNotNone(execution_id, "execution_started must emit execution_id")

        # a) Client SSE terminal event validation
        terminal_events = [e for e in parsed_events if e.get("type") == "execution_complete"]
        self.assertEqual(len(terminal_events), 1)
        term = terminal_events[0]
        self.assertEqual(term.get("status"), "cancelled")
        self.assertEqual(len(term.get("sub_workflow_executions", [])), 1)
        term_sub = term["sub_workflow_executions"][0]

        # Sub-workflow inputs, outputs, node_results must be masked in client SSE
        term_inputs_str = json.dumps(term_sub.get("inputs"))
        self.assertNotIn(
            secret_token,
            term_inputs_str,
            "Client SSE must NOT contain raw secret in sub-workflow inputs",
        )
        self.assertIn(
            "sk-live**",
            term_inputs_str,
            "Client SSE must contain masked secret in sub-workflow inputs",
        )

        term_outputs_str = json.dumps(term_sub.get("outputs"))
        self.assertNotIn(
            secret_token,
            term_outputs_str,
            "Client SSE must NOT contain raw secret in sub-workflow outputs",
        )
        self.assertIn(
            "sk-live**",
            term_outputs_str,
            "Client SSE must contain masked secret in sub-workflow outputs",
        )

        term_nr_str = json.dumps(term_sub.get("node_results"))
        self.assertNotIn(
            secret_token,
            term_nr_str,
            "Client SSE must NOT contain raw secret in sub-workflow node_results",
        )
        self.assertIn(
            "sk-live**",
            term_nr_str,
            "Client SSE must contain masked secret in sub-workflow node_results",
        )

        # b) Active observer SSE response validation
        completed_obs = get_completed_execution_result(execution_id, workflow_id=parent_wid)
        self.assertIsNotNone(
            completed_obs, "Active observer should receive completed execution payload"
        )
        self.assertEqual(completed_obs.get("status"), "cancelled")
        self.assertEqual(len(completed_obs.get("sub_workflow_executions", [])), 1)
        obs_sub = completed_obs["sub_workflow_executions"][0]

        obs_inputs_str = json.dumps(obs_sub.get("inputs"))
        self.assertNotIn(
            secret_token,
            obs_inputs_str,
            "Observer must NOT contain raw secret in sub-workflow inputs",
        )
        self.assertIn(
            "sk-live**",
            obs_inputs_str,
            "Observer must contain masked secret in sub-workflow inputs",
        )

        obs_outputs_str = json.dumps(obs_sub.get("outputs"))
        self.assertNotIn(
            secret_token,
            obs_outputs_str,
            "Observer must NOT contain raw secret in sub-workflow outputs",
        )
        self.assertIn(
            "sk-live**",
            obs_outputs_str,
            "Observer must contain masked secret in sub-workflow outputs",
        )

        obs_nr_str = json.dumps(obs_sub.get("node_results"))
        self.assertNotIn(
            secret_token,
            obs_nr_str,
            "Observer must NOT contain raw secret in sub-workflow node_results",
        )
        self.assertIn(
            "sk-live**",
            obs_nr_str,
            "Observer must contain masked secret in sub-workflow node_results",
        )

        # c) Child ExecutionHistory in PostgreSQL validation
        child_h = None
        for _ in range(50):
            async with async_session_maker() as s:
                child_rows = (
                    (
                        await s.execute(
                            select(ExecutionHistory).where(
                                ExecutionHistory.workflow_id == child_wid
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if child_rows:
                    child_h = child_rows[0]
                    break
            await asyncio.sleep(0.05)

        self.assertIsNotNone(child_h, "Child ExecutionHistory row must be persisted in PostgreSQL")
        db_inputs_str = json.dumps(child_h.inputs)
        self.assertNotIn(
            secret_token,
            db_inputs_str,
            "Child ExecutionHistory.inputs in DB must NOT leak raw secret",
        )
        self.assertIn(
            "sk-live**",
            db_inputs_str,
            "Child ExecutionHistory.inputs in DB must contain masked secret",
        )

        db_outputs_str = json.dumps(child_h.outputs)
        self.assertNotIn(
            secret_token,
            db_outputs_str,
            "Child ExecutionHistory.outputs in DB must NOT leak raw secret",
        )
        self.assertIn(
            "sk-live**",
            db_outputs_str,
            "Child ExecutionHistory.outputs in DB must contain masked secret",
        )

        db_nr_str = json.dumps(child_h.node_results)
        self.assertNotIn(
            secret_token,
            db_nr_str,
            "Child ExecutionHistory.node_results in DB must NOT leak raw secret",
        )
        self.assertIn(
            "sk-live**",
            db_nr_str,
            "Child ExecutionHistory.node_results in DB must contain masked secret",
        )

        # Live execution object must NOT have been mutated
        self.assertEqual(
            sub_exec.inputs["api_key"],
            secret_token,
            "Live SubWorkflowExecution object must not be mutated",
        )
        self.assertEqual(
            sub_exec.outputs["result"],
            f"received {secret_token}",
            "Live SubWorkflowExecution object must not be mutated",
        )
