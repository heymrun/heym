import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from app.api.ai_assistant import (
    _extract_pending_hitl_review_payload,
    _extract_pending_review_from_candidate,
    resolve_hitl_review_tool,
    run_execute_workflow_tool,
)
from app.db.models import (
    CodexFollowupRequest,
    ExecutionHistory,
    HITLRequest,
    User,
    Workflow,
    WorkflowAnalyticsSnapshot,
)
from app.db.session import async_session_maker
from app.services.global_variables_service import get_global_variables_context
from app.services.workflow_executor import ExecutionResult, SubWorkflowExecution


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
                    "answerUrl": "http://localhost/answer/tok",
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
        self.assertEqual(data["pending_review"]["answer_url"], "http://localhost/answer/tok")
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
            "answerUrl": "http://localhost:3000/codex/answer/sample-token",
            "requestId": "11111111-1111-1111-1111-111111111111",
            "expiresAt": "2026-10-01T00:00:00Z",
        }
        extracted = _extract_pending_review_from_candidate(candidate)
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted["kind"], "codex")
        self.assertEqual(extracted["type"], "codex")
        self.assertEqual(extracted["question"], "Which GitHub repo should be used?")
        self.assertEqual(extracted["answer_url"], "http://localhost:3000/codex/answer/sample-token")
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
        self.assertEqual(extracted["type"], "hitl")
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
                    "answer_url": "http://localhost:3000/codex/answer/token-123",
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
                        "answerUrl": "http://localhost:3000/codex/answer/token-123",
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

    async def test_resolve_hitl_review_tool_rejects_codex_answer_url(self) -> None:
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
                review_url="http://localhost:3000/codex/answer/codex-token-abc",
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
