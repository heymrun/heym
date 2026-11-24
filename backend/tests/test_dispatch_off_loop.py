"""Trigger runs execute off the application loop.

A run executed on the loop thread stops the process serving requests for as long as it
runs. With a Heym node that sends a chat message it never ends: the turn is submitted to
the loop the run is holding, so the run and the loop wait on each other.
"""

import ast
import asyncio
import logging
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.models import ExecutionHistory
from app.services import app_loop
from app.services.cluster import dispatch as dispatch_module
from app.services.heym_event_dispatcher import HeymEventDispatcher
from app.services.trigger_run_dispatch import run_trigger_workflow

APP_DIR = Path(__file__).resolve().parents[1] / "app"

TRIGGER_CALL_SITES = {
    "api/discord.py",
    "api/slack.py",
    "api/telegram.py",
    "services/heym_event_dispatcher.py",
    "services/rabbitmq_consumer.py",
    "services/trigger_run_dispatch.py",
    "services/websocket_trigger_service.py",
}

# Bounds the run on a regression: without it a deadlocked run would hang the test.
RUN_TIMEOUT_SECONDS = 3
CHAT_TURN_SECONDS = 0.3
MAX_LOOP_GAP_SECONDS = 0.5


def _dispatch_calls() -> list[tuple[str, int, ast.Call]]:
    calls: list[tuple[str, int, ast.Call]] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Await) or not isinstance(node.value, ast.Call):
                continue
            func = node.value.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "dispatch_workflow":
                calls.append((path.relative_to(APP_DIR).as_posix(), node.lineno, node.value))
    return calls


def _runs_in_thread(call: ast.Call) -> bool:
    return any(
        keyword.arg == "run_in_thread"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in call.keywords
    )


class DispatchCallSitesTests(unittest.TestCase):
    def test_every_dispatch_runs_off_the_application_loop(self) -> None:
        on_loop = [
            f"app/{path}:{line}"
            for path, line, call in _dispatch_calls()
            if not _runs_in_thread(call)
        ]
        self.assertEqual(on_loop, [], "these dispatch_workflow calls run on the loop thread")

    def test_the_scan_sees_every_trigger_call_site(self) -> None:
        found = {path for path, _line, _call in _dispatch_calls()}
        self.assertLessEqual(TRIGGER_CALL_SITES, found)


