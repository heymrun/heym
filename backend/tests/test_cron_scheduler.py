import unittest
import uuid
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.db.models import ExecutionHistory
from app.services.cron_scheduler import CronScheduler
from app.services.workflow_executor import (
    DotList,
    ExecutionResult,
    NodeResult,
    SubWorkflowExecution,
)


class CronSchedulerExecutionHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_workflow_persists_cron_trigger_source(self) -> None:
        scheduler = CronScheduler()
        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        sub_workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=owner_id,
            name="Main workflow",
            nodes=[],
            edges=[],
        )

        added_rows: list[object] = []

        def add_row(row: object) -> None:
            added_rows.append(row)

        db = SimpleNamespace(
            add=add_row,
            commit=AsyncMock(),
        )
        execution_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"ok": True},
            execution_time_ms=12.5,
            node_results=[],
            sub_workflow_executions=[
                SubWorkflowExecution(
                    workflow_id=str(sub_workflow_id),
                    inputs={"source": "main"},
                    outputs={"done": True},
                    status="success",
                    execution_time_ms=4.0,
                    node_results=[],
                    workflow_name="Child workflow",
                )
            ],
        )

        with (
            patch(
                "app.services.cron_scheduler.collect_referenced_workflows",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.cron_scheduler.get_credentials_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.cron_scheduler.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch("app.services.cron_scheduler.execute_workflow", return_value=execution_result),
            patch(
                "app.services.cron_scheduler.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ),
            patch(
                "app.services.cron_scheduler._persist_global_variables_from_execution",
                AsyncMock(),
            ),
        ):
            await scheduler._execute_workflow(db, workflow)

        history_rows = [row for row in added_rows if isinstance(row, ExecutionHistory)]
        self.assertEqual(len(history_rows), 2)
        parent = next(r for r in history_rows if r.workflow_id == workflow_id)
        child = next(r for r in history_rows if r.workflow_id == sub_workflow_id)
        self.assertEqual(parent.trigger_source, "cron")
        self.assertEqual(child.trigger_source, "SUB_WORKFLOW")

    async def test_execute_workflow_joins_allow_downstream_before_history(self) -> None:
        scheduler = CronScheduler()
        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=owner_id,
            name="Cron allow downstream",
            nodes=[],
            edges=[],
        )

        added_rows: list[object] = []

        def add_row(row: object) -> None:
            added_rows.append(row)

        db = SimpleNamespace(
            add=add_row,
            commit=AsyncMock(),
        )

        completed_future: Future = Future()
        completed_future.set_result(None)
        execution_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"output": {"text": "ack"}},
            execution_time_ms=1.0,
            node_results=[
                {
                    "node_id": "output",
                    "node_label": "output",
                    "node_type": "output",
                    "status": "success",
                    "output": {"text": "ack"},
                    "execution_time_ms": 1.0,
                    "error": None,
                }
            ],
            sub_workflow_executions=[],
            _allow_downstream_pending=[completed_future],
            _allow_downstream_node_results=[
                NodeResult(
                    node_id="execute",
                    node_label="execute",
                    node_type="execute",
                    status="success",
                    output={"items": DotList(["done"])},
                    execution_time_ms=2.0,
                )
            ],
        )

        with (
            patch(
                "app.services.cron_scheduler.collect_referenced_workflows",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.cron_scheduler.get_credentials_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.cron_scheduler.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch("app.services.cron_scheduler.execute_workflow", return_value=execution_result),
            patch(
                "app.services.cron_scheduler.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ),
            patch(
                "app.services.cron_scheduler._persist_global_variables_from_execution",
                AsyncMock(),
            ),
        ):
            await scheduler._execute_workflow(db, workflow)

        history_rows = [row for row in added_rows if isinstance(row, ExecutionHistory)]
        self.assertEqual(len(history_rows), 1)
        parent = history_rows[0]
        self.assertFalse(execution_result.allow_downstream_pending)
        self.assertEqual(
            [node_result["node_id"] for node_result in parent.node_results],
            ["output", "execute"],
        )
        self.assertEqual(parent.node_results[1]["output"], {"items": ["done"]})
