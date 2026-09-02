"""A run that pauses for human review must be minted where it executed.

Without this the claiming instance writes a bare 'pending' history row and
nothing else: no HITL request, no public token, no review URL, and no
notification branch. The queue row is marked done, so nothing retries it and the
run sits at pending forever. The waiting caller cannot repair it either - it only
ever receives the summary, which carries none of the pause metadata.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def _workflow() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="Review run",
        nodes=[{"id": "agent", "type": "agent", "data": {"humanInTheLoop": True}}],
        edges=[],
    )


def _row(workflow: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        execution_id=uuid.uuid4(),
        workflow_id=workflow.id,
        inputs={"triggered_by": "cron"},
        trigger_source="schedule",
        actor_user_id=workflow.owner_id,
        credentials_owner_id=workflow.owner_id,
        test_run=False,
        timeout_seconds=None,
        return_on_chart_output=False,
    )


def _pending_result(kind: str | None = None) -> SimpleNamespace:
    pending: dict = {"summary": "Approve this", "draft_text": "draft"}
    if kind:
        pending["kind"] = kind
    return SimpleNamespace(
        status="pending",
        outputs={"Agent": {"text": "draft"}},
        node_results=[],
        execution_time_ms=12.0,
        sub_workflow_executions=[],
        pending_review=pending,
        resume_snapshot={"paused_node_id": "agent", "paused_node_label": "Agent"},
    )


class ClaimedPendingRunTests(unittest.IsolatedAsyncioTestCase):
    async def _claim(self, result: SimpleNamespace) -> dict[str, object]:
        from app.services.cluster.dispatch import RunQueueWorker

        workflow = _workflow()
        row = _row(workflow)

        db = MagicMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow))
        db.get = AsyncMock(return_value=workflow)
        db.commit = AsyncMock()
        session_factory = MagicMock()
        session_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        history_entry = SimpleNamespace(id=row.execution_id)

        def _mint(**kwargs: object) -> tuple[SimpleNamespace, SimpleNamespace]:
            # The real helper rewrites outputs with the review URL in place.
            result.outputs = {"Agent": {"reviewUrl": "https://heym.test/review/tok"}}
            return history_entry, SimpleNamespace(id=uuid.uuid4())

        hitl = AsyncMock(side_effect=_mint)
        codex = AsyncMock(side_effect=_mint)
        terminal = AsyncMock()
        complete = AsyncMock()

        with (
            patch("app.db.session.async_session_maker", session_factory),
            patch("app.services.cluster.run_history.async_session_maker", session_factory),
            patch("app.api.workflows.get_credentials_context", new=AsyncMock(return_value={})),
            patch("app.api.workflows.collect_referenced_workflows", new=AsyncMock(return_value={})),
            patch(
                "app.api.workflows._persist_global_variables_from_execution", new=AsyncMock()
            ) as globals_writer,
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                new=AsyncMock(return_value={}),
            ),
            patch("app.services.cluster.dispatch.register_execution"),
            patch(
                "app.services.cluster.dispatch.asyncio.to_thread",
                new=AsyncMock(return_value=result),
            ),
            patch("app.services.cluster.dispatch.persist_run_history", terminal),
            patch("app.services.hitl_service.persist_pending_hitl_execution", hitl),
            patch(
                "app.services.codex_followup_service.persist_pending_codex_followup_execution",
                codex,
            ),
            patch(
                "app.services.hitl_service.build_default_public_base_url",
                MagicMock(return_value="https://heym.test"),
            ),
            patch(
                "app.services.cluster.run_history.upsert_workflow_analytics_snapshot",
                new=AsyncMock(),
            ),
            patch("app.services.cluster.dispatch.run_queue.complete", complete),
            patch("app.services.cluster.dispatch.run_queue.notify_done", new=AsyncMock()),
        ):
            await RunQueueWorker()._execute_claimed(row)  # type: ignore[arg-type]

        return {
            "hitl": hitl,
            "codex": codex,
            "terminal": terminal,
            "complete": complete,
            "workflow": workflow,
            "row": row,
            "globals_writer": globals_writer,
            "history_entry": history_entry,
        }

    async def test_a_paused_run_mints_its_review_request(self) -> None:
        claimed = self._claim(_pending_result())
        captured = await claimed
        captured["hitl"].assert_awaited_once()
        kwargs = captured["hitl"].await_args.kwargs
        self.assertEqual(kwargs["history_entry_id"], captured["row"].execution_id)
        self.assertEqual(kwargs["public_base_url"], "https://heym.test")
        self.assertEqual(kwargs["trigger_source"], "schedule")
        self.assertEqual(kwargs["credentials_owner_id"], captured["workflow"].owner_id)

    async def test_a_paused_run_does_not_also_write_a_terminal_history_row(self) -> None:
        captured = await self._claim(_pending_result())
        captured["terminal"].assert_not_awaited()

    async def test_the_review_url_reaches_the_waiting_caller(self) -> None:
        captured = await self._claim(_pending_result())
        summary = captured["complete"].await_args.kwargs["result"]
        self.assertEqual(summary["status"], "pending")
        self.assertEqual(summary["outputs"]["Agent"]["reviewUrl"], "https://heym.test/review/tok")

    async def test_a_paused_codex_run_mints_a_follow_up_instead(self) -> None:
        captured = await self._claim(_pending_result(kind="codex"))
        captured["codex"].assert_awaited_once()
        captured["hitl"].assert_not_awaited()

    async def test_a_paused_run_defers_global_variable_writes_to_the_resume(self) -> None:
        captured = await self._claim(_pending_result())
        captured["globals_writer"].assert_not_awaited()

    async def test_a_finished_run_still_takes_the_terminal_path(self) -> None:
        finished = SimpleNamespace(
            status="success",
            outputs={"Agent": {"text": "done"}},
            node_results=[],
            execution_time_ms=3.0,
            sub_workflow_executions=[],
            pending_review=None,
            resume_snapshot=None,
        )
        captured = await self._claim(finished)
        captured["terminal"].assert_awaited_once()
        captured["hitl"].assert_not_awaited()
        captured["codex"].assert_not_awaited()


class OffloadedRunShapeTests(unittest.TestCase):
    """The execute endpoint reads these off whatever dispatch returns."""

    def test_an_offloaded_run_carries_the_workflow_id(self) -> None:
        from app.services.cluster.run_history import from_summary

        run = from_summary(
            {
                "execution_id": str(uuid.uuid4()),
                "workflow_id": "wf-1",
                "status": "pending",
                "outputs": {},
                "execution_time_ms": 1.0,
            }
        )
        self.assertEqual(run.workflow_id, "wf-1")

    def test_a_run_summary_carries_the_workflow_id(self) -> None:
        from app.services.cluster.run_history import summarize

        workflow_id = uuid.uuid4()
        summary = summarize(
            SimpleNamespace(
                workflow_id=workflow_id, status="success", outputs={}, execution_time_ms=1.0
            ),
            uuid.uuid4(),
        )
        self.assertEqual(summary["workflow_id"], str(workflow_id))


if __name__ == "__main__":
    unittest.main()
