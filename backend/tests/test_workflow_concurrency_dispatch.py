"""dispatch_workflow admits, queues, rejects, and always gives the slot back."""

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.cluster import dispatch
from app.services.workflow_concurrency import Admission, QueueInfo

NODES = [{"id": "a", "type": "set", "data": {"label": "a"}}]


def _result(status: str = "success", futures: tuple = ()) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        outputs={},
        node_results=[],
        allow_downstream_pending=bool(futures),
        allow_downstream_futures=lambda: futures,
    )


class DispatchGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.workflow_id = uuid.uuid4()
        self.execution_id = uuid.uuid4()

    async def _dispatch(self, admission: Admission | None, *, execute=None, **kwargs):
        admit = AsyncMock(return_value=admission)
        # Kept on self so a test whose dispatch raises can still inspect it.
        release = self.release = AsyncMock()
        execute = execute or (lambda **_: _result())
        with (
            patch.object(dispatch.settings, "cluster_enabled", False),
            patch("app.services.cluster.dispatch.workflow_concurrency.admit", admit),
            patch("app.services.cluster.dispatch.workflow_concurrency.release", release),
            patch(
                "app.services.cluster.dispatch.workflow_concurrency.record_queue_full",
                AsyncMock(),
            ) as full,
            patch("app.services.cluster.dispatch.execute_workflow", side_effect=execute),
            patch("app.services.cluster.dispatch.run_error_workflow_for_failed_run", AsyncMock()),
            patch(
                "app.services.cluster.dispatch.wait_for_result",
                AsyncMock(return_value=_result()),
            ) as wait,
        ):
            result = await dispatch.dispatch_workflow(
                workflow_id=self.workflow_id,
                nodes=NODES,
                edges=[],
                inputs={},
                execution_id=self.execution_id,
                trigger_source="API",
                **kwargs,
            )
            await asyncio.sleep(0)
        return result, admit, release, full, wait

    async def test_no_limit_never_calls_admit(self) -> None:
        _, admit, release, _, _ = await self._dispatch(None)
        admit.assert_not_awaited()
        release.assert_not_awaited()

    async def test_an_exempt_editor_test_run_is_not_gated(self) -> None:
        _, admit, _, _, _ = await self._dispatch(
            None, concurrency_limit=1, concurrency_exempt=True, test_run=True
        )
        admit.assert_not_awaited()

    async def test_an_admitted_run_releases_after_executing(self) -> None:
        _, admit, release, _, _ = await self._dispatch(
            Admission(kind="admitted", execution_id=self.execution_id), concurrency_limit=1
        )
        admit.assert_awaited_once()
        release.assert_awaited_once_with(self.execution_id)

    async def test_a_raising_run_still_releases(self) -> None:
        def boom(**_: object) -> None:
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            await self._dispatch(
                Admission(kind="admitted", execution_id=self.execution_id),
                execute=boom,
                concurrency_limit=1,
            )
        self.release.assert_awaited_once_with(self.execution_id)

    async def test_a_hitl_pause_releases_immediately(self) -> None:
        _, _, release, _, _ = await self._dispatch(
            Admission(kind="admitted", execution_id=self.execution_id),
            execute=lambda **_: _result("pending"),
            concurrency_limit=1,
        )
        release.assert_awaited_once_with(self.execution_id)

    async def test_allow_downstream_keeps_the_slot_until_the_branch_joins(self) -> None:
        from concurrent.futures import Future

        # Exercised directly: the release runs after dispatch returns, so the patch
        # has to stay active until the branch finishes.
        branch: Future = Future()
        release = AsyncMock()
        with patch("app.services.cluster.dispatch.workflow_concurrency.release", release):
            await dispatch.release_slot_when_done(_result(futures=(branch,)), self.execution_id)
            await asyncio.sleep(0.05)
            release.assert_not_awaited()
            branch.set_result(None)
            for _ in range(100):
                if release.await_count:
                    break
                await asyncio.sleep(0.01)
        release.assert_awaited_once_with(self.execution_id)

    async def test_a_queued_run_returns_the_admission_when_asked(self) -> None:
        admission = Admission(
            kind="queued", execution_id=self.execution_id, queue=QueueInfo(1, 1, 1, 1)
        )
        result, _, release, _, _ = await self._dispatch(
            admission, concurrency_limit=1, on_queued="return"
        )
        self.assertIs(result, admission)
        release.assert_not_awaited()

    async def test_a_queued_background_run_waits_for_its_result(self) -> None:
        admission = Admission(
            kind="queued", execution_id=self.execution_id, queue=QueueInfo(1, 1, 1, 1)
        )
        result, _, _, _, wait = await self._dispatch(admission, concurrency_limit=1)
        wait.assert_awaited_once()
        self.assertEqual(result.status, "success")

    async def test_a_full_queue_records_history_and_reports_queue_full(self) -> None:
        admission = Admission(
            kind="queue_full", execution_id=self.execution_id, queue=QueueInfo(0, 5, 1, 1)
        )
        result, _, _, full, _ = await self._dispatch(admission, concurrency_limit=1)
        full.assert_awaited_once()
        self.assertEqual(result.status, "queue_full")
        self.assertTrue(result.history_written)

    async def test_held_runs_carry_the_error_workflow_guard(self) -> None:
        admission = Admission(
            kind="queued", execution_id=self.execution_id, queue=QueueInfo(1, 1, 1, 1)
        )
        _, admit, _, _, _ = await self._dispatch(
            admission, concurrency_limit=1, run_error_workflow=False, on_queued="return"
        )
        held = admit.await_args.args[0]
        self.assertEqual(held.run_options["run_error_workflow"], False)
