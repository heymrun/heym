"""When a run is kept in-process, and how an offloaded result comes back."""

import asyncio
import logging
import threading
import unittest
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState

from app.observability import tracing
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

    async def test_a_cancelled_run_returns_cancelled_status_and_outputs(self) -> None:
        execution_id = uuid.uuid4()
        event = bus_module.run_result_bus.register(execution_id)
        event.set()
        with patch(
            "app.services.cluster.dispatch.run_queue.read_terminal_result",
            new=AsyncMock(
                return_value=(
                    "done",
                    {
                        "status": "cancelled",
                        "outputs": {"error": "Execution was cancelled"},
                        "error": None,
                    },
                    None,
                )
            ),
        ):
            result = await wait_for_result(execution_id, timeout_seconds=1.0)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.outputs, {"error": "Execution was cancelled"})
        self.assertIsNone(result.error)
        self.assertTrue(result.history_written)


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
        db.get = AsyncMock(return_value=None)
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
        db.get = AsyncMock(return_value=None)
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


class RetiredRunTests(unittest.IsolatedAsyncioTestCase):
    """A run the queue retired must still reach the user's execution history.

    offloaded_error() reported history_written=True, so every trigger call site
    took the "the instance that ran it already wrote history" branch for a run
    no instance ever ran. Nothing was written, the reason was dropped, and the
    only trace was one INFO line saying "status: error".
    """

    async def test_a_queue_failure_is_not_reported_by_any_instance(self) -> None:
        execution_id = uuid.uuid4()
        bus_module.run_result_bus.register(execution_id).set()
        with patch(
            "app.services.cluster.dispatch.run_queue.read_terminal_result",
            new=AsyncMock(return_value=("failed", None, "boom")),
        ):
            result = await wait_for_result(execution_id, timeout_seconds=1.0)
        self.assertFalse(result.reported)

    async def test_the_reason_survives_where_history_can_show_it(self) -> None:
        execution_id = uuid.uuid4()
        bus_module.run_result_bus.register(execution_id).set()
        with patch(
            "app.services.cluster.dispatch.run_queue.read_terminal_result",
            new=AsyncMock(return_value=("skipped_late", None, "too late")),
        ):
            result = await wait_for_result(execution_id, timeout_seconds=1.0)
        self.assertEqual(result.outputs, {"error": "too late"})

    async def test_a_reported_run_is_left_to_the_instance_that_ran_it(self) -> None:
        execution_id = uuid.uuid4()
        bus_module.run_result_bus.register(execution_id).set()
        with patch(
            "app.services.cluster.dispatch.run_queue.read_terminal_result",
            new=AsyncMock(return_value=("done", {"status": "error", "outputs": {}}, None)),
        ):
            result = await wait_for_result(execution_id, timeout_seconds=1.0)
        self.assertTrue(result.reported)

    async def test_a_timeout_is_left_to_the_run_that_may_still_be_going(self) -> None:
        """The live run still owns this execution id; a second row would collide."""
        execution_id = uuid.uuid4()
        with patch(
            "app.services.cluster.dispatch.run_queue.read_terminal_result",
            new=AsyncMock(return_value=("claimed", None, None)),
        ):
            result = await wait_for_result(execution_id, timeout_seconds=0.05)
        self.assertTrue(result.reported)

    async def _dispatch(self, waited: object) -> AsyncMock:
        from app.services.cluster.dispatch import dispatch_workflow

        record = AsyncMock(return_value=True)
        with (
            patch("app.services.cluster.dispatch.settings.cluster_enabled", True),
            patch("app.services.cluster.dispatch.identity.is_main", return_value=False),
            patch(
                "app.services.cluster.dispatch.run_queue.enqueue",
                new=AsyncMock(return_value="worker-1"),
            ),
            patch("app.services.cluster.dispatch.run_queue.notify_queue", new=AsyncMock()),
            patch(
                "app.services.cluster.dispatch.wait_for_result",
                new=AsyncMock(return_value=waited),
            ),
            patch("app.services.cluster.dispatch.record_failed_dispatch", record),
        ):
            await dispatch_workflow(
                workflow_id=uuid.uuid4(),
                nodes=[{"type": "http", "data": {}}],
                edges=[],
                inputs={"triggered_by": "cron"},
                trigger_source="cron",
            )
        return record

    async def test_a_run_no_instance_reported_is_recorded_by_the_dispatcher(self) -> None:
        from app.services.cluster.run_history import offloaded_error

        record = await self._dispatch(offloaded_error("boom"))
        record.assert_awaited_once()
        self.assertEqual(record.await_args.kwargs["message"], "boom")
        self.assertEqual(record.await_args.kwargs["trigger_source"], "cron")

    async def test_a_reported_run_is_not_recorded_twice(self) -> None:
        from app.services.cluster.run_history import from_summary

        record = await self._dispatch(from_summary({"status": "error", "outputs": {}}))
        record.assert_not_awaited()


