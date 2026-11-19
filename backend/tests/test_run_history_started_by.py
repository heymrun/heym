"""Who started a run, and deleting one run from History."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, status
from sqlalchemy import delete, select

from app.api.workflows import (
    delete_execution_history_entry,
    delete_workflow_execution_history_entry,
    get_execution_history,
    list_all_execution_history,
    persist_stream_execution_result,
)
from app.db.models import ExecutionHistory, RunHistory, User, Workflow
from app.db.session import async_session_maker
from app.services.cluster.attribution import started_by_user, started_by_user_options
from app.services.cluster.run_history import persist_run_history
from app.services.run_history_meta import workflow_run_meta
from tests.workflow_concurrency_fixtures import ConcurrencyPostgresCase

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)


class _Rows:
    def __init__(self, rows: list[object] | None = None, *, scalar: object | None = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def all(self) -> list[object]:
        return self._rows

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalar(self) -> object | None:
        return self._scalar

    def scalar_one(self) -> object:
        return self._scalar if self._scalar is not None else 0

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def scalars(self) -> "_Rows":
        return self


class _Deleted:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


def _user(user_id: uuid.UUID, name: str = "Ada") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, name=name, email=f"{user_id}@example.com")


def _list_row(entry_id: uuid.UUID, run_type: str = "workflow") -> SimpleNamespace:
    return SimpleNamespace(
        id=entry_id,
        workflow_id=uuid.uuid4(),
        workflow_name="Flow",
        run_type=run_type,
        started_at=NOW,
        status="success",
        execution_time_ms=5.0,
        trigger_source="API",
        recovered=False,
        encrypted=False,
        executed_by_instance_id=None,
        executed_by_instance_name=None,
    )


def _meta_row(
    entry_id: uuid.UUID, starter_id: uuid.UUID | None, name: str | None, owner_id: uuid.UUID
) -> SimpleNamespace:
    return SimpleNamespace(
        id=entry_id, executed_by_user_id=starter_id, name=name, owner_id=owner_id
    )


class RunHistoryListStarterTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_list_names_the_starter_and_marks_owned_runs_deletable(self) -> None:
        viewer = _user(uuid.uuid4(), "Viewer")
        starter_id = uuid.uuid4()
        owned, shared, trigger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _Rows(scalar=3),
                _Rows([_list_row(owned), _list_row(shared), _list_row(trigger)]),
                _Rows(
                    [
                        _meta_row(owned, starter_id, "Grace", viewer.id),
                        _meta_row(shared, starter_id, "Grace", uuid.uuid4()),
                        _meta_row(trigger, None, None, viewer.id),
                    ]
                ),
            ]
        )

        response = await list_all_execution_history(
            current_user=viewer,
            db=db,
            execution_status=None,
            trigger_source=None,
            workflow_id=None,
            instance_id=None,
            search=None,
        )

        by_id = {item.id: item for item in response.items}
        self.assertEqual(by_id[owned].executed_by_user_name, "Grace")
        self.assertEqual(by_id[owned].executed_by_user_id, starter_id)
        self.assertTrue(by_id[owned].can_delete)
        self.assertEqual(by_id[shared].executed_by_user_name, "Grace")
        self.assertFalse(by_id[shared].can_delete)
        self.assertIsNone(by_id[trigger].executed_by_user_id)
        self.assertIsNone(by_id[trigger].executed_by_user_name)

    async def test_all_list_credits_a_chat_run_to_its_user(self) -> None:
        viewer = _user(uuid.uuid4(), "Viewer")
        chat = uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_Rows(scalar=1), _Rows([_list_row(chat, "dashboard_chat")])]
        )

        response = await list_all_execution_history(
            current_user=viewer,
            db=db,
            execution_status=None,
            trigger_source=None,
            workflow_id=None,
            instance_id=None,
            search=None,
        )

        item = response.items[0]
        self.assertEqual(item.executed_by_user_id, viewer.id)
        self.assertEqual(item.executed_by_user_name, "Viewer")
        self.assertTrue(item.can_delete)
        self.assertEqual(db.execute.await_count, 2)

    async def test_per_workflow_list_carries_the_starter(self) -> None:
        owner = _user(uuid.uuid4(), "Owner")
        starter_id = uuid.uuid4()
        entry_id = uuid.uuid4()
        workflow = SimpleNamespace(id=uuid.uuid4(), name="Flow", owner_id=owner.id)
        history = SimpleNamespace(
            id=entry_id,
            workflow_id=workflow.id,
            started_at=NOW,
            status="success",
            execution_time_ms=5.0,
            trigger_source="API",
            recovered=False,
            encrypted=False,
            executed_by_instance_id=None,
            executed_by_instance_name=None,
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _Rows(scalar=1),
                _Rows([history]),
                _Rows([_meta_row(entry_id, starter_id, "Grace", owner.id)]),
            ]
        )

        with patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)):
            response = await get_execution_history(
                workflow_id=workflow.id,
                current_user=owner,
                db=db,
                trigger_source=None,
                instance_id=None,
                execution_status=None,
                search=None,
            )

        item = response.items[0]
        self.assertEqual(item.executed_by_user_name, "Grace")
        self.assertTrue(item.can_delete)


class DeleteRunTests(unittest.IsolatedAsyncioTestCase):
    def _workflow(self, owner_id: uuid.UUID) -> SimpleNamespace:
        return SimpleNamespace(id=uuid.uuid4(), owner_id=owner_id, name="Flow")

    def _history(self, workflow: SimpleNamespace, *, encrypted: bool = False) -> SimpleNamespace:
        return SimpleNamespace(id=uuid.uuid4(), workflow_id=workflow.id, encrypted=encrypted)

    async def test_owner_deletes_one_run_and_it_is_audited(self) -> None:
        owner = _user(uuid.uuid4())
        workflow = self._workflow(owner.id)
        history = self._history(workflow, encrypted=True)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_Rows([(history, workflow)]), _Deleted(1)])

        with self.assertLogs("winston.audit", level="INFO") as captured:
            await delete_execution_history_entry(entry_id=history.id, current_user=owner, db=db)

        expected = ExecutionHistory.__table__.delete().where(ExecutionHistory.id == history.id)
        self.assertTrue(db.execute.call_args_list[1].args[0].compare(expected))
        line = captured.records[0].getMessage()
        self.assertIn("action=workflow.history_delete", line)
        self.assertIn("outcome=success", line)
        self.assertIn(f"execution_id={history.id}", line)
        self.assertIn(f"actor_id={owner.id}", line)

    async def test_collaborator_cannot_delete_a_run_of_a_shared_workflow(self) -> None:
        collaborator = _user(uuid.uuid4())
        workflow = self._workflow(uuid.uuid4())
        history = self._history(workflow)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_Rows([(history, workflow)])])

        with self.assertLogs("winston.audit", level="INFO") as captured:
            with self.assertRaises(HTTPException) as ctx:
                await delete_execution_history_entry(
                    entry_id=history.id, current_user=collaborator, db=db
                )

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(db.execute.await_count, 1)
        line = captured.records[0].getMessage()
        self.assertIn("outcome=denied", line)
        self.assertIn("reason=not_owner", line)

    async def test_user_deletes_their_own_chat_run(self) -> None:
        viewer = _user(uuid.uuid4())
        chat_id = uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_Rows(), _Deleted(1)])

        await delete_execution_history_entry(entry_id=chat_id, current_user=viewer, db=db)

        statement = db.execute.call_args_list[1].args[0]
        expected = RunHistory.__table__.delete().where(
            RunHistory.id == chat_id, RunHistory.user_id == viewer.id
        )
        self.assertTrue(statement.compare(expected))

    async def test_unknown_run_is_a_404(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_Rows(), _Deleted(0)])

        with self.assertRaises(HTTPException) as ctx:
            await delete_execution_history_entry(
                entry_id=uuid.uuid4(), current_user=_user(uuid.uuid4()), db=db
            )

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)

    async def test_per_workflow_delete_is_owner_only(self) -> None:
        collaborator = _user(uuid.uuid4())
        workflow = self._workflow(uuid.uuid4())
        history = self._history(workflow)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_Rows(scalar=history)])

        with patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)):
            with self.assertRaises(HTTPException) as ctx:
                await delete_workflow_execution_history_entry(
                    workflow_id=workflow.id,
                    entry_id=history.id,
                    current_user=collaborator,
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(db.execute.await_count, 1)

    async def test_per_workflow_delete_of_another_workflows_run_is_a_404(self) -> None:
        owner = _user(uuid.uuid4())
        workflow = self._workflow(owner.id)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_Rows(scalar=None)])

        with patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)):
            with self.assertRaises(HTTPException) as ctx:
                await delete_workflow_execution_history_entry(
                    workflow_id=workflow.id,
                    entry_id=uuid.uuid4(),
                    current_user=owner,
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)

    async def test_per_workflow_delete_without_workflow_access_is_a_404(self) -> None:
        db = AsyncMock()

        with patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await delete_workflow_execution_history_entry(
                    workflow_id=uuid.uuid4(),
                    entry_id=uuid.uuid4(),
                    current_user=_user(uuid.uuid4()),
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)
        db.execute.assert_not_called()


class StartedByQueueOptionTests(unittest.TestCase):
    def test_the_starter_survives_the_queue_round_trip(self) -> None:
        user_id = uuid.uuid4()

        self.assertEqual(started_by_user(started_by_user_options(user_id)), user_id)

    def test_a_run_without_a_starter_adds_no_option(self) -> None:
        self.assertEqual(started_by_user_options(None), {})
        self.assertIsNone(started_by_user({}))
        self.assertIsNone(started_by_user(None))

    def test_a_malformed_option_reads_as_no_starter(self) -> None:
        self.assertIsNone(started_by_user({"started_by_user_id": "not-a-uuid"}))


class RunHistoryStartedByPostgresTests(ConcurrencyPostgresCase):
    """Real rows: the column, the join behind the list, and the foreign key."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.starter_id = uuid.uuid4()
        self.addAsyncCleanup(self._remove_starter)
        async with async_session_maker() as db:
            db.add(
                User(
                    id=self.starter_id,
                    email=f"starter-{self.starter_id.hex}@example.com",
                    hashed_password="test-only",
                    name="Grace Hopper",
                )
            )
            await db.commit()

    async def _remove_starter(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                delete(ExecutionHistory).where(ExecutionHistory.workflow_id == self.workflow_id)
            )
            await db.execute(delete(User).where(User.id == self.starter_id))
            await db.commit()

    async def _write_run(self, started_by: uuid.UUID | None) -> uuid.UUID:
        execution_id = uuid.uuid4()
        result = SimpleNamespace(
            outputs={},
            node_results=[],
            status="success",
            execution_time_ms=1.0,
            sub_workflow_executions=[],
        )
        await persist_run_history(
            execution_id=execution_id,
            workflow_id=self.workflow_id,
            owner_id=self.user_id,
            workflow_name="Concurrency fixture",
            inputs={},
            trigger_source="API",
            result=result,
            started_by_user_id=started_by,
        )
        return execution_id

    async def test_a_queued_run_keeps_the_user_who_started_it(self) -> None:
        execution_id = await self._write_run(self.starter_id)

        async with async_session_maker() as db:
            stored = await db.get(ExecutionHistory, execution_id)
            meta = await workflow_run_meta(db, [execution_id], self.user_id)
            as_collaborator = await workflow_run_meta(db, [execution_id], self.starter_id)

        assert stored is not None
        self.assertEqual(stored.executed_by_user_id, self.starter_id)
        self.assertEqual(meta[execution_id].user_name, "Grace Hopper")
        self.assertTrue(meta[execution_id].can_delete)
        self.assertFalse(as_collaborator[execution_id].can_delete)

    async def test_a_trigger_run_has_no_starter(self) -> None:
        execution_id = await self._write_run(None)

        async with async_session_maker() as db:
            meta = await workflow_run_meta(db, [execution_id], self.user_id)

        self.assertIsNone(meta[execution_id].user_id)
        self.assertIsNone(meta[execution_id].user_name)

    async def test_deleting_the_user_keeps_the_run_and_clears_the_starter(self) -> None:
        execution_id = await self._write_run(self.starter_id)

        async with async_session_maker() as db:
            await db.execute(delete(User).where(User.id == self.starter_id))
            await db.commit()

        async with async_session_maker() as db:
            stored = (
                await db.execute(
                    select(ExecutionHistory).where(ExecutionHistory.id == execution_id)
                )
            ).scalar_one()
        self.assertIsNone(stored.executed_by_user_id)

    async def _stream_run(self, final_result: dict, *, was_cancelled: bool) -> uuid.UUID:
        execution_id = uuid.uuid4()
        async with async_session_maker() as db:
            workflow = await db.get(Workflow, self.workflow_id)
            written = await persist_stream_execution_result(
                db,
                workflow=workflow,
                execution_id=execution_id,
                enriched_inputs={},
                trigger_source="API",
                raw_body=None,
                query_params={},
                workflow_cache={},
                credentials_owner_id=self.starter_id,
                final_result=final_result,
                was_cancelled=was_cancelled,
                started_by_user_id=self.starter_id,
            )
            self.assertTrue(written)
            await db.commit()
        return execution_id

    async def test_a_streamed_run_keeps_the_user_who_started_it(self) -> None:
        finished = await self._stream_run(
            {"status": "success", "outputs": {}, "node_results": [], "execution_time_ms": 1},
            was_cancelled=False,
        )
        cancelled = await self._stream_run(
            {"status": "cancelled", "outputs": {}, "node_results": [], "execution_time_ms": 1},
            was_cancelled=True,
        )

        async with async_session_maker() as db:
            rows = (
                await db.execute(
                    select(ExecutionHistory.id, ExecutionHistory.executed_by_user_id).where(
                        ExecutionHistory.id.in_([finished, cancelled])
                    )
                )
            ).all()
        self.assertEqual(
            {row.id: row.executed_by_user_id for row in rows},
            {
                finished: self.starter_id,
                cancelled: self.starter_id,
            },
        )

    async def test_the_owner_can_delete_one_run_and_the_others_stay(self) -> None:
        keep = await self._write_run(self.starter_id)
        drop = await self._write_run(self.starter_id)
        owner = MagicMock()
        owner.id = self.user_id
        owner.email = "owner@example.com"

        async with async_session_maker() as db:
            await delete_execution_history_entry(entry_id=drop, current_user=owner, db=db)
            await db.commit()

        async with async_session_maker() as db:
            remaining = (
                (
                    await db.execute(
                        select(ExecutionHistory.id).where(
                            ExecutionHistory.workflow_id == self.workflow_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        self.assertEqual(remaining, [keep])


if __name__ == "__main__":
    unittest.main()
