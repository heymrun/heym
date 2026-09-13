"""The configured error workflow must reach every non-test top-level run.

The hook used to sit in one branch of the non-streaming execute endpoint, under
``not already_written``. A cluster-offloaded run reports ``history_written=True``,
so that branch was skipped and neither side called it; the SSE API, the portal and
every trigger service never had the call at all. Reported as discussion #552.
"""

import unittest
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.portal import portal_execute
from app.api.workflows import persist_stream_execution_result
from app.services.cluster.dispatch import dispatch_workflow
from app.services.cluster.run_history import (
    OffloadedRun,
    failed_node_summary,
    failure_node_results,
    from_summary,
    offloaded_error,
    summarize,
)
from app.services.error_workflow_runner import build_error_context, run_error_workflow_for_run

FAILED_NODE = {
    "node_id": "n2",
    "node_label": "callApi",
    "node_type": "http",
    "status": "error",
    "error": "boom",
    "output": {},
    "execution_time_ms": 2.0,
}
NODE_RESULTS = [
    {
        "node_id": "n1",
        "node_label": "start",
        "node_type": "set",
        "status": "success",
        "output": {},
        "execution_time_ms": 1.0,
    },
    FAILED_NODE,
]


def _run_result(status: str = "error", node_results: list | None = None) -> SimpleNamespace:
    """Shaped like ExecutionResult where dispatch reads it. It carries no `error`."""
    return SimpleNamespace(
        workflow_id=uuid.uuid4(),
        status=status,
        outputs={},
        execution_time_ms=4.0,
        node_results=NODE_RESULTS if node_results is None else node_results,
        sub_workflow_executions=[],
    )


class DispatchSeamTests(unittest.IsolatedAsyncioTestCase):
    """One seam behind every dispatch_workflow call site: API, cron and all triggers."""

    async def _dispatch(
        self,
        result: object,
        *,
        cluster_enabled: bool = False,
        test_run: bool = False,
        offloaded: bool = False,
    ) -> AsyncMock:
        hook = AsyncMock(return_value=True)
        execution_id = uuid.uuid4()
        with ExitStack() as stack:
            enter = stack.enter_context
            enter(
                patch(
                    "app.services.error_workflow_runner.run_error_workflow_for_run",
                    hook,
                )
            )
            enter(patch("app.services.cluster.dispatch.settings.cluster_enabled", cluster_enabled))
            enter(
                patch(
                    "app.services.cluster.dispatch.run_queue.choose_target",
                    AsyncMock(return_value="worker-1"),
                )
            )
            if offloaded:
                enter(patch("app.services.cluster.dispatch.identity.is_main", return_value=True))
                enter(
                    patch(
                        "app.services.cluster.dispatch.run_queue.enqueue",
                        AsyncMock(return_value="worker-1"),
                    )
                )
                enter(patch("app.services.cluster.dispatch.run_queue.notify_queue", AsyncMock()))
                enter(
                    patch(
                        "app.services.cluster.dispatch.wait_for_result",
                        AsyncMock(return_value=result),
                    )
                )
                enter(patch("app.services.cluster.dispatch.record_failed_dispatch", AsyncMock()))
            else:
                enter(patch("app.services.cluster.dispatch.execute_workflow", return_value=result))
            await dispatch_workflow(
                workflow_id=uuid.uuid4(),
                nodes=[{"type": "set"}],
                edges=[],
                inputs={},
                test_run=test_run,
                execution_id=execution_id,
                actor_user_id=uuid.uuid4(),
            )
        return hook

    async def test_an_in_process_failure_runs_the_error_workflow(self) -> None:
        hook = await self._dispatch(_run_result())
        hook.assert_awaited_once()
        self.assertEqual(hook.await_args.kwargs["node_results"], NODE_RESULTS)

    async def test_an_offloaded_failure_runs_the_error_workflow(self) -> None:
        """The discussion #552 case: the run executed on another instance and failed."""
        offloaded = OffloadedRun(
            status="error",
            outputs={},
            workflow_id=str(uuid.uuid4()),
            failed_node=FAILED_NODE,
        )
        hook = await self._dispatch(offloaded, cluster_enabled=True, offloaded=True)
        hook.assert_awaited_once()
        self.assertEqual(hook.await_args.kwargs["node_results"], [FAILED_NODE])

    async def test_a_successful_run_does_not(self) -> None:
        hook = await self._dispatch(_run_result(status="success", node_results=[]))
        hook.assert_not_awaited()

    async def test_a_test_run_does_not(self) -> None:
        """Canvas runs are test runs, and the docs promise they never trigger it."""
        hook = await self._dispatch(_run_result(), test_run=True)
        hook.assert_not_awaited()

    async def test_a_run_no_instance_ever_executed_does_not(self) -> None:
        """The queue retired the row. Recovery may still run it, so this is not its failure."""
        hook = await self._dispatch(
            offloaded_error("retired before any instance executed it"),
            cluster_enabled=True,
            offloaded=True,
        )
        hook.assert_not_awaited()

    async def test_a_wait_that_timed_out_does_not(self) -> None:
        """The workflow may still be executing somewhere; its outcome is not known yet."""
        hook = await self._dispatch(
            offloaded_error("did not report a result in time", reported=True),
            cluster_enabled=True,
            offloaded=True,
        )
        hook.assert_not_awaited()


