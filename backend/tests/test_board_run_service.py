import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import board_run_service


def _activity(kind="comment", content="hello", author_type="user"):
    return SimpleNamespace(
        kind=kind,
        author_type=author_type,
        content=content,
        data={},
        created_at=datetime(2026, 7, 11, tzinfo=timezone.utc),
    )


def _card(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        title="Write launch email",
        content="Draft the launch email for the beta",
        card_metadata={"attachments": [{"name": "brief", "url": "https://x/brief"}]},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestBuildCardPayload(unittest.TestCase):
    def test_payload_contract_fields(self):
        card = _card()
        board = SimpleNamespace(id=uuid.uuid4(), name="Launch board")
        payload = board_run_service.build_card_payload(
            card=card,
            board=board,
            from_column_name="Backlog",
            to_column_name="Planning",
            comments=[_activity(content="Use friendly tone")],
            history=[_activity(kind="event", content="Card created", author_type="system")],
            previous_runs=[
                SimpleNamespace(
                    workflow_name="Research",
                    output={"summary": "done"},
                    finished_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
                    column_id=uuid.uuid4(),
                )
            ],
            chain_position=1,
            chain_length=2,
            previous_workflow_outputs=[{"workflow_name": "Enrich", "output": {"plan": "v1"}}],
            rerun=False,
        )

        self.assertEqual(payload["triggered_by"], "board")
        self.assertEqual(payload["card"]["title"], "Write launch email")
        self.assertEqual(payload["card"]["comments"][0]["content"], "Use friendly tone")
        self.assertEqual(payload["card"]["previous_outputs"][0]["workflow_name"], "Research")
        self.assertEqual(payload["move"], {"from_column": "Backlog", "to_column": "Planning"})
        self.assertFalse(payload["rerun"])
        self.assertEqual(payload["chain"]["position"], 1)
        self.assertEqual(payload["chain"]["length"], 2)
        self.assertEqual(payload["chain"]["previous_workflow_outputs"][0]["output"], {"plan": "v1"})
        self.assertEqual(payload["card"]["metadata"]["attachments"][0]["url"], "https://x/brief")

    def test_rerun_has_null_move_and_history_is_capped(self):
        payload = board_run_service.build_card_payload(
            card=_card(),
            board=SimpleNamespace(id=uuid.uuid4(), name="B"),
            from_column_name=None,
            to_column_name="Planning",
            comments=[],
            history=[_activity(kind="event", content=f"e{i}") for i in range(250)],
            previous_runs=[],
            chain_position=0,
            chain_length=1,
            previous_workflow_outputs=[],
            rerun=True,
        )
        self.assertIsNone(payload["move"])
        self.assertTrue(payload["rerun"])
        self.assertEqual(len(payload["card"]["history"]), 200)
        self.assertEqual(payload["card"]["history"][-1]["content"], "e249")


class _FakeSession:
    """Minimal async-session stand-in recording adds and serving db.get lookups."""

    def __init__(self, objects):
        self.objects = objects  # {(type_name, id): obj}
        self.added = []
        self.commit = AsyncMock()
        self.flush = AsyncMock(side_effect=self._assign_ids)

    async def _assign_ids(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def add(self, obj):
        self.added.append(obj)

    async def get(self, model, pk):
        return self.objects.get((model.__name__, pk))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _success_result(outputs):
    return SimpleNamespace(
        status="success",
        outputs=outputs,
        node_results=[],
        execution_time_ms=1.0,
        sub_workflow_executions=[],
        allow_downstream_pending=False,
        join_allow_downstream=lambda: None,
    )


def _chain_env():
    """Common fixtures: card, board, two workflows, fake session factory."""
    from app.db.models import BoardCard, Workflow

    card_id = uuid.uuid4()
    card = SimpleNamespace(
        id=card_id,
        title="T",
        content="C",
        card_metadata={},
        run_status="running",
        board_id=uuid.uuid4(),
        column_id=uuid.uuid4(),
    )
    board = SimpleNamespace(id=card.board_id, name="B", owner_id=uuid.uuid4())
    wf1 = SimpleNamespace(id=uuid.uuid4(), name="WF1", nodes=[], edges=[])
    wf2 = SimpleNamespace(id=uuid.uuid4(), name="WF2", nodes=[], edges=[])
    objects = {
        (BoardCard.__name__, card_id): card,
        (Workflow.__name__, wf1.id): wf1,
        (Workflow.__name__, wf2.id): wf2,
    }
    session = _FakeSession(objects)

    def factory():
        return session

    links = [
        {"workflow_id": wf1.id, "workflow_name": "WF1", "position": 0},
        {"workflow_id": wf2.id, "workflow_name": "WF2", "position": 1},
    ]
    context = dict(
        card=card,
        board=board,
        comments=[],
        history=[],
        previous_runs=[],
        from_column_name="Backlog",
        to_column_name="Planning",
    )
    return card, board, session, factory, links, context


def _runner_patches(context, execute_side_effect):
    return [
        patch.object(board_run_service, "_load_card_context", AsyncMock(return_value=context)),
        patch.object(board_run_service, "collect_referenced_workflows", AsyncMock(return_value={})),
        patch.object(board_run_service, "get_credentials_context", AsyncMock(return_value={})),
        patch.object(board_run_service, "get_global_variables_context", AsyncMock(return_value={})),
        patch.object(
            board_run_service,
            "upsert_workflow_analytics_snapshot",
            AsyncMock(return_value=None),
        ),
        patch.object(
            board_run_service,
            "_persist_global_variables_from_execution",
            AsyncMock(return_value=None),
        ),
        patch.object(
            board_run_service,
            "persist_pending_hitl_execution",
            AsyncMock(return_value=(SimpleNamespace(id=uuid.uuid4()), None)),
        ),
        patch.object(
            board_run_service,
            "persist_pending_codex_followup_execution",
            AsyncMock(return_value=(SimpleNamespace(id=uuid.uuid4()), None)),
        ),
        patch.object(
            board_run_service,
            "build_default_public_base_url",
            MagicMock(return_value="http://localhost:10105"),
        ),
        patch.object(
            board_run_service, "execute_workflow", MagicMock(side_effect=execute_side_effect)
        ),
    ]


class TestRunCardChain(unittest.IsolatedAsyncioTestCase):
    async def test_sequential_success_marks_card_green(self):
        card, board, session, factory, links, context = _chain_env()
        calls = []

        def fake_execute(**kwargs):
            calls.append(kwargs["workflow_id"])
            return _success_result({"text": f"out-{len(calls)}"})

        patches = _runner_patches(context, fake_execute)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        await board_run_service._run_chain(
            card_id=card.id,
            board_id=board.id,
            column_id=card.column_id,
            links=links,
            move={"from_column": "Backlog", "to_column": "Planning"},
            rerun=False,
            session_factory=factory,
        )

        self.assertEqual(calls, [links[0]["workflow_id"], links[1]["workflow_id"]])
        runs = [o for o in session.added if type(o).__name__ == "BoardCardRun"]
        self.assertEqual([r.status for r in runs], ["success", "success"])
        activities = [o for o in session.added if type(o).__name__ == "BoardCardActivity"]
        self.assertTrue(any(a.kind == "output" for a in activities))
        histories = [o for o in session.added if type(o).__name__ == "ExecutionHistory"]
        self.assertEqual(len(histories), 2)
        self.assertEqual(histories[0].trigger_source, "board")
        self.assertEqual(card.run_status, "success")

    async def test_failure_stops_chain_and_marks_card_red(self):
        card, board, session, factory, links, context = _chain_env()

        def fake_execute(**kwargs):
            raise RuntimeError("boom")

        patches = _runner_patches(context, fake_execute)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        await board_run_service._run_chain(
            card_id=card.id,
            board_id=board.id,
            column_id=card.column_id,
            links=links,
            move=None,
            rerun=True,
            session_factory=factory,
        )

        runs = [o for o in session.added if type(o).__name__ == "BoardCardRun"]
        self.assertEqual([r.status for r in runs], ["failed", "skipped"])
        self.assertIn("boom", runs[0].error)
        self.assertEqual(card.run_status, "failed")

    async def _run_pending_chain(self, pending_review):
        card, board, session, factory, links, context = _chain_env()

        def fake_execute(**kwargs):
            return SimpleNamespace(
                status="pending",
                outputs={},
                node_results=[],
                execution_time_ms=1.0,
                sub_workflow_executions=[],
                allow_downstream_pending=False,
                join_allow_downstream=lambda: None,
                pending_review=pending_review,
            )

        patches = _runner_patches(context, fake_execute)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        await board_run_service._run_chain(
            card_id=card.id,
            board_id=board.id,
            column_id=card.column_id,
            links=links,
            move=None,
            rerun=True,
            session_factory=factory,
        )
        return card, session

    async def test_pending_result_pauses_chain(self):
        card, session = await self._run_pending_chain({"kind": "hitl"})

        runs = [o for o in session.added if type(o).__name__ == "BoardCardRun"]
        self.assertEqual(runs[0].status, "pending")
        self.assertEqual(card.run_status, "pending")
        # A HITL pause is persisted as a review request, not a Codex follow-up.
        board_run_service.persist_pending_hitl_execution.assert_awaited_once()
        board_run_service.persist_pending_codex_followup_execution.assert_not_awaited()

    async def test_codex_pending_is_persisted_as_a_codex_followup(self):
        card, session = await self._run_pending_chain({"kind": "codex", "question": "Which repo?"})

        runs = [o for o in session.added if type(o).__name__ == "BoardCardRun"]
        self.assertEqual(runs[0].status, "pending")
        self.assertEqual(card.run_status, "pending")
        # A Codex question has its own answer UI and resume path.
        board_run_service.persist_pending_codex_followup_execution.assert_awaited_once()
        board_run_service.persist_pending_hitl_execution.assert_not_awaited()


class TestResumeCardChain(unittest.IsolatedAsyncioTestCase):
    """After a HITL / Codex answer, the paused board chain must carry on."""

    def _env(self, *, history_status, outputs, chain_position, chain_length, remaining_links):
        from app.db.models import Board, BoardCard, BoardColumn, ExecutionHistory, Workflow

        history_id = uuid.uuid4()
        card = SimpleNamespace(
            id=uuid.uuid4(), board_id=uuid.uuid4(), column_id=uuid.uuid4(), run_status="pending"
        )
        column = SimpleNamespace(id=card.column_id, ai_instructions=None)
        board = SimpleNamespace(id=card.board_id, name="B", owner_id=uuid.uuid4())
        workflow = SimpleNamespace(id=uuid.uuid4(), name="WF1", nodes=[])
        run = SimpleNamespace(
            id=uuid.uuid4(),
            card_id=card.id,
            column_id=column.id,
            workflow_id=workflow.id,
            workflow_name="WF1",
            chain_position=chain_position,
            chain_length=chain_length,
            status="pending",
            output=None,
            error=None,
            finished_at=None,
            execution_history_id=history_id,
        )
        history = SimpleNamespace(id=history_id, status=history_status, outputs=outputs)

        session = _FakeSession(
            {
                (ExecutionHistory.__name__, history_id): history,
                (BoardCard.__name__, card.id): card,
                (BoardColumn.__name__, column.id): column,
                (Board.__name__, board.id): board,
                (Workflow.__name__, workflow.id): workflow,
            }
        )
        run_res = MagicMock()
        run_res.scalars.return_value.first.return_value = run
        session.execute = AsyncMock(return_value=run_res)

        # The full chain: the paused link plus whatever follows it.
        links = [
            {"workflow_id": workflow.id, "workflow_name": "WF1", "position": 0}
        ] * chain_position
        links.append({"workflow_id": workflow.id, "workflow_name": "WF1", "position": 0})
        links.extend(remaining_links)

        return history_id, card, run, session, links, (lambda: session)

    async def test_success_records_output_and_advances_when_chain_is_done(self):
        history_id, card, run, session, links, factory = self._env(
            history_status="success",
            outputs={"text": "shipped"},
            chain_position=0,
            chain_length=1,
            remaining_links=[],
        )

        with (
            patch.object(board_run_service, "_column_links", AsyncMock(return_value=links)),
            patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance,
            patch.object(board_run_service, "_spawn_chain", MagicMock()) as spawn,
        ):
            await board_run_service.resume_card_chain(history_id, session_factory=factory)

        self.assertEqual(run.status, "success")
        self.assertEqual(run.output, {"text": "shipped"})
        self.assertEqual(card.run_status, "success")
        outputs = [o for o in session.added if type(o).__name__ == "BoardCardActivity"]
        self.assertEqual(outputs[0].kind, "output")
        spawn.assert_not_called()
        advance.assert_awaited_once()

    async def test_success_runs_the_rest_of_the_chain(self):
        remaining = [{"workflow_id": uuid.uuid4(), "workflow_name": "WF2", "position": 1}]
        history_id, card, run, session, links, factory = self._env(
            history_status="success",
            outputs={"text": "answered"},
            chain_position=0,
            chain_length=2,
            remaining_links=remaining,
        )

        with (
            patch.object(board_run_service, "_column_links", AsyncMock(return_value=links)),
            patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance,
            patch.object(board_run_service, "_spawn_chain", MagicMock()) as spawn,
        ):
            await board_run_service.resume_card_chain(history_id, session_factory=factory)

        self.assertEqual(run.status, "success")
        self.assertEqual(card.run_status, "running")
        spawn.assert_called_once()
        kwargs = spawn.call_args.kwargs
        # The tail of the chain keeps its original step numbering and carries the
        # paused link's output forward.
        self.assertEqual([link["workflow_name"] for link in kwargs["links"]], ["WF2"])
        self.assertEqual(kwargs["start_index"], 1)
        self.assertEqual(kwargs["chain_length"], 2)
        self.assertEqual(kwargs["initial_outputs"][0]["output"], {"text": "answered"})
        advance.assert_not_awaited()

    async def test_failed_resume_fails_the_card_and_skips_the_rest(self):
        remaining = [{"workflow_id": uuid.uuid4(), "workflow_name": "WF2", "position": 1}]
        history_id, card, run, session, links, factory = self._env(
            history_status="error",
            outputs={"error": "boom"},
            chain_position=0,
            chain_length=2,
            remaining_links=remaining,
        )

        with (
            patch.object(board_run_service, "_column_links", AsyncMock(return_value=links)),
            patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance,
            patch.object(board_run_service, "_spawn_chain", MagicMock()) as spawn,
        ):
            await board_run_service.resume_card_chain(history_id, session_factory=factory)

        self.assertEqual(run.status, "failed")
        self.assertEqual(card.run_status, "failed")
        skipped = [
            o for o in session.added if type(o).__name__ == "BoardCardRun" and o.status == "skipped"
        ]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0].chain_position, 1)
        spawn.assert_not_called()
        advance.assert_not_awaited()

    async def test_still_pending_keeps_the_card_waiting(self):
        history_id, card, run, session, links, factory = self._env(
            history_status="pending",
            outputs={},
            chain_position=0,
            chain_length=1,
            remaining_links=[],
        )

        with (
            patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance,
            patch.object(board_run_service, "_spawn_chain", MagicMock()) as spawn,
        ):
            await board_run_service.resume_card_chain(history_id, session_factory=factory)

        self.assertEqual(run.status, "pending")
        self.assertEqual(card.run_status, "pending")
        spawn.assert_not_called()
        advance.assert_not_awaited()

    async def test_non_board_execution_is_a_no_op(self):
        session = _FakeSession({})
        empty = MagicMock()
        empty.scalars.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=empty)

        with patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance:
            await board_run_service.resume_card_chain(uuid.uuid4(), session_factory=lambda: session)

        advance.assert_not_awaited()
        self.assertEqual(session.added, [])


