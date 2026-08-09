import asyncio
import datetime
import json
import threading
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.workflows import (
    list_active_workflow_executions,
    stream_active_workflow_execution,
)
from app.models.schemas import ActiveExecutionItem
from app.services.execution_cancellation import (
    MAX_PROGRESS_EVENT_PAYLOAD_BYTES,
    MAX_PROGRESS_EVENTS,
    ActiveExecutionRecord,
    ExecutionCancellationHandle,
    active_execution_registry,
    clear_execution,
    get_active_execution_events,
    get_active_execution_inputs,
    get_active_execution_progress,
    get_active_execution_stream_snapshot,
    list_active_executions,
    list_persisted_active_executions_for_user,
    mark_execution_publishes_progress_events,
    record_execution_node_completed,
    record_execution_node_started,
    record_execution_progress_event,
    register_execution,
)
from app.services.workflow_executor import (
    ExecutionResult,
    WorkflowCancelledError,
    WorkflowExecutor,
    WorkflowTimeoutError,
)


def _make_handle(workflow_id: uuid.UUID, execution_id: uuid.UUID) -> ExecutionCancellationHandle:
    return ExecutionCancellationHandle(
        workflow_id=workflow_id,
        execution_id=execution_id,
        event=threading.Event(),
        started_at=datetime.datetime(2025, 1, 1, 12, 0, 0),
        inputs={"text": "local input"},
    )


async def _drain_frames(iterator, *, limit: int, timeout: float = 1.0) -> list[str]:
    """Collect SSE frames until the stream goes quiet, so extra frames are detectable."""
    frames: list[str] = []
    try:
        while len(frames) < limit:
            frames.append(await asyncio.wait_for(anext(iterator), timeout))
    except (TimeoutError, asyncio.TimeoutError, StopAsyncIteration):
        pass
    return frames


def _make_record(workflow_id: uuid.UUID, execution_id: uuid.UUID) -> ActiveExecutionRecord:
    return ActiveExecutionRecord(
        workflow_id=workflow_id,
        execution_id=execution_id,
        workflow_name="My Workflow",
        started_at=datetime.datetime(2025, 1, 1, 12, 0, 0),
        inputs={"text": "persisted input"},
    )


class ListActiveWorkflowExecutionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_empty_when_no_active_executions(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()

        with (
            patch(
                "app.services.active_execution_overview.list_persisted_active_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.active_execution_overview.list_pending_review_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch("app.services.active_execution_overview.list_active_executions", return_value=[]),
        ):
            result = await list_active_workflow_executions(current_user=user, db=db)

        self.assertEqual(result, [])
        db.execute.assert_not_called()

    async def test_returns_persisted_active_executions(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        db = AsyncMock()

        with (
            patch(
                "app.services.active_execution_overview.list_persisted_active_executions_for_user",
                AsyncMock(return_value=[_make_record(wf_id, ex_id)]),
            ),
            patch(
                "app.services.active_execution_overview.list_pending_review_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch("app.services.active_execution_overview.list_active_executions", return_value=[]),
        ):
            result = await list_active_workflow_executions(current_user=user, db=db)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].execution_id, str(ex_id))
        self.assertEqual(result[0].workflow_id, str(wf_id))
        self.assertEqual(result[0].workflow_name, "My Workflow")
        self.assertEqual(result[0].inputs, {"text": "persisted input"})
        self.assertEqual(result[0].status, "running")
        self.assertIsInstance(result[0], ActiveExecutionItem)
        db.execute.assert_not_called()

    async def test_returns_every_execution_for_the_same_workflow(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()

        workflow_id = uuid.uuid4()
        execution_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        records = [_make_record(workflow_id, execution_id) for execution_id in execution_ids]
        db = AsyncMock()

        with (
            patch(
                "app.services.active_execution_overview.list_persisted_active_executions_for_user",
                AsyncMock(return_value=records),
            ),
            patch(
                "app.services.active_execution_overview.list_pending_review_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch("app.services.active_execution_overview.list_active_executions", return_value=[]),
        ):
            result = await list_active_workflow_executions(current_user=user, db=db)

        self.assertEqual(len(result), 3)
        self.assertEqual(
            {item.execution_id for item in result},
            {str(execution_id) for execution_id in execution_ids},
        )
        self.assertEqual({item.workflow_id for item in result}, {str(workflow_id)})

    async def test_includes_pending_hitl_and_codex_reviews_in_count(self) -> None:
        from app.services.execution_cancellation import PendingReviewExecutionRecord

        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()

        running_wf = uuid.uuid4()
        running_ex = uuid.uuid4()
        hitl_wf = uuid.uuid4()
        hitl_ex = uuid.uuid4()
        codex_wf = uuid.uuid4()
        codex_ex = uuid.uuid4()

        pending = [
            PendingReviewExecutionRecord(
                execution_id=hitl_ex,
                workflow_id=hitl_wf,
                workflow_name="HITL Workflow",
                started_at=datetime.datetime(2025, 1, 1, 11, 0, 0),
                inputs={},
                pending_kind="hitl",
            ),
            PendingReviewExecutionRecord(
                execution_id=codex_ex,
                workflow_id=codex_wf,
                workflow_name="Codex Workflow",
                started_at=datetime.datetime(2025, 1, 1, 10, 0, 0),
                inputs={},
                pending_kind="codex",
            ),
        ]

        with (
            patch(
                "app.services.active_execution_overview.list_persisted_active_executions_for_user",
                AsyncMock(return_value=[_make_record(running_wf, running_ex)]),
            ),
            patch(
                "app.services.active_execution_overview.list_pending_review_executions_for_user",
                AsyncMock(return_value=pending),
            ),
            patch("app.services.active_execution_overview.list_active_executions", return_value=[]),
        ):
            result = await list_active_workflow_executions(current_user=user, db=db)

        self.assertEqual(len(result), 3)
        by_id = {item.execution_id: item for item in result}
        self.assertEqual(by_id[str(running_ex)].status, "running")
        self.assertEqual(by_id[str(hitl_ex)].status, "pending")
        self.assertEqual(by_id[str(hitl_ex)].pending_kind, "hitl")
        self.assertEqual(by_id[str(codex_ex)].status, "pending")
        self.assertEqual(by_id[str(codex_ex)].pending_kind, "codex")

    async def test_filters_local_fallback_to_accessible_workflows(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()

        wf_id_owned = uuid.uuid4()
        wf_id_other = uuid.uuid4()
        ex_id_owned = uuid.uuid4()
        ex_id_other = uuid.uuid4()

        handles = [
            _make_handle(wf_id_owned, ex_id_owned),
            _make_handle(wf_id_other, ex_id_other),
        ]

        owned_workflow = MagicMock()
        owned_workflow.id = wf_id_owned
        owned_workflow.name = "My Workflow"

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = [owned_workflow]
        db.execute.return_value = db_result

        with (
            patch(
                "app.services.active_execution_overview.list_persisted_active_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.active_execution_overview.list_pending_review_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.active_execution_overview.list_active_executions",
                return_value=handles,
            ),
            patch(
                "app.services.active_execution_overview.get_active_execution_progress",
                return_value=([], []),
            ),
        ):
            result = await list_active_workflow_executions(current_user=user, db=db)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].execution_id, str(ex_id_owned))
        self.assertEqual(result[0].workflow_id, str(wf_id_owned))
        self.assertEqual(result[0].workflow_name, "My Workflow")
        self.assertEqual(result[0].inputs, {"text": "local input"})
        self.assertIsInstance(result[0], ActiveExecutionItem)

    async def test_returns_started_at_from_handle(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        handle = _make_handle(wf_id, ex_id)

        workflow = MagicMock()
        workflow.id = wf_id
        workflow.name = "Workflow A"

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = [workflow]
        db.execute.return_value = db_result

        with (
            patch(
                "app.services.active_execution_overview.list_persisted_active_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.active_execution_overview.list_pending_review_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.active_execution_overview.list_active_executions",
                return_value=[handle],
            ),
            patch(
                "app.services.active_execution_overview.get_active_execution_progress",
                return_value=([], []),
            ),
        ):
            result = await list_active_workflow_executions(current_user=user, db=db)

        self.assertEqual(result[0].started_at, datetime.datetime(2025, 1, 1, 12, 0, 0))

    async def test_excludes_cancelled_local_fallback_handles(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        handle = _make_handle(wf_id, ex_id)
        handle.event.set()

        db = AsyncMock()

        with (
            patch(
                "app.services.active_execution_overview.list_persisted_active_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.active_execution_overview.list_pending_review_executions_for_user",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.active_execution_overview.list_active_executions",
                return_value=[handle],
            ),
        ):
            result = await list_active_workflow_executions(current_user=user, db=db)

        self.assertEqual(result, [])
        db.execute.assert_not_called()


class ListPersistedActiveExecutionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_filters_out_cancel_requested_rows(self) -> None:
        db = AsyncMock()
        db_result = MagicMock()
        db_result.all.return_value = []
        db.execute.return_value = db_result

        await list_persisted_active_executions_for_user(db, uuid.uuid4())

        stmt = db.execute.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        self.assertIn("active_workflow_executions.cancel_requested_at IS NULL", compiled)


class LiveExecutionSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def test_records_running_and_completed_nodes_on_active_handle(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        register_execution(workflow_id=workflow_id, execution_id=execution_id)
        try:
            with patch.object(active_execution_registry, "_wake") as registry_wake:
                record_execution_node_started(str(execution_id), "node-1")
                record_execution_node_completed(
                    str(execution_id),
                    "node-1",
                    {
                        "node_id": "node-1",
                        "node_label": "Console",
                        "node_type": "consoleLog",
                        "status": "success",
                        "output": {"message": "live"},
                        "execution_time_ms": 4.0,
                        "error": None,
                    },
                )
                registry_wake.assert_not_called()

            node_result = {
                "node_id": "node-1",
                "node_label": "Console",
                "node_type": "consoleLog",
                "status": "success",
                "output": {"message": "live"},
                "execution_time_ms": 4.0,
                "error": None,
            }
            handle = next(
                item for item in list_active_executions() if item.execution_id == execution_id
            )
            self.assertEqual(handle.progress_version, 2)
            self.assertEqual(handle.running_node_ids, set())
            self.assertEqual(handle.node_results, [node_result])

            record_execution_node_started(str(execution_id), "node-2")
            self.assertEqual(
                get_active_execution_progress(execution_id, workflow_id=workflow_id),
                (["node-2"], [node_result]),
            )
            self.assertEqual(
                get_active_execution_inputs(execution_id, workflow_id=workflow_id),
                {},
            )
        finally:
            clear_execution(execution_id)

    async def test_registry_writes_progress_only_after_node_state_changes(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        register_execution(workflow_id=workflow_id, execution_id=execution_id)

        session = AsyncMock()
        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = []
        session.execute.return_value = select_result
        # begin_nested() is a plain method returning an async context manager, so it
        # must not be an AsyncMock coroutine.
        savepoint = MagicMock()
        savepoint.__aenter__ = AsyncMock(return_value=savepoint)
        savepoint.__aexit__ = AsyncMock(return_value=False)
        session.begin_nested = MagicMock(return_value=savepoint)
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=None)

        async def sync_update_sql() -> str:
            session.execute.reset_mock()
            with patch(
                "app.db.session.async_session_maker",
                return_value=session_context,
            ):
                await active_execution_registry._sync_local_handles()
            update_statement = session.execute.await_args_list[-1].args[0]
            return str(update_statement).partition(" WHERE ")[0]

        try:
            heartbeat_only_sql = await sync_update_sql()
            self.assertNotIn("running_node_ids", heartbeat_only_sql)
            self.assertNotIn("node_results", heartbeat_only_sql)

            record_execution_node_started(str(execution_id), "node-1")
            progress_sql = await sync_update_sql()
            self.assertIn("running_node_ids", progress_sql)
            self.assertIn("node_results", progress_sql)

            next_heartbeat_sql = await sync_update_sql()
            self.assertNotIn("running_node_ids", next_heartbeat_sql)
            self.assertNotIn("node_results", next_heartbeat_sql)
        finally:
            clear_execution(execution_id)

    async def test_stream_replays_live_node_snapshot_as_canvas_events(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        register_execution(
            workflow_id=workflow_id,
            execution_id=execution_id,
            inputs={"text": "live input"},
        )
        record_execution_node_completed(
            str(execution_id),
            "console",
            {
                "node_id": "console",
                "node_label": "Console",
                "node_type": "consoleLog",
                "status": "success",
                "output": {"message": "hello"},
                "execution_time_ms": 3.0,
                "error": None,
            },
        )
        record_execution_node_started(str(execution_id), "wait")

        workflow = MagicMock()
        workflow.id = workflow_id
        workflow.nodes = []
        user = MagicMock()
        user.id = uuid.uuid4()
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)

        try:
            with patch(
                "app.api.workflows.get_workflow_for_user",
                AsyncMock(return_value=workflow),
            ):
                response = await stream_active_workflow_execution(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    request=request,
                    current_user=user,
                    db=AsyncMock(),
                )

            iterator = response.body_iterator
            started = await anext(iterator)
            completed = await anext(iterator)
            running = await anext(iterator)
            await iterator.aclose()

            self.assertIn('"type": "execution_started"', started)
            self.assertIn('"inputs": {"text": "live input"}', started)
            self.assertIn('"type": "node_complete"', completed)
            self.assertIn('"message": "hello"', completed)
            self.assertIn('"type": "node_start"', running)
            self.assertIn('"node_id": "wait"', running)
        finally:
            clear_execution(execution_id)

    async def test_stream_replays_runner_events_for_publishing_execution(self) -> None:
        """A canvas attaching mid-run replays agent progress and sub-agent lifecycle."""
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        register_execution(
            workflow_id=workflow_id,
            execution_id=execution_id,
            inputs={"text": "live input"},
        )
        mark_execution_publishes_progress_events(str(execution_id))
        # Coarse snapshot the observer must NOT re-emit once live events exist.
        record_execution_node_completed(
            str(execution_id),
            "input_1",
            {
                "node_id": "input_1",
                "node_label": "userInput",
                "node_type": "textInput",
                "status": "success",
                "output": {"source": "snapshot"},
                "execution_time_ms": 1.0,
                "error": None,
            },
        )
        record_execution_node_started(str(execution_id), "agent_1")
        for event in (
            {
                "type": "node_complete",
                "node_id": "input_1",
                "node_label": "userInput",
                "node_type": "textInput",
                "status": "success",
                "output": {"source": "live"},
                "execution_time_ms": 1.0,
                "error": None,
            },
            {"type": "node_start", "node_id": "agent_1", "node_label": "orchestrator"},
            {
                "type": "agent_progress",
                "node_id": "agent_1",
                "node_label": "orchestrator",
                "entry": {"name": "call_sub_agent", "phase": "start"},
            },
            {"type": "node_start", "node_id": "agent_2", "node_label": "growthHackerAgent"},
        ):
            record_execution_progress_event(str(execution_id), event)

        workflow = MagicMock()
        workflow.id = workflow_id
        workflow.nodes = []
        user = MagicMock()
        user.id = uuid.uuid4()
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)

        try:
            with patch(
                "app.api.workflows.get_workflow_for_user",
                AsyncMock(return_value=workflow),
            ):
                response = await stream_active_workflow_execution(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    request=request,
                    current_user=user,
                    db=AsyncMock(),
                )

            iterator = response.body_iterator
            frames = await _drain_frames(iterator, limit=6)
            await iterator.aclose()

            self.assertIn('"type": "execution_started"', frames[0])
            payloads = [json.loads(frame.removeprefix("data: ")) for frame in frames[1:]]
            self.assertEqual(
                [(item["type"], item.get("node_id")) for item in payloads],
                [
                    ("node_complete", "input_1"),
                    ("node_start", "agent_1"),
                    ("agent_progress", "agent_1"),
                    ("node_start", "agent_2"),
                ],
            )
            self.assertEqual(payloads[0]["output"], {"source": "live"})
        finally:
            clear_execution(execution_id)

    async def test_stream_sends_new_runner_events_after_the_initial_replay(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        register_execution(workflow_id=workflow_id, execution_id=execution_id)
        mark_execution_publishes_progress_events(str(execution_id))
        record_execution_progress_event(
            str(execution_id),
            {"type": "node_start", "node_id": "agent_1", "node_label": "orchestrator"},
        )

        workflow = MagicMock()
        workflow.id = workflow_id
        workflow.nodes = []
        user = MagicMock()
        user.id = uuid.uuid4()
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)

        try:
            with patch(
                "app.api.workflows.get_workflow_for_user",
                AsyncMock(return_value=workflow),
            ):
                response = await stream_active_workflow_execution(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    request=request,
                    current_user=user,
                    db=AsyncMock(),
                )

            iterator = response.body_iterator
            self.assertIn('"type": "execution_started"', await anext(iterator))
            self.assertIn('"node_id": "agent_1"', await anext(iterator))

            record_execution_progress_event(
                str(execution_id),
                {
                    "type": "node_complete",
                    "node_id": "agent_2",
                    "node_label": "growthHackerAgent",
                    "node_type": "agent",
                    "status": "success",
                    "output": {"text": "done"},
                    "execution_time_ms": 12.0,
                    "error": None,
                },
            )
            follow_up = await anext(iterator)
            await iterator.aclose()

            self.assertIn('"type": "node_complete"', follow_up)
            self.assertIn('"node_id": "agent_2"', follow_up)
        finally:
            clear_execution(execution_id)

    async def test_stream_marks_a_vanished_execution_as_gone(self) -> None:
        """Cancelled mid-flight runs must terminate the stream, not stall the canvas."""
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()

        workflow = MagicMock()
        workflow.id = workflow_id
        workflow.nodes = []
        user = MagicMock()
        user.id = uuid.uuid4()
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)

        stream_db = AsyncMock()
        stream_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=stream_db)
        session_context.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "app.api.workflows.get_workflow_for_user",
                AsyncMock(return_value=workflow),
            ),
            patch("app.api.workflows.async_session_maker", return_value=session_context),
            patch("app.api.workflows.WORKFLOW_OBSERVE_MISSING_TICK_LIMIT", 1),
        ):
            response = await stream_active_workflow_execution(
                workflow_id=workflow_id,
                execution_id=execution_id,
                request=request,
                current_user=user,
                db=AsyncMock(),
            )

            iterator = response.body_iterator
            self.assertIn('"type": "execution_started"', await anext(iterator))
            gone = json.loads((await anext(iterator)).removeprefix("data: "))
            with self.assertRaises(StopAsyncIteration):
                await anext(iterator)

        self.assertEqual(gone["type"], "error")
        self.assertEqual(gone["code"], "execution_gone")

    async def test_stream_sends_heartbeat_while_active_node_is_idle(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        register_execution(workflow_id=workflow_id, execution_id=execution_id)

        workflow = MagicMock()
        workflow.id = workflow_id
        workflow.nodes = []
        user = MagicMock()
        user.id = uuid.uuid4()
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)

        try:
            with (
                patch(
                    "app.api.workflows.get_workflow_for_user",
                    AsyncMock(return_value=workflow),
                ),
                patch("app.api.workflows.WORKFLOW_SSE_HEARTBEAT_SECONDS", 0),
            ):
                response = await stream_active_workflow_execution(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    request=request,
                    current_user=user,
                    db=AsyncMock(),
                )

                iterator = response.body_iterator
                started = await anext(iterator)
                heartbeat = await anext(iterator)
                await iterator.aclose()

            self.assertIn('"type": "execution_started"', started)
            self.assertEqual(heartbeat, ": heartbeat\n\n")
        finally:
            clear_execution(execution_id)


class LiveExecutionEventBufferTests(unittest.TestCase):
    """The live event buffer backs the observe stream for other tabs."""

    def setUp(self) -> None:
        self.workflow_id = uuid.uuid4()
        self.execution_id = uuid.uuid4()
        register_execution(workflow_id=self.workflow_id, execution_id=self.execution_id)
        self.addCleanup(clear_execution, self.execution_id)

    def _snapshot(self):
        return get_active_execution_stream_snapshot(
            self.execution_id,
            workflow_id=self.workflow_id,
        )

    def test_marking_the_run_flags_it_for_event_replay(self) -> None:
        snapshot = self._snapshot()
        assert snapshot is not None
        self.assertFalse(snapshot.publishes_progress_events)

        mark_execution_publishes_progress_events(str(self.execution_id))
        record_execution_progress_event(
            str(self.execution_id),
            {"type": "node_start", "node_id": "agent_1"},
        )

        snapshot = self._snapshot()
        assert snapshot is not None
        self.assertTrue(snapshot.publishes_progress_events)
        self.assertEqual(len(snapshot.events), 1)
        self.assertEqual(snapshot.next_event_seq, 1)
        self.assertEqual(snapshot.dropped_event_count, 0)

    def test_skips_internal_and_observer_synthesized_events(self) -> None:
        for event in (
            {"type": "_internal_node_result", "result": object()},
            {"type": "execution_started", "execution_id": str(self.execution_id)},
            {"type": "execution_complete", "status": "success"},
            {"type": "node_complete", "node_id": "n1", "output": {"blob": object()}},
        ):
            record_execution_progress_event(str(self.execution_id), event)

        snapshot = self._snapshot()
        assert snapshot is not None
        self.assertEqual(snapshot.events, [])

    def test_cursor_returns_only_newer_events(self) -> None:
        for index in range(3):
            record_execution_progress_event(
                str(self.execution_id),
                {"type": "node_start", "node_id": f"node-{index}"},
            )

        payloads, next_seq = get_active_execution_events(
            self.execution_id,
            workflow_id=self.workflow_id,
            after_seq=1,
        )
        self.assertEqual(next_seq, 3)
        self.assertEqual(
            [json.loads(payload)["node_id"] for payload in payloads],
            ["node-1", "node-2"],
        )

    def test_oversized_event_is_buffered_without_its_payload(self) -> None:
        record_execution_progress_event(
            str(self.execution_id),
            {
                "type": "node_complete",
                "node_id": "big",
                "node_label": "Big",
                "status": "success",
                "output": {"blob": "x" * (MAX_PROGRESS_EVENT_PAYLOAD_BYTES + 1)},
            },
        )

        snapshot = self._snapshot()
        assert snapshot is not None
        payload = json.loads(snapshot.events[0])
        self.assertEqual(payload["node_id"], "big")
        self.assertEqual(payload["status"], "success")
        self.assertTrue(payload["_truncated"])
        self.assertNotIn("output", payload)

    def test_oldest_events_are_dropped_once_the_count_cap_is_reached(self) -> None:
        for index in range(MAX_PROGRESS_EVENTS + 5):
            record_execution_progress_event(
                str(self.execution_id),
                {"type": "node_start", "node_id": f"node-{index}"},
            )

        snapshot = self._snapshot()
        assert snapshot is not None
        self.assertEqual(len(snapshot.events), MAX_PROGRESS_EVENTS)
        self.assertEqual(snapshot.dropped_event_count, 5)
        self.assertEqual(json.loads(snapshot.events[0])["node_id"], "node-5")

    def test_unknown_execution_id_is_ignored(self) -> None:
        record_execution_progress_event("not-a-uuid", {"type": "node_start", "node_id": "n"})
        record_execution_progress_event(
            str(uuid.uuid4()),
            {"type": "node_start", "node_id": "n"},
        )

        snapshot = self._snapshot()
        assert snapshot is not None
        self.assertEqual(snapshot.events, [])


class SubWorkflowActiveTrackingTests(unittest.TestCase):
    """Sub-workflow executions must appear in the active list while running."""

    _TOOL_DEF_BASE: dict = {"_sub_workflow_ids": [], "_sub_workflow_names": {}}

    def _make_fake_result(self, workflow_id: str) -> ExecutionResult:
        return ExecutionResult(
            workflow_id=uuid.UUID(workflow_id),
            status="success",
            outputs={},
            execution_time_ms=5.0,
        )

    def _call_sub_workflow_tool(
        self,
        executor: WorkflowExecutor,
        sub_wf_id: str,
        *,
        side_effect: Exception | None = None,
    ) -> dict:
        tool_def = {
            "_sub_workflow_ids": [sub_wf_id],
            "_sub_workflow_names": {sub_wf_id: "Sub WF"},
        }
        fake_result = self._make_fake_result(sub_wf_id)

        with patch("app.services.workflow_executor.WorkflowExecutor") as mock_wfe:
            mock_sub = MagicMock()
            mock_sub.sub_workflow_executions = []
            if side_effect:
                mock_sub.execute.side_effect = side_effect
            else:
                mock_sub.execute.return_value = fake_result
            mock_wfe.return_value = mock_sub

            return executor._execute_sub_workflow_tool(
                tool_def=tool_def,
                _name="call_sub_workflow",
                args={"workflow_id": sub_wf_id, "inputs": {}},
                _timeout_seconds=30.0,
            )

    def test_register_and_clear_called_on_success(self) -> None:
        sub_wf_id = str(uuid.uuid4())
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }

        registered: list[uuid.UUID] = []
        cleared: list[uuid.UUID] = []

        def fake_register(**kwargs: object) -> threading.Event:
            registered.append(kwargs["execution_id"])
            return threading.Event()

        def fake_clear(execution_id: uuid.UUID) -> None:
            cleared.append(execution_id)

        with (
            patch("app.services.workflow_executor._register_sub_execution", fake_register),
            patch("app.services.workflow_executor._clear_sub_execution", fake_clear),
        ):
            result = self._call_sub_workflow_tool(executor, sub_wf_id)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(registered), 1)
        self.assertEqual(len(cleared), 1)
        self.assertEqual(registered[0], cleared[0])

    def test_clear_called_even_when_sub_workflow_raises(self) -> None:
        """finally block must clear the registration on exception."""
        sub_wf_id = str(uuid.uuid4())
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }

        registered: list[uuid.UUID] = []
        cleared: list[uuid.UUID] = []

        def fake_register(**kwargs: object) -> threading.Event:
            registered.append(kwargs["execution_id"])
            return threading.Event()

        def fake_clear(execution_id: uuid.UUID) -> None:
            cleared.append(execution_id)

        with (
            patch("app.services.workflow_executor._register_sub_execution", fake_register),
            patch("app.services.workflow_executor._clear_sub_execution", fake_clear),
        ):
            result = self._call_sub_workflow_tool(
                executor, sub_wf_id, side_effect=RuntimeError("boom")
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("boom", result.get("error", ""))
        # clear must have been called despite the exception
        self.assertEqual(len(cleared), 1)
        self.assertEqual(registered, cleared)

    def test_independently_cancelled_sub_workflow_returns_cancelled_status(self) -> None:
        """Child-only cancel must surface explicit cancelled status, not status=error."""
        sub_wf_id = str(uuid.uuid4())
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }

        with (
            patch(
                "app.services.workflow_executor._register_sub_execution",
                return_value=threading.Event(),
            ),
            patch("app.services.workflow_executor._clear_sub_execution"),
        ):
            result = self._call_sub_workflow_tool(
                executor,
                sub_wf_id,
                side_effect=WorkflowCancelledError("Workflow execution cancelled"),
            )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["error"], "Workflow execution cancelled")

    def test_independently_timed_out_sub_workflow_returns_timeout_status(self) -> None:
        sub_wf_id = str(uuid.uuid4())
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }

        with (
            patch(
                "app.services.workflow_executor._register_sub_execution",
                return_value=threading.Event(),
            ),
            patch("app.services.workflow_executor._clear_sub_execution"),
        ):
            result = self._call_sub_workflow_tool(
                executor,
                sub_wf_id,
                side_effect=WorkflowTimeoutError("Workflow timed out after 30 seconds"),
            )

        self.assertEqual(result["status"], "timeout")
        self.assertIn("timed out", result["error"])

    def test_sub_workflow_visible_in_active_list_during_execution(self) -> None:
        """Integration: sub-workflow workflow_id appears in list_active_executions while running."""
        sub_wf_id = str(uuid.uuid4())
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }
        fake_result = self._make_fake_result(sub_wf_id)

        active_wf_ids_mid_run: list[uuid.UUID] = []

        def fake_execute(*, workflow_id: uuid.UUID, initial_inputs: dict) -> ExecutionResult:
            # Inspect the global active list while the sub-workflow is "running".
            active_wf_ids_mid_run.extend(h.workflow_id for h in list_active_executions())
            return fake_result

        with patch("app.services.workflow_executor.WorkflowExecutor") as mock_wfe:
            mock_sub = MagicMock()
            mock_sub.sub_workflow_executions = []
            mock_sub.execute.side_effect = fake_execute
            mock_wfe.return_value = mock_sub

            executor._execute_sub_workflow_tool(
                tool_def={
                    "_sub_workflow_ids": [sub_wf_id],
                    "_sub_workflow_names": {sub_wf_id: "Sub WF"},
                },
                _name="call_sub_workflow",
                args={"workflow_id": sub_wf_id, "inputs": {}},
                _timeout_seconds=30.0,
            )

        self.assertIn(uuid.UUID(sub_wf_id), active_wf_ids_mid_run)
        # After completion the entry must be gone.
        post_run_ids = [h.workflow_id for h in list_active_executions()]
        self.assertNotIn(uuid.UUID(sub_wf_id), post_run_ids)