class OffloadedFailureContextTests(unittest.TestCase):
    """Without this the error workflow fires across instances with an empty context."""

    def test_the_failing_node_survives_the_instance_boundary(self) -> None:
        summary = summarize(_run_result(), uuid.uuid4())
        run = from_summary(summary)
        workflow = SimpleNamespace(id=uuid.uuid4(), name="Orders")

        context = build_error_context(workflow, failure_node_results(run), run_id="run-1")

        self.assertEqual(context["error"], "boom")
        self.assertEqual(context["errorNode"], "callApi")
        self.assertEqual(context["errorNodeType"], "http")

    def test_a_successful_run_carries_no_failed_node(self) -> None:
        summary = summarize(_run_result(status="success", node_results=[]), uuid.uuid4())
        self.assertIsNone(summary["failed_node"])
        self.assertEqual(failure_node_results(from_summary(summary)), [])

    def test_only_the_four_context_fields_cross_the_boundary(self) -> None:
        """node_results stay in the history row; only what build_error_context reads travels."""
        noisy = [{**FAILED_NODE, "output": {"blob": object()}}]
        self.assertEqual(
            failed_node_summary(noisy),
            {"status": "error", "error": "boom", "node_label": "callApi", "node_type": "http"},
        )

    def test_a_local_result_keeps_its_own_node_results(self) -> None:
        self.assertEqual(failure_node_results(_run_result()), NODE_RESULTS)


class SessionOwningEntryPointTests(unittest.IsolatedAsyncioTestCase):
    """run_error_workflow_for_run swallows everything, so its wiring needs proving."""

    def _patches(self, session: AsyncMock, workflows: list) -> ExitStack:
        maker = MagicMock()
        maker.return_value.__aenter__ = AsyncMock(return_value=session)
        maker.return_value.__aexit__ = AsyncMock(return_value=False)
        stack = ExitStack()
        module = "app.services.error_workflow_runner."
        stack.enter_context(patch(module + "async_session_maker", maker))
        stack.enter_context(patch(module + "_load_workflow", AsyncMock(side_effect=workflows)))
        stack.enter_context(
            patch(module + "collect_referenced_workflows", AsyncMock(return_value={}))
        )
        stack.enter_context(patch(module + "get_credentials_context", AsyncMock(return_value={})))
        stack.enter_context(
            patch(module + "get_global_variables_context", AsyncMock(return_value={}))
        )
        return stack

    async def test_it_executes_the_target_and_commits_its_own_session(self) -> None:
        source = SimpleNamespace(
            id=uuid.uuid4(), name="Orders", nodes=[{"type": "set"}], error_workflow_id=uuid.uuid4()
        )
        target = SimpleNamespace(id=source.error_workflow_id, nodes=[{"type": "set"}], edges=[])
        session = AsyncMock()
        session.add = MagicMock()
        executed = AsyncMock(
            return_value=SimpleNamespace(
                outputs={},
                node_results=[],
                status="success",
                execution_time_ms=1.0,
                history_written=False,
            )
        )
        with self._patches(session, [source, target]):
            with patch("app.services.error_workflow_runner.dispatch_workflow", executed):
                ran = await run_error_workflow_for_run(
                    workflow_id=source.id,
                    status="error",
                    node_results=NODE_RESULTS,
                    run_id="run-1",
                    actor_user_id=uuid.uuid4(),
                )

        self.assertTrue(ran)
        self.assertEqual(executed.await_args.kwargs["workflow_id"], target.id)
        context = executed.await_args.kwargs["inputs"]["body"]
        self.assertEqual(context["error"], "boom")
        self.assertEqual(context["errorNode"], "callApi")
        self.assertEqual(context["run_id"], "run-1")
        session.commit.assert_awaited_once()

    async def test_a_deleted_workflow_is_not_an_error(self) -> None:
        session = AsyncMock()
        with self._patches(session, [None]):
            ran = await run_error_workflow_for_run(
                workflow_id=uuid.uuid4(),
                status="error",
                node_results=NODE_RESULTS,
                run_id="run-1",
                actor_user_id=uuid.uuid4(),
            )
        self.assertFalse(ran)
        session.commit.assert_not_awaited()


