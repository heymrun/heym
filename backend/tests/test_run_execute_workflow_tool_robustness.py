import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.ai_assistant import run_execute_workflow_tool
from app.services.global_variables_service import get_global_variables_context
from app.services.workflow_executor import ExecutionResult


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
        self.assertEqual(data["pending_review"]["review_url"], "http://localhost/answer/tok")

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
        db.flush = AsyncMock()

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.ai_assistant.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.ai_assistant._spawn_detached_task") as mock_spawn,
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

        # Detached task spawned with _finalize_allow_downstream_history
        mock_spawn.assert_called_once()
        mock_finalize.assert_called_once()
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