class OffloadedRunLoggingTests(unittest.TestCase):
    """The log line is the only thing an operator sees for an offloaded run."""

    def _log(self, result: object) -> tuple[str, str]:
        from app.services.cluster.dispatch import log_offloaded_run

        with self.assertLogs("cluster", level="INFO") as captured:
            log_offloaded_run(
                logging.getLogger("cluster"), workflow_id="wf-1", trigger="cron", result=result
            )
        return captured.records[0].levelname, captured.records[0].getMessage()

    def test_a_dispatch_failure_names_its_reason(self) -> None:
        from app.services.cluster.run_history import offloaded_error

        level, message = self._log(offloaded_error("Skipped: not claimed in time"))
        self.assertEqual(level, "ERROR")
        self.assertIn("Skipped: not claimed in time", message)

    def test_a_successful_run_names_the_instance_that_ran_it(self) -> None:
        from app.services.cluster.run_history import from_summary

        level, message = self._log(
            from_summary({"status": "success", "outputs": {}, "instance": "worker-1"})
        )
        self.assertEqual(level, "INFO")
        self.assertIn("worker-1", message)

    def test_a_workflow_that_ran_and_failed_is_a_warning(self) -> None:
        """Not an error of dispatch: the run happened, its history holds the node."""
        from app.services.cluster.run_history import from_summary

        level, message = self._log(
            from_summary({"status": "error", "outputs": {}, "instance": "worker-1"})
        )
        self.assertEqual(level, "WARNING")
        self.assertIn("history", message)


class RecordFailedDispatchTests(unittest.IsolatedAsyncioTestCase):
    """The row written for a run that never executed anywhere."""

    def _session(self, inserted: object) -> tuple[MagicMock, MagicMock]:
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4(), name="Nightly")
        db = MagicMock()
        db.get = AsyncMock(return_value=workflow)
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: inserted))
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=db)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        return db, factory

    async def _record(self, inserted: object) -> tuple[MagicMock, AsyncMock, bool]:
        from app.services.cluster.run_history import record_failed_dispatch

        db, factory = self._session(inserted)
        snapshot = AsyncMock()
        with (
            patch("app.services.cluster.run_history.async_session_maker", factory),
            patch("app.services.cluster.run_history.upsert_workflow_analytics_snapshot", snapshot),
        ):
            written = await record_failed_dispatch(
                execution_id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                inputs={"triggered_by": "cron"},
                trigger_source="cron",
                message="Skipped: not claimed inside the misfire grace window",
            )
        return db, snapshot, written

    async def test_the_failed_run_is_written_with_its_reason(self) -> None:
        _db, _snapshot, written = await self._record(uuid.uuid4())
        self.assertTrue(written)

    async def test_the_failed_run_counts_in_analytics(self) -> None:
        _db, snapshot, _written = await self._record(uuid.uuid4())
        snapshot.assert_awaited_once()
        self.assertEqual(snapshot.await_args.kwargs["status"], "error")

    async def test_a_run_that_reported_late_keeps_its_own_row(self) -> None:
        """The insert conflicts, so the analytics bucket must not count it twice."""
        db, snapshot, written = await self._record(None)
        self.assertFalse(written)
        snapshot.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_a_deleted_workflow_is_not_recorded(self) -> None:
        from app.services.cluster.run_history import record_failed_dispatch

        _db, factory = self._session(uuid.uuid4())
        factory.return_value.__aenter__.return_value.get = AsyncMock(return_value=None)
        with patch("app.services.cluster.run_history.async_session_maker", factory):
            written = await record_failed_dispatch(
                execution_id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                inputs={},
                trigger_source="cron",
                message="boom",
            )
        self.assertFalse(written)