def _chat_workflow() -> SimpleNamespace:
    """Heym Trigger -> Heym node Send Chat Message, with the default switches."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="Chat on event",
        nodes=[
            {
                "id": "t",
                "type": "heymTrigger",
                "position": {"x": 0, "y": 0},
                "data": {"label": "event", "eventNames": ["workflow.updated"]},
            },
            {
                "id": "h",
                "type": "heym",
                "position": {"x": 300, "y": 0},
                "data": {
                    "label": "chat",
                    "heymOperation": "sendChatMessage",
                    "heymChatMessage": "A workflow changed",
                },
            },
        ],
        edges=[{"id": "e1", "source": "t", "target": "h"}],
        concurrency_limit=None,
        workflow_timeout_seconds=RUN_TIMEOUT_SECONDS,
    )


async def _fake_chat_turn(_request: object) -> dict:
    await asyncio.sleep(CHAT_TURN_SECONDS)
    return {
        "conversation_id": str(uuid.uuid4()),
        "status": "completed",
        "reply": "Noted.",
        "tool_names": [],
        "verified": False,
        "workflow_links": [],
        "eval_suite_links": [],
        "credential_form_urls": [],
    }


class TriggerRunWithHeymChatTests(unittest.IsolatedAsyncioTestCase):
    """The real trigger entry point, dispatch, executor and Heym node; only the turn is fake."""

    async def asyncSetUp(self) -> None:
        previous = app_loop.get_app_loop()
        app_loop.set_app_loop(asyncio.get_running_loop())
        self.addCleanup(app_loop.set_app_loop, previous)

        session_cm = MagicMock()
        session_cm.__enter__.return_value = MagicMock()
        session_cm.__exit__.return_value = False
        for active in (
            patch.object(dispatch_module.settings, "cluster_enabled", False),
            # A failed run would look its error workflow up in the database.
            patch.object(dispatch_module, "run_error_workflow_for_failed_run", AsyncMock()),
            patch("app.db.session.SessionLocal", MagicMock(return_value=session_cm)),
            patch(
                "app.services.heym_chat_node.send_and_wait",
                new=MagicMock(side_effect=_fake_chat_turn),
            ),
        ):
            active.start()
            self.addCleanup(active.stop)

        self.workflow = _chat_workflow()
        self.added: list = []

    def _session_maker(self) -> AsyncMock:
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(scalar_one_or_none=lambda: self.workflow)
            ),
            add=self.added.append,
            commit=AsyncMock(),
        )
        session = AsyncMock()
        session.__aenter__.return_value = db
        session.__aexit__.return_value = None
        return session

    async def _largest_loop_gap_while(self, work: object) -> float:
        """Run ``work`` and return the longest the loop went without serving a ticker."""
        gaps: list[float] = []
        done = asyncio.Event()

        async def ticker() -> None:
            last = time.monotonic()
            while not done.is_set():
                await asyncio.sleep(0.01)
                now = time.monotonic()
                gaps.append(now - last)
                last = now

        task = asyncio.create_task(ticker())
        try:
            await work
        finally:
            done.set()
            await task
        return max(gaps, default=float("inf"))

    def _history_row(self) -> ExecutionHistory:
        rows = [row for row in self.added if isinstance(row, ExecutionHistory)]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def _assert_chat_completed(self, row: ExecutionHistory, gap: float) -> None:
        self.assertEqual(row.status, "success", row.outputs)
        chat = next(result for result in row.node_results if result.get("node_id") == "h")
        self.assertEqual(chat["output"]["status"], "completed")
        self.assertEqual(chat["output"]["reply"], "Noted.")
        self.assertLess(gap, MAX_LOOP_GAP_SECONDS)

    async def test_a_polled_trigger_run_sends_its_chat_message_and_the_loop_keeps_serving(
        self,
    ) -> None:
        module = "app.services.trigger_run_dispatch"
        for active in (
            patch(f"{module}.async_session_maker", self._session_maker),
            patch(f"{module}.collect_referenced_workflows", AsyncMock(return_value={})),
            patch(f"{module}.get_credentials_context", AsyncMock(return_value={})),
            patch(f"{module}.get_global_variables_context", AsyncMock(return_value={})),
            patch(f"{module}.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(f"{module}._persist_global_variables_from_execution", AsyncMock()),
        ):
            active.start()
            self.addCleanup(active.stop)

        gap = await self._largest_loop_gap_while(
            run_trigger_workflow(
                workflow_id=self.workflow.id,
                inputs={"triggered_by": "imap", "trigger_node_id": "t"},
                trigger_source="imap",
                trigger_label="IMAP trigger",
                log=logging.getLogger(__name__),
            )
        )

        self._assert_chat_completed(self._history_row(), gap)

    async def test_a_heym_event_run_sends_its_chat_message_and_the_loop_keeps_serving(
        self,
    ) -> None:
        for active in (
            patch("app.services.heym_event_dispatcher.async_session_maker", self._session_maker),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows._persist_global_variables_from_execution", AsyncMock()),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch("app.api.analytics.upsert_workflow_analytics_snapshot", AsyncMock()),
        ):
            active.start()
            self.addCleanup(active.stop)

        gap = await self._largest_loop_gap_while(
            HeymEventDispatcher()._run_workflow(
                self.workflow, "t", {"triggered_by": "heym_event", "events": [], "count": 0}
            )
        )

        self._assert_chat_completed(self._history_row(), gap)


if __name__ == "__main__":
    unittest.main()
