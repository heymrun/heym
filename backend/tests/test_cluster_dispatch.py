"""When a run is kept in-process, and how an offloaded result comes back."""

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.cluster import run_result_bus as bus_module
from app.services.cluster.dispatch import (
    resolve_placement,
    should_run_in_process,
    wait_for_result,
)
from app.services.cluster.run_result_bus import RunResultBus


class InProcessDecisionTests(unittest.TestCase):
    def test_a_single_instance_install_never_enqueues(self) -> None:
        self.assertTrue(
            should_run_in_process(cluster_enabled=False, placement="anywhere", is_main=True)
        )

    def test_a_main_only_run_on_main_stays_in_process(self) -> None:
        self.assertTrue(
            should_run_in_process(cluster_enabled=True, placement="main_only", is_main=True)
        )

    def test_a_main_only_run_on_a_worker_is_enqueued(self) -> None:
        self.assertFalse(
            should_run_in_process(cluster_enabled=True, placement="main_only", is_main=False)
        )

    def test_an_anywhere_run_on_main_is_enqueued(self) -> None:
        """Main must go through the queue or it would never share the load."""
        self.assertFalse(
            should_run_in_process(cluster_enabled=True, placement="anywhere", is_main=True)
        )

    def test_an_anywhere_run_on_a_worker_is_enqueued(self) -> None:
        self.assertFalse(
            should_run_in_process(cluster_enabled=True, placement="anywhere", is_main=False)
        )

    def test_a_disabled_cluster_keeps_main_only_work_in_process(self) -> None:
        self.assertTrue(
            should_run_in_process(cluster_enabled=False, placement="main_only", is_main=True)
        )


class PlacementResolutionTests(unittest.TestCase):
    def test_a_plain_graph_resolves_to_anywhere(self) -> None:
        nodes = [{"type": "http", "data": {}}]
        self.assertEqual(resolve_placement(nodes, None), "anywhere")

    def test_a_file_touching_graph_resolves_to_main_only(self) -> None:
        nodes = [{"type": "drive", "data": {}}]
        self.assertEqual(resolve_placement(nodes, None), "main_only")

    def test_sub_workflows_are_resolved_from_the_executor_cache(self) -> None:
        nodes = [{"type": "execute", "data": {"executeWorkflowId": "wf-2"}}]
        cache = {"wf-2": {"nodes": [{"type": "codex", "data": {}}]}}
        self.assertEqual(resolve_placement(nodes, cache), "main_only")


class ResultBusTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_notification_wakes_the_registered_waiter(self) -> None:
        bus = RunResultBus()
        execution_id = uuid.uuid4()
        event = bus.register(execution_id)
        self.assertTrue(bus.handle_payload(str(execution_id)))
        self.assertTrue(event.is_set())

    async def test_a_notification_for_another_execution_is_ignored(self) -> None:
        bus = RunResultBus()
        bus.register(uuid.uuid4())
        self.assertFalse(bus.handle_payload(str(uuid.uuid4())))

    async def test_registering_before_enqueue_makes_the_race_safe(self) -> None:
        """A run that finishes before the caller waits must still wake it."""
        bus = RunResultBus()
        execution_id = uuid.uuid4()
        event = bus.register(execution_id)
        bus.handle_payload(str(execution_id))
        await asyncio.wait_for(event.wait(), timeout=0.1)

    async def test_release_removes_the_waiter(self) -> None:
        bus = RunResultBus()
        execution_id = uuid.uuid4()
        bus.register(execution_id)
        bus.release(execution_id)
        self.assertFalse(bus.handle_payload(str(execution_id)))


class WaitForResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_finished_run_returns_its_result(self) -> None:
        execution_id = uuid.uuid4()
        event = bus_module.run_result_bus.register(execution_id)
        event.set()
        with patch(
            "app.services.cluster.dispatch.run_queue.read_terminal_result",
            new=AsyncMock(
                return_value=("done", {"status": "success", "outputs": {"text": "hi"}}, None)
            ),
        ):
            result = await wait_for_result(execution_id, timeout_seconds=1.0)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.outputs, {"text": "hi"})
        self.assertTrue(result.history_written)

    async def test_a_failed_run_reports_the_error(self) -> None:
        execution_id = uuid.uuid4()
        event = bus_module.run_result_bus.register(execution_id)
        event.set()
        with patch(
            "app.services.cluster.dispatch.run_queue.read_terminal_result",
            new=AsyncMock(return_value=("failed", None, "boom")),
        ):
            result = await wait_for_result(execution_id, timeout_seconds=1.0)
        self.assertEqual(result.status, "error")
        self.assertIn("boom", result.error)

    async def test_a_run_skipped_as_late_says_so(self) -> None:
        execution_id = uuid.uuid4()
        event = bus_module.run_result_bus.register(execution_id)
        event.set()
        with patch(
            "app.services.cluster.dispatch.run_queue.read_terminal_result",
            new=AsyncMock(return_value=("skipped_late", None, "too late")),
        ):
            result = await wait_for_result(execution_id, timeout_seconds=1.0)
        self.assertEqual(result.status, "error")

    async def test_waiting_gives_up_rather_than_hanging_forever(self) -> None:
        """A worker that dies mid-run must not strand the request."""
        execution_id = uuid.uuid4()
        with patch(
            "app.services.cluster.dispatch.run_queue.read_terminal_result",
            new=AsyncMock(return_value=("claimed", None, None)),
        ):
            result = await wait_for_result(execution_id, timeout_seconds=0.05)
        self.assertEqual(result.status, "error")
        self.assertIn("still", result.error.lower())

    async def test_the_waiter_is_released_after_a_result(self) -> None:
        execution_id = uuid.uuid4()
        event = bus_module.run_result_bus.register(execution_id)
        event.set()
        with patch(
            "app.services.cluster.dispatch.run_queue.read_terminal_result",
            new=AsyncMock(return_value=("done", {"status": "success", "outputs": {}}, None)),
        ):
            await wait_for_result(execution_id, timeout_seconds=1.0)
        self.assertFalse(bus_module.run_result_bus.handle_payload(str(execution_id)))


class TestRunTests(unittest.TestCase):
    def test_a_test_run_never_leaves_this_instance(self) -> None:
        """An interactive editor run's latency is being watched; queueing buys nothing."""
        self.assertTrue(
            should_run_in_process(
                cluster_enabled=True, placement="anywhere", is_main=False, test_run=True
            )
        )


class ClaimedRunAlwaysCompletesTests(unittest.IsolatedAsyncioTestCase):
    """A claimed row must always reach a terminal state and notify its waiter.

    A failure that escapes _execute_claimed leaves the row 'claimed' forever and
    the waiting request blocks for its whole timeout. That is exactly what a
    mistyped import did: it raised before the try block, so neither complete()
    nor notify_done() ran.
    """

    async def _run_with_failure(self, exc: Exception) -> tuple[AsyncMock, AsyncMock]:
        from app.services.cluster.dispatch import RunQueueWorker

        row = SimpleNamespace(
            execution_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            inputs={},
            trigger_source="API",
            actor_user_id=None,
            credentials_owner_id=None,
            test_run=False,
            timeout_seconds=None,
        )
        complete = AsyncMock()
        notify_done = AsyncMock()
        with (
            patch("app.db.session.async_session_maker", side_effect=exc),
            patch("app.services.cluster.dispatch.run_queue.complete", complete),
            patch("app.services.cluster.dispatch.run_queue.notify_done", notify_done),
        ):
            await RunQueueWorker()._execute_claimed(row)  # type: ignore[arg-type]
        return complete, notify_done

    async def test_a_failure_still_completes_the_row(self) -> None:
        complete, _notify = await self._run_with_failure(RuntimeError("boom"))
        complete.assert_awaited_once()
        self.assertIn("boom", str(complete.await_args.kwargs["error"]))

    async def test_a_failure_still_wakes_the_waiter(self) -> None:
        _complete, notify = await self._run_with_failure(RuntimeError("boom"))
        notify.assert_awaited_once()

    async def test_an_import_error_is_handled_like_any_other(self) -> None:
        """The original bug: an ImportError raised outside the try block."""
        complete, notify = await self._run_with_failure(ImportError("cannot import name"))
        complete.assert_awaited_once()
        notify.assert_awaited_once()


class ClaimedRunExecutionOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_chart_early_return_reaches_the_executing_instance(self) -> None:
        """Dashboard charts return on their output even when a worker claims the run."""
        from app.services.cluster.dispatch import RunQueueWorker

        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Dashboard chart",
            nodes=[{"id": "chart", "type": "chartOutput", "data": {}}],
            edges=[],
        )
        row = SimpleNamespace(
            execution_id=uuid.uuid4(),
            workflow_id=workflow.id,
            inputs={},
            trigger_source="dashboard",
            actor_user_id=workflow.owner_id,
            credentials_owner_id=workflow.owner_id,
            test_run=False,
            timeout_seconds=None,
            return_on_chart_output=True,
        )
        db = MagicMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow))
        db.commit = AsyncMock()
        session_factory = MagicMock()
        session_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        result = SimpleNamespace(
            status="success",
            outputs={"type": "bar"},
            node_results=[],
            execution_time_ms=1.0,
            sub_workflow_executions=[],
        )
        execute = AsyncMock(return_value=result)

        with (
            patch("app.db.session.async_session_maker", session_factory),
            patch(
                "app.api.workflows.get_credentials_context",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.api.workflows.collect_referenced_workflows",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                new=AsyncMock(return_value={}),
            ),
            patch("app.services.cluster.dispatch.register_execution"),
            patch("app.services.cluster.dispatch.asyncio.to_thread", execute),
            patch(
                "app.services.cluster.dispatch.persist_run_history",
                new=AsyncMock(),
            ),
            patch("app.services.cluster.dispatch.run_queue.complete", new=AsyncMock()),
            patch("app.services.cluster.dispatch.run_queue.notify_done", new=AsyncMock()),
        ):
            await RunQueueWorker()._execute_claimed(row)

        self.assertTrue(execute.await_args.kwargs["return_on_chart_output"])