class TestAnswerCardComment(unittest.IsolatedAsyncioTestCase):
    """A comment on a gated card releases the gate instead of re-running the column."""

    @staticmethod
    def _db(column_ids, *, active, answered):
        columns_res = MagicMock()
        columns_res.scalars.return_value.all.return_value = column_ids
        active_res = MagicMock()
        active_res.scalars.return_value.all.return_value = active
        answered_res = MagicMock()
        answered_res.first.return_value = answered

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[columns_res, active_res, answered_res])
        return db

    async def test_answer_advances_without_rerunning_the_column(self):
        card = SimpleNamespace(id=uuid.uuid4(), run_status="success")
        column = SimpleNamespace(id=uuid.uuid4())
        board = SimpleNamespace(id=uuid.uuid4())
        db = self._db([uuid.uuid4(), column.id, uuid.uuid4()], active=[], answered=(uuid.uuid4(),))

        with (
            patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance,
            patch.object(board_run_service, "enqueue_card_chain", AsyncMock()) as enqueue,
        ):
            result = await board_run_service.answer_card_comment(
                db, card=card, column=column, board=board
            )

        self.assertTrue(result)
        enqueue.assert_not_awaited()
        advance.assert_awaited_once()
        self.assertTrue(advance.await_args.kwargs["ignore_gate"])
        # The card shows as active on the board as soon as the comment is posted.
        self.assertEqual(card.run_status, "running")

    async def test_answer_is_ignored_when_the_gate_chain_never_finished(self):
        card = SimpleNamespace(id=uuid.uuid4(), run_status="idle")
        column = SimpleNamespace(id=uuid.uuid4())
        board = SimpleNamespace(id=uuid.uuid4())
        db = self._db([uuid.uuid4(), column.id], active=[], answered=None)

        with patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance:
            result = await board_run_service.answer_card_comment(
                db, card=card, column=column, board=board
            )

        self.assertFalse(result)
        advance.assert_not_awaited()
        self.assertEqual(card.run_status, "idle")

    async def test_answer_is_ignored_past_the_gate(self):
        card = SimpleNamespace(id=uuid.uuid4(), run_status="success")
        column = SimpleNamespace(id=uuid.uuid4())
        board = SimpleNamespace(id=uuid.uuid4())
        columns_res = MagicMock()
        columns_res.scalars.return_value.all.return_value = [
            uuid.uuid4(),
            uuid.uuid4(),
            column.id,
        ]
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[columns_res])

        with patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance:
            result = await board_run_service.answer_card_comment(
                db, card=card, column=column, board=board
            )

        self.assertFalse(result)
        advance.assert_not_awaited()


class TestEnqueueHoldsTaskReference(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_retains_background_task(self):
        import asyncio

        card = SimpleNamespace(id=uuid.uuid4(), run_status="idle")
        column = SimpleNamespace(id=uuid.uuid4())
        board = SimpleNamespace(id=uuid.uuid4())
        link = SimpleNamespace(workflow_id=uuid.uuid4(), position=0)

        active_res = MagicMock()
        active_res.scalars.return_value.all.return_value = []
        links_res = MagicMock()
        links_res.all.return_value = [(link, "WF")]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[active_res, links_res])

        with patch.object(board_run_service, "_run_chain", AsyncMock(return_value=None)):
            result = await board_run_service.enqueue_card_chain(
                db, card=card, column=column, board=board, move=None, rerun=True
            )
            # The task must be strongly referenced so the GC cannot drop it mid-run.
            self.assertTrue(result)
            self.assertEqual(card.run_status, "running")
            self.assertGreaterEqual(len(board_run_service._BACKGROUND_CHAIN_TASKS), 1)
            # let the scheduled task finish and clear itself from the set
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        self.assertEqual(len(board_run_service._BACKGROUND_CHAIN_TASKS), 0)
