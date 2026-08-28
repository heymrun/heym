"""When a run is kept in-process, and how an offloaded result comes back."""

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
