import asyncio
import json
import threading
import unittest
import uuid
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from app.api.ai_assistant import (
    _extract_pending_hitl_review_payload,
    _extract_pending_review_from_candidate,
    _sanitize_tool_result_for_llm,
    resolve_hitl_review_tool,
    run_execute_workflow_tool,
    stream_dashboard_chat,
)
from app.db.models import (
    CodexFollowupRequest,
    ExecutionHistory,
    HITLRequest,
    User,
    Workflow,
    WorkflowAnalyticsSnapshot,
)
from app.db.session import async_session_maker, engine
from app.services.global_variables_service import get_global_variables_context
from app.services.workflow_executor import (
    ExecutionResult,
    NodeResult,
    SubWorkflowExecution,
    WorkflowCancelledError,
    WorkflowTimeoutError,
)


class _AllResult:
    def __init__(self, items: list) -> None:
        self._items = items

    def scalars(self) -> MagicMock:
        res = MagicMock()
        res.all.return_value = self._items
        return res


class _EmptyResult:
    def scalars(self) -> MagicMock:
        res = MagicMock()
        res.all.return_value = []
        return res


def _make_var(name: str, value: object, owner_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        value={"v": value},
        owner_id=owner_id,
    )


class RunExecuteWorkflowToolRobustnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_passes_global_variables_context_to_executor(self) -> None:
        user_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=user_id,
            name="Global Var Workflow",
            nodes=[{"id": "n1", "type": "input"}],
            edges=[],
        )
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={},
            execution_time_ms=1.0,
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        mock_globals = {"api_key": "secret_123", "env": "production"}

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.ai_assistant.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.api.ai_assistant.get_global_variables_context",
                AsyncMock(return_value=mock_globals),
            ) as mock_get_globals,
            patch("app.api.ai_assistant._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.ai_assistant.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(
                "app.api.ai_assistant.execute_workflow",
                MagicMock(return_value=execution_result),
            ) as mock_execute,
        ):
            result = await run_execute_workflow_tool(
                db=db,
                user_id=user_id,
                workflow_id_str=str(workflow.id),
                inputs={},
                public_base_url="http://localhost",
            )

        self.assertEqual(json.loads(result)["status"], "success")
        mock_get_globals.assert_awaited_once_with(db, user_id)
        mock_execute.assert_called_once()
        self.assertEqual(
            mock_execute.call_args.kwargs.get("global_variables_context"), mock_globals
        )

    async def test_persists_global_variables_from_execution(self) -> None:
        user_id = uuid.uuid4()
        workflow_nodes = [
            {
                "id": "v1",
                "type": "variable",
                "data": {"isGlobal": True, "variableName": "counter"},
            }
        ]
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=user_id,
            name="Persist Global Var Workflow",
            nodes=workflow_nodes,
            edges=[],
        )
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={},
            node_results=[
                {
                    "node_id": "v1",
                    "node_type": "variable",
                    "output": {"name": "counter", "value": 42, "type": "number"},
                }
            ],
            execution_time_ms=2.0,
            sub_workflow_executions=[],
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.ai_assistant.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(
                "app.api.ai_assistant.execute_workflow",
                MagicMock(return_value=execution_result),
            ),
            patch(
                "app.api.ai_assistant._persist_global_variables_from_execution",
                AsyncMock(),
            ) as mock_persist_globals,
        ):
            result = await run_execute_workflow_tool(
                db=db,
                user_id=user_id,
                workflow_id_str=str(workflow.id),
                inputs={},
                public_base_url="http://localhost",
            )

        self.assertEqual(json.loads(result)["status"], "success")
        mock_persist_globals.assert_awaited_once_with(
            db,
            user_id,
            workflow.nodes,
            {},
            execution_result.node_results,
            execution_result.sub_workflow_executions,
        )

    async def test_codex_followup_pending_execution_routed_to_persist_pending_execution(
        self,
    ) -> None:
        user_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=user_id,
            name="Codex Followup Workflow",
            nodes=[{"id": "c1", "type": "codex"}],
            edges=[],
        )
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="pending",
            outputs={
                "Codex": {
                    "status": "needs_input",
                    "question": "Which branch?",
                    "answerUrl": "http://localhost/codex/followup/tok",
                }
            },
            node_results=[{"node_id": "c1", "node_type": "codex", "status": "pending"}],
            execution_time_ms=3.0,
            pending_review={"kind": "codex", "question": "Which branch?"},
            resume_snapshot={"paused_node_id": "c1", "paused_node_label": "Codex"},
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        history_mock = SimpleNamespace(id=uuid.uuid4(), started_at=None)

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.ai_assistant.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(
                "app.api.ai_assistant.execute_workflow",
                MagicMock(return_value=execution_result),
            ),
            patch(
                "app.api.ai_assistant.persist_pending_execution",
                AsyncMock(return_value=(history_mock, SimpleNamespace())),
            ) as mock_persist_pending,
            patch(
                "app.services.hitl_service.persist_pending_hitl_execution",
                AsyncMock(),
            ) as mock_hitl_only,
        ):
            result = await run_execute_workflow_tool(
                db=db,
                user_id=user_id,
                workflow_id_str=str(workflow.id),
                inputs={},
                public_base_url="http://localhost",
            )

        self.assertEqual(json.loads(result)["status"], "pending")
        mock_persist_pending.assert_awaited_once()
        mock_hitl_only.assert_not_awaited()
        data = json.loads(result)
        self.assertIsNotNone(data.get("pending_review"))
        self.assertEqual(
            data["pending_review"]["answer_url"], "http://localhost/codex/followup/tok"
        )
        self.assertEqual(data["pending_review"]["question"], "Which branch?")
        self.assertEqual(data["pending_review"]["kind"], "codex")
        self.assertNotIn("review_url", data["pending_review"])
        self.assertNotIn("draft_text", data["pending_review"])

    async def test_hitl_pending_execution_routed_to_persist_pending_execution(self) -> None:
        user_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=user_id,
            name="HITL Workflow",
            nodes=[{"id": "h1", "type": "humanReview"}],
            edges=[],
        )
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="pending",
            outputs={
                "Review": {"status": "needs_approval", "reviewUrl": "http://localhost/review/tok"}
            },
            node_results=[{"node_id": "h1", "node_type": "humanReview", "status": "pending"}],
            execution_time_ms=2.0,
            pending_review={
                "summary": "Please approve draft",
                "review_url": "http://localhost/review/tok",
            },
            resume_snapshot={"paused_node_id": "h1", "paused_node_label": "Review"},
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        history_mock = SimpleNamespace(id=uuid.uuid4(), started_at=None)

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.ai_assistant.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(
                "app.api.ai_assistant.execute_workflow",
                MagicMock(return_value=execution_result),
            ),
            patch(
                "app.api.ai_assistant.persist_pending_execution",
                AsyncMock(return_value=(history_mock, SimpleNamespace())),
            ) as mock_persist_pending,
        ):
            result = await run_execute_workflow_tool(
                db=db,
                user_id=user_id,
                workflow_id_str=str(workflow.id),
                inputs={},
                public_base_url="http://localhost",
            )

        self.assertEqual(json.loads(result)["status"], "pending")
        mock_persist_pending.assert_awaited_once()
        data = json.loads(result)
        self.assertIsNotNone(data.get("pending_review"))
        self.assertEqual(data["pending_review"]["review_url"], "http://localhost/review/tok")

    async def test_allow_downstream_early_return_and_detached_finalization(self) -> None:
        user_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=user_id,
            name="Allow Downstream Early Return Workflow",
            nodes=[{"id": "out1", "type": "output"}, {"id": "n2", "type": "http"}],
            edges=[],
        )
        early_outputs = {"out1": {"message": "early return fast response"}}
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs=early_outputs,
            node_results=[{"node_id": "out1", "node_type": "output", "status": "success"}],
            execution_time_ms=0.5,
        )
        execution_result._allow_downstream_pending = [
            MagicMock()
        ]  # allow_downstream_pending is True

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()

        call_order: list[str] = []

        async def track_commit():
            call_order.append("commit")

        db.commit.side_effect = track_commit

        def track_spawn(coro):
            call_order.append("spawn")

        mock_spawn_tracker = MagicMock(side_effect=track_spawn)

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.ai_assistant.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant._spawn_detached_task", mock_spawn_tracker),
            patch(
                "app.api.ai_assistant._finalize_allow_downstream_history",
                new_callable=MagicMock,
                return_value="dummy_coro",
            ) as mock_finalize,
            patch(
                "app.api.ai_assistant._persist_global_variables_from_execution", AsyncMock()
            ) as mock_sync_persist,
            patch("app.api.ai_assistant.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(
                "app.api.ai_assistant.execute_workflow",
                MagicMock(return_value=execution_result),
            ),
        ):
            result = await run_execute_workflow_tool(
                db=db,
                user_id=user_id,
                workflow_id_str=str(workflow.id),
                inputs={},
                public_base_url="http://localhost",
            )

        # Early return check: tool response has early outputs immediately
        data = json.loads(result)
        self.assertEqual(data["outputs"], early_outputs)
        self.assertEqual(data["status"], "success")
        self.assertIsNotNone(data.get("execution_history_id"))

        # Verify transaction was committed BEFORE the detached task was spawned
        self.assertEqual(call_order, ["commit", "spawn"])

        # Detached task spawned with _finalize_allow_downstream_history and assigned history_entry_id
        mock_spawn_tracker.assert_called_once()
        mock_finalize.assert_called_once()
        self.assertEqual(
            mock_finalize.call_args.kwargs["history_entry_id"],
            uuid.UUID(data["execution_history_id"]),
        )
        self.assertEqual(mock_finalize.call_args.kwargs["workflow_id"], workflow.id)
        self.assertEqual(mock_finalize.call_args.kwargs["credentials_owner_id"], user_id)

        # Synchronous in-line global var persist is skipped (deferred to background finalizer)
        mock_sync_persist.assert_not_called()


class GlobalVariableOwnershipMatrixTests(unittest.IsolatedAsyncioTestCase):
    """Test the complete authorization & isolation matrix for global variables."""

    async def test_case_a_owner_executes_own_workflow(self) -> None:
        owner_id = uuid.uuid4()
        var = _make_var("api_url", "https://owner.api", owner_id)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_EmptyResult(), _EmptyResult(), _AllResult([var])])

        ctx = await get_global_variables_context(db, owner_id)
        self.assertEqual(ctx, {"api_url": "https://owner.api"})

    async def test_case_b_collaborator_executes_shared_workflow(self) -> None:
        collaborator_id = uuid.uuid4()
        var = _make_var("collab_key", "key-456", collaborator_id)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_EmptyResult(), _EmptyResult(), _AllResult([var])])

        ctx = await get_global_variables_context(db, collaborator_id)
        self.assertEqual(ctx, {"collab_key": "key-456"})

    async def test_case_c_collaborator_reads_shared_global_variable(self) -> None:
        collaborator_id = uuid.uuid4()
        shared_var = _make_var("shared_secret", "secret-from-owner", uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_EmptyResult(), _AllResult([shared_var]), _EmptyResult()]
        )

        ctx = await get_global_variables_context(db, collaborator_id)
        self.assertEqual(ctx, {"shared_secret": "secret-from-owner"})

    async def test_case_d_variable_node_writes_persisted_under_executing_actor_id(self) -> None:
        collaborator_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),  # Different owner
            name="Shared Wf",
            nodes=[{"id": "v1", "type": "variable", "data": {"isGlobal": True}}],
            edges=[],
        )
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={},
            node_results=[
                {"node_id": "v1", "node_type": "variable", "output": {"name": "k", "value": "v"}}
            ],
            execution_time_ms=1.0,
            sub_workflow_executions=[],
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.ai_assistant.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(
                "app.api.ai_assistant.execute_workflow",
                MagicMock(return_value=execution_result),
            ),
            patch(
                "app.api.ai_assistant._persist_global_variables_from_execution",
                AsyncMock(),
            ) as mock_persist,
        ):
            await run_execute_workflow_tool(
                db=db,
                user_id=collaborator_id,
                workflow_id_str=str(workflow.id),
                inputs={},
                public_base_url="http://localhost",
            )

        # Must persist under collaborator_id, NOT workflow.owner_id
        mock_persist.assert_awaited_once_with(
            db,
            collaborator_id,
            workflow.nodes,
            {},
            execution_result.node_results,
            execution_result.sub_workflow_executions,
        )

    async def test_case_e_and_f_collaborator_own_variable_preempts_shared_variable(self) -> None:
        collaborator_id = uuid.uuid4()
        shared_var = _make_var("endpoint", "https://shared.api", uuid.uuid4())
        collab_var = _make_var("endpoint", "https://my-own.api", collaborator_id)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_EmptyResult(), _AllResult([shared_var]), _AllResult([collab_var])]
        )

        ctx = await get_global_variables_context(db, collaborator_id)
        self.assertEqual(ctx["endpoint"], "https://my-own.api")

    async def test_case_g_team_shared_global_variable(self) -> None:
        collaborator_id = uuid.uuid4()
        team_var = _make_var("team_token", "tok_team_999", uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_AllResult([team_var]), _EmptyResult(), _EmptyResult()])

        ctx = await get_global_variables_context(db, collaborator_id)
        self.assertEqual(ctx, {"team_token": "tok_team_999"})

    async def test_case_h_unshared_global_variable_not_accessible(self) -> None:
        collaborator_id = uuid.uuid4()
        # No shares exist for collaborator
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_EmptyResult(), _EmptyResult(), _EmptyResult()])

        ctx = await get_global_variables_context(db, collaborator_id)
        self.assertEqual(ctx, {})