class ErrorWorkflowPlacementTests(unittest.IsolatedAsyncioTestCase):
    """The target's own placement decides where it runs, not whoever caught the failure.

    Cron, IMAP, RabbitMQ, WebSocket and the Heym event dispatcher all start on every
    instance, and the cron leader may be a worker while main is down. Running a
    MAIN_ONLY error workflow there would send `sendEmail` out of the wrong IP and
    point `drive` at the wrong disk.
    """

    async def _run(self, dispatched: AsyncMock) -> AsyncMock:
        source = SimpleNamespace(
            id=uuid.uuid4(),
            name="Orders",
            nodes=[{"type": "set"}],
            error_workflow_id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
        )
        target = SimpleNamespace(
            id=source.error_workflow_id, nodes=[{"type": "sendEmail"}], edges=[]
        )
        session = AsyncMock()
        session.add = MagicMock()
        module = "app.services.error_workflow_runner."
        maker = MagicMock()
        maker.return_value.__aenter__ = AsyncMock(return_value=session)
        maker.return_value.__aexit__ = AsyncMock(return_value=False)
        with (
            patch(module + "async_session_maker", maker),
            patch(module + "_load_workflow", AsyncMock(side_effect=[source, target])),
            patch(module + "collect_referenced_workflows", AsyncMock(return_value={})),
            patch(module + "get_credentials_context", AsyncMock(return_value={})),
            patch(module + "get_global_variables_context", AsyncMock(return_value={})),
            patch(module + "dispatch_workflow", dispatched),
        ):
            await run_error_workflow_for_run(
                workflow_id=source.id,
                status="error",
                node_results=NODE_RESULTS,
                run_id="run-1",
                actor_user_id=uuid.uuid4(),
            )
        self.target = target
        return session

    def _dispatched(self, *, history_written: bool) -> AsyncMock:
        return AsyncMock(
            return_value=SimpleNamespace(
                outputs={},
                node_results=[],
                status="success",
                execution_time_ms=1.0,
                history_written=history_written,
            )
        )

    async def test_the_target_goes_through_dispatch_with_its_own_graph(self) -> None:
        """dispatch_workflow resolves placement from these nodes, so they must be the target's."""
        dispatched = self._dispatched(history_written=False)
        await self._run(dispatched)
        self.assertEqual(dispatched.await_args.kwargs["nodes"], self.target.nodes)
        self.assertEqual(dispatched.await_args.kwargs["trigger_source"], "ERROR_WORKFLOW")

    async def test_the_target_never_triggers_an_error_workflow_of_its_own(self) -> None:
        dispatched = self._dispatched(history_written=False)
        await self._run(dispatched)
        self.assertIs(dispatched.await_args.kwargs["run_error_workflow"], False)

    async def test_a_locally_run_target_is_written_to_history(self) -> None:
        session = await self._run(self._dispatched(history_written=False))
        session.add.assert_called_once()

    async def test_an_offloaded_target_is_not_written_to_history_twice(self) -> None:
        """The instance that ran it already wrote the row, keyed on the same execution id."""
        session = await self._run(self._dispatched(history_written=True))
        session.add.assert_not_called()


class SuppressedHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_suppressed_dispatch_does_not_fire_the_hook(self) -> None:
        hook = AsyncMock(return_value=True)
        with (
            patch("app.services.error_workflow_runner.run_error_workflow_for_run", hook),
            patch("app.services.cluster.dispatch.settings.cluster_enabled", False),
            patch(
                "app.services.cluster.dispatch.execute_workflow",
                return_value=_run_result(),
            ),
        ):
            await dispatch_workflow(
                workflow_id=uuid.uuid4(),
                nodes=[{"type": "set"}],
                edges=[],
                inputs={},
                execution_id=uuid.uuid4(),
                run_error_workflow=False,
            )
        hook.assert_not_awaited()


class StreamApiSeamTests(unittest.IsolatedAsyncioTestCase):
    """`/execute/stream` writes its history through persist_stream_execution_result."""

    async def _persist(self, *, status: str, test_run: bool) -> AsyncMock:
        hook = AsyncMock(return_value=True)
        db = AsyncMock()
        db.add = MagicMock()
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Orders",
            nodes=[],
            cache_ttl_seconds=None,
            error_workflow_id=uuid.uuid4(),
        )
        with (
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows._persist_global_variables_from_execution", AsyncMock()),
            patch("app.services.error_workflow_runner.maybe_run_error_workflow", hook),
        ):
            await persist_stream_execution_result(
                db,
                workflow=workflow,
                execution_id=uuid.uuid4(),
                enriched_inputs={"body": {}},
                trigger_source="API",
                raw_body={},
                query_params={},
                workflow_cache={},
                credentials_owner_id=uuid.uuid4(),
                final_result={
                    "status": status,
                    "outputs": {},
                    "execution_time_ms": 3.0,
                    "node_results": NODE_RESULTS,
                },
                was_cancelled=False,
                test_run=test_run,
            )
        return hook

    async def test_a_failed_sse_api_run_runs_the_error_workflow(self) -> None:
        hook = await self._persist(status="error", test_run=False)
        hook.assert_awaited_once()

    async def test_a_canvas_test_run_does_not(self) -> None:
        hook = await self._persist(status="error", test_run=True)
        hook.assert_not_awaited()

    async def test_a_successful_sse_api_run_does_not(self) -> None:
        hook = await self._persist(status="success", test_run=False)
        hook.assert_not_awaited()


class PortalSeamTests(unittest.IsolatedAsyncioTestCase):
    """The portal runs in process on every install, so it never reached the hook at all."""

    async def _portal_execute(self, status: str) -> AsyncMock:
        hook = AsyncMock(return_value=True)
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Support portal",
            nodes=[{"type": "set"}],
            edges=[],
            error_workflow_id=uuid.uuid4(),
            cache_ttl_seconds=None,
        )
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            ]
        )
        request = SimpleNamespace(headers={}, query_params={})
        execute_data = SimpleNamespace(inputs={}, conversation_history=[], conversation_id=None)
        result = _run_result(status=status, node_results=NODE_RESULTS if status == "error" else [])

        with (
            patch("app.api.portal.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.portal.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.portal.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.portal.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.portal._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.portal.execute_workflow", return_value=result),
            patch("app.services.error_workflow_runner.maybe_run_error_workflow", hook),
        ):
            await portal_execute(
                slug="support",
                execute_data=execute_data,  # type: ignore[arg-type]
                request=request,  # type: ignore[arg-type]
                db=db,
            )
        return hook

    async def test_a_failed_portal_run_runs_the_error_workflow(self) -> None:
        hook = await self._portal_execute("error")
        hook.assert_awaited_once()

    async def test_a_successful_portal_run_does_not(self) -> None:
        hook = await self._portal_execute("success")
        hook.assert_not_awaited()
