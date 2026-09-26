import asyncio
import threading
import uuid
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.workflow_executor import WorkflowCancelledError


class _DeferredResult:
    def __init__(self) -> None:
        self.status = "success"
        self.outputs = {"output": {"result": "early"}}
        self.workflow_id = uuid.uuid4()
        self.execution_time_ms = 1.0
        self.node_results = [
            {"node_id": "input", "node_label": "input", "status": "success"},
            {"node_id": "output", "node_label": "output", "status": "success"},
        ]
        self.sub_workflow_executions = []
        self.started = threading.Event()
        self.release = threading.Event()
        self._pending = True

    @property
    def allow_downstream_pending(self) -> bool:
        return self._pending

    def join_allow_downstream(self) -> None:
        self.started.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("timed out waiting for downstream release")
        self.node_results.append(
            {"node_id": "downstream", "node_label": "downstream", "status": "success"}
        )
        self.execution_time_ms = 250.0
        self._pending = False


class _CancellableDeferredResult(_DeferredResult):
    def __init__(self, cancel_event: threading.Event) -> None:
        super().__init__()
        self.cancel_event = cancel_event

    def join_allow_downstream(self) -> None:
        self.started.set()
        if not self.cancel_event.wait(timeout=5):
            raise AssertionError("timed out waiting for cancellation")
        raise WorkflowCancelledError("Workflow execution cancelled")


class ClusterAllowDownstreamFinalizationTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from app.services.execution_cancellation import _ACTIVE_EXECUTIONS

        _ACTIVE_EXECUTIONS.clear()

    def tearDown(self) -> None:
        from app.services.execution_cancellation import _ACTIVE_EXECUTIONS

        _ACTIVE_EXECUTIONS.clear()

    def _session_context(
        self, workflow: SimpleNamespace, active_row: SimpleNamespace
    ) -> tuple[MagicMock, MagicMock]:
        session = MagicMock()
        session.get = AsyncMock(side_effect=[active_row])
        workflow_result = MagicMock()
        workflow_result.scalar_one_or_none.return_value = workflow
        session.execute = AsyncMock(return_value=workflow_result)
        session.commit = AsyncMock()

        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=False)
        return session, context

    async def _wait_for(self, event: threading.Event) -> None:
        for _ in range(50):
            if event.is_set():
                return
            await asyncio.sleep(0.01)
        self.fail("background finalizer did not start")

    async def test_early_result_is_published_before_final_persistence(self) -> None:
        from app.services.cluster.dispatch import RunQueueWorker
        from app.services.execution_cancellation import (
            complete_execution,
            get_active_execution_handle,
            register_execution,
        )

        run_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        credentials_owner_id = uuid.uuid4()
        active_row = SimpleNamespace(cancel_requested_at=None)
        workflow = SimpleNamespace(
            nodes=[
                {"id": "input", "type": "textInput", "data": {"label": "input"}},
                {"id": "output", "type": "output", "data": {"label": "output"}},
                {"id": "downstream", "type": "setGlobalVariable", "data": {"label": "downstream"}},
            ],
            edges=[],
            owner_id=uuid.uuid4(),
            name="allow-downstream",
        )
        row = SimpleNamespace(
            id=None,
            execution_id=run_id,
            workflow_id=workflow_id,
            inputs={"value": 1},
            trigger_source="api",
            actor_user_id=None,
            credentials_owner_id=credentials_owner_id,
            test_run=False,
            timeout_seconds=None,
            return_on_chart_output=False,
        )
        result = _DeferredResult()
        registered_event = None

        def spy_register(*args, **kwargs):
            nonlocal registered_event
            registered_event = register_execution(*args, **kwargs)
            return registered_event

        session, context = self._session_context(workflow, active_row)
        worker = RunQueueWorker()

        with (
            patch("app.db.session.async_session_maker", return_value=context),
            patch("app.api.workflows.get_credentials_context", new=AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                new=AsyncMock(return_value={}),
            ),
            patch("app.api.workflows.collect_referenced_workflows", new=AsyncMock(return_value={})),
            patch(
                "app.services.hitl_service.build_default_public_base_url",
                return_value="http://test",
            ),
            patch("app.services.cluster.dispatch.execute_workflow", return_value=result),
            patch(
                "app.services.cluster.dispatch.run_queue.complete", new=AsyncMock()
            ) as complete,
            patch(
                "app.services.cluster.dispatch.run_queue.notify_done", new=AsyncMock()
            ) as notify_done,
            patch(
                "app.services.cluster.dispatch.persist_run_history", new=AsyncMock()
            ) as persist_history,
            patch(
                "app.api.workflows._persist_global_variables_from_execution",
                new=AsyncMock(),
            ) as persist_globals,
            patch("app.services.cluster.dispatch.register_execution", side_effect=spy_register),
            patch(
                "app.services.cluster.dispatch.complete_execution",
                wraps=complete_execution,
            ) as complete_execution_spy,
        ):
            await worker._execute_claimed(row)
            await self._wait_for(result.started)

            self.assertEqual(complete.await_count, 1)
            early_summary = complete.await_args_list[0].kwargs["result"]
            self.assertEqual(early_summary["outputs"], {"output": {"result": "early"}})
            self.assertEqual(early_summary["execution_time_ms"], 1.0)
            self.assertEqual(notify_done.await_count, 1)

            self.assertIsNotNone(registered_event)
            self.assertIsNotNone(get_active_execution_handle(run_id))
            self.assertEqual(persist_history.await_count, 0)
            self.assertEqual(persist_globals.await_count, 0)
            self.assertEqual(complete_execution_spy.call_count, 0)

            result.release.set()
            for _ in range(100):
                await asyncio.sleep(0.01)
                if persist_history.await_count == 1:
                    break

            for _ in range(50):
                await asyncio.sleep(0.01)
                if not worker._active_finalizers:
                    break

            self.assertEqual(persist_history.await_count, 1)
            self.assertEqual(persist_globals.await_count, 1)
            self.assertEqual(complete.await_count, 2)
            self.assertEqual(notify_done.await_count, 2)
            self.assertEqual(complete_execution_spy.call_count, 1)
            self.assertIsNone(get_active_execution_handle(run_id))
            self.assertIn(
                {"node_id": "downstream", "node_label": "downstream", "status": "success"},
                persist_history.await_args.kwargs["result"].node_results,
            )
            self.assertEqual(session.commit.await_count, 1)
            self.assertEqual(len(worker._active_finalizers), 0)

    async def test_cancellation_after_early_response_reaches_downstream_finalizer(self) -> None:
        from app.services.cluster.dispatch import RunQueueWorker
        from app.services.execution_cancellation import (
            _ACTIVE_EXECUTIONS,
            cancel_execution,
            complete_execution,
            get_active_execution_handle,
            register_execution,
        )

        run_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        active_row = SimpleNamespace(cancel_requested_at=None)
        workflow = SimpleNamespace(
            nodes=[
                {"id": "output", "type": "output", "data": {"label": "output"}},
            ],
            edges=[],
            owner_id=uuid.uuid4(),
            name="allow-downstream-cancel",
        )
        row = SimpleNamespace(
            id=None,
            execution_id=run_id,
            workflow_id=workflow_id,
            inputs={},
            trigger_source="api",
            actor_user_id=None,
            credentials_owner_id=None,
            test_run=False,
            timeout_seconds=None,
            return_on_chart_output=False,
        )
        registered_event = None
        result_holder = {}

        def execute_stub() -> _CancellableDeferredResult:
            event = registered_event
            assert event is not None
            result = _CancellableDeferredResult(event)
            result_holder["result"] = result
            return result

        def spy_register(*args, **kwargs):
            nonlocal registered_event
            registered_event = register_execution(*args, **kwargs)
            return registered_event

        _session, context = self._session_context(workflow, active_row)
        worker = RunQueueWorker()

        with (
            patch("app.db.session.async_session_maker", return_value=context),
            patch("app.api.workflows.get_credentials_context", new=AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                new=AsyncMock(return_value={}),
            ),
            patch("app.api.workflows.collect_referenced_workflows", new=AsyncMock(return_value={})),
            patch(
                "app.services.hitl_service.build_default_public_base_url",
                return_value="http://test",
            ),
            patch("app.services.cluster.dispatch.execute_workflow", side_effect=execute_stub),
            patch(
                "app.services.cluster.dispatch.run_queue.complete", new=AsyncMock()
            ) as complete,
            patch(
                "app.services.cluster.dispatch.run_queue.notify_done", new=AsyncMock()
            ) as notify_done,
            patch(
                "app.services.cluster.dispatch.persist_run_history", new=AsyncMock()
            ) as persist_history,
            patch("app.services.cluster.dispatch.register_execution", side_effect=spy_register),
            patch(
                "app.services.cluster.dispatch.complete_execution",
                wraps=complete_execution,
            ) as complete_execution_spy,
        ):
            await worker._execute_claimed(row)
            result = result_holder["result"]
            await self._wait_for(result.started)

            self.assertTrue(cancel_execution(workflow_id=workflow_id, execution_id=run_id))
            self.assertTrue(registered_event.is_set())

            for _ in range(100):
                await asyncio.sleep(0.01)
                if persist_history.await_count == 1:
                    break

            for _ in range(50):
                await asyncio.sleep(0.01)
                if not worker._active_finalizers:
                    break

            self.assertEqual(persist_history.await_count, 1)
            self.assertEqual(
                persist_history.await_args.kwargs["result"].status,
                "cancelled",
            )
            self.assertEqual(complete.await_count, 2)
            final_summary = complete.await_args_list[-1].kwargs["result"]
            self.assertEqual(final_summary["status"], "cancelled")
            self.assertEqual(complete_execution_spy.call_count, 1)
            self.assertIsNone(get_active_execution_handle(run_id))
            self.assertEqual(notify_done.await_count, 2)
            self.assertIn(
                {"output": {"result": "early"}},
                [persist_history.await_args.kwargs["result"].outputs],
            )
