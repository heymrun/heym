import asyncio
import threading
import uuid
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.node_execution import registry as node_registry
from app.services.workflow_executor import WorkflowCancelledError, execute_workflow


def _allow_downstream_workflow() -> tuple[list[dict], list[dict]]:
    nodes = [
        {
            "id": "input",
            "type": "textInput",
            "data": {"label": "input", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "before_output",
            "type": "variable",
            "data": {
                "label": "beforeOutput",
                "variableName": "before_output",
                "variableValue": "$input.text",
                "variableType": "string",
                "isGlobal": True,
            },
        },
        {
            "id": "output",
            "type": "output",
            "data": {
                "label": "output",
                "message": "$input.text",
                "allowDownstream": True,
            },
        },
        {"id": "downstream", "type": "wait", "data": {"label": "downstream", "duration": 1}},
    ]
    edges = [
        {"id": "e1", "source": "input", "target": "before_output"},
        {"id": "e2", "source": "before_output", "target": "output"},
        {"id": "e3", "source": "output", "target": "downstream"},
    ]
    return nodes, edges


def _row(workflow_id: uuid.UUID, execution_id: uuid.UUID, credentials_owner_id: uuid.UUID | None):
    return SimpleNamespace(
        id=None,
        execution_id=execution_id,
        workflow_id=workflow_id,
        inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
        trigger_source="api",
        actor_user_id=None,
        credentials_owner_id=credentials_owner_id,
        test_run=False,
        timeout_seconds=None,
        return_on_chart_output=False,
    )


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
        for _ in range(100):
            if event.is_set():
                return
            await asyncio.sleep(0.01)
        self.fail("expected background downstream work to start")

    async def _wait_for_completion(self, worker, persist_history) -> None:
        for _ in range(100):
            if persist_history.await_count and not worker._active_finalizers:
                return
            await asyncio.sleep(0.01)
        self.fail("expected allow-downstream finalizer to finish")

    def _patch_worker_dependencies(
        self,
        context: MagicMock,
        persist_history,
        persist_globals,
        **extra_patches,
    ):
        patches = [
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
            patch("app.services.cluster.dispatch.run_queue.complete", new=AsyncMock()),
            patch("app.services.cluster.dispatch.run_queue.notify_done", new=AsyncMock()),
            patch("app.services.cluster.dispatch.persist_run_history", new=persist_history),
            patch(
                "app.api.workflows._persist_global_variables_from_execution",
                new=persist_globals,
            ),
        ]
        patches.extend(extra_patches.values())
        return patches

    async def test_real_executor_publishes_early_and_persists_after_join(self) -> None:
        from app.services.cluster.dispatch import RunQueueWorker
        from app.services.execution_cancellation import get_active_execution_handle

        release = threading.Event()
        started = threading.Event()

        def downstream_handler(_ctx):
            started.set()
            if not release.wait(timeout=5):
                raise AssertionError("timed out waiting for downstream release")
            return {"value": "done"}

        nodes, edges = _allow_downstream_workflow()
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        credentials_owner_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=uuid.uuid4(),
            name="allow-downstream-real-executor",
            nodes=nodes,
            edges=edges,
        )
        active_row = SimpleNamespace(cancel_requested_at=None)
        row = _row(workflow_id, execution_id, credentials_owner_id)
        session, context = self._session_context(workflow, active_row)
        worker = RunQueueWorker()
        persist_history = AsyncMock()
        persist_globals = AsyncMock()

        patches = self._patch_worker_dependencies(context, persist_history, persist_globals)
        with (
            *patches,
            patch.dict(node_registry._HANDLER_CACHE, {"wait": downstream_handler}),
        ):
            await worker._execute_claimed(row)
            await self._wait_for(started)

            complete = patches[5].new
            notify_done = patches[6].new
            self.assertEqual(complete.await_count, 1)
            self.assertEqual(notify_done.await_count, 1)
            early_summary = complete.await_args.kwargs["result"]
            self.assertEqual(early_summary["outputs"], {"output": {"result": "hello"}})
            self.assertEqual(persist_history.await_count, 0)
            self.assertEqual(persist_globals.await_count, 0)
            self.assertIsNotNone(get_active_execution_handle(execution_id))

            release.set()
            await self._wait_for_completion(worker, persist_history)

            self.assertEqual(persist_history.await_count, 1)
            final_result = persist_history.await_args.kwargs["result"]
            self.assertEqual(final_result.status, "success")
            self.assertIn(
                {"node_id": "downstream", "node_label": "downstream", "status": "success"},
                final_result.node_results,
            )
            self.assertEqual(persist_globals.await_count, 1)
            self.assertEqual(complete.await_count, 2)
            self.assertEqual(notify_done.await_count, 2)
            self.assertIsNone(get_active_execution_handle(execution_id))

    async def test_successful_retry_does_not_mark_deferred_run_failed(self) -> None:
        from app.services.cluster.dispatch import RunQueueWorker

        release = threading.Event()
        started = threading.Event()
        attempts = 0

        def retrying_handler(_ctx):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient downstream failure")
            started.set()
            if not release.wait(timeout=5):
                raise AssertionError("timed out waiting for retry release")
            return {"value": "done"}

        nodes, edges = _allow_downstream_workflow()
        nodes[-1]["data"].update(
            {"retryEnabled": True, "retryMaxAttempts": 2, "retryWaitSeconds": 0}
        )
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=uuid.uuid4(),
            name="allow-downstream-retry",
            nodes=nodes,
            edges=edges,
        )
        active_row = SimpleNamespace(cancel_requested_at=None)
        row = _row(workflow_id, execution_id, None)
        _session, context = self._session_context(workflow, active_row)
        worker = RunQueueWorker()
        persist_history = AsyncMock()
        persist_globals = AsyncMock()

        patches = self._patch_worker_dependencies(context, persist_history, persist_globals)
        with (
            *patches,
            patch.dict(node_registry._HANDLER_CACHE, {"wait": retrying_handler}),
        ):
            await worker._execute_claimed(row)
            await self._wait_for(started)
            self.assertEqual(attempts, 2)
            complete = patches[5].new
            self.assertEqual(complete.await_count, 1)

            release.set()
            await self._wait_for_finalizer(worker)

            final_result = persist_history.await_args.kwargs["result"]
            self.assertEqual(final_result.status, "success")
            self.assertTrue(
                any(
                    node_result.get("status") == "error"
                    and node_result.get("error") == "transient downstream failure"
                    for node_result in final_result.node_results
                )
            )
            self.assertEqual(complete.await_count, 2)

    async def test_downstream_failure_keeps_earlier_global_updates(self) -> None:
        from app.services.cluster.dispatch import RunQueueWorker

        started = threading.Event()

        def failing_handler(_ctx):
            started.set()
            raise RuntimeError("downstream failed")

        nodes, edges = _allow_downstream_workflow()
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        credentials_owner_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=uuid.uuid4(),
            name="allow-downstream-failure",
            nodes=nodes,
            edges=edges,
        )
        active_row = SimpleNamespace(cancel_requested_at=None)
        row = _row(workflow_id, execution_id, credentials_owner_id)
        _session, context = self._session_context(workflow, active_row)
        worker = RunQueueWorker()
        persist_history = AsyncMock()
        persist_globals = AsyncMock()

        patches = self._patch_worker_dependencies(context, persist_history, persist_globals)
        with (
            *patches,
            patch.dict(node_registry._HANDLER_CACHE, {"wait": failing_handler}),
        ):
            await worker._execute_claimed(row)
            await self._wait_for(started)
            await self._wait_for_finalizer(worker)

            final_result = persist_history.await_args.kwargs["result"]
            self.assertEqual(final_result.status, "error")
            self.assertEqual(final_result.outputs, {"output": {"result": "hello"}})
            self.assertEqual(persist_globals.await_count, 1)
            global_results = persist_globals.await_args.kwargs["node_results"]
            self.assertTrue(
                any(
                    node_result.get("node_id") == "before_output"
                    and node_result.get("status") == "success"
                    for node_result in global_results
                )
            )

    async def test_cancellation_after_early_response_reaches_real_finalizer(self) -> None:
        from app.services.cluster.dispatch import RunQueueWorker
        from app.services.execution_cancellation import (
            cancel_execution,
            get_active_execution_handle,
        )

        started = threading.Event()

        def cancellable_handler(_ctx):
            started.set()
            while True:
                handle = get_active_execution_handle(execution_id)
                if handle is not None and handle.event.wait(0.01):
                    raise WorkflowCancelledError("Workflow execution cancelled")

        nodes, edges = _allow_downstream_workflow()
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=uuid.uuid4(),
            name="allow-downstream-cancel",
            nodes=nodes,
            edges=edges,
        )
        active_row = SimpleNamespace(cancel_requested_at=None)
        row = _row(workflow_id, execution_id, None)
        _session, context = self._session_context(workflow, active_row)
        worker = RunQueueWorker()
        persist_history = AsyncMock()
        persist_globals = AsyncMock()

        patches = self._patch_worker_dependencies(context, persist_history, persist_globals)
        with (
            *patches,
            patch.dict(node_registry._HANDLER_CACHE, {"wait": cancellable_handler}),
        ):
            await worker._execute_claimed(row)
            await self._wait_for(started)

            self.assertTrue(cancel_execution(workflow_id=workflow_id, execution_id=execution_id))
            await self._wait_for_finalizer(worker)

            final_result = persist_history.await_args.kwargs["result"]
            self.assertEqual(final_result.status, "cancelled")
            self.assertEqual(final_result.outputs, {"output": {"result": "hello"}})
            self.assertEqual(persist_globals.await_count, 0)
            self.assertIsNone(get_active_execution_handle(execution_id))

            complete = patches[5].new
            notify_done = patches[6].new
            self.assertEqual(complete.await_count, 2)
            self.assertEqual(complete.await_args_list[-1].kwargs["result"]["status"], "cancelled")
            self.assertEqual(notify_done.await_count, 2)

    async def test_persistence_failure_is_reported_in_final_queue_result(self) -> None:
        from app.services.cluster.dispatch import RunQueueWorker

        def fast_handler(_ctx):
            return {"value": "done"}

        nodes, edges = _allow_downstream_workflow()
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=uuid.uuid4(),
            name="allow-downstream-persist-failure",
            nodes=nodes,
            edges=edges,
        )
        active_row = SimpleNamespace(cancel_requested_at=None)
        row = _row(workflow_id, execution_id, None)
        _session, context = self._session_context(workflow, active_row)
        worker = RunQueueWorker()
        persist_history = AsyncMock(side_effect=RuntimeError("history database unavailable"))
        persist_globals = AsyncMock()

        patches = self._patch_worker_dependencies(context, persist_history, persist_globals)
        with (
            *patches,
            patch.dict(node_registry._HANDLER_CACHE, {"wait": fast_handler}),
        ):
            await worker._execute_claimed(row)
            await self._wait_for_finalizer(worker)

            complete = patches[5].new
            final_summary = complete.await_args_list[-1].kwargs["result"]
            self.assertEqual(final_summary["status"], "error")
            self.assertFalse(final_summary["history_written"])
            self.assertEqual(final_summary["error"], "history database unavailable")

    async def test_shutdown_cancels_real_finalizer_without_leaking_execution(self) -> None:
        from app.services.cluster.dispatch import RunQueueWorker
        from app.services.execution_cancellation import get_active_execution_handle

        started = threading.Event()
        release = threading.Event()

        def blocking_handler(_ctx):
            started.set()
            if not release.wait(timeout=10):
                raise AssertionError("timed out waiting for shutdown test")
            return {"value": "done"}

        nodes, edges = _allow_downstream_workflow()
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=uuid.uuid4(),
            name="allow-downstream-shutdown",
            nodes=nodes,
            edges=edges,
        )
        row = _row(workflow_id, execution_id, None)
        worker = RunQueueWorker()
        persist_history = AsyncMock()
        persist_globals = AsyncMock()
        complete = AsyncMock()
        notify_done = AsyncMock()

        with patch.dict(
            node_registry._HANDLER_CACHE,
            {"wait": blocking_handler},
        ):
            active_row = SimpleNamespace(cancel_requested_at=None)
            _session, context = self._session_context(workflow, active_row)
            with (
                patch("app.db.session.async_session_maker", return_value=context),
                patch(
                    "app.api.workflows.get_credentials_context",
                    new=AsyncMock(return_value={}),
                ),
                patch(
                    "app.services.global_variables_service.get_global_variables_context",
                    new=AsyncMock(return_value={}),
                ),
                patch(
                    "app.api.workflows.collect_referenced_workflows",
                    new=AsyncMock(return_value={}),
                ),
                patch(
                    "app.services.hitl_service.build_default_public_base_url",
                    return_value="http://test",
                ),
                patch("app.services.cluster.dispatch.run_queue.complete", new=complete),
                patch("app.services.cluster.dispatch.run_queue.notify_done", new=notify_done),
                patch("app.services.cluster.dispatch.persist_run_history", new=persist_history),
                patch(
                    "app.api.workflows._persist_global_variables_from_execution",
                    new=persist_globals,
                ),
            ):
                await worker._execute_claimed(row)
                await self._wait_for(started)
                for _ in range(100):
                    if worker._active_finalizers:
                        break
                    await asyncio.sleep(0.01)
                else:
                    self.fail("expected an active allow-downstream finalizer")

                async def fake_wait(tasks, timeout):
                    self.assertEqual(timeout, 10.0)
                    return set(), set(tasks)

                with patch("app.services.cluster.dispatch.asyncio.wait", new=fake_wait):
                    await worker.stop()

                self.assertEqual(persist_history.await_count, 1)
                final_result = persist_history.await_args.kwargs["result"]
                self.assertEqual(final_result.status, "error")
                self.assertFalse(worker._active_finalizers)
                self.assertGreaterEqual(complete.await_count, 2)
                self.assertGreaterEqual(notify_done.await_count, 1)
                self.assertIsNone(get_active_execution_handle(execution_id))

        release.set()
        await asyncio.sleep(0.05)


if __name__ == "__main__":
    import unittest

    unittest.main()
