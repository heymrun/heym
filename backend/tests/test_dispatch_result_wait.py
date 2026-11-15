"""How long a dispatcher waits for a run's result is not the run's own timeout."""

import unittest
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.cluster import dispatch
from app.services.cluster.run_result_bus import DEFAULT_WAIT_SECONDS
from app.services.workflow_concurrency import Admission, QueueInfo

NODES = [{"id": "a", "type": "set", "data": {"label": "a"}}]
REPORTED = SimpleNamespace(status="success", outputs={}, reported=True, error=None)


class ResultWaitSecondsTests(unittest.TestCase):
    def test_without_a_timeout_the_default_wait_applies(self) -> None:
        self.assertIsNone(dispatch.result_wait_seconds(None, held=True))
        self.assertIsNone(dispatch.result_wait_seconds(None, held=False))

    def test_a_held_run_waits_at_least_the_default(self) -> None:
        self.assertEqual(dispatch.result_wait_seconds(4, held=True), DEFAULT_WAIT_SECONDS)
        self.assertEqual(
            dispatch.result_wait_seconds(3600, held=True),
            3600 + dispatch.RESULT_WAIT_GRACE_SECONDS,
        )

    def test_an_offloaded_run_waits_its_timeout_plus_a_grace(self) -> None:
        self.assertEqual(
            dispatch.result_wait_seconds(4, held=False), 4 + dispatch.RESULT_WAIT_GRACE_SECONDS
        )


class DispatchWaitBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def _wait_budget(self, *, held: bool) -> float | None:
        execution_id = uuid.uuid4()
        wait = AsyncMock(return_value=REPORTED)
        with ExitStack() as stack:
            enter = stack.enter_context
            enter(patch("app.services.cluster.dispatch.wait_for_result", wait))
            if held:
                admission = Admission(
                    kind="queued", execution_id=execution_id, queue=QueueInfo(1, 1, 1, 1)
                )
                enter(patch.object(dispatch.settings, "cluster_enabled", False))
                enter(
                    patch(
                        "app.services.cluster.dispatch.workflow_concurrency.admit",
                        AsyncMock(return_value=admission),
                    )
                )
            else:
                enter(patch.object(dispatch.settings, "cluster_enabled", True))
                enter(patch("app.services.cluster.dispatch.identity.is_main", return_value=True))
                for name, value in (
                    ("choose_target", "worker-1"),
                    ("enqueue", "worker-1"),
                    ("notify_queue", None),
                ):
                    enter(
                        patch(
                            f"app.services.cluster.dispatch.run_queue.{name}",
                            AsyncMock(return_value=value),
                        )
                    )
            await dispatch.dispatch_workflow(
                workflow_id=uuid.uuid4(),
                nodes=NODES,
                edges=[],
                inputs={},
                execution_id=execution_id,
                trigger_source="CRON",
                actor_user_id=uuid.uuid4(),
                timeout_seconds=4,
                concurrency_limit=1 if held else None,
            )
        wait.assert_awaited_once()
        return wait.await_args.kwargs["timeout_seconds"]

    async def test_a_run_held_by_the_concurrency_gate_waits_its_turn(self) -> None:
        # Limit 1, timeout 4 s: a queued run must not give up after 4 s in the queue.
        self.assertEqual(await self._wait_budget(held=True), DEFAULT_WAIT_SECONDS)

    async def test_an_offloaded_run_waits_for_the_workers_timeout_result(self) -> None:
        # The worker stops the run at 4 s and reports it; the dispatcher must still be waiting.
        self.assertEqual(
            await self._wait_budget(held=False), 4 + dispatch.RESULT_WAIT_GRACE_SECONDS
        )


if __name__ == "__main__":
    unittest.main()
