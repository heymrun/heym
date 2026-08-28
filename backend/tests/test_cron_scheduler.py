import threading
import unittest
import uuid
from concurrent.futures import Future
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.db.models import ExecutionHistory
from app.services.cron_scheduler import CronScheduler
from app.services.workflow_executor import (
    DotList,
    ExecutionResult,
    NodeResult,
    SubWorkflowExecution,
)


class CronSchedulerExecutionHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_workflow_persists_cron_trigger_source(self) -> None:
        scheduler = CronScheduler()
        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        sub_workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=owner_id,
            name="Main workflow",
            nodes=[],
            edges=[],
        )

        added_rows: list[object] = []

        def add_row(row: object) -> None:
            added_rows.append(row)

        db = SimpleNamespace(
            add=add_row,
            commit=AsyncMock(),
        )
        execution_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"ok": True},
            execution_time_ms=12.5,
            node_results=[],
            sub_workflow_executions=[
                SubWorkflowExecution(
                    workflow_id=str(sub_workflow_id),
                    inputs={"source": "main"},
                    outputs={"done": True},
                    status="success",
                    execution_time_ms=4.0,
                    node_results=[],
                    workflow_name="Child workflow",
                )
            ],
        )

        with (
            patch(
                "app.services.cron_scheduler.collect_referenced_workflows",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.cron_scheduler.get_credentials_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.cron_scheduler.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch("app.services.cluster.dispatch.execute_workflow", return_value=execution_result),
            patch(
                "app.services.cron_scheduler.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ),
            patch(
                "app.services.cron_scheduler._persist_global_variables_from_execution",
                AsyncMock(),
            ),
        ):
            await scheduler._execute_workflow(db, workflow)

        history_rows = [row for row in added_rows if isinstance(row, ExecutionHistory)]
        self.assertEqual(len(history_rows), 2)
        parent = next(r for r in history_rows if r.workflow_id == workflow_id)
        child = next(r for r in history_rows if r.workflow_id == sub_workflow_id)
        self.assertEqual(parent.trigger_source, "cron")
        self.assertEqual(child.trigger_source, "SUB_WORKFLOW")

    async def test_execute_workflow_joins_allow_downstream_before_history(self) -> None:
        scheduler = CronScheduler()
        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=owner_id,
            name="Cron allow downstream",
            nodes=[],
            edges=[],
        )

        added_rows: list[object] = []

        def add_row(row: object) -> None:
            added_rows.append(row)

        db = SimpleNamespace(
            add=add_row,
            commit=AsyncMock(),
        )

        completed_future: Future = Future()
        completed_future.set_result(None)
        execution_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"output": {"text": "ack"}},
            execution_time_ms=1.0,
            node_results=[
                {
                    "node_id": "output",
                    "node_label": "output",
                    "node_type": "output",
                    "status": "success",
                    "output": {"text": "ack"},
                    "execution_time_ms": 1.0,
                    "error": None,
                }
            ],
            sub_workflow_executions=[],
            _allow_downstream_pending=[completed_future],
            _allow_downstream_node_results=[
                NodeResult(
                    node_id="execute",
                    node_label="execute",
                    node_type="execute",
                    status="success",
                    output={"items": DotList(["done"])},
                    execution_time_ms=2.0,
                )
            ],
        )

        with (
            patch(
                "app.services.cron_scheduler.collect_referenced_workflows",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.cron_scheduler.get_credentials_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.cron_scheduler.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch("app.services.cluster.dispatch.execute_workflow", return_value=execution_result),
            patch(
                "app.services.cron_scheduler.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ),
            patch(
                "app.services.cron_scheduler._persist_global_variables_from_execution",
                AsyncMock(),
            ),
        ):
            await scheduler._execute_workflow(db, workflow)

        history_rows = [row for row in added_rows if isinstance(row, ExecutionHistory)]
        self.assertEqual(len(history_rows), 1)
        parent = history_rows[0]
        self.assertFalse(execution_result.allow_downstream_pending)
        self.assertEqual(
            [node_result["node_id"] for node_result in parent.node_results],
            ["output", "execute"],
        )
        self.assertEqual(parent.node_results[1]["output"], {"items": ["done"]})

    async def test_execute_workflow_persists_pending_hitl_with_review_url_context(self) -> None:
        scheduler = CronScheduler()
        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=owner_id,
            name="Cron HITL workflow",
            nodes=[],
            edges=[],
        )

        added_rows: list[object] = []

        def add_row(row: object) -> None:
            added_rows.append(row)

        db = SimpleNamespace(
            add=add_row,
            commit=AsyncMock(),
        )
        execution_result = ExecutionResult(
            workflow_id=workflow_id,
            status="pending",
            outputs={
                "Reviewer": {
                    "decision": None,
                    "reviewUrl": None,
                    "requestId": None,
                }
            },
            execution_time_ms=5.0,
            node_results=[
                {
                    "node_id": "agent",
                    "node_label": "Reviewer",
                    "node_type": "agent",
                    "status": "pending",
                    "output": {
                        "decision": None,
                        "reviewUrl": None,
                        "requestId": None,
                    },
                    "execution_time_ms": 5.0,
                    "error": None,
                }
            ],
            pending_review={"summary": "Review required", "draft_text": "Draft"},
            resume_snapshot={"paused_node_id": "agent", "paused_node_label": "Reviewer"},
        )

        persisted_history = SimpleNamespace(id=uuid.uuid4())
        persisted_request = SimpleNamespace(id=uuid.uuid4())
        persist_pending_hitl_execution = AsyncMock(
            return_value=(persisted_history, persisted_request)
        )

        with (
            patch(
                "app.services.cron_scheduler.collect_referenced_workflows",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.cron_scheduler.get_credentials_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.cron_scheduler.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch("app.services.cluster.dispatch.execute_workflow", return_value=execution_result),
            patch(
                "app.services.cron_scheduler.persist_pending_hitl_execution",
                persist_pending_hitl_execution,
            ),
            patch(
                "app.services.cron_scheduler.build_default_public_base_url",
                return_value="https://app.example.com",
            ),
            patch(
                "app.services.cron_scheduler.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ),
            patch(
                "app.services.cron_scheduler._persist_global_variables_from_execution",
                AsyncMock(),
            ),
        ):
            await scheduler._execute_workflow(db, workflow)

        persist_pending_hitl_execution.assert_awaited_once()
        persist_kwargs = persist_pending_hitl_execution.await_args.kwargs
        self.assertIs(persist_kwargs["execution_result"], execution_result)
        self.assertEqual(persist_kwargs["workflow"], workflow)
        self.assertEqual(persist_kwargs["enriched_inputs"], {"triggered_by": "cron"})
        self.assertEqual(persist_kwargs["trigger_source"], "cron")
        self.assertEqual(persist_kwargs["credentials_owner_id"], owner_id)
        self.assertEqual(persist_kwargs["trace_user_id"], owner_id)
        self.assertEqual(persist_kwargs["public_base_url"], "https://app.example.com")
        self.assertEqual(added_rows, [])
        db.commit.assert_awaited_once()


class CronDueSlotTests(unittest.TestCase):
    """Slot selection: which scheduled slot (if any) a scheduler pass should run."""

    EXPR = "0 9 * * *"
    NODE_KEY = "wf_n1"
    TZ = ZoneInfo("Europe/Berlin")

    def _at(self, hour: int, minute: int = 0, second: int = 0) -> datetime:
        return datetime(2026, 8, 4, hour, minute, second, tzinfo=self.TZ)

    def test_returns_slot_when_pass_runs_just_after_it(self) -> None:
        scheduler = CronScheduler()

        slot = scheduler._due_slot(self.EXPR, self._at(9, 0, 12), self.NODE_KEY)

        self.assertEqual(slot, self._at(9))

    def test_returns_slot_on_first_pass_of_a_fresh_process(self) -> None:
        """A restart must not silently swallow a slot that just came due."""
        scheduler = CronScheduler()
        self.assertEqual(scheduler._last_check, {})

        slot = scheduler._due_slot(self.EXPR, self._at(9, 2), self.NODE_KEY)

        self.assertEqual(slot, self._at(9))

    def test_skips_slot_older_than_the_misfire_grace_window(self) -> None:
        """The leadership-handoff case: a worker with stale state must not backfill."""
        scheduler = CronScheduler()
        scheduler._last_check[self.NODE_KEY] = self._at(3)

        slot = scheduler._due_slot(self.EXPR, self._at(18, 14, 38), self.NODE_KEY)

        self.assertIsNone(slot)

    def test_skips_slot_this_process_already_handled(self) -> None:
        scheduler = CronScheduler()
        scheduler.mark_slot_handled(self.NODE_KEY, self._at(9))

        slot = scheduler._due_slot(self.EXPR, self._at(9, 0, 42), self.NODE_KEY)

        self.assertIsNone(slot)

    def test_returns_none_for_invalid_expression(self) -> None:
        scheduler = CronScheduler()

        self.assertIsNone(scheduler._due_slot("not a cron", self._at(9), self.NODE_KEY))


class CronSlotClaimTests(unittest.IsolatedAsyncioTestCase):
    """A due slot runs at most once across all workers, whoever wins the claim."""

    def _scheduler_with_one_cron_workflow(self) -> tuple[CronScheduler, SimpleNamespace]:
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Cron workflow",
            # Every minute, so the previous slot is always freshly due.
            nodes=[{"id": "n1", "type": "cron", "data": {"cronExpression": "* * * * *"}}],
            edges=[],
        )
        scheduler = CronScheduler()
        return scheduler, workflow

    async def _run_pass(
        self, scheduler: CronScheduler, workflow: SimpleNamespace, *, claimed: bool
    ) -> AsyncMock:
        execute = AsyncMock()
        claim = AsyncMock(return_value=claimed)
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.__aexit__.return_value = False

        with (
            patch("app.services.cron_scheduler.async_session_maker", return_value=session),
            patch.object(
                CronScheduler, "_get_workflows_with_cron", AsyncMock(return_value=[workflow])
            ),
            patch.object(CronScheduler, "_execute_workflow", execute),
            patch("app.services.cron_scheduler.claim_cron_slot", claim),
        ):
            await scheduler._check_and_execute()
        self.claim = claim
        return execute

    async def test_executes_when_this_worker_wins_the_slot_claim(self) -> None:
        scheduler, workflow = self._scheduler_with_one_cron_workflow()

        execute = await self._run_pass(scheduler, workflow, claimed=True)

        execute.assert_awaited_once()
        claim_kwargs = self.claim.await_args.kwargs
        self.assertEqual(claim_kwargs["workflow_id"], workflow.id)
        self.assertEqual(claim_kwargs["node_id"], "n1")
        slot = claim_kwargs["slot_at"]
        self.assertEqual(slot.second, 0)
        self.assertEqual(slot.microsecond, 0)
        self.assertLess((datetime.now(slot.tzinfo) - slot).total_seconds(), 120)

    async def test_skips_execution_when_another_worker_claimed_the_slot(self) -> None:
        scheduler, workflow = self._scheduler_with_one_cron_workflow()

        execute = await self._run_pass(scheduler, workflow, claimed=False)

        execute.assert_not_awaited()

    async def test_lost_claim_is_not_retried_on_the_next_pass(self) -> None:
        """Without this, the next pass gets a fresh minute key and double-fires."""
        scheduler, workflow = self._scheduler_with_one_cron_workflow()

        await self._run_pass(scheduler, workflow, claimed=False)
        execute = await self._run_pass(scheduler, workflow, claimed=True)

        execute.assert_not_awaited()
        self.claim.assert_not_awaited()


class CronExecutorThreadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_workflow_runs_the_executor_off_the_event_loop(self) -> None:
        """A blocking run must not stall the worker's event loop (leader heartbeat, HTTP)."""
        scheduler = CronScheduler()
        workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=uuid.uuid4(),
            name="Cron workflow",
            nodes=[],
            edges=[],
        )
        db = SimpleNamespace(add=lambda row: None, commit=AsyncMock())
        execution_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={},
            execution_time_ms=1.0,
            node_results=[],
        )
        run_threads: list[str] = []

        def fake_execute(**_kwargs: object) -> ExecutionResult:
            run_threads.append(threading.current_thread().name)
            return execution_result

        with (
            patch(
                "app.services.cron_scheduler.collect_referenced_workflows",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.cron_scheduler.get_credentials_context", AsyncMock(return_value={})
            ),
            patch(
                "app.services.cron_scheduler.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch("app.services.cluster.dispatch.execute_workflow", fake_execute),
            patch("app.services.cron_scheduler.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(
                "app.services.cron_scheduler._persist_global_variables_from_execution", AsyncMock()
            ),
        ):
            await scheduler._execute_workflow(db, workflow)

        self.assertEqual(len(run_threads), 1)
        self.assertNotEqual(run_threads[0], threading.current_thread().name)