class RunHistoryLastWriterWinsTests(unittest.IsolatedAsyncioTestCase):
    """The instance that ran it holds the real answer, even if the queue gave up.

    A stranded claim is retired while its run may still be going. The retiring
    pass records the failure under the same execution id, so the run's own
    history write has to replace that row rather than collide with it.
    """

    async def test_the_run_row_replaces_a_row_already_recorded_for_it(self) -> None:
        from sqlalchemy.dialects import postgresql

        from app.services.cluster.run_history import persist_run_history

        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=db)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        result = SimpleNamespace(
            status="success",
            outputs={},
            node_results=[],
            execution_time_ms=1.0,
            sub_workflow_executions=[],
        )
        with (
            patch("app.services.cluster.run_history.async_session_maker", factory),
            patch(
                "app.services.cluster.run_history.upsert_workflow_analytics_snapshot",
                new=AsyncMock(),
            ),
        ):
            await persist_run_history(
                execution_id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                owner_id=uuid.uuid4(),
                workflow_name="Nightly",
                inputs={},
                trigger_source="cron",
                result=result,
            )
        statement = db.execute.await_args.args[0]
        compiled = str(statement.compile(dialect=postgresql.dialect())).upper()
        self.assertIn("ON CONFLICT (ID) DO UPDATE", compiled)
        # A late real result replaces the queue's empty failure row; its nodes get counted.
        self.assertIn("NODE_ANALYTICS_PENDING", compiled.split("DO UPDATE SET")[1])


class DispatchHandoffLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from app.services.execution_cancellation import _ACTIVE_EXECUTIONS

        _ACTIVE_EXECUTIONS.clear()

    async def test_dispatch_workflow_relinquishes_execution_after_enqueue(self) -> None:
        from app.services.cluster.dispatch import dispatch_workflow
        from app.services.execution_cancellation import (
            _ACTIVE_EXECUTIONS,
            active_execution_registry,
            clear_execution,
            get_active_execution_handle,
            register_execution,
        )

        wf_id = uuid.uuid4()
        run_id = uuid.uuid4()
        nodes = [{"type": "http", "data": {}}]

        # Pre-register dispatcher handle before dispatch
        cancel_event = register_execution(
            workflow_id=wf_id,
            execution_id=run_id,
            inputs={},
        )
        disp_handle = get_active_execution_handle(run_id)
        self.assertIsNotNone(disp_handle)

        with (
            patch("app.services.cluster.dispatch.settings") as s,
            patch("app.services.cluster.dispatch.identity.is_main", return_value=True),
            patch(
                "app.services.cluster.dispatch.run_queue.enqueue", new=AsyncMock()
            ) as mock_enqueue,
            patch("app.services.cluster.dispatch.run_queue.notify_queue", new=AsyncMock()),
            patch(
                "app.services.cluster.dispatch.wait_for_result",
                new=AsyncMock(return_value=SimpleNamespace(reported=True)),
            ),
            patch.object(active_execution_registry, "record_finished") as mock_finish,
        ):
            s.cluster_enabled = True
            await dispatch_workflow(
                workflow_id=wf_id,
                nodes=nodes,
                edges=[],
                inputs={},
                execution_id=run_id,
                cancel_event=cancel_event,
                wait_for_completion=True,
            )
            mock_enqueue.assert_awaited_once()

        # The dispatcher relinquished its handle
        self.assertTrue(disp_handle.relinquished)
        self.assertNotIn(run_id, _ACTIVE_EXECUTIONS)

        # Dispatcher caller cleaning up its relinquished handle is a safe NO-OP returning False
        cleared = clear_execution(run_id, handle=disp_handle)
        self.assertIs(cleared, False)
        # record_finished was not called for the relinquished dispatcher handle
        mock_finish.assert_not_called()


class QueuedRunCancellationWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_claimed_run_with_persisted_cancellation_exits_before_executor(self) -> None:
        """A run marked cancelled while queued must not invoke execute_workflow,
        must write cancelled execution history, and complete the queue cleanly.
        Covers both STATUS_QUEUED and STATUS_WAITING_FOR_MAIN.
        """
        import datetime

        from app.db.models import ActiveWorkflowExecution
        from app.services.cluster.dispatch import RunQueueWorker
        from app.services.cluster.run_queue import (
            STATUS_QUEUED,
            STATUS_WAITING_FOR_MAIN,
        )

        worker = RunQueueWorker()

        for queue_status in (STATUS_QUEUED, STATUS_WAITING_FOR_MAIN):
            run_id = uuid.uuid4()
            wf_id = uuid.uuid4()
            now = datetime.datetime.now(datetime.timezone.utc)
            queued_row = SimpleNamespace(
                execution_id=run_id,
                workflow_id=wf_id,
                status=queue_status,
                target_instance_id="test-worker",
                inputs={"x": 1},
                trigger_source="api",
                actor_user_id=None,
                credentials_owner_id=None,
                test_run=False,
                timeout_seconds=None,
                enqueued_at=now,
                not_after=now + datetime.timedelta(seconds=60),
                return_on_chart_output=False,
            )

            active_row = MagicMock(spec=ActiveWorkflowExecution)
            active_row.execution_id = run_id
            active_row.cancel_requested_at = now

            mock_session = AsyncMock()
            mock_session.get = AsyncMock(return_value=active_row)
            exec_result = MagicMock()
            exec_result.first.return_value = (uuid.uuid4(), "Test Workflow")
            mock_session.execute = AsyncMock(return_value=exec_result)
            mock_session.commit = AsyncMock()

            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=mock_session)
            cm.__aexit__ = AsyncMock(return_value=False)

            from app.services.execution_cancellation import register_execution

            event_captured = None

            def spy_register(*args, **kwargs):
                nonlocal event_captured
                event = register_execution(*args, **kwargs)
                event_captured = event
                return event

            with (
                patch("app.db.session.async_session_maker", return_value=cm),
                patch(
                    "app.services.cluster.dispatch.execute_workflow", new=AsyncMock()
                ) as mock_exec,
                patch(
                    "app.services.cluster.dispatch.run_queue.complete", new=AsyncMock()
                ) as mock_complete,
                patch("app.services.cluster.dispatch.run_queue.notify_done", new=AsyncMock()),
                patch("app.services.cluster.dispatch.register_execution", side_effect=spy_register),
                patch(
                    "app.services.cluster.dispatch.upsert_workflow_analytics_snapshot",
                    new=AsyncMock(),
                ) as mock_analytics,
            ):
                await worker._execute_claimed(queued_row)

                # Proves executor was NEVER invoked
                mock_exec.assert_not_called()
                # Proves cancel_event was registered and set
                self.assertIsNotNone(event_captured)
                self.assertTrue(event_captured.is_set())
                # Proves run_queue was completed with status="cancelled" and error=None
                mock_complete.assert_awaited_once()
                complete_call = mock_complete.await_args
                self.assertEqual(complete_call.args[0], run_id)
                self.assertEqual(complete_call.kwargs["result"]["status"], "cancelled")
                self.assertIsNone(complete_call.kwargs["error"])
                # Proves analytics snapshot and history row were inserted
                mock_analytics.assert_awaited_once()
                self.assertEqual(mock_analytics.await_args.kwargs["status"], "cancelled")
                mock_session.commit.assert_awaited_once()


class InProcessDispatchNoLeakedHandleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from app.services.execution_cancellation import _ACTIVE_EXECUTIONS

        _ACTIVE_EXECUTIONS.clear()

    async def test_in_process_dispatch_without_caller_handle_does_not_leak_active_execution(
        self,
    ) -> None:
        """In-process execution without a caller-provided handle must not register a ghost
        handle in _ACTIVE_EXECUTIONS.
        """
        from app.services.cluster.dispatch import dispatch_workflow
        from app.services.execution_cancellation import _ACTIVE_EXECUTIONS

        wf_id = uuid.uuid4()
        run_id = uuid.uuid4()
        mock_result = SimpleNamespace(status="success", execution_time_ms=10.0, node_results=[])

        with (
            patch("app.services.cluster.dispatch.settings") as s,
            patch("app.services.cluster.dispatch.identity.is_main", return_value=True),
            patch(
                "app.services.cluster.dispatch.execute_workflow", return_value=mock_result
            ) as mock_exec,
            patch(
                "app.services.cluster.dispatch.run_error_workflow_for_failed_run",
                new=AsyncMock(),
            ),
        ):
            s.cluster_enabled = False
            result = await dispatch_workflow(
                workflow_id=wf_id,
                nodes=[{"id": "n1", "type": "textInput", "data": {}}],
                edges=[],
                inputs={},
                execution_id=run_id,
            )

        mock_exec.assert_called_once()
        self.assertIs(result, mock_result)
        # Verify no handle was leaked into _ACTIVE_EXECUTIONS
        self.assertNotIn(run_id, _ACTIVE_EXECUTIONS)
        self.assertEqual(len(_ACTIVE_EXECUTIONS), 0)


class OffloadDispatchEnqueueFailureCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from app.services.execution_cancellation import _ACTIVE_EXECUTIONS

        _ACTIVE_EXECUTIONS.clear()

    async def test_enqueue_failure_cleans_up_locally_registered_handle(self) -> None:
        """If dispatch_workflow registered a handle locally and enqueue raises,
        the handle must be cleaned up from _ACTIVE_EXECUTIONS.
        """
        from app.services.cluster.dispatch import dispatch_workflow
        from app.services.execution_cancellation import _ACTIVE_EXECUTIONS

        wf_id = uuid.uuid4()
        run_id = uuid.uuid4()

        with (
            patch("app.services.cluster.dispatch.settings") as s,
            patch("app.services.cluster.dispatch.identity.is_main", return_value=True),
            patch("app.services.cluster.dispatch.resolve_placement", return_value="worker"),
            patch("app.services.cluster.dispatch.should_run_in_process", return_value=False),
            patch(
                "app.services.cluster.dispatch.run_queue.enqueue",
                side_effect=RuntimeError("Database connection lost"),
            ),
        ):
            s.cluster_enabled = True
            with self.assertRaises(RuntimeError):
                await dispatch_workflow(
                    workflow_id=wf_id,
                    nodes=[{"id": "n1", "type": "textInput", "data": {}}],
                    edges=[],
                    inputs={},
                    execution_id=run_id,
                )

        # Verify handle was cleaned up and not leaked
        self.assertNotIn(run_id, _ACTIVE_EXECUTIONS)
        self.assertEqual(len(_ACTIVE_EXECUTIONS), 0)


class QueueTraceContextTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the producer and real async-to-thread handoff, including its scope."""

    def setUp(self) -> None:
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.addCleanup(provider.shutdown)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(trace, "_TRACER_PROVIDER", provider))
        stack.enter_context(patch.object(tracing, "_provider", provider))
        self.tracer = provider.get_tracer("queue-context-test")
        self.workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Queue trace context",
            nodes=[
                {
                    "id": "seed",
                    "type": "set",
                    "data": {"label": "seed", "mappings": [{"key": "answer", "value": "42"}]},
                }
            ],
            edges=[],
        )
        self.phases: list[tuple[str, SpanContext]] = []
        self.persist = AsyncMock(side_effect=lambda **_kwargs: self._record("history"))
        self.complete = AsyncMock(side_effect=lambda *_args, **_kwargs: self._record("complete"))
        self.notify = AsyncMock(side_effect=lambda *_args: self._record("notify"))

    def _record(self, phase: str) -> dict:
        self.phases.append((phase, trace.get_current_span().get_span_context()))
        return {}

    def _carrier(self) -> tuple[dict[str, str], SpanContext]:
        with self.tracer.start_as_current_span("producer", context=otel_context.Context()) as span:
            carrier = tracing.capture_queue_context()
            self.assertIsNotNone(carrier)
            return carrier, span.get_span_context()

    def _row(self, carrier: object = None) -> SimpleNamespace:
        return SimpleNamespace(
            id=None,
            execution_id=uuid.uuid4(),
            workflow_id=self.workflow.id,
            inputs={},
            trigger_source="api",
            actor_user_id=None,
            credentials_owner_id=self.workflow.owner_id,
            test_run=False,
            timeout_seconds=None,
            return_on_chart_output=False,
            trace_context=carrier,
        )

    @contextmanager
    def _worker(self) -> Iterator[Any]:
        from app.services.cluster.dispatch import RunQueueWorker

        db = MagicMock()
        db.get = AsyncMock(return_value=None)
        query_result = SimpleNamespace(scalar_one_or_none=lambda: self.workflow, first=lambda: None)

        def query(*_args: object) -> SimpleNamespace:
            self._record("database")
            return query_result

        db.execute = AsyncMock(side_effect=query)
        db.commit = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=db)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        with ExitStack() as stack:
            stack.enter_context(patch("app.db.session.async_session_maker", factory))
            for target in (
                "app.api.workflows.get_credentials_context",
                "app.api.workflows.collect_referenced_workflows",
                "app.services.global_variables_service.get_global_variables_context",
            ):
                stack.enter_context(patch(target, new=AsyncMock(return_value={})))
            stack.enter_context(
                patch(
                    "app.api.workflows._persist_global_variables_from_execution",
                    new=AsyncMock(side_effect=lambda *_args: self._record("globals")),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.cluster.dispatch.register_execution",
                    side_effect=lambda **_kwargs: threading.Event(),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.cluster.dispatch.complete_execution",
                    side_effect=lambda *_args, **_kwargs: self._record("cleanup"),
                )
            )
            stack.enter_context(
                patch("app.services.hitl_service.build_default_public_base_url", return_value="")
            )
            for target, mock in (
                ("persist_run_history", self.persist),
                ("persist_pending_run_history", self.persist),
                ("run_queue.complete", self.complete),
                ("run_queue.notify_done", self.notify),
            ):
                stack.enter_context(patch(f"app.services.cluster.dispatch.{target}", mock))
            yield RunQueueWorker()

    async def _wait_event(self, event: threading.Event) -> None:
        async with asyncio.timeout(5):
            while not event.is_set():
                await asyncio.sleep(0.01)

    def _assert_phases(self, expected: SpanContext) -> None:
        self.assertTrue(self.phases)
        for phase, observed in self.phases:
            self.assertEqual(observed, expected, phase)

    async def _dispatch(self) -> Any:
        from app.services.cluster.dispatch import dispatch_workflow

        enqueue = AsyncMock(return_value="worker-a")
        with (
            patch("app.services.cluster.dispatch.settings.cluster_enabled", True),
            patch("app.services.cluster.dispatch.identity.is_main", return_value=False),
            patch(
                "app.services.cluster.dispatch.register_execution", return_value=threading.Event()
            ),
            patch("app.services.cluster.dispatch.get_active_execution_handle", return_value=None),
            patch("app.services.cluster.dispatch.relinquish_execution"),
            patch("app.services.cluster.dispatch.run_queue.enqueue", enqueue),
            patch("app.services.cluster.dispatch.run_queue.notify_queue", new=AsyncMock()),
        ):
            await dispatch_workflow(
                workflow_id=self.workflow.id,
                nodes=self.workflow.nodes,
                edges=self.workflow.edges,
                inputs={"business": "unchanged"},
                wait_for_completion=False,
            )
        enqueue.assert_awaited_once()
        return enqueue.await_args.args[0]

    async def test_dispatch_captures_active_parent_without_changing_business_inputs(self) -> None:
        from opentelemetry import baggage

        from app.services.cluster.run_queue import build_queue_values

        with self.tracer.start_as_current_span("request", context=otel_context.Context()) as parent:
            token = otel_context.attach(baggage.set_baggage("private", "do-not-persist"))
            try:
                queued = await self._dispatch()
            finally:
                otel_context.detach(token)
        context = parent.get_span_context()
        self.assertEqual(
            queued.trace_context,
            {
                "traceparent": f"00-{context.trace_id:032x}-{context.span_id:016x}-{context.trace_flags:02x}"
            },
        )
        values = build_queue_values(queued, target_instance_id="worker-a", grace_seconds=60)
        self.assertEqual(values["trace_context"], queued.trace_context)
        self.assertEqual(values["inputs"], {"business": "unchanged"})

    async def test_disabled_tracing_preserves_dispatch_and_legacy_row_execution(self) -> None:
        with patch.object(tracing, "_provider", None):
            queued = await self._dispatch()
            self.assertIsNone(queued.trace_context)
            row = self._row()
            row.inputs = queued.inputs
            del row.trace_context
            with self._worker() as worker:
                await worker._execute_claimed(row)
        self.persist.assert_awaited_once()
        result = self.persist.await_args.kwargs["result"]
        self.assertEqual(result.status, "success")
        self.assertEqual(result.node_results[0]["output"], {"answer": "42"})
        self.assertEqual(self.persist.await_args.kwargs["inputs"], queued.inputs)
        self.complete.assert_awaited_once()
        self.assertEqual(self.exporter.get_finished_spans(), ())

    async def test_capture_failure_does_not_prevent_enqueue(self) -> None:
        with patch.object(trace, "get_current_span", side_effect=RuntimeError("unavailable")):
            queued = await self._dispatch()
        self.assertIsNone(queued.trace_context)
        self.assertEqual(queued.inputs, {"business": "unchanged"})

    async def test_real_executor_continues_parent_and_restores_context_before_persistence(
        self,
    ) -> None:
        carrier, producer = self._carrier()
        with self.tracer.start_as_current_span(
            "consumer", context=otel_context.Context()
        ) as sentinel:
            with self._worker() as worker:
                await worker._execute_claimed(self._row(carrier))
            self.assertEqual(
                trace.get_current_span().get_span_context(), sentinel.get_span_context()
            )
            self._assert_phases(sentinel.get_span_context())
        self.persist.assert_awaited_once()
        result = self.persist.await_args.kwargs["result"]
        self.assertEqual(result.status, "success")
        self.assertEqual(result.node_results[0]["output"], {"answer": "42"})
        spans = self.exporter.get_finished_spans()
        workflow = next(span for span in spans if span.name == "heym.workflow.execute")
        node = next(span for span in spans if span.name == "heym.node.execute")
        self.assertEqual(workflow.context.trace_id, producer.trace_id)
        self.assertEqual(workflow.parent.span_id, producer.span_id)
        self.assertTrue(workflow.parent.is_remote)
        self.assertEqual(node.parent.span_id, workflow.context.span_id)

    async def test_unsampled_parent_survives_real_executor_without_exporting_children(self) -> None:
        from app.services.node_execution import registry
        from app.services.node_execution.nodes.set_node import execute as execute_set

        parent = SpanContext(
            trace_id=0x1234,
            span_id=0x5678,
            is_remote=False,
            trace_flags=TraceFlags(0),
            trace_state=TraceState([("vendor", "sample")]),
        )
        with trace.use_span(NonRecordingSpan(parent)):
            carrier = tracing.capture_queue_context()
        observed = []

        def record_node(ctx: Any) -> object:
            observed.append(trace.get_current_span().get_span_context())
            return execute_set(ctx)

        with (
            self._worker() as worker,
            patch.dict(registry._HANDLER_CACHE, {"set": record_node}),
        ):
            await worker._execute_claimed(self._row(carrier))
        self.assertEqual(self.persist.await_args.kwargs["result"].status, "success")
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0].trace_id, parent.trace_id)
        self.assertEqual(observed[0].trace_flags, parent.trace_flags)
        self.assertEqual(observed[0].trace_state, parent.trace_state)
        self.assertEqual(self.exporter.get_finished_spans(), ())

    async def test_overlapping_runs_and_parentless_run_do_not_share_context(self) -> None:
        from app.services.workflow_executor import ExecutionResult

        first, first_parent = self._carrier()
        second, second_parent = self._carrier()
        rows = [self._row(first), self._row(second)]
        ready = threading.Event()
        release = threading.Event()
        barrier = threading.Barrier(2, action=ready.set)
        observed = {}
        after_release = {}

        def execute(**kwargs: Any) -> ExecutionResult:
            run_id = kwargs["execution_id"]
            observed[run_id] = trace.get_current_span().get_span_context()
            if run_id in {str(row.execution_id) for row in rows}:
                barrier.wait(timeout=5)
                if not release.wait(timeout=5):
                    raise AssertionError("concurrent runs were not released")
                after_release[run_id] = trace.get_current_span().get_span_context()
            return ExecutionResult(
                workflow_id=self.workflow.id, status="success", outputs={}, execution_time_ms=0.0
            )

        with (
            self.tracer.start_as_current_span(
                "consumer", context=otel_context.Context()
            ) as sentinel,
            self._worker() as worker,
            patch(
                "app.services.cluster.dispatch.execute_workflow", side_effect=execute
            ) as executor,
        ):
            tasks = [asyncio.create_task(worker._execute_claimed(row)) for row in rows]
            try:
                await self._wait_event(ready)
            finally:
                release.set()
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
            for row, parent in zip(rows, (first_parent, second_parent), strict=True):
                actual = observed[str(row.execution_id)]
                self.assertEqual(
                    (actual.trace_id, actual.span_id), (parent.trace_id, parent.span_id)
                )
                self.assertEqual(after_release[str(row.execution_id)], actual)
            for carrier in (None, {"traceparent": "invalid"}):
                row = self._row(carrier)
                await worker._execute_claimed(row)
                self.assertFalse(observed[str(row.execution_id)].is_valid)
            self.assertEqual(executor.call_count, 4)
            self.assertEqual(self.complete.await_count, 4)
            for call in self.complete.await_args_list:
                self.assertEqual(call.kwargs["result"]["status"], "success")
            self._assert_phases(sentinel.get_span_context())

    async def test_business_failure_and_cooperative_cancel_restore_context_without_retry(
        self,
    ) -> None:
        from app.services.workflow_executor import WorkflowCancelledError

        carrier, _ = self._carrier()
        for error in (RuntimeError("execution failed"), WorkflowCancelledError("cancelled")):
            with self.subTest(error=type(error).__name__):
                self.phases.clear()
                self.complete.reset_mock()
                with (
                    self.tracer.start_as_current_span(
                        "consumer", context=otel_context.Context()
                    ) as sentinel,
                    self._worker() as worker,
                    patch(
                        "app.services.cluster.dispatch.execute_workflow", side_effect=error
                    ) as execute,
                ):
                    await worker._execute_claimed(self._row(carrier))
                    self._assert_phases(sentinel.get_span_context())
                    self.assertEqual(
                        trace.get_current_span().get_span_context(), sentinel.get_span_context()
                    )
                execute.assert_called_once()
                self.complete.assert_awaited_once()
                if isinstance(error, WorkflowCancelledError):
                    self.assertEqual(
                        self.complete.await_args.kwargs["result"]["status"], "cancelled"
                    )
                else:
                    self.assertEqual(self.complete.await_args.kwargs["error"], str(error))

    async def test_task_cancellation_detaches_before_the_running_thread_finishes(self) -> None:
        from app.services.workflow_executor import ExecutionResult

        carrier, producer = self._carrier()
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        observed = []

        def execute(**_kwargs: Any) -> ExecutionResult:
            observed.append(trace.get_current_span().get_span_context())
            started.set()
            try:
                if not release.wait(timeout=5):
                    raise AssertionError("cancelled thread was not released")
                observed.append(trace.get_current_span().get_span_context())
                return ExecutionResult(
                    workflow_id=self.workflow.id,
                    status="success",
                    outputs={},
                    execution_time_ms=0.0,
                )
            finally:
                finished.set()

        with (
            self.tracer.start_as_current_span(
                "consumer", context=otel_context.Context()
            ) as sentinel,
            self._worker() as worker,
            patch(
                "app.services.cluster.dispatch.execute_workflow", side_effect=execute
            ) as executor,
        ):

            async def run() -> None:
                try:
                    await worker._execute_claimed(self._row(carrier))
                finally:
                    self._record("cancelled_task")

            task = asyncio.create_task(run())
            try:
                await self._wait_event(started)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertFalse(finished.is_set())
                self._assert_phases(sentinel.get_span_context())
                self.notify.assert_awaited_once()
            finally:
                release.set()
                await self._wait_event(finished)
                await asyncio.wait_for(
                    asyncio.get_running_loop().shutdown_default_executor(), timeout=5
                )
                if not task.done():
                    await task
        executor.assert_called_once()
        self.persist.assert_not_awaited()
        self.assertEqual(len(observed), 2)
        for context in observed:
            self.assertEqual(
                (context.trace_id, context.span_id), (producer.trace_id, producer.span_id)
            )

    async def test_allow_downstream_finalizer_is_created_after_context_is_restored(self) -> None:
        from app.services.node_execution import registry
        from app.services.workflow_executor import ExecutionResult

        carrier, _ = self._carrier()
        started = threading.Event()
        release = threading.Event()
        self.workflow.nodes.extend(
            [
                {
                    "id": "output",
                    "type": "output",
                    "data": {"message": "done", "allowDownstream": True},
                },
                {"id": "wait", "type": "wait", "data": {}},
            ]
        )
        self.workflow.edges = [
            {"id": "first", "source": "seed", "target": "output"},
            {"id": "last", "source": "output", "target": "wait"},
        ]
        original_join = ExecutionResult.join_allow_downstream

        def downstream(_ctx: Any) -> dict:
            started.set()
            if not release.wait(timeout=5):
                raise AssertionError("downstream was not released")
            return {"done": True}

        def join(result: ExecutionResult) -> None:
            self._record("finalizer_join")
            original_join(result)

        with (
            self.tracer.start_as_current_span(
                "consumer", context=otel_context.Context()
            ) as sentinel,
            self._worker() as worker,
            patch.dict(registry._HANDLER_CACHE, {"wait": downstream}),
            patch.object(ExecutionResult, "join_allow_downstream", join),
        ):
            try:
                await worker._execute_claimed(self._row(carrier))
                await self._wait_event(started)
                self.assertTrue(worker._active_finalizers)
                self.complete.assert_awaited_once()
                self.persist.assert_not_awaited()
            finally:
                release.set()
                await asyncio.wait_for(asyncio.gather(*tuple(worker._active_finalizers)), timeout=5)
            self.assertEqual(self.complete.await_count, 2)
            self.persist.assert_awaited_once()
            self.assertEqual(self.persist.await_args.kwargs["result"].status, "success")
            self.assertIn("finalizer_join", [phase for phase, _ in self.phases])
            self._assert_phases(sentinel.get_span_context())
