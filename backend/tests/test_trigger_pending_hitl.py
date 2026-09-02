"""Every background trigger must mint the pause, not just write a pending row.

A workflow that pauses for human review is stranded unless its HITL request is
created: no public token, no review link, no notification branch, and no
snapshot to resume from. Cron already did this; these triggers did not, so a run
started from Slack, Telegram, a queue or the cluster's run queue sat at pending
forever whether or not a cluster was involved.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def _result(status: str = "pending", *, kind: str | None = None) -> SimpleNamespace:
    pending: dict | None = None
    if status == "pending":
        pending = {"summary": "Approve", "draft_text": "draft"}
        if kind:
            pending["kind"] = kind
    return SimpleNamespace(
        status=status,
        outputs={"Agent": {"text": "draft"}},
        node_results=[],
        execution_time_ms=5.0,
        sub_workflow_executions=[],
        pending_review=pending,
        resume_snapshot={"paused_node_id": "a", "paused_node_label": "Agent"} if pending else None,
    )


class PendingPersistGuardTests(unittest.TestCase):
    def test_a_local_pause_must_be_persisted_by_the_caller(self) -> None:
        from app.services.pending_execution import needs_local_pending_persist

        self.assertTrue(needs_local_pending_persist(_result()))

    def test_an_offloaded_pause_was_already_persisted(self) -> None:
        from app.services.pending_execution import needs_local_pending_persist

        offloaded = _result()
        offloaded.history_written = True
        self.assertFalse(needs_local_pending_persist(offloaded))

    def test_a_finished_run_is_never_a_pending_persist(self) -> None:
        from app.services.pending_execution import needs_local_pending_persist

        self.assertFalse(needs_local_pending_persist(_result("success")))


class PendingMintRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def _mint(self, result: SimpleNamespace, **kwargs: object) -> dict[str, object]:
        from app.services.pending_execution import persist_pending_execution

        entry = SimpleNamespace(inputs={}, outputs={}, node_results=[])
        request = SimpleNamespace(execution_snapshot={})
        hitl = AsyncMock(return_value=(entry, request))
        codex = AsyncMock(return_value=(entry, request))
        with (
            patch("app.services.hitl_service.persist_pending_hitl_execution", hitl),
            patch(
                "app.services.codex_followup_service.persist_pending_codex_followup_execution",
                codex,
            ),
        ):
            await persist_pending_execution(
                db=MagicMock(),
                workflow=SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4(), name="W"),
                enriched_inputs={},
                execution_result=result,
                trigger_source="Slack",
                credentials_owner_id=uuid.uuid4(),
                trace_user_id=None,
                public_base_url="https://heym.test",
                **kwargs,  # type: ignore[arg-type]
            )
        return {"hitl": hitl, "codex": codex, "entry": entry, "request": request}

    async def test_a_human_review_pause_goes_to_the_hitl_persister(self) -> None:
        minted = await self._mint(_result())
        minted["hitl"].assert_awaited_once()
        minted["codex"].assert_not_awaited()

    async def test_a_codex_pause_goes_to_the_follow_up_persister(self) -> None:
        minted = await self._mint(_result(kind="codex"))
        minted["codex"].assert_awaited_once()
        minted["hitl"].assert_not_awaited()

    async def test_a_request_secret_is_redacted_before_it_reaches_the_pause(self) -> None:
        """Discord carries an interaction token; it must not land in the request row."""
        result = _result()
        result.outputs = {"Agent": {"text": "tok-abc"}}
        result.pending_review = {"summary": "tok-abc", "draft_text": "tok-abc"}
        result.resume_snapshot = {
            "paused_node_id": "a",
            "paused_node_label": "Agent",
            "t": "tok-abc",
        }

        def redact(value: object) -> object:
            if isinstance(value, str):
                return value.replace("tok-abc", "[redacted]")
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items()}
            if isinstance(value, list):
                return [redact(v) for v in value]
            return value

        minted = await self._mint(result, redact=redact)
        passed = minted["hitl"].await_args.kwargs["execution_result"]
        self.assertNotIn("tok-abc", str(passed.pending_review))
        self.assertNotIn("tok-abc", str(passed.resume_snapshot))
        self.assertNotIn("tok-abc", str(passed.outputs))


class TriggerCallSiteCoverageTests(unittest.TestCase):
    """A trigger that can reach a paused run must know how to mint it.

    This is the guard that caught the original bug: every one of these modules
    dispatched a run and then wrote its status straight into history.
    """

    TRIGGERS = (
        "app/api/telegram.py",
        "app/api/slack.py",
        "app/api/discord.py",
        "app/api/mcp.py",
        "app/api/mcp_servers.py",
        "app/services/imap_trigger_service.py",
        "app/services/rabbitmq_consumer.py",
        "app/services/websocket_trigger_service.py",
        "app/services/heym_event_dispatcher.py",
        "app/services/dashboard_data.py",
        "app/services/cluster/dispatch.py",
    )

    def test_every_dispatching_trigger_handles_a_pause(self) -> None:
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        missing = []
        for rel in self.TRIGGERS:
            source = (root / rel).read_text()
            if "persist_pending" not in source:
                missing.append(rel)
        self.assertEqual(missing, [], f"trigger(s) with no pause branch: {missing}")


if __name__ == "__main__":
    unittest.main()
