import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

from app.api.workflows import get_execution_history, list_all_execution_history


class _ExecuteResult:
    def __init__(
        self, *, scalar_value: object | None = None, rows: list[object] | None = None
    ) -> None:
        self._scalar_value = scalar_value
        self._rows = rows or []

    def scalar(self) -> object | None:
        return self._scalar_value

    def scalars(self) -> "_ExecuteResult":
        return self

    def all(self) -> list[object]:
        return self._rows


def _compile_sql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


class ExecutionHistoryApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = MagicMock()
        self.user.id = uuid.uuid4()
        self.db = AsyncMock()

    async def test_per_workflow_history_applies_trigger_source_filter(self) -> None:
        workflow_id = uuid.uuid4()
        workflow = MagicMock()
        workflow.name = "Tagged Workflow"
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(scalar_value=0),
                _ExecuteResult(rows=[]),
            ]
        )

        with patch(
            "app.api.workflows.get_workflow_for_user",
            AsyncMock(return_value=workflow),
        ):
            response = await get_execution_history(
                workflow_id=workflow_id,
                current_user=self.user,
                db=self.db,
                trigger_source="Quick Drawer",
            )

        self.assertEqual(response.total, 0)

        total_sql = _compile_sql(self.db.execute.call_args_list[0].args[0])
        history_sql = _compile_sql(self.db.execute.call_args_list[1].args[0])

        self.assertIn("execution_history.trigger_source = 'quick drawer'", total_sql)
        self.assertIn("execution_history.trigger_source = 'quick drawer'", history_sql)
        self.assertNotIn("ilike", total_sql)
        self.assertNotIn("ilike", history_sql)

    async def test_per_workflow_history_combines_search_and_trigger_source_filter(self) -> None:
        workflow_id = uuid.uuid4()
        workflow = MagicMock()
        workflow.name = "Canvas Workflow"
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(scalar_value=0),
                _ExecuteResult(rows=[]),
            ]
        )

        with patch(
            "app.api.workflows.get_workflow_for_user",
            AsyncMock(return_value=workflow),
        ):
            response = await get_execution_history(
                workflow_id=workflow_id,
                current_user=self.user,
                db=self.db,
                search="payload",
                trigger_source="Canvas",
            )

        self.assertEqual(response.total, 0)

        total_sql = _compile_sql(self.db.execute.call_args_list[0].args[0])
        history_sql = _compile_sql(self.db.execute.call_args_list[1].args[0])

        self.assertIn("execution_history.trigger_source = 'canvas'", total_sql)
        self.assertIn("execution_history.trigger_source = 'canvas'", history_sql)
        self.assertIn("ilike", total_sql)
        self.assertIn("ilike", history_sql)

    async def test_all_history_combines_search_and_trigger_source_filter(self) -> None:
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(rows=[]),
                _ExecuteResult(rows=[]),
            ]
        )

        response = await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            search="canvas",
            execution_status=None,
            trigger_source="Quick Drawer",
            workflow_id=None,
        )

        self.assertEqual(response.total, 0)

        workflow_sql = _compile_sql(self.db.execute.call_args_list[0].args[0])
        run_sql = _compile_sql(self.db.execute.call_args_list[1].args[0])

        self.assertIn("execution_history.trigger_source = 'quick drawer'", workflow_sql)
        self.assertIn("run_history.trigger_source = 'quick drawer'", run_sql)
        self.assertIn("ilike", workflow_sql)
        self.assertIn("ilike", run_sql)

    async def test_all_history_workflow_id_filter_applied_to_exec_query(self) -> None:
        """workflow_id param narrows execution_history rows to that workflow."""
        target_id = uuid.uuid4()
        self.db.execute = AsyncMock(return_value=_ExecuteResult(rows=[]))

        response = await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            execution_status=None,
            trigger_source=None,
            workflow_id=str(target_id),
        )

        self.assertEqual(response.total, 0)
        # Only one db.execute call – RunHistory is skipped when filtering by workflow_id.
        self.assertEqual(self.db.execute.call_count, 1)

        exec_sql = _compile_sql(self.db.execute.call_args_list[0].args[0])
        self.assertIn(str(target_id), exec_sql)
        self.assertNotIn("run_history", exec_sql)

    async def test_all_history_workflow_id_skips_run_history_query(self) -> None:
        """When workflow_id is given the chat/assistant RunHistory table is not queried."""
        self.db.execute = AsyncMock(return_value=_ExecuteResult(rows=[]))

        await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            execution_status=None,
            trigger_source=None,
            workflow_id=str(uuid.uuid4()),
        )

        # Exactly one query must have been issued (only ExecutionHistory).
        self.assertEqual(self.db.execute.call_count, 1)
        exec_sql = _compile_sql(self.db.execute.call_args_list[0].args[0])
        self.assertNotIn("run_history", exec_sql)

    async def test_all_history_workflow_id_and_status_combined(self) -> None:
        """workflow_id and execution_status filters are both applied to the same query."""
        target_id = uuid.uuid4()
        self.db.execute = AsyncMock(return_value=_ExecuteResult(rows=[]))

        await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            execution_status="error",
            trigger_source=None,
            workflow_id=str(target_id),
        )

        self.assertEqual(self.db.execute.call_count, 1)
        exec_sql = _compile_sql(self.db.execute.call_args_list[0].args[0])
        self.assertIn(str(target_id), exec_sql)
        self.assertIn("'error'", exec_sql)

    async def test_all_history_without_workflow_id_queries_both_tables(self) -> None:
        """Without a workflow_id filter both ExecutionHistory and RunHistory are queried."""
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(rows=[]),
                _ExecuteResult(rows=[]),
            ]
        )

        await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            execution_status=None,
            trigger_source=None,
            workflow_id=None,
        )

        # Two queries: one for ExecutionHistory, one for RunHistory.
        self.assertEqual(self.db.execute.call_count, 2)
        run_sql = _compile_sql(self.db.execute.call_args_list[1].args[0])
        self.assertIn("run_history", run_sql)

    async def test_all_history_workflow_id_without_status_no_status_clause(self) -> None:
        """When only workflow_id is given, the query must not contain a status filter."""
        target_id = uuid.uuid4()
        self.db.execute = AsyncMock(return_value=_ExecuteResult(rows=[]))

        await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            execution_status=None,
            trigger_source=None,
            workflow_id=str(target_id),
        )

        exec_sql = _compile_sql(self.db.execute.call_args_list[0].args[0])
        self.assertIn(str(target_id), exec_sql)
        # No status literal should appear when execution_status was not provided.
        self.assertNotIn("'error'", exec_sql)
        self.assertNotIn("'success'", exec_sql)
