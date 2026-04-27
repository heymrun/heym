import datetime
import threading
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.workflows import list_active_workflow_executions
from app.models.schemas import ActiveExecutionItem
from app.services.execution_cancellation import (
    ExecutionCancellationHandle,
    list_active_executions,
)
from app.services.workflow_executor import ExecutionResult, WorkflowExecutor


def _make_handle(workflow_id: uuid.UUID, execution_id: uuid.UUID) -> ExecutionCancellationHandle:
    return ExecutionCancellationHandle(
        workflow_id=workflow_id,
        execution_id=execution_id,
        event=threading.Event(),
        started_at=datetime.datetime(2025, 1, 1, 12, 0, 0),
    )


class ListActiveWorkflowExecutionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_empty_when_no_active_executions(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()

        with patch("app.api.workflows.list_active_executions", return_value=[]):
            result = await list_active_workflow_executions(current_user=user, db=db)

        self.assertEqual(result, [])
        db.execute.assert_not_called()

    async def test_filters_to_accessible_workflows(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()

        wf_id_owned = uuid.uuid4()
        wf_id_other = uuid.uuid4()
        ex_id_owned = uuid.uuid4()
        ex_id_other = uuid.uuid4()

        handles = [
            _make_handle(wf_id_owned, ex_id_owned),
            _make_handle(wf_id_other, ex_id_other),
        ]

        owned_workflow = MagicMock()
        owned_workflow.id = wf_id_owned
        owned_workflow.name = "My Workflow"

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = [owned_workflow]
        db.execute.return_value = db_result

        with patch("app.api.workflows.list_active_executions", return_value=handles):
            result = await list_active_workflow_executions(current_user=user, db=db)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].execution_id, str(ex_id_owned))
        self.assertEqual(result[0].workflow_id, str(wf_id_owned))
        self.assertEqual(result[0].workflow_name, "My Workflow")
        self.assertIsInstance(result[0], ActiveExecutionItem)

    async def test_returns_started_at_from_handle(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        handle = _make_handle(wf_id, ex_id)

        workflow = MagicMock()
        workflow.id = wf_id
        workflow.name = "Workflow A"

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = [workflow]
        db.execute.return_value = db_result

        with patch("app.api.workflows.list_active_executions", return_value=[handle]):
            result = await list_active_workflow_executions(current_user=user, db=db)

        self.assertEqual(result[0].started_at, datetime.datetime(2025, 1, 1, 12, 0, 0))


class SubWorkflowActiveTrackingTests(unittest.TestCase):
    """Sub-workflow executions must appear in the active list while running."""

    _TOOL_DEF_BASE: dict = {"_sub_workflow_ids": [], "_sub_workflow_names": {}}

    def _make_fake_result(self, workflow_id: str) -> ExecutionResult:
        return ExecutionResult(
            workflow_id=uuid.UUID(workflow_id),
            status="success",
            outputs={},
            execution_time_ms=5.0,
        )

    def _call_sub_workflow_tool(
        self,
        executor: WorkflowExecutor,
        sub_wf_id: str,
        *,
        side_effect: Exception | None = None,
    ) -> dict:
        tool_def = {
            "_sub_workflow_ids": [sub_wf_id],
            "_sub_workflow_names": {sub_wf_id: "Sub WF"},
        }
        fake_result = self._make_fake_result(sub_wf_id)

        with patch("app.services.workflow_executor.WorkflowExecutor") as mock_wfe:
            mock_sub = MagicMock()
            mock_sub.sub_workflow_executions = []
            if side_effect:
                mock_sub.execute.side_effect = side_effect
            else:
                mock_sub.execute.return_value = fake_result
            mock_wfe.return_value = mock_sub

            return executor._execute_sub_workflow_tool(
                tool_def=tool_def,
                _name="call_sub_workflow",
                args={"workflow_id": sub_wf_id, "inputs": {}},
                _timeout_seconds=30.0,
            )

    def test_register_and_clear_called_on_success(self) -> None:
        sub_wf_id = str(uuid.uuid4())
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }

        registered: list[uuid.UUID] = []
        cleared: list[uuid.UUID] = []

        def fake_register(**kwargs: object) -> threading.Event:
            registered.append(kwargs["execution_id"])
            return threading.Event()

        def fake_clear(execution_id: uuid.UUID) -> None:
            cleared.append(execution_id)

        with (
            patch("app.services.workflow_executor._register_sub_execution", fake_register),
            patch("app.services.workflow_executor._clear_sub_execution", fake_clear),
        ):
            result = self._call_sub_workflow_tool(executor, sub_wf_id)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(registered), 1)
        self.assertEqual(len(cleared), 1)
        self.assertEqual(registered[0], cleared[0])

    def test_clear_called_even_when_sub_workflow_raises(self) -> None:
        """finally block must clear the registration on exception."""
        sub_wf_id = str(uuid.uuid4())
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }

        registered: list[uuid.UUID] = []
        cleared: list[uuid.UUID] = []

        def fake_register(**kwargs: object) -> threading.Event:
            registered.append(kwargs["execution_id"])
            return threading.Event()

        def fake_clear(execution_id: uuid.UUID) -> None:
            cleared.append(execution_id)

        with (
            patch("app.services.workflow_executor._register_sub_execution", fake_register),
            patch("app.services.workflow_executor._clear_sub_execution", fake_clear),
        ):
            result = self._call_sub_workflow_tool(
                executor, sub_wf_id, side_effect=RuntimeError("boom")
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("boom", result.get("error", ""))
        # clear must have been called despite the exception
        self.assertEqual(len(cleared), 1)
        self.assertEqual(registered, cleared)

    def test_sub_workflow_visible_in_active_list_during_execution(self) -> None:
        """Integration: sub-workflow workflow_id appears in list_active_executions while running."""
        sub_wf_id = str(uuid.uuid4())
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }
        fake_result = self._make_fake_result(sub_wf_id)

        active_wf_ids_mid_run: list[uuid.UUID] = []

        def fake_execute(*, workflow_id: uuid.UUID, initial_inputs: dict) -> ExecutionResult:
            # Inspect the global active list while the sub-workflow is "running".
            active_wf_ids_mid_run.extend(h.workflow_id for h in list_active_executions())
            return fake_result

        with patch("app.services.workflow_executor.WorkflowExecutor") as mock_wfe:
            mock_sub = MagicMock()
            mock_sub.sub_workflow_executions = []
            mock_sub.execute.side_effect = fake_execute
            mock_wfe.return_value = mock_sub

            executor._execute_sub_workflow_tool(
                tool_def={
                    "_sub_workflow_ids": [sub_wf_id],
                    "_sub_workflow_names": {sub_wf_id: "Sub WF"},
                },
                _name="call_sub_workflow",
                args={"workflow_id": sub_wf_id, "inputs": {}},
                _timeout_seconds=30.0,
            )

        self.assertIn(uuid.UUID(sub_wf_id), active_wf_ids_mid_run)
        # After completion the entry must be gone.
        post_run_ids = [h.workflow_id for h in list_active_executions()]
        self.assertNotIn(uuid.UUID(sub_wf_id), post_run_ids)
