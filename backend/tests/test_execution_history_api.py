import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.workflows import (
    clear_all_execution_history,
    clear_execution_history,
    get_execution_history,
    get_execution_history_entry,
    list_all_execution_history,
)
from app.db.models import ExecutionHistory, Workflow


class _ExecuteResult:
    def __init__(
        self, *, scalar_value: object | None = None, rows: list[object] | None = None
    ) -> None:
        self._scalar_value = scalar_value
        self._rows = rows or []

    def scalar(self) -> object | None:
        return self._scalar_value

    def scalar_one(self) -> object:
        return self._scalar_value if self._scalar_value is not None else 0

    def scalars(self) -> "_ExecuteResult":
        return self

    def all(self) -> list[object]:
        return self._rows

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value


class _DeleteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


def _actor(user_id: uuid.UUID) -> SimpleNamespace:
    """A stand-in for User. audit() reads `email`, so a stub without it is not one."""
    return SimpleNamespace(id=user_id, email=f"{user_id}@example.com")


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

    async def test_collaborator_bulk_clear_preserves_shared_workflow_history(self) -> None:
        collaborator_id = uuid.uuid4()
        self.db.execute = AsyncMock(side_effect=[_DeleteResult(0), _DeleteResult(0)])

        await clear_all_execution_history(
            current_user=_actor(collaborator_id),
            db=self.db,
        )

        history_delete = self.db.execute.call_args_list[0].args[0]
        expected_delete = ExecutionHistory.__table__.delete().where(
            ExecutionHistory.workflow_id.in_(
                select(Workflow.id).where(Workflow.owner_id == collaborator_id)
            )
        )

        self.assertTrue(history_delete.compare(expected_delete))

    async def test_collaborator_cannot_clear_shared_workflow_history(self) -> None:
        workflow_id = uuid.uuid4()
        collaborator_id = uuid.uuid4()
        workflow = SimpleNamespace(id=workflow_id, owner_id=uuid.uuid4(), name="Shared workflow")
        self.db.execute = AsyncMock()

        with patch(
            "app.api.workflows.get_workflow_for_user",
            AsyncMock(return_value=workflow),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await clear_execution_history(
                    workflow_id=workflow_id,
                    current_user=_actor(collaborator_id),
                    db=self.db,
                )

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ctx.exception.detail, "Only the owner can clear history")
        self.db.execute.assert_not_called()

    async def test_owner_can_clear_owned_workflow_history(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        workflow = SimpleNamespace(id=workflow_id, owner_id=owner_id, name="Owned workflow")
        self.db.execute = AsyncMock()

        with patch(
            "app.api.workflows.get_workflow_for_user",
            AsyncMock(return_value=workflow),
        ):
            await clear_execution_history(
                workflow_id=workflow_id,
                current_user=_actor(owner_id),
                db=self.db,
            )

        self.db.execute.assert_awaited_once()

    async def test_owner_clear_emits_a_success_audit_line(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        workflow = SimpleNamespace(id=workflow_id, owner_id=owner_id, name="Owned workflow")
        self.db.execute = AsyncMock()

        with patch(
            "app.api.workflows.get_workflow_for_user",
            AsyncMock(return_value=workflow),
        ):
            with self.assertLogs("winston.audit", level="INFO") as captured:
                await clear_execution_history(
                    workflow_id=workflow_id,
                    current_user=_actor(owner_id),
                    db=self.db,
                )

        line = captured.records[0].getMessage()
        self.assertIn("action=workflow.history_clear", line)
        self.assertIn("outcome=success", line)
        self.assertIn(f"target=workflow:{workflow_id}", line)

    async def test_denied_clear_is_audited_rather_than_silently_rejected(self) -> None:
        """A collaborator reaching for someone else's history has to leave a trail."""
        workflow_id = uuid.uuid4()
        collaborator_id = uuid.uuid4()
        workflow = SimpleNamespace(id=workflow_id, owner_id=uuid.uuid4(), name="Shared workflow")
        self.db.execute = AsyncMock()

        with patch(
            "app.api.workflows.get_workflow_for_user",
            AsyncMock(return_value=workflow),
        ):
            with self.assertLogs("winston.audit", level="INFO") as captured:
                with self.assertRaises(HTTPException):
                    await clear_execution_history(
                        workflow_id=workflow_id,
                        current_user=_actor(collaborator_id),
                        db=self.db,
                    )

        line = captured.records[0].getMessage()
        self.assertIn("action=workflow.history_clear", line)
        self.assertIn("outcome=denied", line)
        self.assertIn("reason=not_owner", line)
        self.assertIn(f"actor_id={collaborator_id}", line)
        self.assertIn(f"target=workflow:{workflow_id}", line)

    async def test_bulk_clear_is_audited_with_the_number_of_rows_removed(self) -> None:
        owner_id = uuid.uuid4()
        self.db.execute = AsyncMock(side_effect=[_DeleteResult(7), _DeleteResult(3)])

        with self.assertLogs("winston.audit", level="INFO") as captured:
            await clear_all_execution_history(current_user=_actor(owner_id), db=self.db)

        line = captured.records[0].getMessage()
        self.assertIn("action=workflow.history_clear_all", line)
        self.assertIn("outcome=success", line)
        self.assertIn(f"actor_id={owner_id}", line)
        self.assertIn("workflow_runs_deleted=7", line)
        self.assertIn("chat_runs_deleted=3", line)

    async def test_all_history_list_reaches_team_shared_workflows(self) -> None:
        """The aggregated list must use the same access rule as opening the workflow."""
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(scalar_value=0),  # COUNT
                _ExecuteResult(rows=[]),  # items
            ]
        )

        await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            execution_status=None,
            trigger_source=None,
            workflow_id=None,
        )

        union_sql = _compile_sql(self.db.execute.call_args_list[0].args[0])
        self.assertIn("workflow_shares", union_sql)
        self.assertIn("workflow_team_shares", union_sql)
        self.assertIn("team_members", union_sql)

    async def test_all_history_entry_reaches_team_shared_workflows(self) -> None:
        """A row the list shows has to be openable, so both use one access rule."""
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(rows=[]),  # ExecutionHistory lookup
                _ExecuteResult(scalar_value=None),  # RunHistory fallback
            ]
        )

        with self.assertRaises(HTTPException) as ctx:
            await get_execution_history_entry(
                entry_id=uuid.uuid4(),
                current_user=self.user,
                db=self.db,
            )

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)
        entry_sql = _compile_sql(self.db.execute.call_args_list[0].args[0])
        self.assertIn("workflow_shares", entry_sql)
        self.assertIn("workflow_team_shares", entry_sql)
        self.assertIn("team_members", entry_sql)

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
        # Now uses UNION ALL: 2 calls total (COUNT + items), both contain both tables.
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(scalar_value=0),  # COUNT query
                _ExecuteResult(rows=[]),  # items query
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
        self.assertEqual(self.db.execute.call_count, 2)

        # UNION ALL SQL contains filters for both exec and run tables in one statement.
        union_sql = _compile_sql(self.db.execute.call_args_list[0].args[0])
        self.assertIn("execution_history.trigger_source = 'quick drawer'", union_sql)
        self.assertIn("run_history.trigger_source = 'quick drawer'", union_sql)
        self.assertIn("ilike", union_sql)

    async def test_all_history_workflow_id_filter_applied_to_exec_query(self) -> None:
        """workflow_id param narrows execution_history rows to that workflow."""
        target_id = uuid.uuid4()
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(scalar_value=0),  # COUNT
                _ExecuteResult(rows=[]),  # items
            ]
        )

        response = await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            execution_status=None,
            trigger_source=None,
            workflow_id=str(target_id),
        )

        self.assertEqual(response.total, 0)
        # Two calls: COUNT + items (RunHistory is skipped when filtering by workflow_id).
        self.assertEqual(self.db.execute.call_count, 2)

        for call in self.db.execute.call_args_list:
            sql = _compile_sql(call.args[0])
            self.assertIn(str(target_id), sql)
            self.assertNotIn("run_history", sql)

    async def test_all_history_workflow_id_skips_run_history_query(self) -> None:
        """When workflow_id is given the chat/assistant RunHistory table is not queried."""
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(scalar_value=0),
                _ExecuteResult(rows=[]),
            ]
        )

        await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            execution_status=None,
            trigger_source=None,
            workflow_id=str(uuid.uuid4()),
        )

        self.assertEqual(self.db.execute.call_count, 2)
        for call in self.db.execute.call_args_list:
            sql = _compile_sql(call.args[0])
            self.assertNotIn("run_history", sql)

    async def test_all_history_workflow_id_and_status_combined(self) -> None:
        """workflow_id and execution_status filters are both applied to the same query."""
        target_id = uuid.uuid4()
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(scalar_value=0),
                _ExecuteResult(rows=[]),
            ]
        )

        await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            execution_status="error",
            trigger_source=None,
            workflow_id=str(target_id),
        )

        self.assertEqual(self.db.execute.call_count, 2)
        for call in self.db.execute.call_args_list:
            sql = _compile_sql(call.args[0])
            self.assertIn(str(target_id), sql)
            self.assertIn("'error'", sql)

    async def test_all_history_without_workflow_id_queries_both_tables(self) -> None:
        """Without a workflow_id filter the UNION ALL covers both ExecutionHistory and RunHistory."""
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(scalar_value=0),  # COUNT
                _ExecuteResult(rows=[]),  # items
            ]
        )

        await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            execution_status=None,
            trigger_source=None,
            workflow_id=None,
        )

        self.assertEqual(self.db.execute.call_count, 2)
        union_sql = _compile_sql(self.db.execute.call_args_list[0].args[0])
        self.assertIn("run_history", union_sql)

    async def test_all_history_workflow_id_without_status_no_status_clause(self) -> None:
        """When only workflow_id is given, the query must not contain a status filter."""
        target_id = uuid.uuid4()
        self.db.execute = AsyncMock(
            side_effect=[
                _ExecuteResult(scalar_value=0),
                _ExecuteResult(rows=[]),
            ]
        )

        await list_all_execution_history(
            current_user=self.user,
            db=self.db,
            execution_status=None,
            trigger_source=None,
            workflow_id=str(target_id),
        )

        for call in self.db.execute.call_args_list:
            sql = _compile_sql(call.args[0])
            self.assertIn(str(target_id), sql)
            self.assertNotIn("'error'", sql)
            self.assertNotIn("'success'", sql)