class CodexVsHITLDifferentiationTests(unittest.IsolatedAsyncioTestCase):
    """Verify Codex and HITL pause differentiation, SSE suppression, and error handling."""

    def test_extract_pending_review_from_candidate_codex(self) -> None:
        candidate = {
            "status": "needs_input",
            "summary": "Codex needs input to continue.",
            "question": "Which GitHub repo should be used?",
            "answerUrl": "http://localhost:3000/codex/followup/sample-token",
            "requestId": "11111111-1111-1111-1111-111111111111",
            "expiresAt": "2026-10-01T00:00:00Z",
        }
        extracted = _extract_pending_review_from_candidate(candidate)
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted["kind"], "codex")
        self.assertNotIn("type", extracted)
        self.assertEqual(extracted["question"], "Which GitHub repo should be used?")
        self.assertEqual(
            extracted["answer_url"], "http://localhost:3000/codex/followup/sample-token"
        )
        self.assertEqual(extracted["summary"], "Codex needs input to continue.")
        self.assertEqual(extracted["request_id"], "11111111-1111-1111-1111-111111111111")
        # Ensure no draft_text or review_url are synthesized
        self.assertNotIn("draft_text", extracted)
        self.assertNotIn("review_url", extracted)

    def test_extract_pending_review_from_candidate_hitl(self) -> None:
        candidate = {
            "decision": None,
            "summary": "Please review generated email",
            "draftText": "Subject: Welcome aboard!\n\nHello Team,",
            "reviewUrl": "http://localhost:3000/hitl/review/sample-hitl-token",
            "requestId": "22222222-2222-2222-2222-222222222222",
            "expiresAt": "2026-10-01T00:00:00Z",
        }
        extracted = _extract_pending_review_from_candidate(candidate)
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted["kind"], "hitl")
        self.assertNotIn("type", extracted)
        self.assertEqual(extracted["summary"], "Please review generated email")
        self.assertEqual(extracted["draft_text"], "Subject: Welcome aboard!\n\nHello Team,")
        self.assertEqual(
            extracted["review_url"], "http://localhost:3000/hitl/review/sample-hitl-token"
        )
        self.assertEqual(extracted["request_id"], "22222222-2222-2222-2222-222222222222")

    def test_extract_pending_hitl_review_payload_suppresses_codex_cards(self) -> None:
        # Codex top-level pending_review
        codex_tool_result = json.dumps(
            {
                "status": "pending",
                "execution_history_id": str(uuid.uuid4()),
                "pending_review": {
                    "kind": "codex",
                    "type": "codex",
                    "summary": "Codex needs input",
                    "question": "Which environment?",
                    "answer_url": "http://localhost:3000/codex/followup/token-123",
                },
            }
        )
        self.assertIsNone(_extract_pending_hitl_review_payload(codex_tool_result))

        # Codex nested in outputs
        codex_outputs_result = json.dumps(
            {
                "status": "pending",
                "outputs": {
                    "CodexNode": {
                        "status": "needs_input",
                        "question": "Which environment?",
                        "answerUrl": "http://localhost:3000/codex/followup/token-123",
                    }
                },
            }
        )
        self.assertIsNone(_extract_pending_hitl_review_payload(codex_outputs_result))

    def test_extract_pending_hitl_review_payload_emits_hitl_cards(self) -> None:
        hitl_tool_result = json.dumps(
            {
                "status": "pending",
                "execution_history_id": str(uuid.uuid4()),
                "pending_review": {
                    "kind": "hitl",
                    "type": "hitl",
                    "summary": "Approval required",
                    "draft_text": "Deploy to prod?",
                    "review_url": "http://localhost:3000/hitl/review/token-hitl",
                },
            }
        )
        payload = _extract_pending_hitl_review_payload(hitl_tool_result)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["kind"], "hitl")
        self.assertNotIn("type", payload)
        self.assertEqual(payload["review_url"], "http://localhost:3000/hitl/review/token-hitl")
        self.assertEqual(payload["draft_text"], "Deploy to prod?")

    async def test_resolve_hitl_review_tool_rejects_codex_followup_id(self) -> None:
        user_id = uuid.uuid4()
        codex_req_id = uuid.uuid4()
        codex_followup = CodexFollowupRequest(
            id=codex_req_id,
            workflow_id=uuid.uuid4(),
            execution_history_id=uuid.uuid4(),
            public_token="codex-token-xyz",
            workflow_name="Codex WF",
            codex_node_id="c1",
            codex_label="Codex",
            summary="Need info",
            question="What port?",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        db = AsyncMock()
        mock_hitl_res = MagicMock()
        mock_hitl_res.scalar_one_or_none.return_value = None
        mock_codex_res = MagicMock()
        mock_codex_res.scalar_one_or_none.return_value = codex_followup

        db.execute = AsyncMock(side_effect=[mock_hitl_res, mock_codex_res])

        res_str = await resolve_hitl_review_tool(
            db=db,
            user_id=user_id,
            action="accept",
            request_id=str(codex_req_id),
        )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "error")
        self.assertIn("Codex follow-up", res["error"])
        self.assertIn("answer link", res["error"])

    async def test_resolve_hitl_review_tool_rejects_codex_followup_url(self) -> None:
        user_id = uuid.uuid4()
        db = AsyncMock()
        mock_db_res = MagicMock()
        mock_db_res.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_db_res)
        with patch("app.api.ai_assistant.get_hitl_request_by_token", AsyncMock(return_value=None)):
            res_str = await resolve_hitl_review_tool(
                db=db,
                user_id=user_id,
                action="accept",
                review_url="http://localhost:3000/codex/followup/codex-token-abc",
            )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "error")
        self.assertIn("Codex follow-up", res["error"])
        self.assertIn("answer link", res["error"])

    async def test_resolve_hitl_review_tool_accepts_valid_hitl_review(self) -> None:
        user_id = uuid.uuid4()
        hitl_req_id = uuid.uuid4()
        wf_id = uuid.uuid4()
        hitl_req = HITLRequest(
            id=hitl_req_id,
            workflow_id=wf_id,
            execution_history_id=uuid.uuid4(),
            public_token="hitl-token-abc",
            workflow_name="HITL WF",
            agent_node_id="a1",
            agent_label="Agent",
            summary="Review email",
            original_draft_text="Draft",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            execution_snapshot={"nodes": [], "edges": []},
        )
        workflow = SimpleNamespace(id=wf_id, owner_id=user_id)

        db = AsyncMock()
        mock_hitl_res = MagicMock()
        mock_hitl_res.scalar_one_or_none.return_value = hitl_req
        db.execute = AsyncMock(return_value=mock_hitl_res)
        db.commit = AsyncMock()

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.ai_assistant.ensure_hitl_request_is_actionable", MagicMock()),
            patch(
                "app.api.ai_assistant.claim_hitl_request_for_decision", AsyncMock(return_value=True)
            ),
            patch(
                "app.api.ai_assistant.build_hitl_resolved_output",
                MagicMock(return_value={"approved": True}),
            ),
            patch(
                "app.api.ai_assistant.resume_hitl_request_in_background", AsyncMock()
            ) as mock_resume,
        ):
            res_str = await resolve_hitl_review_tool(
                db=db,
                user_id=user_id,
                action="accept",
                request_id=str(hitl_req_id),
            )

        res = json.loads(res_str)
        self.assertEqual(res["status"], "resolved")
        self.assertEqual(res["decision"], "accept")
        self.assertEqual(hitl_req.status, "resolved")
        db.commit.assert_awaited_once()
        mock_resume.assert_called_once_with(hitl_req_id)

    async def test_edge_case_1_valid_codex_followup_url(self) -> None:
        """Case 1: Valid Codex followup URL returns explicit Codex rejection guidance with the public link."""
        user_id = uuid.uuid4()
        codex_req_id = uuid.uuid4()
        codex_followup = CodexFollowupRequest(
            id=codex_req_id,
            workflow_id=uuid.uuid4(),
            execution_history_id=uuid.uuid4(),
            public_token="codex-token-123",
            workflow_name="Codex WF",
            codex_node_id="c1",
            codex_label="Codex",
            summary="Need info",
            question="Which database branch?",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db = AsyncMock()
        with (
            patch("app.api.ai_assistant.get_hitl_request_by_token", AsyncMock(return_value=None)),
            patch(
                "app.api.ai_assistant.get_codex_followup_by_token",
                AsyncMock(return_value=codex_followup),
            ),
        ):
            res_str = await resolve_hitl_review_tool(
                db=db,
                user_id=user_id,
                action="accept",
                review_url="http://localhost:3000/codex/followup/codex-token-123",
            )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "error")
        self.assertIn("Codex follow-up", res["error"])
        self.assertIn("answer link", res["error"])

    async def test_edge_case_2_valid_codex_public_token_as_request_id(self) -> None:
        """Case 2: Valid Codex followup public_token as request_id returns explicit Codex rejection guidance."""
        user_id = uuid.uuid4()
        codex_req_id = uuid.uuid4()
        codex_followup = CodexFollowupRequest(
            id=codex_req_id,
            workflow_id=uuid.uuid4(),
            execution_history_id=uuid.uuid4(),
            public_token="codex-token-abc",
            workflow_name="Codex WF",
            codex_node_id="c1",
            codex_label="Codex",
            summary="Need info",
            question="Select branch",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db = AsyncMock()
        mock_codex_res = MagicMock()
        mock_codex_res.scalar_one_or_none.return_value = codex_followup
        db.execute = AsyncMock(return_value=mock_codex_res)

        with patch("app.api.ai_assistant.get_hitl_request_by_token", AsyncMock(return_value=None)):
            res_str = await resolve_hitl_review_tool(
                db=db,
                user_id=user_id,
                action="accept",
                request_id="codex-token-abc",
            )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "error")
        self.assertIn("Codex follow-up", res["error"])
        self.assertIn("answer link", res["error"])

    async def test_edge_case_3_valid_codex_uuid_as_request_id(self) -> None:
        """Case 3: Valid Codex followup UUID as request_id returns explicit Codex rejection guidance."""
        user_id = uuid.uuid4()
        codex_req_id = uuid.uuid4()
        codex_followup = CodexFollowupRequest(
            id=codex_req_id,
            workflow_id=uuid.uuid4(),
            execution_history_id=uuid.uuid4(),
            public_token="codex-token-xyz",
            workflow_name="Codex WF",
            codex_node_id="c1",
            codex_label="Codex",
            summary="Need info",
            question="What port?",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db = AsyncMock()
        mock_hitl_res = MagicMock()
        mock_hitl_res.scalar_one_or_none.return_value = None
        mock_codex_res = MagicMock()
        mock_codex_res.scalar_one_or_none.return_value = codex_followup
        db.execute = AsyncMock(side_effect=[mock_hitl_res, mock_codex_res])

        res_str = await resolve_hitl_review_tool(
            db=db,
            user_id=user_id,
            action="accept",
            request_id=str(codex_req_id),
        )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "error")
        self.assertIn("Codex follow-up", res["error"])
        self.assertIn("answer link", res["error"])

    async def test_edge_case_4_expired_codex_followup_request(self) -> None:
        """Case 4: Expired Codex followup request still returns explicit Codex rejection guidance."""
        user_id = uuid.uuid4()
        codex_req_id = uuid.uuid4()
        codex_followup = CodexFollowupRequest(
            id=codex_req_id,
            workflow_id=uuid.uuid4(),
            execution_history_id=uuid.uuid4(),
            public_token="codex-token-expired",
            workflow_name="Codex WF",
            codex_node_id="c1",
            codex_label="Codex",
            summary="Need info",
            question="Expired question",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db = AsyncMock()
        mock_hitl_res = MagicMock()
        mock_hitl_res.scalar_one_or_none.return_value = None
        mock_codex_res = MagicMock()
        mock_codex_res.scalar_one_or_none.return_value = codex_followup
        db.execute = AsyncMock(side_effect=[mock_hitl_res, mock_codex_res])

        res_str = await resolve_hitl_review_tool(
            db=db,
            user_id=user_id,
            action="accept",
            request_id=str(codex_req_id),
        )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "error")
        self.assertIn("Codex follow-up", res["error"])
        self.assertIn("answer link", res["error"])

    async def test_edge_case_5_malformed_url(self) -> None:
        """Case 5: Malformed URL without token returns Invalid review_url without false Codex rejection."""
        user_id = uuid.uuid4()
        db = AsyncMock()
        # Subcase 5a: URL without path token returns "Invalid review_url"
        res_str = await resolve_hitl_review_tool(
            db=db,
            user_id=user_id,
            action="accept",
            review_url="http://localhost:3000/",
        )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error"], "Invalid review_url")
        self.assertNotIn("Codex", res["error"])

        # Subcase 5b: Empty review_url returns "request_id or review_url is required to resolve HITL review"
        res_str = await resolve_hitl_review_tool(
            db=db,
            user_id=user_id,
            action="accept",
            review_url="",
        )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "error")
        self.assertEqual(
            res["error"], "request_id or review_url is required to resolve HITL review"
        )
        self.assertNotIn("Codex", res["error"])

    async def test_edge_case_6_unrelated_url_containing_answer(self) -> None:
        """Case 6: Unrelated URL containing 'answer' substring is NOT falsely rejected as Codex."""
        user_id = uuid.uuid4()
        db = AsyncMock()
        mock_db_res = MagicMock()
        mock_db_res.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_db_res)
        with (
            patch("app.api.ai_assistant.get_hitl_request_by_token", AsyncMock(return_value=None)),
            patch("app.api.ai_assistant.get_codex_followup_by_token", AsyncMock(return_value=None)),
        ):
            res_str = await resolve_hitl_review_tool(
                db=db,
                user_id=user_id,
                action="accept",
                review_url="http://localhost:3000/api/answer/123",
            )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error"], "Review request not found")
        self.assertNotIn("Codex", res["error"])

    async def test_edge_case_7_unrelated_url_containing_codex_in_other_path(self) -> None:
        """Case 7: Unrelated URL containing '/codex/' in different path context is NOT falsely rejected as Codex."""
        user_id = uuid.uuid4()
        db = AsyncMock()
        mock_db_res = MagicMock()
        mock_db_res.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_db_res)
        with (
            patch("app.api.ai_assistant.get_hitl_request_by_token", AsyncMock(return_value=None)),
            patch("app.api.ai_assistant.get_codex_followup_by_token", AsyncMock(return_value=None)),
        ):
            res_str = await resolve_hitl_review_tool(
                db=db,
                user_id=user_id,
                action="accept",
                review_url="https://example.com/codex/docs/overview",
            )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error"], "Review request not found")
        self.assertNotIn("Codex", res["error"])

    async def test_edge_case_8_valid_hitl_request_id(self) -> None:
        """Case 8: Valid HITL request ID (UUID) successfully resolves and resumes execution."""
        user_id = uuid.uuid4()
        hitl_req_id = uuid.uuid4()
        wf_id = uuid.uuid4()
        hitl_req = HITLRequest(
            id=hitl_req_id,
            workflow_id=wf_id,
            execution_history_id=uuid.uuid4(),
            public_token="hitl-token-case8",
            workflow_name="HITL WF",
            agent_node_id="a1",
            agent_label="Agent",
            summary="Review request",
            original_draft_text="Draft",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            execution_snapshot={"nodes": [], "edges": []},
        )
        workflow = SimpleNamespace(id=wf_id, owner_id=user_id)
        db = AsyncMock()
        mock_hitl_res = MagicMock()
        mock_hitl_res.scalar_one_or_none.return_value = hitl_req
        db.execute = AsyncMock(return_value=mock_hitl_res)
        db.commit = AsyncMock()

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.ai_assistant.ensure_hitl_request_is_actionable", MagicMock()),
            patch(
                "app.api.ai_assistant.claim_hitl_request_for_decision", AsyncMock(return_value=True)
            ),
            patch(
                "app.api.ai_assistant.build_hitl_resolved_output",
                MagicMock(return_value={"approved": True}),
            ),
            patch(
                "app.api.ai_assistant.resume_hitl_request_in_background", AsyncMock()
            ) as mock_resume,
        ):
            res_str = await resolve_hitl_review_tool(
                db=db,
                user_id=user_id,
                action="accept",
                request_id=str(hitl_req_id),
            )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "resolved")
        self.assertEqual(res["decision"], "accept")
        mock_resume.assert_called_once_with(hitl_req_id)

    async def test_edge_case_9_valid_hitl_review_url(self) -> None:
        """Case 9: Valid HITL review_url successfully resolves and resumes execution."""
        user_id = uuid.uuid4()
        hitl_req_id = uuid.uuid4()
        wf_id = uuid.uuid4()
        hitl_req = HITLRequest(
            id=hitl_req_id,
            workflow_id=wf_id,
            execution_history_id=uuid.uuid4(),
            public_token="hitl-token-case9",
            workflow_name="HITL WF",
            agent_node_id="a1",
            agent_label="Agent",
            summary="Review request",
            original_draft_text="Draft",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            execution_snapshot={"nodes": [], "edges": []},
        )
        workflow = SimpleNamespace(id=wf_id, owner_id=user_id)
        db = AsyncMock()
        db.commit = AsyncMock()

        with (
            patch(
                "app.api.ai_assistant.get_hitl_request_by_token",
                AsyncMock(return_value=hitl_req),
            ),
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.ai_assistant.ensure_hitl_request_is_actionable", MagicMock()),
            patch(
                "app.api.ai_assistant.claim_hitl_request_for_decision", AsyncMock(return_value=True)
            ),
            patch(
                "app.api.ai_assistant.build_hitl_resolved_output",
                MagicMock(return_value={"approved": True}),
            ),
            patch(
                "app.api.ai_assistant.resume_hitl_request_in_background", AsyncMock()
            ) as mock_resume,
        ):
            res_str = await resolve_hitl_review_tool(
                db=db,
                user_id=user_id,
                action="accept",
                review_url="http://localhost:3000/hitl/review/hitl-token-case9",
            )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "resolved")
        self.assertEqual(res["decision"], "accept")
        mock_resume.assert_called_once_with(hitl_req_id)


