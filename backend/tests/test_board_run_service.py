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

    async def test_pending_result_pauses_chain(self):
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

        runs = [o for o in session.added if type(o).__name__ == "BoardCardRun"]
        self.assertEqual(runs[0].status, "pending")
        self.assertEqual(card.run_status, "pending")


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
