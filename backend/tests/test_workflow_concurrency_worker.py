"""The worker finishes concurrency rows completely, since their caller may be gone."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.cluster.dispatch import RunQueueWorker


def _row(*, concurrency_seq: int | None = 7, run_options: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=None,
        execution_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        inputs={},
        trigger_source="API",
        actor_user_id=uuid.uuid4(),
        credentials_owner_id=uuid.uuid4(),
        test_run=False,
        timeout_seconds=None,
        return_on_chart_output=False,
        concurrency_seq=concurrency_seq,
        run_options=run_options,
    )


class ClaimedConcurrencyRowTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, row: SimpleNamespace, status: str = "success") -> dict[str, AsyncMock]:
        workflow = SimpleNamespace(
            id=row.workflow_id, owner_id=uuid.uuid4(), name="wf", nodes=[], edges=[]
        )
        db = MagicMock()
        db.get = AsyncMock(return_value=None)
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow))
        db.commit = AsyncMock()
        session_factory = MagicMock()
        session_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        result = SimpleNamespace(
            status=status,
            outputs={},
            node_results=[],
            execution_time_ms=1.0,
            sub_workflow_executions=[],
            allow_downstream_pending=False,
        )
        mocks = {
            "execute": AsyncMock(return_value=result),
            "release": AsyncMock(),
            "error_workflow": AsyncMock(),
        }
        with (
            patch("app.db.session.async_session_maker", session_factory),
            patch("app.api.workflows.get_credentials_context", new=AsyncMock(return_value={})),
            patch("app.api.workflows.collect_referenced_workflows", new=AsyncMock(return_value={})),
            patch("app.api.workflows._persist_global_variables_from_execution", new=AsyncMock()),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                new=AsyncMock(return_value={}),
            ),
            patch("app.services.cluster.dispatch.register_execution"),
            patch("app.services.cluster.dispatch.asyncio.to_thread", mocks["execute"]),
            patch("app.services.cluster.dispatch.persist_run_history", new=AsyncMock()),
            patch("app.services.cluster.dispatch.run_queue.complete", new=AsyncMock()),
            patch("app.services.cluster.dispatch.run_queue.notify_done", new=AsyncMock()),
            patch("app.services.cluster.dispatch.workflow_concurrency.release", mocks["release"]),
            patch(
                "app.services.cluster.dispatch.run_error_workflow_for_failed_run",
                mocks["error_workflow"],
            ),
        ):
            await RunQueueWorker()._execute_claimed(row)
        return mocks

    async def test_the_slot_is_released_after_the_run(self) -> None:
        row = _row()
        mocks = await self._run(row)
        mocks["release"].assert_awaited_once_with(row.execution_id)

    async def test_a_plain_cluster_row_does_not_touch_slots(self) -> None:
        mocks = await self._run(_row(concurrency_seq=None))
        mocks["release"].assert_not_awaited()

    async def test_an_offloaded_slot_holder_releases(self) -> None:
        row = _row(concurrency_seq=None, run_options={"holds_concurrency_slot": True})
        mocks = await self._run(row)
        mocks["release"].assert_awaited_once_with(row.execution_id)

    async def test_portal_options_reach_the_executor(self) -> None:
        history = [{"role": "user", "content": "hi"}]
        mocks = await self._run(
            _row(run_options={"conversation_history": history, "llm_session_id": "conv-1"})
        )
        kwargs = mocks["execute"].await_args.kwargs
        self.assertEqual(kwargs["conversation_history"], history)
        self.assertEqual(kwargs["llm_session_id"], "conv-1")

    async def test_the_worker_fires_the_error_workflow_for_a_queued_failure(self) -> None:
        mocks = await self._run(_row(), status="error")
        mocks["error_workflow"].assert_awaited_once()

    async def test_the_recursion_guard_is_honoured(self) -> None:
        mocks = await self._run(_row(run_options={"run_error_workflow": False}), status="error")
        mocks["error_workflow"].assert_not_awaited()

    async def test_a_plain_cluster_failure_leaves_the_error_workflow_to_the_dispatcher(
        self,
    ) -> None:
        mocks = await self._run(_row(concurrency_seq=None), status="error")
        mocks["error_workflow"].assert_not_awaited()


class WorkerStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_worker_starts_without_a_cluster(self) -> None:
        bus = MagicMock()
        bus.start = AsyncMock()
        bus.stop = AsyncMock()
        bus.wait_for_work = AsyncMock(side_effect=AssertionError("stop"))
        worker = RunQueueWorker()
        with (
            patch("app.services.cluster.dispatch.settings.cluster_enabled", False),
            patch("app.services.cluster.run_queue_bus.QueueWakeBus", return_value=bus),
        ):
            await worker.start()
            self.assertIsNotNone(worker._task)
            await worker.stop()


class AllowDownstreamFuturesTests(unittest.TestCase):
    def test_futures_are_listed_without_being_consumed(self) -> None:
        from concurrent.futures import Future

        from app.services.workflow_executor import ExecutionResult

        future: Future = Future()
        result = ExecutionResult(
            workflow_id=uuid.uuid4(),
            status="success",
            outputs={},
            node_results=[],
            execution_time_ms=0.0,
        )
        result._allow_downstream_pending.append(future)
        self.assertEqual(result.allow_downstream_futures(), (future,))
        self.assertTrue(result.allow_downstream_pending)