class ClaimedRunContextTests(unittest.IsolatedAsyncioTestCase):
    """A claimed run sees the context its trigger call site would have built."""

    async def _claim(
        self,
        *,
        nodes: list[dict] | None = None,
        node_results: list[dict] | None = None,
        credentials_owner_id: uuid.UUID | None = ...,  # type: ignore[assignment]
    ) -> dict[str, object]:
        from app.services.cluster.dispatch import RunQueueWorker

        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Cron run",
            nodes=nodes if nodes is not None else [{"id": "n1", "type": "set", "data": {}}],
            edges=[],
        )
        row = SimpleNamespace(
            execution_id=uuid.uuid4(),
            workflow_id=workflow.id,
            inputs={},
            trigger_source="schedule",
            actor_user_id=workflow.owner_id,
            credentials_owner_id=(
                workflow.owner_id if credentials_owner_id is ... else credentials_owner_id
            ),
            test_run=False,
            timeout_seconds=None,
            return_on_chart_output=False,
        )
        db = MagicMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow))
        db.commit = AsyncMock()
        session_factory = MagicMock()
        session_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        result = SimpleNamespace(
            status="success",
            outputs={},
            node_results=node_results or [],
            execution_time_ms=1.0,
            sub_workflow_executions=[],
        )
        execute = AsyncMock(return_value=result)
        credentials_loader = AsyncMock(return_value={})
        globals_loader = AsyncMock(return_value={"authCookies": [{"name": "auth_token"}]})
        cache_loader = AsyncMock(return_value={"sub-id": {"nodes": [], "edges": []}})
        persist_globals = AsyncMock()

        with (
            patch("app.db.session.async_session_maker", session_factory),
            patch("app.api.workflows.get_credentials_context", new=credentials_loader),
            patch("app.api.workflows.collect_referenced_workflows", new=cache_loader),
            patch(
                "app.api.workflows._persist_global_variables_from_execution",
                new=persist_globals,
            ),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                new=globals_loader,
            ),
            patch("app.services.cluster.dispatch.register_execution"),
            patch("app.services.cluster.dispatch.asyncio.to_thread", execute),
            patch("app.services.cluster.dispatch.persist_run_history", new=AsyncMock()),
            patch("app.services.cluster.dispatch.run_queue.complete", new=AsyncMock()),
            patch("app.services.cluster.dispatch.run_queue.notify_done", new=AsyncMock()),
        ):
            await RunQueueWorker()._execute_claimed(row)

        return {
            "row": row,
            "workflow": workflow,
            "kwargs": execute.await_args.kwargs,
            "credentials_loader": credentials_loader,
            "globals_loader": globals_loader,
            "cache_loader": cache_loader,
            "persist_globals": persist_globals,
        }

    @staticmethod
    def _owner_arg(loader: AsyncMock) -> object:
        if "actor_user_id" in loader.await_args.kwargs:
            return loader.await_args.kwargs["actor_user_id"]
        return loader.await_args.args[1]

    async def test_global_variables_reach_the_claiming_instance(self) -> None:
        """$global.x resolved to nothing on every cluster run: nobody loaded it."""
        claimed = await self._claim()
        self.assertEqual(
            claimed["kwargs"]["global_variables_context"],
            {"authCookies": [{"name": "auth_token"}]},
        )

    async def test_global_variables_are_scoped_to_the_credentials_owner(self) -> None:
        """Globals hold secrets, so they may never reach further than credentials do."""
        claimed = await self._claim()
        self.assertEqual(
            self._owner_arg(claimed["globals_loader"]),  # type: ignore[arg-type]
            self._owner_arg(claimed["credentials_loader"]),  # type: ignore[arg-type]
        )

    async def test_a_run_without_a_credentials_owner_gets_no_globals(self) -> None:
        """No identified actor means no credentials today, and no globals either."""
        claimed = await self._claim(credentials_owner_id=None)
        self.assertIsNone(self._owner_arg(claimed["globals_loader"]))  # type: ignore[arg-type]
        self.assertIsNone(self._owner_arg(claimed["cache_loader"]))  # type: ignore[arg-type]

    async def test_sub_workflows_reach_the_claiming_instance(self) -> None:
        """Without the cache an execute node silently does nothing."""
        claimed = await self._claim()
        self.assertEqual(
            claimed["kwargs"]["workflow_cache"], {"sub-id": {"nodes": [], "edges": []}}
        )

    async def test_the_public_base_url_reaches_the_claiming_instance(self) -> None:
        """$workflowUrl and HITL review links are built from it."""
        claimed = await self._claim()
        self.assertTrue(str(claimed["kwargs"]["public_base_url"]).strip())

    async def test_global_variable_writes_are_persisted_where_the_run_happened(self) -> None:
        """A cluster run that refreshes a global must save it, like history."""
        claimed = await self._claim(
            nodes=[{"id": "v1", "type": "variable", "data": {"isGlobal": True}}],
            node_results=[
                {
                    "node_id": "v1",
                    "node_type": "variable",
                    "output": {"name": "authCookies", "value": [], "type": "array"},
                }
            ],
        )
        persist: AsyncMock = claimed["persist_globals"]  # type: ignore[assignment]
        persist.assert_awaited_once()
        self.assertEqual(
            persist.await_args.args[1],
            claimed["row"].credentials_owner_id,  # type: ignore[union-attr]
        )

    async def test_a_run_without_a_credentials_owner_writes_no_globals(self) -> None:
        """An unowned run must not overwrite the owner's global variables."""
        claimed = await self._claim(
            credentials_owner_id=None,
            nodes=[{"id": "v1", "type": "variable", "data": {"isGlobal": True}}],
            node_results=[
                {
                    "node_id": "v1",
                    "node_type": "variable",
                    "output": {"name": "authCookies", "value": [], "type": "array"},
                }
            ],
        )
        persist: AsyncMock = claimed["persist_globals"]  # type: ignore[assignment]
        persist.assert_not_awaited()
