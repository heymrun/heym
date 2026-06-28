import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.error_workflow_runner import (
    build_error_context,
    maybe_run_error_workflow,
    should_run_error_workflow,
)


def _wf(error_workflow_id=None, nodes=None):
    class _W:
        pass

    w = _W()
    w.id = uuid.uuid4()
    w.name = "My WF"
    w.error_workflow_id = error_workflow_id
    w.nodes = nodes or []
    return w


class TestShouldRunErrorWorkflow(unittest.TestCase):
    def test_runs_when_error_no_handler_and_target_set(self) -> None:
        wf = _wf(error_workflow_id=uuid.uuid4(), nodes=[{"type": "httpRequest"}])
        self.assertTrue(should_run_error_workflow(wf, "error"))

    def test_skips_when_status_not_error(self) -> None:
        wf = _wf(error_workflow_id=uuid.uuid4(), nodes=[{"type": "httpRequest"}])
        self.assertFalse(should_run_error_workflow(wf, "success"))

    def test_skips_when_no_error_workflow_id(self) -> None:
        wf = _wf(error_workflow_id=None, nodes=[{"type": "httpRequest"}])
        self.assertFalse(should_run_error_workflow(wf, "error"))

    def test_skips_when_local_error_handler_node_present(self) -> None:
        wf = _wf(
            error_workflow_id=uuid.uuid4(),
            nodes=[{"type": "httpRequest"}, {"type": "errorHandler"}],
        )
        self.assertFalse(should_run_error_workflow(wf, "error"))


class TestBuildErrorContext(unittest.TestCase):
    def test_extracts_failed_node_from_results(self) -> None:
        wf = _wf()
        node_results = [
            {"node_label": "ok", "node_type": "textInput", "status": "success"},
            {
                "node_label": "callApi",
                "node_type": "httpRequest",
                "status": "error",
                "error": "boom",
            },
        ]
        ctx = build_error_context(wf, node_results, run_id="run-1")
        self.assertEqual(ctx["workflow_name"], "My WF")
        self.assertEqual(ctx["run_id"], "run-1")
        self.assertEqual(ctx["errorNode"], "callApi")
        self.assertEqual(ctx["errorNodeType"], "httpRequest")
        self.assertEqual(ctx["error"], "boom")
        self.assertIn("timestamp", ctx)


class TestRunErrorWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_guard_false(self) -> None:
        wf = _wf(error_workflow_id=None, nodes=[])
        db = AsyncMock()
        with patch("app.services.error_workflow_runner.execute_workflow") as exec_mock:
            ran = await maybe_run_error_workflow(
                db,
                wf,
                status="success",
                node_results=[],
                run_id="r",
                actor_user_id=uuid.uuid4(),
            )
        self.assertFalse(ran)
        exec_mock.assert_not_called()

    async def test_runs_target_when_guard_true(self) -> None:
        target_id = uuid.uuid4()
        wf = _wf(error_workflow_id=target_id, nodes=[{"type": "httpRequest"}])

        target = MagicMock()
        target.id = target_id
        target.nodes = [{"id": "n1", "type": "output", "data": {"label": "out"}}]
        target.edges = []
        target.owner_id = uuid.uuid4()

        db = AsyncMock()
        db.add = MagicMock()
        with (
            patch(
                "app.services.error_workflow_runner._load_workflow",
                new=AsyncMock(return_value=target),
            ),
            patch(
                "app.services.error_workflow_runner.collect_referenced_workflows",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.error_workflow_runner.get_credentials_context",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.error_workflow_runner.get_global_variables_context",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.error_workflow_runner.asyncio.to_thread", new=AsyncMock()
            ) as to_thread_mock,
        ):
            ran = await maybe_run_error_workflow(
                db,
                wf,
                status="error",
                node_results=[
                    {
                        "status": "error",
                        "error": "boom",
                        "node_label": "x",
                        "node_type": "httpRequest",
                    }
                ],
                run_id="r",
                actor_user_id=uuid.uuid4(),
            )

        self.assertTrue(ran)
        to_thread_mock.assert_awaited()

    async def test_swallows_target_failure(self) -> None:
        target_id = uuid.uuid4()
        wf = _wf(error_workflow_id=target_id, nodes=[{"type": "httpRequest"}])
        db = AsyncMock()
        with patch(
            "app.services.error_workflow_runner._load_workflow",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ):
            ran = await maybe_run_error_workflow(
                db,
                wf,
                status="error",
                node_results=[{"status": "error"}],
                run_id="r",
                actor_user_id=uuid.uuid4(),
            )
        self.assertFalse(ran)


if __name__ == "__main__":
    unittest.main()