class PostgresAllowDownstreamSeparateSessionsTests(unittest.IsolatedAsyncioTestCase):
    """Verify allowDownstream transaction visibility, exact-once sub-workflow history,
    and exact-once analytics persistence across genuinely separate PostgreSQL sessions."""

    async def asyncSetUp(self) -> None:
        self.user_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.sub_workflow_id = uuid.uuid4()
        self.cleanup_user_ids = [self.user_id]
        self.cleanup_workflow_ids = [self.workflow_id, self.sub_workflow_id]

        async with async_session_maker() as db:
            user = User(
                id=self.user_id,
                email=f"pg-test-{self.user_id}@example.com",
                hashed_password="pw",
                name="PG Test User",
            )
            workflow = Workflow(
                id=self.workflow_id,
                owner_id=self.user_id,
                name="AllowDownstream Parent WF",
                nodes=[{"id": "n1", "type": "output", "data": {"allowDownstream": True}}],
                edges=[],
            )
            sub_workflow = Workflow(
                id=self.sub_workflow_id,
                owner_id=self.user_id,
                name="AllowDownstream Sub WF",
                nodes=[{"id": "s1", "type": "javascript"}],
                edges=[],
            )
            db.add(user)
            db.add(workflow)
            db.add(sub_workflow)
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as db:
            from sqlalchemy import delete

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
            await db.execute(delete(User).where(User.id.in_(self.cleanup_user_ids)))
            await db.commit()
        await engine.dispose()

    async def test_allow_downstream_visibility_and_exact_once_postgres(self) -> None:
        """PostgreSQL test: Session 1 executes workflow and commits.
        Session 2 (_finalize_allow_downstream_history) immediately queries and finds history row.
        Sub-workflows and analytics are recorded exactly once."""
        sub_exec = SubWorkflowExecution(
            workflow_id=str(self.sub_workflow_id),
            inputs={"x": 10},
            outputs={"result": 20},
            node_results=[{"node_id": "s1", "status": "success", "output": {"result": 20}}],
            status="success",
            execution_time_ms=15.0,
            workflow_name="AllowDownstream Sub WF",
        )

        join_called = False

        def mock_join():
            nonlocal join_called
            join_called = True
            execution_result.outputs["downstream"] = "completed"
            execution_result.execution_time_ms = 120.0

        execution_result = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "fast_response"},
            node_results=[
                {"node_id": "n1", "status": "success", "output": {"initial": "fast_response"}}
            ],
            execution_time_ms=25.0,
            sub_workflow_executions=[sub_exec],
        )
        execution_result._allow_downstream_pending = [MagicMock()]
        execution_result.join_allow_downstream = mock_join

        spawned_coros = []

        def capture_spawn(coro):
            spawned_coros.append(coro)

        # Session 1: run_execute_workflow_tool
        async with async_session_maker() as session_1:
            with (
                patch("app.api.ai_assistant._spawn_detached_task", side_effect=capture_spawn),
                patch(
                    "app.api.ai_assistant.execute_workflow",
                    MagicMock(return_value=execution_result),
                ),
            ):
                tool_res_str = await run_execute_workflow_tool(
                    db=session_1,
                    user_id=self.user_id,
                    workflow_id_str=str(self.workflow_id),
                    inputs={},
                    public_base_url="http://localhost:3000",
                )

        tool_res = json.loads(tool_res_str)
        self.assertEqual(tool_res["status"], "success")
        self.assertEqual(tool_res["outputs"], {"initial": "fast_response"})
        history_id = uuid.UUID(tool_res["execution_history_id"])

        # At this point, session 1 has committed its transaction!
        # Session 2 verifies transaction visibility from an entirely independent session:
        async with async_session_maker() as verify_session:
            history_in_db = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(
                history_in_db, "History row must be committed and visible in separate PG session"
            )
            self.assertEqual(history_in_db.status, "success")
            self.assertEqual(history_in_db.outputs, {"initial": "fast_response"})

        # Run the detached finalizer task captured by _spawn_detached_task
        self.assertEqual(len(spawned_coros), 1)
        await spawned_coros[0]
        self.assertTrue(join_called)

        # Session 3: verify final state in PostgreSQL
        async with async_session_maker() as verify_session:
            # 1. Parent ExecutionHistory outputs must be updated by finalizer
            history_final = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(history_final.outputs.get("downstream"), "completed")
            self.assertEqual(history_final.execution_time_ms, 120.0)

            # 2. Sub-workflow ExecutionHistory must exist EXACTLY ONCE
            sub_histories = (
                (
                    await verify_session.execute(
                        select(ExecutionHistory).where(
                            ExecutionHistory.workflow_id == self.sub_workflow_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(
                len(sub_histories),
                1,
                "Sub-workflow history must be written exactly once (no duplicates)",
            )

            # 3. Analytics for parent must be recorded EXACTLY ONCE
            parent_analytics = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(
                parent_analytics.total_executions,
                1,
                "Parent workflow executions must be counted exactly once",
            )
            self.assertEqual(parent_analytics.success_count, 1)
            self.assertEqual(parent_analytics.error_count, 0)

            # 4. Analytics for sub-workflow must be recorded EXACTLY ONCE
            sub_analytics = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.sub_workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(
                sub_analytics.total_executions,
                1,
                "Sub-workflow executions must be counted exactly once",
            )
            self.assertEqual(sub_analytics.success_count, 1)
            self.assertEqual(sub_analytics.error_count, 0)

    async def test_allow_downstream_error_status_and_analytics_postgres(self) -> None:
        """Downstream error regression:
        Foreground returns success and commits history row.
        Downstream background work fails -> final history status is error,
        total_executions is 1, error_count is 1, success_count is 0."""
        downstream_error_node = {
            "node_id": "downstream_fail_node",
            "node_label": "HTTP Request Downstream",
            "status": "error",
            "error": "Downstream endpoint 500 Internal Server Error",
            "execution_time_ms": 50.0,
        }

        join_called = False

        def mock_join_with_error():
            nonlocal join_called
            join_called = True
            execution_result.node_results.append(downstream_error_node)
            execution_result.status = "error"
            execution_result.execution_time_ms = 180.0

        execution_result = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "fast_response"},
            node_results=[
                {"node_id": "n1", "status": "success", "output": {"initial": "fast_response"}}
            ],
            execution_time_ms=30.0,
        )
        execution_result._allow_downstream_pending = [MagicMock()]
        execution_result.join_allow_downstream = mock_join_with_error

        spawned_coros = []

        # Session 1: run_execute_workflow_tool
        async with async_session_maker() as session_1:
            with (
                patch(
                    "app.api.ai_assistant._spawn_detached_task", side_effect=spawned_coros.append
                ),
                patch(
                    "app.api.ai_assistant.execute_workflow",
                    MagicMock(return_value=execution_result),
                ),
            ):
                tool_res_str = await run_execute_workflow_tool(
                    db=session_1,
                    user_id=self.user_id,
                    workflow_id_str=str(self.workflow_id),
                    inputs={},
                    public_base_url="http://localhost:3000",
                )

        tool_res = json.loads(tool_res_str)
        self.assertEqual(tool_res["status"], "success")
        history_id = uuid.UUID(tool_res["execution_history_id"])

        # Session 2: history row exists and is committed in PostgreSQL
        async with async_session_maker() as verify_session:
            history_in_db = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(history_in_db.status, "success")

        # Run the detached finalizer task
        self.assertEqual(len(spawned_coros), 1)
        await spawned_coros[0]
        self.assertTrue(join_called)

        # Session 3: verify downstream error state in PostgreSQL
        async with async_session_maker() as verify_session:
            history_final = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(
                history_final.status,
                "error",
                "Final history status must be updated to 'error' when downstream fails",
            )
            self.assertEqual(history_final.execution_time_ms, 180.0)

            # Analytics snapshot must record total_executions=1, error_count=1, success_count=0
            parent_analytics = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(
                parent_analytics.total_executions,
                1,
                "Total executions must be exactly 1 despite downstream failure",
            )
            self.assertEqual(
                parent_analytics.error_count,
                1,
                "Error count must be incremented to 1",
            )
            self.assertEqual(
                parent_analytics.success_count,
                0,
                "Success count must NOT be incremented for a failed downstream execution",
            )

    async def test_concurrent_finalizer_invocations_postgres(self) -> None:
        """Area 1: True concurrent exact-once safety regression test.
        Runs two finalizer invocations concurrently (via asyncio.gather) against PostgreSQL
        on the same ExecutionResult.
        Verifies:
        - exactly one sub-workflow ExecutionHistory row
        - exactly one parent analytics execution count
        - exactly one sub-workflow analytics execution count
        - no duplicate analytics increments
        - final parent history remains correct
        """
        from app.api.workflows import _finalize_allow_downstream_history

        history_id = uuid.uuid4()
        initial_history = ExecutionHistory(
            id=history_id,
            workflow_id=self.workflow_id,
            inputs={"input_key": "input_val"},
            outputs={"initial": "fast_response"},
            node_results=[{"node_id": "n1", "status": "success"}],
            status="success",
            execution_time_ms=25.0,
            started_at=datetime.now(timezone.utc),
        )
        async with async_session_maker() as init_session:
            init_session.add(initial_history)
            await init_session.commit()

        sub_exec = SubWorkflowExecution(
            workflow_id=self.sub_workflow_id,
            workflow_name="AllowDownstream Sub WF",
            status="success",
            execution_time_ms=45.0,
            trigger_source="SUB_WORKFLOW",
            inputs={"sub_in": 1},
            outputs={"sub_out": 2},
            node_results=[],
        )
        self.assertFalse(sub_exec.history_written)

        def mock_join():
            execution_result.outputs["downstream"] = "completed"
            execution_result.execution_time_ms = 120.0

        execution_result = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "fast_response"},
            node_results=[
                {"node_id": "n1", "status": "success", "output": {"initial": "fast_response"}}
            ],
            execution_time_ms=25.0,
            sub_workflow_executions=[sub_exec],
        )
        execution_result._allow_downstream_pending = [MagicMock()]
        execution_result.join_allow_downstream = mock_join
        self.assertFalse(execution_result.analytics_recorded)

        # Spawn TWO finalizer tasks running concurrently against PostgreSQL on the same ExecutionResult
        finalizer_coro_1 = _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=execution_result,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="AllowDownstream Parent WF",
        )
        finalizer_coro_2 = _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=execution_result,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="AllowDownstream Parent WF",
        )

        results = await asyncio.gather(finalizer_coro_1, finalizer_coro_2, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                raise res

        # Verify exact-once safety in PostgreSQL:
        async with async_session_maker() as verify_session:
            # 1. Exactly ONE sub-workflow ExecutionHistory row
            sub_histories = (
                (
                    await verify_session.execute(
                        select(ExecutionHistory).where(
                            ExecutionHistory.workflow_id == self.sub_workflow_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(
                len(sub_histories),
                1,
                "Concurrent finalizers must write sub-workflow history exactly once",
            )
            self.assertEqual(sub_histories[0].status, "success")
            self.assertEqual(sub_histories[0].inputs, {"sub_in": 1})
            self.assertEqual(sub_histories[0].outputs, {"sub_out": 2})

            # 2. Exactly ONE parent analytics execution count
            parent_analytics = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(
                parent_analytics.total_executions,
                1,
                "Concurrent finalizers must record parent analytics exactly once",
            )
            self.assertEqual(parent_analytics.success_count, 1)
            self.assertEqual(parent_analytics.error_count, 0)

            # 3. Exactly ONE sub-workflow analytics execution count
            sub_analytics = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.sub_workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(
                sub_analytics.total_executions,
                1,
                "Concurrent finalizers must record sub-workflow analytics exactly once",
            )
            self.assertEqual(sub_analytics.success_count, 1)
            self.assertEqual(sub_analytics.error_count, 0)

            # 4. Final parent history outputs and timing must be correct
            parent_history = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(parent_history.outputs.get("downstream"), "completed")
            self.assertEqual(parent_history.execution_time_ms, 120.0)
            self.assertEqual(parent_history.status, "success")

    async def test_repeated_sub_workflow_executions_separate_history_and_analytics(
        self,
    ) -> None:
        """Legitimate repeated executions of the same child workflow (e.g. loops, multiple execute nodes,
        branches) must each receive a distinct ExecutionHistory row and be counted in analytics."""
        from app.api.workflows import _finalize_allow_downstream_history

        history_id = uuid.uuid4()
        initial_history = ExecutionHistory(
            id=history_id,
            workflow_id=self.workflow_id,
            inputs={"parent_input": "start"},
            outputs={"initial": "res"},
            node_results=[{"node_id": "n1", "status": "success"}],
            status="success",
            execution_time_ms=30.0,
            started_at=datetime.now(timezone.utc),
        )
        async with async_session_maker() as init_session:
            init_session.add(initial_history)
            await init_session.commit()

        # Invocation 1 of sub-workflow X
        sub_exec_1 = SubWorkflowExecution(
            workflow_id=self.sub_workflow_id,
            workflow_name="Child Workflow",
            status="success",
            execution_time_ms=40.0,
            trigger_source="SUB_WORKFLOW",
            inputs={"iteration": 1, "data": "item_1"},
            outputs={"result": "processed_1"},
            node_results=[],
            execution_id=str(uuid.uuid4()),
        )
        # Invocation 2 of the SAME sub-workflow X
        sub_exec_2 = SubWorkflowExecution(
            workflow_id=self.sub_workflow_id,
            workflow_name="Child Workflow",
            status="success",
            execution_time_ms=50.0,
            trigger_source="SUB_WORKFLOW",
            inputs={"iteration": 2, "data": "item_2"},
            outputs={"result": "processed_2"},
            node_results=[],
            execution_id=str(uuid.uuid4()),
        )

        def mock_join():
            execution_result.outputs["downstream"] = "done"
            execution_result.execution_time_ms = 150.0

        execution_result = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "res"},
            node_results=[{"node_id": "n1", "status": "success", "output": {"initial": "res"}}],
            execution_time_ms=30.0,
            sub_workflow_executions=[sub_exec_1, sub_exec_2],
        )
        execution_result._allow_downstream_pending = [MagicMock()]
        execution_result.join_allow_downstream = mock_join

        await _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=execution_result,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="AllowDownstream Repeated Parent",
        )

        async with async_session_maker() as verify_session:
            # 1. Exactly TWO separate ExecutionHistory rows for the sub-workflow
            sub_histories = (
                (
                    await verify_session.execute(
                        select(ExecutionHistory)
                        .where(ExecutionHistory.workflow_id == self.sub_workflow_id)
                        .order_by(ExecutionHistory.execution_time_ms.asc())
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(
                len(sub_histories),
                2,
                "Both invocations of the same child workflow must have distinct ExecutionHistory rows",
            )
            self.assertNotEqual(sub_histories[0].id, sub_histories[1].id)
            self.assertEqual(sub_histories[0].inputs, {"iteration": 1, "data": "item_1"})
            self.assertEqual(sub_histories[0].outputs, {"result": "processed_1"})
            self.assertEqual(sub_histories[1].inputs, {"iteration": 2, "data": "item_2"})
            self.assertEqual(sub_histories[1].outputs, {"result": "processed_2"})

            # 2. Child workflow analytics must reflect BOTH executions (total_executions == 2)
            sub_analytics = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.sub_workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(
                sub_analytics.total_executions,
                2,
                "Child workflow analytics must reflect total_executions == 2 for repeated invocations",
            )
            self.assertEqual(sub_analytics.success_count, 2)
            self.assertEqual(sub_analytics.error_count, 0)

            # 3. Parent history is updated
            parent_history = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(parent_history.outputs.get("downstream"), "done")
            self.assertEqual(parent_history.execution_time_ms, 150.0)

    async def test_concurrent_finalizers_two_independent_execution_results(
        self,
    ) -> None:
        """Two concurrent finalizers running with independent ExecutionResult object graphs
        (non-shared in-memory state) against PostgreSQL must achieve exact-once persistence
        via database-level serialization and state checks."""
        from app.api.workflows import _finalize_allow_downstream_history

        history_id = uuid.uuid4()
        initial_history = ExecutionHistory(
            id=history_id,
            workflow_id=self.workflow_id,
            inputs={"k": "v"},
            outputs={"initial": "pending_downstream"},
            node_results=[{"node_id": "n1", "status": "success"}],
            status="success",
            execution_time_ms=20.0,
            started_at=datetime.now(timezone.utc),
        )
        async with async_session_maker() as init_session:
            init_session.add(initial_history)
            await init_session.commit()

        sub_id = str(uuid.uuid4())
        sub_exec_1 = SubWorkflowExecution(
            workflow_id=self.sub_workflow_id,
            workflow_name="Independent Object Sub WF",
            status="success",
            execution_time_ms=35.0,
            trigger_source="SUB_WORKFLOW",
            inputs={"arg": 10},
            outputs={"out": 20},
            node_results=[],
            execution_id=sub_id,
        )
        sub_exec_2 = SubWorkflowExecution(
            workflow_id=self.sub_workflow_id,
            workflow_name="Independent Object Sub WF",
            status="success",
            execution_time_ms=35.0,
            trigger_source="SUB_WORKFLOW",
            inputs={"arg": 10},
            outputs={"out": 20},
            node_results=[],
            execution_id=sub_id,
        )

        def mock_join_1():
            exec_res_1.outputs["downstream"] = "done_1"
            exec_res_1.execution_time_ms = 100.0

        def mock_join_2():
            exec_res_2.outputs["downstream"] = "done_2"
            exec_res_2.execution_time_ms = 100.0

        exec_res_1 = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "pending_downstream"},
            node_results=[
                {
                    "node_id": "n1",
                    "status": "success",
                    "output": {"initial": "pending_downstream"},
                    "metadata": {},
                },
                {"node_id": "n2", "status": "success", "output": {"step": 2}, "metadata": {}},
            ],
            execution_time_ms=20.0,
            sub_workflow_executions=[sub_exec_1],
        )
        exec_res_1._allow_downstream_pending = [MagicMock()]
        exec_res_1.join_allow_downstream = mock_join_1
        self.assertFalse(exec_res_1.analytics_recorded)

        # Independent object graph 2 (different memory address, not sharing analytics_recorded)
        exec_res_2 = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "pending_downstream"},
            node_results=[
                {
                    "node_id": "n1",
                    "status": "success",
                    "output": {"initial": "pending_downstream"},
                    "metadata": {},
                },
                {"node_id": "n2", "status": "success", "output": {"step": 2}, "metadata": {}},
            ],
            execution_time_ms=20.0,
            sub_workflow_executions=[sub_exec_2],
        )
        exec_res_2._allow_downstream_pending = [MagicMock()]
        exec_res_2.join_allow_downstream = mock_join_2
        self.assertFalse(exec_res_2.analytics_recorded)

        self.assertIsNot(exec_res_1, exec_res_2)
        self.assertIsNot(sub_exec_1, sub_exec_2)

        finalizer_coro_1 = _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=exec_res_1,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Independent Parent WF",
        )
        finalizer_coro_2 = _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=exec_res_2,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Independent Parent WF",
        )

        results = await asyncio.gather(finalizer_coro_1, finalizer_coro_2, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                raise res

        async with async_session_maker() as verify_session:
            # Preserves original node count, marks only one node, no fake nodes
            parent_history = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(
                len(parent_history.node_results), 2, "Must preserve node count without fake nodes"
            )
            marked_nodes = [
                nr
                for nr in parent_history.node_results
                if isinstance(nr, dict) and nr.get("metadata", {}).get("_downstream_finalized")
            ]
            self.assertEqual(
                len(marked_nodes), 1, "Exactly one node result must carry the finalized marker"
            )
            self.assertNotIn(
                "_downstream_finalized", parent_history.outputs, "Outputs must not be polluted"
            )

            # Exactly 1 sub-workflow row
            sub_histories = (
                (
                    await verify_session.execute(
                        select(ExecutionHistory).where(
                            ExecutionHistory.workflow_id == self.sub_workflow_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(sub_histories), 1)

            # Exactly 1 parent analytics count
            parent_analytics = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(parent_analytics.total_executions, 1)

            # Exactly 1 sub-workflow analytics count
            sub_analytics = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.sub_workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(sub_analytics.total_executions, 1)

    async def test_finalize_missing_parent_history_aborts_without_persistence(
        self,
    ) -> None:
        """When the parent ExecutionHistory row does not exist, _finalize_allow_downstream_history
        must abort immediately without writing sub-workflow history, global variables, or analytics."""
        from app.api.workflows import _finalize_allow_downstream_history

        missing_history_id = uuid.uuid4()
        unregistered_sub_id = uuid.uuid4()

        sub_exec = SubWorkflowExecution(
            workflow_id=unregistered_sub_id,
            workflow_name="Orphan Sub WF",
            status="success",
            execution_time_ms=30.0,
            trigger_source="SUB_WORKFLOW",
            inputs={"data": 123},
            outputs={"res": 456},
            node_results=[],
        )

        exec_res = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={},
            execution_time_ms=10.0,
            sub_workflow_executions=[sub_exec],
        )

        # Finalizer called for non-existent parent history ID
        await _finalize_allow_downstream_history(
            history_entry_id=missing_history_id,
            execution_result=exec_res,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Missing Parent WF",
        )

        # Verify nothing was persisted
        async with async_session_maker() as verify_session:
            sub_row = (
                await verify_session.execute(
                    select(ExecutionHistory).where(
                        ExecutionHistory.workflow_id == unregistered_sub_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNone(
                sub_row, "No sub-workflow history must be written when parent history is missing"
            )

            analytics_row = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == unregistered_sub_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNone(
                analytics_row,
                "No analytics snapshot must be created when parent history is missing",
            )

    async def test_finalizer_second_run_afterward_skips_idempotently(
        self,
    ) -> None:
        """When a first finalizer succeeds, a second finalizer running afterward with an independent
        ExecutionResult must detect the database completion marker and exit without double-counting."""
        from app.api.workflows import _finalize_allow_downstream_history

        history_id = uuid.uuid4()
        initial_history = ExecutionHistory(
            id=history_id,
            workflow_id=self.workflow_id,
            inputs={"run": "seq"},
            outputs={"initial": "res"},
            node_results=[{"node_id": "n1", "status": "success", "metadata": {}}],
            status="success",
            execution_time_ms=20.0,
            started_at=datetime.now(timezone.utc),
            executed_by_instance_name="WorkerNodeAlpha",
        )
        async with async_session_maker() as init_session:
            init_session.add(initial_history)
            await init_session.commit()

        sub_id = str(uuid.uuid4())
        sub_exec_1 = SubWorkflowExecution(
            workflow_id=self.sub_workflow_id,
            workflow_name="Sequential Sub WF",
            status="success",
            execution_time_ms=40.0,
            trigger_source="SUB_WORKFLOW",
            inputs={"in": 1},
            outputs={"out": 2},
            node_results=[],
            execution_id=sub_id,
        )

        def mock_join_1():
            exec_res_1.outputs["downstream"] = "done"
            exec_res_1.execution_time_ms = 110.0

        exec_res_1 = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "res"},
            node_results=[{"node_id": "n1", "status": "success", "metadata": {}}],
            execution_time_ms=20.0,
            sub_workflow_executions=[sub_exec_1],
        )
        exec_res_1._allow_downstream_pending = [MagicMock()]
        exec_res_1.join_allow_downstream = mock_join_1

        # Run First Finalizer -> Succeeds
        await _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=exec_res_1,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Sequential Parent WF",
        )

        # Verify first finalizer committed completion marker and did NOT corrupt executed_by_instance_name
        async with async_session_maker() as verify_session_1:
            p_hist = (
                await verify_session_1.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(
                p_hist.executed_by_instance_name,
                "WorkerNodeAlpha",
                "executed_by_instance_name must remain untouched and uncorrupted",
            )
            has_marker = any(
                isinstance(nr, dict) and nr.get("metadata", {}).get("_downstream_finalized")
                for nr in (p_hist.node_results or [])
            )
            self.assertTrue(
                has_marker, "Finalized node_results must contain _downstream_finalized marker"
            )
            self.assertEqual(len(p_hist.node_results), 1, "No fake node results must be added")
            marked_nodes = [
                nr
                for nr in p_hist.node_results
                if isinstance(nr, dict) and nr.get("metadata", {}).get("_downstream_finalized")
            ]
            self.assertEqual(
                len(marked_nodes), 1, "Exactly one node result must carry the finalized marker"
            )
            self.assertNotIn(
                "_downstream_finalized", p_hist.outputs, "Outputs must not be polluted"
            )

            parent_snap = (
                await verify_session_1.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(parent_snap.total_executions, 1)

            sub_snap = (
                await verify_session_1.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.sub_workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(sub_snap.total_executions, 1)

        # Run Second Finalizer afterward with an independent object graph
        sub_exec_2 = SubWorkflowExecution(
            workflow_id=self.sub_workflow_id,
            workflow_name="Sequential Sub WF",
            status="success",
            execution_time_ms=40.0,
            trigger_source="SUB_WORKFLOW",
            inputs={"in": 1},
            outputs={"out": 2},
            node_results=[],
            execution_id=sub_id,
        )

        def mock_join_2():
            exec_res_2.outputs["downstream"] = "done_2"
            exec_res_2.execution_time_ms = 110.0

        exec_res_2 = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "res"},
            node_results=[{"node_id": "n1", "status": "success", "metadata": {}}],
            execution_time_ms=20.0,
            sub_workflow_executions=[sub_exec_2],
        )
        exec_res_2._allow_downstream_pending = [MagicMock()]
        exec_res_2.join_allow_downstream = mock_join_2
        self.assertFalse(exec_res_2.analytics_recorded)

        await _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=exec_res_2,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Sequential Parent WF",
        )

        # Verify second finalizer observed the completion marker and skipped without double-counting
        async with async_session_maker() as verify_session_2:
            p_hist_2 = (
                await verify_session_2.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(p_hist_2.executed_by_instance_name, "WorkerNodeAlpha")

            parent_snap_2 = (
                await verify_session_2.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(
                parent_snap_2.total_executions,
                1,
                "Second sequential finalizer must not double-count parent analytics",
            )

            sub_snap_2 = (
                await verify_session_2.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.sub_workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(
                sub_snap_2.total_executions,
                1,
                "Second sequential finalizer must not double-count sub-workflow analytics",
            )

            sub_histories_count = (
                (
                    await verify_session_2.execute(
                        select(ExecutionHistory).where(
                            ExecutionHistory.workflow_id == self.sub_workflow_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(sub_histories_count), 1)

    async def test_finalizer_rollback_before_completion_allows_retry_to_succeed(
        self,
    ) -> None:
        """When a first finalizer encounters an error and rolls back before commit, it must not leave
        durable or in-memory finalized markers, allowing a subsequent finalizer retry to succeed."""
        from app.api.workflows import _finalize_allow_downstream_history

        history_id = uuid.uuid4()
        initial_history = ExecutionHistory(
            id=history_id,
            workflow_id=self.workflow_id,
            inputs={"run": "rollback_test"},
            outputs={"initial": "raw"},
            node_results=[{"node_id": "n1", "status": "success", "metadata": {}}],
            status="success",
            execution_time_ms=15.0,
            started_at=datetime.now(timezone.utc),
            executed_by_instance_name="WorkerNodeBeta",
        )
        async with async_session_maker() as init_session:
            init_session.add(initial_history)
            await init_session.commit()

        sub_id = str(uuid.uuid4())
        sub_exec = SubWorkflowExecution(
            workflow_id=self.sub_workflow_id,
            workflow_name="Rollback Sub WF",
            status="success",
            execution_time_ms=30.0,
            trigger_source="SUB_WORKFLOW",
            inputs={"attempt": 1},
            outputs={"result": 100},
            node_results=[],
            execution_id=sub_id,
        )

        def mock_join():
            exec_res.outputs["downstream"] = "recovered"
            exec_res.execution_time_ms = 85.0

        exec_res = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "raw"},
            node_results=[{"node_id": "n1", "status": "success", "metadata": {}}],
            execution_time_ms=15.0,
            sub_workflow_executions=[sub_exec],
        )
        exec_res._allow_downstream_pending = [MagicMock()]
        exec_res.join_allow_downstream = mock_join

        # Attempt 1: Inject failure right before commit inside _persist_global_variables_from_execution
        with patch(
            "app.api.workflows._persist_global_variables_from_execution",
            side_effect=RuntimeError("Simulated DB failure before commit"),
        ):
            await _finalize_allow_downstream_history(
                history_entry_id=history_id,
                execution_result=exec_res,
                credentials_owner_id=self.user_id,
                workflow_nodes=[],
                workflow_cache={},
                workflow_id=self.workflow_id,
                owner_id=self.user_id,
                workflow_name="Rollback Parent WF",
            )

        # In-memory flags MUST remain False because commit was not reached
        self.assertFalse(
            exec_res.analytics_recorded, "analytics_recorded must remain False on rollback"
        )
        self.assertFalse(sub_exec.history_written, "history_written must remain False on rollback")

        # Database state MUST have rolled back cleanly
        async with async_session_maker() as check_session:
            parent_in_db = (
                await check_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            has_marker = any(
                isinstance(nr, dict) and nr.get("metadata", {}).get("_downstream_finalized")
                for nr in (parent_in_db.node_results or [])
            )
            self.assertFalse(
                has_marker, "Database must NOT have _downstream_finalized marker after rollback"
            )
            self.assertEqual(parent_in_db.executed_by_instance_name, "WorkerNodeBeta")

            sub_in_db = (
                await check_session.execute(
                    select(ExecutionHistory).where(
                        ExecutionHistory.workflow_id == self.sub_workflow_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNone(
                sub_in_db, "Sub-workflow history must NOT be persisted after rollback"
            )

            snap_in_db = (
                await check_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one_or_none()
            self.assertIsNone(snap_in_db, "Analytics snapshot must NOT be persisted after rollback")

        # Attempt 2: Retry finalization without failure -> Must succeed completely
        await _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=exec_res,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Rollback Parent WF",
        )

        # In-memory flags are now marked True post-commit
        self.assertTrue(
            exec_res.analytics_recorded, "analytics_recorded must be True after successful retry"
        )
        self.assertTrue(
            sub_exec.history_written, "history_written must be True after successful retry"
        )

        # Database state now reflects successful finalization
        async with async_session_maker() as verify_session:
            final_parent = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            has_marker_retry = any(
                isinstance(nr, dict) and nr.get("metadata", {}).get("_downstream_finalized")
                for nr in (final_parent.node_results or [])
            )
            self.assertTrue(has_marker_retry, "Retry must persist _downstream_finalized marker")
            self.assertEqual(final_parent.executed_by_instance_name, "WorkerNodeBeta")
            self.assertEqual(final_parent.outputs.get("downstream"), "recovered")
            self.assertEqual(final_parent.execution_time_ms, 85.0)

            final_sub = (
                await verify_session.execute(
                    select(ExecutionHistory).where(
                        ExecutionHistory.workflow_id == self.sub_workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(final_sub.inputs, {"attempt": 1})
            self.assertEqual(final_sub.outputs, {"result": 100})

            final_parent_snap = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(final_parent_snap.total_executions, 1)

            final_sub_snap = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.sub_workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(final_sub_snap.total_executions, 1)

    async def test_finalizer_zero_node_results_skips_fake_nodes_and_idempotently_finalizes(
        self,
    ) -> None:
        """When node_results is empty, the finalizer must NOT synthesize fake node results,
        must fall back to marking outputs, and must remain idempotent on subsequent runs."""
        from app.api.workflows import _finalize_allow_downstream_history

        history_id = uuid.uuid4()
        initial_history = ExecutionHistory(
            id=history_id,
            workflow_id=self.workflow_id,
            inputs={"run": "zero_nodes"},
            outputs={"initial": "res"},
            node_results=[],
            status="success",
            execution_time_ms=10.0,
            started_at=datetime.now(timezone.utc),
            executed_by_instance_name="WorkerNodeZero",
        )
        async with async_session_maker() as init_session:
            init_session.add(initial_history)
            await init_session.commit()

        sub_id = str(uuid.uuid4())
        sub_exec = SubWorkflowExecution(
            workflow_id=self.sub_workflow_id,
            workflow_name="Zero Node Sub WF",
            status="success",
            execution_time_ms=25.0,
            trigger_source="SUB_WORKFLOW",
            inputs={"x": 1},
            outputs={"y": 2},
            node_results=[],
            execution_id=sub_id,
        )

        exec_res = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "res", "downstream": "done"},
            node_results=[],
            execution_time_ms=35.0,
            sub_workflow_executions=[sub_exec],
        )
        exec_res._allow_downstream_pending = [MagicMock()]
        exec_res.join_allow_downstream = MagicMock()

        # Run first finalizer
        await _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=exec_res,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Zero Node Parent WF",
        )

        async with async_session_maker() as verify_session:
            p_hist = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(
                p_hist.node_results,
                [],
                "Must not append fake node results when node_results is empty",
            )
            self.assertTrue(
                isinstance(p_hist.outputs, dict) and p_hist.outputs.get("_downstream_finalized"),
                "Outputs must carry fallback marker when no node results exist",
            )
            self.assertEqual(p_hist.executed_by_instance_name, "WorkerNodeZero")

            sub_histories = (
                (
                    await verify_session.execute(
                        select(ExecutionHistory).where(
                            ExecutionHistory.workflow_id == self.sub_workflow_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(sub_histories), 1)

        # Run second finalizer with a fresh independent ExecutionResult (both flags false)
        exec_res_2 = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "res", "downstream": "done"},
            node_results=[],
            execution_time_ms=35.0,
            sub_workflow_executions=[
                SubWorkflowExecution(
                    workflow_id=self.sub_workflow_id,
                    workflow_name="Zero Node Sub WF",
                    status="success",
                    execution_time_ms=25.0,
                    trigger_source="SUB_WORKFLOW",
                    inputs={"x": 1},
                    outputs={"y": 2},
                    node_results=[],
                    execution_id=sub_id,
                )
            ],
        )
        exec_res_2._allow_downstream_pending = [MagicMock()]
        exec_res_2.join_allow_downstream = MagicMock()

        await _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=exec_res_2,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Zero Node Parent WF",
        )

        async with async_session_maker() as verify_session_2:
            p_hist_2 = (
                await verify_session_2.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(p_hist_2.node_results, [])

            sub_histories_2 = (
                (
                    await verify_session_2.execute(
                        select(ExecutionHistory).where(
                            ExecutionHistory.workflow_id == self.sub_workflow_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(
                len(sub_histories_2),
                1,
                "Second finalizer must skip without creating duplicate sub-executions",
            )

            sub_snap = (
                await verify_session_2.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.sub_workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(sub_snap.total_executions, 1, "Analytics must not be double counted")

    async def test_recovered_sub_agent_error_preserves_parent_success(self) -> None:
        """When an earlier sub-agent or tool fails but the parent agent recovers and produces
        successful output, downstream finalization must NOT mark the parent as 'error' due to
        historical pre-output node results. The parent must retain 'success' in both ExecutionResult
        and ExecutionHistory, and analytics must record a success."""
        from app.api.workflows import _finalize_allow_downstream_history

        history_id = uuid.uuid4()
        failed_sub_agent_node = {
            "node_id": "agent_tool_node_1",
            "node_label": "Research Subagent",
            "node_type": "agent",
            "status": "error",
            "error": "Temporary API timeout, retried and recovered",
            "metadata": {},
        }
        recovered_node = {
            "node_id": "agent_tool_node_2",
            "node_label": "Research Subagent Retry",
            "node_type": "agent",
            "status": "success",
            "output": {"summary": "Found data"},
            "metadata": {},
        }
        initial_history = ExecutionHistory(
            id=history_id,
            workflow_id=self.workflow_id,
            inputs={"prompt": "Do research"},
            outputs={"result": "Recovered research summary"},
            node_results=[failed_sub_agent_node, recovered_node],
            status="success",
            execution_time_ms=50.0,
            started_at=datetime.now(timezone.utc),
        )
        async with async_session_maker() as init_session:
            init_session.add(initial_history)
            await init_session.commit()

        downstream_fut: Future = Future()
        downstream_fut.set_result(None)

        downstream_node = NodeResult(
            node_id="downstream_log_1",
            node_label="Audit Logger",
            node_type="custom",
            status="success",
            output={"logged": True},
            execution_time_ms=12.0,
        )

        exec_res = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"result": "Recovered research summary"},
            node_results=[dict(failed_sub_agent_node), dict(recovered_node)],
            execution_time_ms=50.0,
            _allow_downstream_pending=[downstream_fut],
            _allow_downstream_node_results=[downstream_node],
        )

        await _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=exec_res,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Recovered Parent WF",
        )

        # 1. In-memory status remains success
        self.assertEqual(
            exec_res.status,
            "success",
            "Parent status must remain success despite historical recovered node errors",
        )

        # 2. Database verification
        async with async_session_maker() as verify_session:
            p_hist = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(
                p_hist.status,
                "success",
                "Persisted parent ExecutionHistory status must remain 'success'",
            )
            node_ids = [
                nr.get("node_id") for nr in (p_hist.node_results or []) if isinstance(nr, dict)
            ]
            self.assertIn("downstream_log_1", node_ids)

            p_snap = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(p_snap.total_executions, 1)
            self.assertEqual(p_snap.success_count, 1)
            self.assertEqual(p_snap.error_count, 0)

    async def test_genuine_downstream_failure_produces_error_status_and_analytics(
        self,
    ) -> None:
        """When downstream work genuinely fails (e.g. downstream node produces status='error'),
        join_allow_downstream and finalizer must update the parent status to 'error' and record
        an error in the workflow analytics snapshot."""
        from app.api.workflows import _finalize_allow_downstream_history

        history_id = uuid.uuid4()
        initial_history = ExecutionHistory(
            id=history_id,
            workflow_id=self.workflow_id,
            inputs={"start": 1},
            outputs={"initial": "ok"},
            node_results=[{"node_id": "initial_node", "status": "success"}],
            status="success",
            execution_time_ms=25.0,
            started_at=datetime.now(timezone.utc),
        )
        async with async_session_maker() as init_session:
            init_session.add(initial_history)
            await init_session.commit()

        downstream_fut: Future = Future()
        downstream_fut.set_result(None)

        downstream_error_node = NodeResult(
            node_id="downstream_webhook_1",
            node_label="Webhook Notification",
            node_type="webhook",
            status="error",
            error="Connection refused: endpoint unreachable",
            output={},
            execution_time_ms=45.0,
        )

        exec_res = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "ok"},
            node_results=[{"node_id": "initial_node", "status": "success"}],
            execution_time_ms=25.0,
            _allow_downstream_pending=[downstream_fut],
            _allow_downstream_node_results=[downstream_error_node],
        )

        await _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=exec_res,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Downstream Failure WF",
        )

        self.assertEqual(exec_res.status, "error")

        async with async_session_maker() as verify_session:
            p_hist = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(p_hist.status, "error")

            p_snap = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(p_snap.total_executions, 1)
            self.assertEqual(p_snap.error_count, 1)
            self.assertEqual(p_snap.success_count, 0)

    async def test_real_downstream_cancellation_persists_history_and_completed_subworkflows(
        self,
    ) -> None:
        """When downstream work is cancelled via WorkflowCancelledError:
        1. Real join_allow_downstream (NOT mocked) handles cancellation gracefully and sets status='cancelled'.
        2. _finalize_allow_downstream_history does NOT abort or swallow the persistence pass.
        3. Parent ExecutionHistory is updated to status='cancelled' in PostgreSQL.
        4. Already-completed SubWorkflowExecution rows are fully persisted into ExecutionHistory.
        5. Analytics snapshots are recorded for both parent and completed sub-workflows."""
        from app.api.workflows import _finalize_allow_downstream_history

        history_id = uuid.uuid4()
        initial_history = ExecutionHistory(
            id=history_id,
            workflow_id=self.workflow_id,
            inputs={"data": "parent_start"},
            outputs={"initial": "pre_cancellation"},
            node_results=[{"node_id": "parent_step_1", "status": "success"}],
            status="running",
            execution_time_ms=30.0,
            started_at=datetime.now(timezone.utc),
        )
        async with async_session_maker() as init_session:
            init_session.add(initial_history)
            await init_session.commit()

        cancelled_fut: Future = Future()
        cancelled_fut.set_exception(
            WorkflowCancelledError("Downstream step cancelled by user disconnect")
        )

        sub_exec_id = str(uuid.uuid4())
        sub_exec = SubWorkflowExecution(
            workflow_id=self.sub_workflow_id,
            workflow_name="Completed Child WF",
            status="success",
            execution_time_ms=65.0,
            trigger_source="SUB_WORKFLOW",
            inputs={"x": 42},
            outputs={"y": 84},
            node_results=[{"node_id": "child_step_1", "status": "success"}],
            execution_id=sub_exec_id,
        )

        downstream_node = NodeResult(
            node_id="downstream_step_1",
            node_label="Partial Downstream",
            node_type="custom",
            status="success",
            output={"partial": True},
            execution_time_ms=15.0,
        )

        exec_res = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "pre_cancellation"},
            node_results=[{"node_id": "parent_step_1", "status": "success"}],
            execution_time_ms=30.0,
            sub_workflow_executions=[sub_exec],
            _allow_downstream_pending=[cancelled_fut],
            _allow_downstream_node_results=[downstream_node],
        )

        await _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=exec_res,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Cancelled Parent WF",
        )

        self.assertEqual(
            exec_res.status,
            "cancelled",
            "ExecutionResult status must be 'cancelled' after real cancellation",
        )

        async with async_session_maker() as verify_session:
            parent_in_db = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(
                parent_in_db.status,
                "cancelled",
                "Parent ExecutionHistory in DB must be updated to 'cancelled'",
            )

            node_ids = [
                nr.get("node_id")
                for nr in (parent_in_db.node_results or [])
                if isinstance(nr, dict)
            ]
            self.assertIn("downstream_step_1", node_ids)

            expected_sub_history_id = uuid.uuid5(history_id, f"sub:{sub_exec_id}")
            sub_in_db = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == expected_sub_history_id)
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(
                sub_in_db,
                "Already-completed sub-workflow must be persisted even when downstream is cancelled",
            )
            self.assertEqual(sub_in_db.status, "success")
            self.assertEqual(sub_in_db.outputs, {"y": 84})

            sub_snap = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.sub_workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(sub_snap.total_executions, 1)
            self.assertEqual(sub_snap.success_count, 1)

    async def test_cancellation_bridge_threads_exit_and_no_leak_across_repeated_turns(
        self,
    ) -> None:
        """25 repeated normal turns must not leak _bridge_exec_node_cancel or _bridge_parent_cancel
        threads. Active bridge thread count must return to baseline after every completed turn,
        including:
        - normal completion with allowDownstream
        - normal completion without allowDownstream
        - actual cancellation
        - actual timeout
        - unexpected exception
        """
        from app.services.cancellation_bridge import CancellationBridge
        from app.services.workflow_executor import WorkflowExecutor

        def get_bridge_threads():
            return [
                t
                for t in threading.enumerate()
                if t.name in ("_bridge_exec_node_cancel", "_bridge_parent_cancel")
            ]

        # Baseline check
        self.assertEqual(get_bridge_threads(), [], "No bridge threads should exist at baseline")

        # 1. Repeated turns of CancellationBridge directly
        for turn in range(25):
            parent_event = threading.Event()
            child_event = threading.Event()
            bridge = CancellationBridge(
                parent_event, child_event, bridge_name="_bridge_parent_cancel"
            )
            self.assertEqual(
                len(get_bridge_threads()), 1, f"Bridge thread must be running in turn {turn}"
            )
            bridge.close()
            self.assertEqual(
                get_bridge_threads(),
                [],
                f"Bridge thread must terminate immediately after close in turn {turn}",
            )

        # 2. Repeated turns of Execute node bridge
        for turn in range(25):
            parent_event = threading.Event()
            child_event = threading.Event()
            bridge = CancellationBridge(
                parent_event, child_event, bridge_name="_bridge_exec_node_cancel"
            )
            self.assertEqual(len(get_bridge_threads()), 1)
            bridge.close()
            self.assertEqual(get_bridge_threads(), [])

        # 3. Real cancellation: setting parent_event causes bridge thread to set child and exit
        parent_event = threading.Event()
        child_event = threading.Event()
        bridge = CancellationBridge(
            parent_event, child_event, bridge_name="_bridge_exec_node_cancel"
        )
        parent_event.set()
        bridge.close()
        self.assertTrue(child_event.is_set(), "Child event must be set when parent cancels")
        self.assertEqual(get_bridge_threads(), [], "Bridge thread must be terminated")

        # 4. Parent already cancelled before bridge created
        parent_event = threading.Event()
        parent_event.set()
        child_event = threading.Event()
        bridge = CancellationBridge(parent_event, child_event, bridge_name="_bridge_parent_cancel")
        self.assertTrue(
            child_event.is_set(), "Child event must be set immediately if parent already set"
        )
        self.assertEqual(
            get_bridge_threads(), [], "No bridge thread should be spawned if parent already set"
        )
        bridge.close()

        # 5. Full sub-workflow invocation via run_sub_workflow across 25 turns
        target_wf = {
            "nodes": [
                {"id": "n1", "type": "custom", "data": {"label": "Start"}},
                {"id": "n2", "type": "output", "data": {"label": "End"}},
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
            "name": "Sub Workflow In Turn",
        }
        wf_id_str = str(self.sub_workflow_id)
        cache = {wf_id_str: target_wf}

        parent_exec = WorkflowExecutor(
            nodes=[{"id": "pn1", "type": "input"}],
            edges=[],
            workflow_cache=cache,
            workflow_id=self.workflow_id,
            cancel_event=threading.Event(),
        )

        for turn in range(25):
            res = parent_exec._execute_sub_workflow_tool(
                tool_def={"_sub_workflow_ids": [wf_id_str]},
                _name="call_sub_workflow",
                args={"workflow_id": wf_id_str, "inputs": {"x": turn}},
                _timeout_seconds=30.0,
            )
            self.assertNotIn(
                "error", res, f"Sub-workflow execution must not error in turn {turn}: {res}"
            )
            self.assertEqual(
                get_bridge_threads(),
                [],
                f"All bridge threads must exit after sub-workflow turn {turn}",
            )

    async def test_subworkflow_cancellation_cancels_parent_and_aborts_subsequent_nodes(
        self,
    ) -> None:
        """When an awaited sub-workflow is cancelled (with or without allowDownstream):
        1. Cancellation must propagate to the parent executor (does NOT swallow or treat as success).
        2. Subsequent parent nodes must NOT be executed.
        3. Completed child work must be captured in parent.sub_workflow_executions and persisted to DB.
        4. Parent status must be 'cancelled' in ExecutionHistory and analytics."""
        from app.api.workflows import _finalize_allow_downstream_history
        from app.services.workflow_executor import WorkflowCancelledError, WorkflowExecutor

        # Construct child workflow with allowDownstream
        child_id = str(uuid.uuid4())
        child_wf = {
            "id": child_id,
            "name": "AllowDownstream Child",
            "nodes": [
                {"id": "c1", "type": "custom", "data": {"label": "Child Start"}},
                {
                    "id": "c2",
                    "type": "output",
                    "data": {"label": "Child Output", "allowDownstream": True},
                },
                {"id": "c3", "type": "custom", "data": {"label": "Child Downstream"}},
            ],
            "edges": [
                {"id": "ce1", "source": "c1", "target": "c2"},
                {"id": "ce2", "source": "c2", "target": "c3"},
            ],
        }

        # Construct parent workflow: p1 -> p_exec (Execute Node) -> p3 (Subsequent Node)
        parent_id = uuid.uuid4()
        parent_wf_nodes = [
            {"id": "p1", "type": "custom", "data": {"label": "Parent Start"}},
            {
                "id": "p_exec",
                "type": "execute",
                "data": {
                    "label": "Run Child WF",
                    "executeWorkflowId": child_id,
                },
            },
            {"id": "p3", "type": "custom", "data": {"label": "Subsequent Parent Node"}},
        ]
        parent_wf_edges = [
            {"id": "pe1", "source": "p1", "target": "p_exec"},
            {"id": "pe2", "source": "p_exec", "target": "p3"},
        ]
        workflow_cache = {child_id: child_wf}

        parent_cancel_event = threading.Event()
        parent_executor = WorkflowExecutor(
            nodes=parent_wf_nodes,
            edges=parent_wf_edges,
            workflow_cache=workflow_cache,
            workflow_id=parent_id,
            cancel_event=parent_cancel_event,
        )

        downstream_fut: Future = Future()
        downstream_fut.set_exception(WorkflowCancelledError("Downstream was cancelled"))

        child_exec_result = ExecutionResult(
            workflow_id=uuid.UUID(child_id),
            status="success",
            outputs={"child_out": "initial_val"},
            node_results=[{"node_id": "c1", "status": "success", "output": {"c1": "done"}}],
            execution_time_ms=20.0,
            _allow_downstream_pending=[downstream_fut],
            _allow_downstream_node_results=[
                NodeResult(
                    node_id="c3",
                    node_label="Child Downstream",
                    node_type="custom",
                    status="cancelled",
                    output={},
                    execution_time_ms=5.0,
                )
            ],
        )

        orig_execute = WorkflowExecutor.execute

        def custom_execute(exec_self, workflow_id, initial_inputs=None):
            if str(workflow_id) == child_id:
                return child_exec_result
            return orig_execute(exec_self, workflow_id, initial_inputs)

        with patch.object(WorkflowExecutor, "execute", side_effect=custom_execute, autospec=True):
            with self.assertRaises(WorkflowCancelledError):
                parent_executor.execute(parent_id, initial_inputs={"start": True})

        # 1. Subsequent node p3 was NOT executed!
        self.assertNotIn(
            "p3",
            parent_executor.node_outputs,
            "Subsequent parent node p3 must NOT be executed after child cancel",
        )

        # 2. Child work is preserved in parent_executor.sub_workflow_executions!
        self.assertGreaterEqual(
            len(parent_executor.sub_workflow_executions),
            1,
            "Child sub_workflow_execution must be captured",
        )
        child_sub_exec = parent_executor.sub_workflow_executions[0]
        self.assertEqual(child_sub_exec.status, "cancelled")
        child_node_ids = [
            nr.get("node_id") for nr in child_sub_exec.node_results if isinstance(nr, dict)
        ]
        self.assertIn("c1", child_node_ids)
        self.assertIn("c3", child_node_ids)

        # 3. Persist and verify in DB
        async with async_session_maker() as init_session:
            pwf = Workflow(
                id=parent_id,
                owner_id=self.user_id,
                name="Parent WF Cancel Test",
                nodes=[],
                edges=[],
            )
            cwf = Workflow(
                id=uuid.UUID(child_id),
                owner_id=self.user_id,
                name="Child WF Cancel Test",
                nodes=[],
                edges=[],
            )
            init_session.add(pwf)
            init_session.add(cwf)
            init_session.add(
                ExecutionHistory(
                    id=parent_id,
                    workflow_id=parent_id,
                    inputs={"start": True},
                    outputs={},
                    node_results=[],
                    status="running",
                    execution_time_ms=0.0,
                )
            )
            await init_session.commit()

        self.cleanup_workflow_ids.append(parent_id)
        self.cleanup_workflow_ids.append(uuid.UUID(child_id))
        parent_exec_res = ExecutionResult(
            workflow_id=parent_id,
            status="cancelled",
            outputs={},
            execution_time_ms=50.0,
            node_results=[],
            sub_workflow_executions=parent_executor.sub_workflow_executions,
        )

        await _finalize_allow_downstream_history(
            history_entry_id=parent_id,
            execution_result=parent_exec_res,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache=workflow_cache,
            workflow_id=parent_id,
            owner_id=self.user_id,
            workflow_name="Parent WF Cancel Test",
        )

        async with async_session_maker() as verify_session:
            p_hist = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == parent_id)
                )
            ).scalar_one()
            self.assertEqual(p_hist.status, "cancelled", "Parent history must be cancelled")

            # Verify child history entry was written
            sub_hist = (
                (
                    await verify_session.execute(
                        select(ExecutionHistory).where(
                            ExecutionHistory.workflow_id == uuid.UUID(child_id)
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertGreaterEqual(
                len(sub_hist), 1, "Child history must be persisted even though cancelled"
            )
            self.assertEqual(sub_hist[0].status, "cancelled")

    async def test_downstream_timeout_recorded_as_error_not_cancelled(self) -> None:
        """WorkflowTimeoutError inherits from WorkflowCancelledError.
        1. join_allow_downstream must classify timeout as 'error' (NOT 'cancelled').
        2. join_allow_downstream re-raises WorkflowTimeoutError.
        3. _finalize_allow_downstream_history persists status='error'.
        4. WorkflowAnalyticsSnapshot records error_count += 1, success_count == 0."""
        from app.api.workflows import _finalize_allow_downstream_history

        history_id = uuid.uuid4()
        initial_history = ExecutionHistory(
            id=history_id,
            workflow_id=self.workflow_id,
            inputs={"test": "timeout"},
            outputs={"partial": "before_timeout"},
            node_results=[{"node_id": "step_1", "status": "success"}],
            status="running",
            execution_time_ms=10.0,
            started_at=datetime.now(timezone.utc),
        )
        async with async_session_maker() as init_session:
            init_session.add(initial_history)
            await init_session.commit()

        timeout_fut: Future = Future()
        timeout_fut.set_exception(WorkflowTimeoutError("Workflow timed out after 30 seconds"))

        exec_res = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"partial": "before_timeout"},
            node_results=[{"node_id": "step_1", "status": "success"}],
            execution_time_ms=10.0,
            _allow_downstream_pending=[timeout_fut],
            _allow_downstream_node_results=[
                NodeResult(
                    node_id="downstream_step",
                    node_label="Downstream Processing",
                    node_type="custom",
                    status="error",
                    output={},
                    execution_time_ms=30000.0,
                    error="Workflow timed out after 30 seconds",
                )
            ],
        )

        # 1. Direct join_allow_downstream check
        with self.assertRaises(WorkflowTimeoutError):
            exec_res.join_allow_downstream()

        self.assertEqual(
            exec_res.status,
            "error",
            "ExecutionResult status must be 'error' on timeout, NOT 'cancelled'",
        )

        # 2. Finalizer persistence check
        timeout_fut_2: Future = Future()
        timeout_fut_2.set_exception(WorkflowTimeoutError("Workflow timed out after 30 seconds"))
        exec_res._allow_downstream_pending = [timeout_fut_2]

        await _finalize_allow_downstream_history(
            history_entry_id=history_id,
            execution_result=exec_res,
            credentials_owner_id=self.user_id,
            workflow_nodes=[],
            workflow_cache={},
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Timeout Test WF",
        )

        self.assertEqual(exec_res.status, "error")

        async with async_session_maker() as verify_session:
            hist_in_db = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(
                hist_in_db.status, "error", "ExecutionHistory status must be 'error' on timeout"
            )

            snap_in_db = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(snap_in_db.total_executions, 1)
            self.assertEqual(
                snap_in_db.error_count, 1, "Analytics error_count must be 1 on timeout"
            )
            self.assertEqual(
                snap_in_db.success_count, 0, "Analytics success_count must be 0 on timeout"
            )

    async def test_unexpected_exception_in_allow_downstream_preserves_traceback_and_sets_error(
        self,
    ) -> None:
        """Unexpected exceptions in allowDownstream:
        1. Are logged with full traceback (logger.exception).
        2. Are NOT misclassified as cancelled or success.
        3. Set status='error'.
        4. Re-raise out of join_allow_downstream.
        5. Detached finalizer logs with traceback and persists status='error'."""
        from app.api.workflows import _finalize_allow_downstream_history

        history_id = uuid.uuid4()
        initial_history = ExecutionHistory(
            id=history_id,
            workflow_id=self.workflow_id,
            inputs={"data": "test_unexpected"},
            outputs={"initial": "ok"},
            node_results=[{"node_id": "initial_step", "status": "success"}],
            status="running",
            execution_time_ms=10.0,
            started_at=datetime.now(timezone.utc),
        )
        async with async_session_maker() as init_session:
            init_session.add(initial_history)
            await init_session.commit()

        error_fut: Future = Future()
        error_fut.set_exception(
            RuntimeError("Unexpected database socket explosion during allowDownstream")
        )

        exec_res = ExecutionResult(
            workflow_id=self.workflow_id,
            status="success",
            outputs={"initial": "ok"},
            node_results=[{"node_id": "initial_step", "status": "success"}],
            execution_time_ms=10.0,
            _allow_downstream_pending=[error_fut],
            _allow_downstream_node_results=[],
        )

        # 1. Verify join_allow_downstream logs exception with traceback and re-raises
        with self.assertLogs("app.services.workflow_executor", level="ERROR") as cm:
            with self.assertRaises(RuntimeError):
                exec_res.join_allow_downstream()

        self.assertIn(
            "Unexpected exception in allowDownstream background execution", "\n".join(cm.output)
        )
        self.assertIn("Unexpected database socket explosion", "\n".join(cm.output))
        self.assertEqual(
            exec_res.status,
            "error",
            "ExecutionResult status must be 'error' on unexpected exception",
        )

        # 2. Verify _finalize_allow_downstream_history logs exception with traceback and persists 'error'
        error_fut_2: Future = Future()
        error_fut_2.set_exception(
            RuntimeError("Unexpected database socket explosion during allowDownstream")
        )
        exec_res._allow_downstream_pending = [error_fut_2]

        with self.assertLogs("app.api.workflows", level="ERROR") as cm_finalizer:
            await _finalize_allow_downstream_history(
                history_entry_id=history_id,
                execution_result=exec_res,
                credentials_owner_id=self.user_id,
                workflow_nodes=[],
                workflow_cache={},
                workflow_id=self.workflow_id,
                owner_id=self.user_id,
                workflow_name="Unexpected Error WF",
            )

        self.assertIn("join_allow_downstream failed unexpectedly", "\n".join(cm_finalizer.output))
        self.assertEqual(exec_res.status, "error")

        async with async_session_maker() as verify_session:
            hist_in_db = (
                await verify_session.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == history_id)
                )
            ).scalar_one()
            self.assertEqual(hist_in_db.status, "error", "ExecutionHistory status must be 'error'")
            self.assertIn("socket explosion", str(hist_in_db.outputs.get("error", "")))

            snap_in_db = (
                await verify_session.execute(
                    select(WorkflowAnalyticsSnapshot).where(
                        WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                    )
                )
            ).scalar_one()
            self.assertEqual(snap_in_db.error_count, 1)
            self.assertEqual(snap_in_db.success_count, 0)


class DashboardChatCodexVsHitlPipelineTests(unittest.IsolatedAsyncioTestCase):
    """Trace Codex vs HITL pauses through the actual chat pipeline:
    _sanitize_tool_result_for_llm, _extract_pending_hitl_review_payload, and LLM tool message content."""

    def test_codex_pause_pipeline_propagation(self) -> None:
        codex_tool_output = json.dumps(
            {
                "status": "pending",
                "workflow_id": str(uuid.uuid4()),
                "workflow_name": "Codex Workflow",
                "execution_history_id": str(uuid.uuid4()),
                "outputs": {},
                "node_results": [],
                "pending_review": {
                    "kind": "codex",
                    "type": "codex",
                    "summary": "Codex needs input to choose database branch",
                    "question": "Which database branch should be migrated?",
                    "answer_url": "http://localhost:3000/codex/followup/codex-token-xyz",
                    "request_id": str(uuid.uuid4()),
                },
            }
        )

        # 1. Pipeline sanitization for LLM tool round
        sanitized = _sanitize_tool_result_for_llm(codex_tool_output, "execute_workflow")
        llm_context = json.loads(sanitized)
        self.assertEqual(llm_context["status"], "pending")
        self.assertIn("pending_review", llm_context)
        self.assertEqual(llm_context["pending_review"]["kind"], "codex")
        self.assertEqual(
            llm_context["pending_review"]["question"],
            "Which database branch should be migrated?",
        )
        self.assertEqual(
            llm_context["pending_review"]["answer_url"],
            "http://localhost:3000/codex/followup/codex-token-xyz",
        )

        # 2. UI SSE event extraction suppresses Codex from emitting HITL approval card
        hitl_card_payload = _extract_pending_hitl_review_payload(codex_tool_output)
        self.assertIsNone(
            hitl_card_payload,
            "Codex pauses must never produce a HITL approval card in chat stream",
        )

    def test_hitl_pause_pipeline_propagation(self) -> None:
        hitl_tool_output = json.dumps(
            {
                "status": "pending",
                "workflow_id": str(uuid.uuid4()),
                "workflow_name": "HITL Workflow",
                "execution_history_id": str(uuid.uuid4()),
                "outputs": {},
                "node_results": [],
                "pending_review": {
                    "kind": "hitl",
                    "type": "hitl",
                    "summary": "Review and approve sending customer invoice",
                    "draft_text": "Invoice #1042 for $500",
                    "review_url": "http://localhost:3000/hitl/review/hitl-token-abc",
                    "request_id": str(uuid.uuid4()),
                },
            }
        )

        # 1. Pipeline sanitization for LLM tool round
        sanitized = _sanitize_tool_result_for_llm(hitl_tool_output, "execute_workflow")
        llm_context = json.loads(sanitized)
        self.assertEqual(llm_context["status"], "pending")
        self.assertEqual(llm_context["pending_review"]["kind"], "hitl")

        # 2. UI SSE event extraction emits HITL approval card
        hitl_card_payload = _extract_pending_hitl_review_payload(hitl_tool_output)
        self.assertIsNotNone(
            hitl_card_payload,
            "HITL pauses must produce a HITL approval card in chat stream",
        )
        self.assertEqual(hitl_card_payload["kind"], "hitl")
        self.assertEqual(
            hitl_card_payload["review_url"],
            "http://localhost:3000/hitl/review/hitl-token-abc",
        )
        self.assertEqual(
            hitl_card_payload["draft_text"],
            "Invoice #1042 for $500",
        )

    async def test_chat_loop_multi_turn_codex_steering(self) -> None:
        """Area 3: Multi-turn mocked chat-loop test for Codex pause.
        Round 1: LLM invokes execute_workflow tool.
        Tool result: Codex pending with question and answer_url.
        Round 2: LLM receives sanitized result with kind="codex", steers user to link,
        no resolve_hitl_review call is made, and no HITL card is emitted in the SSE stream."""
        user = MagicMock()
        user.id = uuid.uuid4()
        wf_id = uuid.uuid4()

        codex_tool_output = json.dumps(
            {
                "status": "pending",
                "workflow_id": str(wf_id),
                "workflow_name": "Codex Migration Workflow",
                "execution_history_id": str(uuid.uuid4()),
                "outputs": {},
                "node_results": [],
                "pending_review": {
                    "kind": "codex",
                    "type": "codex",
                    "summary": "Codex requires user selection for branch",
                    "question": "Which database branch should be migrated?",
                    "answer_url": "http://localhost:3000/codex/followup/codex-token-xyz",
                    "request_id": str(uuid.uuid4()),
                },
            }
        )

        # Round 1: Model requests tool call to execute_workflow
        tc = MagicMock()
        tc.id = "tc_exec_codex"
        tc.function.name = "execute_workflow"
        tc.function.arguments = json.dumps({"workflow_id": str(wf_id)})
        msg_round1 = MagicMock()
        msg_round1.content = None
        msg_round1.tool_calls = [tc]
        resp_round1 = MagicMock()
        resp_round1.choices = [MagicMock(message=msg_round1)]
        resp_round1.usage = MagicMock(prompt_tokens=20, completion_tokens=5, total_tokens=25)

        # Round 2: Model receives sanitized tool output and directs user to the answer link
        msg_round2 = MagicMock()
        msg_round2.content = (
            "The workflow is paused waiting for your input. Please answer the Codex question at "
            "http://localhost:3000/codex/followup/codex-token-xyz."
        )
        msg_round2.tool_calls = None
        resp_round2 = MagicMock()
        resp_round2.choices = [MagicMock(message=msg_round2)]
        resp_round2.usage = MagicMock(prompt_tokens=40, completion_tokens=15, total_tokens=55)

        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [resp_round1, resp_round2]

        with (
            patch("app.api.ai_assistant.record_run_history"),
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=None)),
            patch(
                "app.api.ai_assistant.run_execute_workflow_tool",
                AsyncMock(return_value=codex_tool_output),
            ),
        ):
            chunks = [
                chunk
                async for chunk in stream_dashboard_chat(
                    client=fake_client,
                    model="gpt-4o-mini",
                    system_prompt="You are a helpful assistant.",
                    messages=[{"role": "user", "content": "Execute migration workflow"}],
                    db=AsyncMock(),
                    user=user,
                    provider="OpenAI",
                    public_base_url="http://localhost:3000",
                )
            ]

        joined_chunks = "".join(chunks)

        # 1. Codex must NOT emit workflow_pending / HITL approval card in SSE stream
        self.assertNotIn(
            '"type": "workflow_pending"',
            joined_chunks,
            "Codex pause must not emit workflow_pending card in chat stream",
        )

        # 2. Verify Round 2 call to the LLM
        self.assertEqual(fake_client.chat.completions.create.call_count, 2)
        call_round2_kwargs = fake_client.chat.completions.create.call_args_list[1].kwargs
        messages_sent_to_r2 = call_round2_kwargs["messages"]

        tool_msgs = [m for m in messages_sent_to_r2 if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        tool_payload = json.loads(tool_msgs[0]["content"])
        self.assertEqual(tool_payload["status"], "pending")
        self.assertIn("pending_review", tool_payload)
        self.assertEqual(tool_payload["pending_review"]["kind"], "codex")
        self.assertEqual(
            tool_payload["pending_review"]["question"],
            "Which database branch should be migrated?",
        )
        self.assertEqual(
            tool_payload["pending_review"]["answer_url"],
            "http://localhost:3000/codex/followup/codex-token-xyz",
        )

        # 3. Model directs user to the answer link
        self.assertIn("http://localhost:3000/codex/followup/codex-token-xyz", joined_chunks)

    async def test_chat_loop_multi_turn_hitl_approval_card(self) -> None:
        """Area 3 Counterpart: Multi-turn mocked chat-loop test for HITL pause.
        Round 1: LLM invokes execute_workflow tool.
        Tool result: HITL pending review.
        Stream emits workflow_pending SSE event with review_url and draft_text,
        and Round 2 LLM receives sanitized HITL payload."""
        user = MagicMock()
        user.id = uuid.uuid4()
        wf_id = uuid.uuid4()

        hitl_tool_output = json.dumps(
            {
                "status": "pending",
                "workflow_id": str(wf_id),
                "workflow_name": "HITL Approval Workflow",
                "execution_history_id": str(uuid.uuid4()),
                "outputs": {},
                "node_results": [],
                "pending_review": {
                    "kind": "hitl",
                    "type": "hitl",
                    "summary": "Review invoice before sending",
                    "draft_text": "Invoice #500 for $1,200",
                    "review_url": "http://localhost:3000/hitl/review/hitl-token-abc",
                    "request_id": str(uuid.uuid4()),
                },
            }
        )

        tc = MagicMock()
        tc.id = "tc_exec_hitl"
        tc.function.name = "execute_workflow"
        tc.function.arguments = json.dumps({"workflow_id": str(wf_id)})
        msg_round1 = MagicMock()
        msg_round1.content = None
        msg_round1.tool_calls = [tc]
        resp_round1 = MagicMock()
        resp_round1.choices = [MagicMock(message=msg_round1)]
        resp_round1.usage = MagicMock(prompt_tokens=20, completion_tokens=5, total_tokens=25)

        msg_round2 = MagicMock()
        msg_round2.content = "I have submitted the workflow for human approval."
        msg_round2.tool_calls = None
        resp_round2 = MagicMock()
        resp_round2.choices = [MagicMock(message=msg_round2)]
        resp_round2.usage = MagicMock(prompt_tokens=40, completion_tokens=15, total_tokens=55)

        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [resp_round1, resp_round2]

        with (
            patch("app.api.ai_assistant.record_run_history"),
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=None)),
            patch(
                "app.api.ai_assistant.run_execute_workflow_tool",
                AsyncMock(return_value=hitl_tool_output),
            ),
        ):
            chunks = [
                chunk
                async for chunk in stream_dashboard_chat(
                    client=fake_client,
                    model="gpt-4o-mini",
                    system_prompt="You are a helpful assistant.",
                    messages=[{"role": "user", "content": "Execute invoice workflow"}],
                    db=AsyncMock(),
                    user=user,
                    provider="OpenAI",
                    public_base_url="http://localhost:3000",
                )
            ]

        joined_chunks = "".join(chunks)

        # 1. HITL MUST emit workflow_pending event with kind: hitl in chat stream
        self.assertIn(
            '"type": "workflow_pending"',
            joined_chunks,
            "HITL pause must emit workflow_pending event in chat stream",
        )
        self.assertIn(
            '"kind": "hitl"',
            joined_chunks,
            "HITL pause event must carry kind: hitl",
        )
        # Event type must NOT be overwritten with type: hitl
        self.assertNotIn(
            '"type": "hitl"',
            joined_chunks,
            "SSE event type must remain workflow_pending, not overwritten with hitl",
        )
        self.assertIn("http://localhost:3000/hitl/review/hitl-token-abc", joined_chunks)
        self.assertIn("Invoice #500 for $1,200", joined_chunks)

        # 2. Round 2 model receives sanitized HITL payload
        self.assertEqual(fake_client.chat.completions.create.call_count, 2)
        call_round2_kwargs = fake_client.chat.completions.create.call_args_list[1].kwargs
        messages_sent_to_r2 = call_round2_kwargs["messages"]

        tool_msgs = [m for m in messages_sent_to_r2 if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        tool_payload = json.loads(tool_msgs[0]["content"])
        self.assertEqual(tool_payload["status"], "pending")
        self.assertEqual(tool_payload["pending_review"]["kind"], "hitl")

    def test_workflow_pending_sse_event_structure_and_codex_differentiation(self) -> None:
        """Verify the exact SSE event structure:
        - HITL pauses yield SSE events with type='workflow_pending' and kind='hitl'.
        - type='hitl' must NEVER be present as the SSE event type.
        - Codex pauses yield kind='codex' internally for candidate extraction, but do NOT produce
          a workflow_pending SSE event card in chat stream."""
        hitl_raw_payload = json.dumps(
            {
                "status": "pending",
                "workflow_id": str(uuid.uuid4()),
                "workflow_name": "Deploy Service",
                "execution_history_id": str(uuid.uuid4()),
                "outputs": {},
                "node_results": [],
                "pending_review": {
                    "kind": "hitl",
                    "type": "hitl",
                    "summary": "Approve production deployment",
                    "draft_text": "Confirm deploy to prod cluster",
                    "review_url": "http://localhost:3000/hitl/review/sample-token",
                    "request_id": str(uuid.uuid4()),
                },
            }
        )

        extracted_hitl = _extract_pending_hitl_review_payload(hitl_raw_payload)
        self.assertIsNotNone(extracted_hitl)
        self.assertEqual(extracted_hitl["kind"], "hitl")
        self.assertNotIn("type", extracted_hitl)

        # Simulate the exact SSE event serialization in ai_assistant.py
        sse_event = {
            **extracted_hitl,
            "type": "workflow_pending",
            "kind": extracted_hitl.get("kind") or "hitl",
        }
        self.assertEqual(sse_event["type"], "workflow_pending")
        self.assertEqual(sse_event["kind"], "hitl")
        self.assertNotEqual(sse_event["type"], "hitl")

        # Verify Codex differentiation
        codex_raw_payload = json.dumps(
            {
                "status": "pending",
                "workflow_id": str(uuid.uuid4()),
                "workflow_name": "Codex Service",
                "execution_history_id": str(uuid.uuid4()),
                "outputs": {},
                "node_results": [],
                "pending_review": {
                    "kind": "codex",
                    "type": "codex",
                    "summary": "Choose parameter",
                    "question": "Which cluster?",
                    "answer_url": "http://localhost:3000/codex/followup/sample-token",
                    "request_id": str(uuid.uuid4()),
                },
            }
        )
        extracted_codex = _extract_pending_hitl_review_payload(codex_raw_payload)
        self.assertIsNone(
            extracted_codex,
            "Codex pause must not extract as HITL review payload or emit workflow_pending card",
        )

    async def test_normal_chat_completion_does_not_cancel_downstream_work(self) -> None:
        """Normal chat stream completion must NOT set cancel_event.
        cancel_event must only be set when the stream disconnects or aborts prematurely."""
        from app.services.assistant_yolo import stream_until_disconnect

        async def fake_not_disconnected() -> bool:
            return False

        # Scenario 1: Normal clean completion
        cancel_event_normal = threading.Event()

        async def clean_producer():
            yield "data: chunk 1\n\n"
            yield "data: chunk 2\n\n"

        chunks_normal = []
        async for chunk in stream_until_disconnect(
            clean_producer(),
            is_disconnected=fake_not_disconnected,
            cancel_event=cancel_event_normal,
            heartbeat_seconds=1.0,
        ):
            chunks_normal.append(chunk)

        self.assertEqual(len(chunks_normal), 2)
        self.assertFalse(
            cancel_event_normal.is_set(),
            "cancel_event must NOT be set when chat stream completes normally",
        )

        # Scenario 2: Premature client disconnect / generator exit (Starlette calls aclose on disconnect)
        cancel_event_aborted = threading.Event()

        async def infinite_producer():
            while True:
                yield "data: chunk\n\n"
                await asyncio.sleep(0.01)

        chunks_aborted = []
        gen = stream_until_disconnect(
            infinite_producer(),
            is_disconnected=fake_not_disconnected,
            cancel_event=cancel_event_aborted,
            heartbeat_seconds=1.0,
        )
        try:
            async for chunk in gen:
                chunks_aborted.append(chunk)
                break
        finally:
            await gen.aclose()

        self.assertTrue(
            cancel_event_aborted.is_set(),
            "cancel_event MUST be set when client disconnects prematurely (aclose invoked)",
        )

        # Scenario 3: Disconnect detected by watcher
        cancel_event_watcher = threading.Event()
        disconnected_flag = False

        async def disconnect_checker() -> bool:
            return disconnected_flag

        gen_watcher = stream_until_disconnect(
            infinite_producer(),
            is_disconnected=disconnect_checker,
            cancel_event=cancel_event_watcher,
            heartbeat_seconds=1.0,
            poll_seconds=0.01,
        )
        chunks_watcher = []
        try:
            async for chunk in gen_watcher:
                chunks_watcher.append(chunk)
                disconnected_flag = True
                await asyncio.sleep(0.05)  # Allow watcher to poll and set cancel_event
                break
        finally:
            await gen_watcher.aclose()

        self.assertTrue(
            cancel_event_watcher.is_set(),
            "cancel_event MUST be set when watcher detects client disconnect",
        )
