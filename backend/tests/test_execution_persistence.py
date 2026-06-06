"""Unit tests for workflow execution persistence helpers."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.db.models import ExecutionHistory
from app.services.execution_persistence import (
    persist_execution_result,
    persist_sub_workflow_execution_histories,
    persist_workflow_execution_analytics,
    persist_workflow_execution_record,
    update_execution_history_and_persist_artifacts,
)
from app.services.workflow_executor import ExecutionResult, SubWorkflowExecution


class PersistWorkflowExecutionAnalyticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_delegates_to_upsert_snapshot(self) -> None:
        db = AsyncMock()
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()

        with patch(
            "app.services.execution_persistence.upsert_workflow_analytics_snapshot",
            AsyncMock(),
        ) as mock_upsert:
            await persist_workflow_execution_analytics(
                db,
                workflow_id=workflow_id,
                owner_id=owner_id,
                workflow_name="My workflow",
                status="success",
                execution_time_ms=42.5,
            )

        mock_upsert.assert_awaited_once_with(
            db,
            workflow_id=workflow_id,
            owner_id=owner_id,
            workflow_name_snapshot="My workflow",
            status="success",
            execution_time_ms=42.5,
        )


class PersistSubWorkflowExecutionHistoriesTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_op_for_empty_list(self) -> None:
        db = SimpleNamespace(add=lambda _row: None)

        with patch(
            "app.services.execution_persistence.upsert_workflow_analytics_snapshot",
            AsyncMock(),
        ) as mock_upsert:
            await persist_sub_workflow_execution_histories(db, [])

        mock_upsert.assert_not_awaited()

    async def test_persists_dataclass_and_dict_sub_executions(self) -> None:
        sub_id = uuid.uuid4()
        added_rows: list[ExecutionHistory] = []
        db = SimpleNamespace(add=lambda row: added_rows.append(row))

        sub_dataclass = SubWorkflowExecution(
            workflow_id=str(sub_id),
            inputs={"a": 1},
            outputs={"b": 2},
            status="success",
            execution_time_ms=10.0,
            node_results=[{"node_id": "n1"}],
            workflow_name="Child",
            trigger_source="SUB_WORKFLOW",
        )
        sub_dict = {
            "workflow_id": str(uuid.uuid4()),
            "inputs": {"x": "y"},
            "outputs": {"ok": True},
            "status": "error",
            "execution_time_ms": 5.0,
            "node_results": [],
            "workflow_name": "Other child",
        }

        with patch(
            "app.services.execution_persistence.upsert_workflow_analytics_snapshot",
            AsyncMock(),
        ) as mock_upsert:
            await persist_sub_workflow_execution_histories(
                db,
                [sub_dataclass, sub_dict],
            )

        self.assertEqual(len(added_rows), 2)
        first, second = added_rows
        self.assertEqual(first.workflow_id, sub_id)
        self.assertEqual(first.trigger_source, "SUB_WORKFLOW")
        self.assertEqual(first.inputs, {"a": 1})
        self.assertEqual(second.trigger_source, "SUB_WORKFLOW")
        self.assertEqual(mock_upsert.await_count, 2)


class PersistWorkflowExecutionRecordTests(unittest.IsolatedAsyncioTestCase):
    def _db(self, added_rows: list[object]) -> SimpleNamespace:
        return SimpleNamespace(add=lambda row: added_rows.append(row))

    async def test_creates_main_history_sub_history_and_globals(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        sub_workflow_id = uuid.uuid4()
        added_rows: list[object] = []
        db = self._db(added_rows)
        workflow_nodes = [{"id": "var-1", "type": "variable", "data": {"isGlobal": True}}]
        workflow_cache = {"cache": True}
        sub_exec = SubWorkflowExecution(
            workflow_id=str(sub_workflow_id),
            inputs={},
            outputs={},
            status="success",
            execution_time_ms=1.0,
        )

        with (
            patch(
                "app.services.execution_persistence.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ) as mock_upsert,
            patch(
                "app.services.execution_persistence.persist_global_variables_from_execution",
                AsyncMock(),
            ) as mock_globals,
        ):
            history_entry = await persist_workflow_execution_record(
                db,
                workflow_id=workflow_id,
                workflow_name="Parent",
                owner_id=owner_id,
                inputs={"triggered_by": "cron"},
                outputs={"result": "ok"},
                node_results=[{"node_type": "output"}],
                status="success",
                execution_time_ms=100.0,
                trigger_source="cron",
                workflow_nodes=workflow_nodes,
                workflow_cache=workflow_cache,
                sub_workflow_executions=[sub_exec],
            )

        history_rows = [row for row in added_rows if isinstance(row, ExecutionHistory)]
        self.assertEqual(len(history_rows), 2)
        self.assertIs(history_entry, history_rows[0])
        self.assertEqual(history_entry.workflow_id, workflow_id)
        self.assertEqual(history_entry.trigger_source, "cron")
        self.assertEqual(history_entry.inputs, {"triggered_by": "cron"})
        self.assertEqual(mock_upsert.await_count, 2)
        mock_globals.assert_awaited_once_with(
            db,
            owner_id,
            workflow_nodes,
            workflow_cache,
            [{"node_type": "output"}],
            [sub_exec],
        )

    async def test_can_skip_sub_workflows_and_globals(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        added_rows: list[object] = []
        db = self._db(added_rows)
        sub_exec = SubWorkflowExecution(
            workflow_id=str(uuid.uuid4()),
            inputs={},
            outputs={},
            status="success",
            execution_time_ms=1.0,
        )

        with (
            patch(
                "app.services.execution_persistence.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ) as mock_upsert,
            patch(
                "app.services.execution_persistence.persist_global_variables_from_execution",
                AsyncMock(),
            ) as mock_globals,
        ):
            await persist_workflow_execution_record(
                db,
                workflow_id=workflow_id,
                workflow_name="Parent",
                owner_id=owner_id,
                inputs={},
                outputs={},
                node_results=[],
                status="success",
                execution_time_ms=1.0,
                trigger_source="API",
                workflow_nodes=[],
                workflow_cache={},
                sub_workflow_executions=[sub_exec],
                persist_sub_workflows=False,
                persist_global_variables=False,
            )

        self.assertEqual(len(added_rows), 1)
        mock_upsert.assert_awaited_once()
        mock_globals.assert_not_awaited()

    async def test_json_compatible_normalizes_payloads(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        added_rows: list[object] = []
        db = self._db(added_rows)

        with (
            patch(
                "app.services.execution_persistence.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ),
            patch(
                "app.services.execution_persistence.persist_global_variables_from_execution",
                AsyncMock(),
            ),
        ):
            history_entry = await persist_workflow_execution_record(
                db,
                workflow_id=workflow_id,
                workflow_name="Parent",
                owner_id=owner_id,
                inputs={"n": 1},
                outputs={"n": 2},
                node_results=[{"n": 3}],
                status="success",
                execution_time_ms=1.0,
                trigger_source="cron",
                workflow_nodes=[],
                workflow_cache={},
                sub_workflow_executions=[],
                json_compatible=True,
            )

        self.assertEqual(history_entry.inputs, {"n": 1})
        self.assertEqual(history_entry.outputs, {"n": 2})
        self.assertEqual(history_entry.node_results, [{"n": 3}])


class PersistExecutionResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_delegates_to_persist_workflow_execution_record(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"out": 1},
            execution_time_ms=9.0,
            node_results=[{"node_id": "n1"}],
            sub_workflow_executions=[],
        )
        expected_history = ExecutionHistory(
            workflow_id=workflow_id,
            inputs={},
            outputs={},
            node_results=[],
            status="success",
            execution_time_ms=9.0,
            trigger_source="MCP",
        )

        with patch(
            "app.services.execution_persistence.persist_workflow_execution_record",
            AsyncMock(return_value=expected_history),
        ) as mock_record:
            history_entry = await persist_execution_result(
                AsyncMock(),
                workflow_id=workflow_id,
                workflow_name="Tool workflow",
                owner_id=owner_id,
                inputs={"body": {}},
                result=result,
                trigger_source="MCP",
                workflow_nodes=[],
                workflow_cache={},
                credentials_owner_id=owner_id,
            )

        self.assertIs(history_entry, expected_history)
        mock_record.assert_awaited_once()
        kwargs = mock_record.await_args.kwargs
        self.assertEqual(kwargs["workflow_id"], workflow_id)
        self.assertEqual(kwargs["outputs"], {"out": 1})
        self.assertEqual(kwargs["node_results"], [{"node_id": "n1"}])
        self.assertEqual(kwargs["status"], "success")
        self.assertEqual(kwargs["execution_time_ms"], 9.0)
        self.assertEqual(kwargs["trigger_source"], "MCP")
        self.assertEqual(kwargs["sub_workflow_executions"], [])


class UpdateExecutionHistoryAndPersistArtifactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_updates_history_persists_subs_globals_and_analytics(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        sub_workflow_id = uuid.uuid4()
        history_entry = ExecutionHistory(
            workflow_id=workflow_id,
            inputs={"old": True},
            outputs={"old": True},
            node_results=[],
            status="pending",
            execution_time_ms=0.0,
            trigger_source="API",
        )
        history_entry.id = uuid.uuid4()
        added_rows: list[object] = []
        db = SimpleNamespace(add=lambda row: added_rows.append(row))
        workflow_nodes: list[dict] = []
        workflow_cache: dict[str, dict] = {}
        sub_exec = SubWorkflowExecution(
            workflow_id=str(sub_workflow_id),
            inputs={},
            outputs={"done": True},
            status="success",
            execution_time_ms=3.0,
        )

        with (
            patch(
                "app.services.execution_persistence.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ) as mock_upsert,
            patch(
                "app.services.execution_persistence.persist_global_variables_from_execution",
                AsyncMock(),
            ) as mock_globals,
        ):
            await update_execution_history_and_persist_artifacts(
                db,
                history_entry,
                workflow_id=workflow_id,
                workflow_name="Parent",
                owner_id=owner_id,
                outputs={"final": True},
                node_results=[{"node_type": "variable", "output": {"name": "x", "value": 1}}],
                status="success",
                execution_time_ms=50.0,
                workflow_nodes=workflow_nodes,
                workflow_cache=workflow_cache,
                sub_workflow_executions=[sub_exec],
            )

        self.assertEqual(history_entry.status, "success")
        self.assertEqual(history_entry.outputs, {"final": True})
        self.assertEqual(history_entry.execution_time_ms, 50.0)
        self.assertEqual(len(added_rows), 1)
        self.assertEqual(added_rows[0].workflow_id, sub_workflow_id)
        mock_globals.assert_awaited_once()
        self.assertEqual(mock_upsert.await_count, 2)

    async def test_refresh_main_analytics_can_be_disabled(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        history_entry = ExecutionHistory(
            workflow_id=workflow_id,
            inputs={},
            outputs={},
            node_results=[],
            status="pending",
            execution_time_ms=0.0,
            trigger_source="API",
        )
        history_entry.id = uuid.uuid4()

        with (
            patch(
                "app.services.execution_persistence.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ) as mock_upsert,
            patch(
                "app.services.execution_persistence.persist_global_variables_from_execution",
                AsyncMock(),
            ),
        ):
            await update_execution_history_and_persist_artifacts(
                SimpleNamespace(add=lambda _row: None),
                history_entry,
                workflow_id=workflow_id,
                workflow_name="Parent",
                owner_id=owner_id,
                outputs={"done": True},
                node_results=[],
                status="success",
                execution_time_ms=10.0,
                workflow_nodes=[],
                workflow_cache={},
                sub_workflow_executions=[],
                refresh_main_analytics=False,
            )

        mock_upsert.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
