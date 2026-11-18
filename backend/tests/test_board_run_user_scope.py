"""Board runs execute in the scope of the user who starts them.

A card's workflow chain uses the credentials, global variables and workflow access of the
user who moved, ran or answered the card, the same as a run that user starts from the
editor. That user is carried through auto-advance, review resumes and restart recovery.
Run rows written before runs recorded that user keep the board owner.
"""

import asyncio
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import boards as boards_api
from app.db.models import (
    Board,
    BoardCard,
    BoardCardRun,
    BoardColumn,
    Credential,
    CredentialType,
    ExecutionHistory,
    GlobalVariable,
    Workflow,
    WorkflowShare,
)
from app.models.board_schemas import CardCreateRequest, CardMoveRequest, ColumnUpdateRequest
from app.services import board_run_service
from app.services.encryption import encrypt_config
from tests.board_pg_support import cleanup, connect_or_skip, make_board, make_user, share_board

# ─── Unit tests: every lookup of a run follows the user who started it ─────────────────


class _Session:
    """An async-session stand-in: records adds and serves ``db.get`` from a dict."""

    def __init__(self, objects: dict, results: list | None = None) -> None:
        self.objects = objects
        self.added: list = []
        self.commit = AsyncMock()
        self.flush = AsyncMock(side_effect=self._assign_ids)
        self.execute = AsyncMock(side_effect=list(results or []))

    async def _assign_ids(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def get(self, model: type, pk: uuid.UUID) -> object:
        return self.objects.get((model.__name__, pk))

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    def runs(self) -> list:
        return [obj for obj in self.added if type(obj).__name__ == "BoardCardRun"]


def _result(status: str = "success") -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        outputs={"text": "done"},
        node_results=[],
        execution_time_ms=1.0,
        sub_workflow_executions=[],
        allow_downstream_pending=False,
        join_allow_downstream=lambda: None,
        pending_review={"kind": "hitl"} if status == "pending" else None,
    )


class _ChainCase(unittest.IsolatedAsyncioTestCase):
    """One card on a board owned by ``owner``, with a two-workflow chain."""

    def setUp(self) -> None:
        self.owner_id = uuid.uuid4()
        self.collaborator_id = uuid.uuid4()
        self.card = SimpleNamespace(
            id=uuid.uuid4(),
            title="T",
            content="C",
            card_metadata={},
            run_status="running",
            board_id=uuid.uuid4(),
            column_id=uuid.uuid4(),
        )
        self.board = SimpleNamespace(id=self.card.board_id, name="B", owner_id=self.owner_id)
        self.workflows = [
            SimpleNamespace(id=uuid.uuid4(), name=f"WF{i}", nodes=[], edges=[]) for i in (1, 2)
        ]
        self.session = _Session(
            {(BoardCard.__name__, self.card.id): self.card}
            | {(Workflow.__name__, wf.id): wf for wf in self.workflows}
        )
        self.links = [
            {"workflow_id": wf.id, "workflow_name": wf.name, "position": i}
            for i, wf in enumerate(self.workflows)
        ]
        context = dict(
            card=self.card,
            board=self.board,
            comments=[],
            history=[],
            previous_runs=[],
            to_column_name="Development",
        )
        self.mocks = {
            "_load_card_context": AsyncMock(return_value=context),
            "collect_referenced_workflows": AsyncMock(return_value={}),
            "get_credentials_context": AsyncMock(return_value={}),
            "get_global_variables_context": AsyncMock(return_value={}),
            "upsert_workflow_analytics_snapshot": AsyncMock(),
            "_persist_global_variables_from_execution": AsyncMock(),
            "persist_pending_hitl_execution": AsyncMock(
                return_value=(SimpleNamespace(id=uuid.uuid4()), None)
            ),
            "build_default_public_base_url": MagicMock(return_value="http://localhost"),
            "register_execution": MagicMock(side_effect=lambda **_kwargs: threading.Event()),
            "clear_execution": MagicMock(),
            "execute_workflow": MagicMock(side_effect=lambda **_kwargs: _result()),
            "user_has_workflow_access": AsyncMock(return_value=True),
            "board_mapper_is_configured": MagicMock(return_value=False),
            "build_workflow_inputs": AsyncMock(return_value={}),
            "_auto_advance": AsyncMock(),
        }
        for name, mock in self.mocks.items():
            patcher = patch.object(board_run_service, name, mock)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def run_chain(self, actor_user_id: uuid.UUID | None) -> None:
        await board_run_service._run_chain(
            card_id=self.card.id,
            board_id=self.board.id,
            column_id=self.card.column_id,
            links=self.links,
            move=None,
            rerun=False,
            actor_user_id=actor_user_id,
            session_factory=lambda: self.session,
        )


class RunAsUserIdTests(unittest.TestCase):
    def test_the_user_who_started_the_run_wins_over_the_board_owner(self) -> None:
        actor = uuid.uuid4()
        board = SimpleNamespace(owner_id=uuid.uuid4())
        self.assertEqual(board_run_service.run_as_user_id(actor, board), actor)

    def test_a_run_row_from_before_the_column_keeps_the_board_owner(self) -> None:
        board = SimpleNamespace(owner_id=uuid.uuid4())
        self.assertEqual(board_run_service.run_as_user_id(None, board), board.owner_id)


class ChainScopeTests(_ChainCase):
    async def test_every_lookup_uses_the_user_who_started_the_chain(self) -> None:
        await self.run_chain(self.collaborator_id)

        user = self.collaborator_id
        m = self.mocks
        self.assertEqual(m["execute_workflow"].call_count, 2)
        for call in m["execute_workflow"].call_args_list:
            self.assertEqual(call.kwargs["actor_user_id"], user)
            self.assertEqual(call.kwargs["trace_user_id"], user)
        for name in ("get_credentials_context", "get_global_variables_context"):
            self.assertEqual([c.args[1] for c in m[name].await_args_list], [user, user])
        for call in m["collect_referenced_workflows"].await_args_list:
            self.assertEqual(call.kwargs["actor_user_id"], user)
        for call in m["register_execution"].call_args_list:
            self.assertEqual(call.kwargs["actor_user_id"], user)
        for call in m["_persist_global_variables_from_execution"].await_args_list:
            self.assertEqual(call.args[1], user)
        for call in m["user_has_workflow_access"].await_args_list:
            self.assertEqual(call.args[2], user)
        self.assertEqual([run.actor_user_id for run in self.session.runs()], [user, user])
        self.assertEqual(m["_auto_advance"].await_args.kwargs["actor_user_id"], user)
        # Run counts stay on the board owner's analytics, as before.
        for call in m["upsert_workflow_analytics_snapshot"].await_args_list:
            self.assertEqual(call.kwargs["owner_id"], self.owner_id)

    async def test_a_chain_without_a_recorded_user_runs_as_the_board_owner(self) -> None:
        await self.run_chain(None)

        m = self.mocks
        for call in m["execute_workflow"].call_args_list:
            self.assertEqual(call.kwargs["actor_user_id"], self.owner_id)
        self.assertEqual(
            [c.args[1] for c in m["get_credentials_context"].await_args_list],
            [self.owner_id, self.owner_id],
        )
        self.assertEqual(
            [run.actor_user_id for run in self.session.runs()], [self.owner_id, self.owner_id]
        )

    async def test_a_workflow_not_shared_with_the_user_does_not_run(self) -> None:
        m = self.mocks
        m["user_has_workflow_access"].return_value = False
        m["board_mapper_is_configured"].return_value = True

        await self.run_chain(self.collaborator_id)

        m["execute_workflow"].assert_not_called()
        m["build_workflow_inputs"].assert_not_awaited()  # nothing about it runs, not even mapping
        m["get_credentials_context"].assert_not_awaited()
        m["get_global_variables_context"].assert_not_awaited()
        m["_auto_advance"].assert_not_awaited()
        runs = self.session.runs()
        self.assertEqual([run.status for run in runs], ["failed", "skipped"])
        self.assertEqual(runs[0].error, board_run_service.WORKFLOW_NOT_SHARED_ERROR)
        self.assertEqual(self.card.run_status, "failed")
        events = [obj for obj in self.session.added if type(obj).__name__ == "BoardCardActivity"]
        self.assertEqual(
            events[0].content,
            "WF1 did not run: it is not shared with the user who started the run",
        )

    async def test_the_chain_stops_at_the_first_workflow_the_user_cannot_reach(self) -> None:
        reachable = {self.workflows[0].id}
        self.mocks["user_has_workflow_access"].side_effect = lambda _db, workflow, _user: (
            workflow.id in reachable
        )

        await self.run_chain(self.collaborator_id)

        executed = [c.kwargs["workflow_id"] for c in self.mocks["execute_workflow"].call_args_list]
        self.assertEqual(executed, [self.workflows[0].id])
        self.assertEqual([run.status for run in self.session.runs()], ["success", "failed"])
        self.assertEqual(self.card.run_status, "failed")

    async def test_a_review_pause_resumes_with_the_user_who_started_the_chain(self) -> None:
        self.mocks["execute_workflow"].side_effect = lambda **_kwargs: _result("pending")

        await self.run_chain(self.collaborator_id)

        kwargs = self.mocks["persist_pending_hitl_execution"].await_args.kwargs
        self.assertEqual(kwargs["credentials_owner_id"], self.collaborator_id)
        self.assertEqual(kwargs["trace_user_id"], self.collaborator_id)


class ContinuationTests(unittest.IsolatedAsyncioTestCase):
    """Chains that continue later keep the user who started them."""

    def _paused_env(self, *, remaining: bool, actor_user_id: uuid.UUID | None):
        history_id = uuid.uuid4()
        card = SimpleNamespace(
            id=uuid.uuid4(), board_id=uuid.uuid4(), column_id=uuid.uuid4(), run_status="pending"
        )
        column = SimpleNamespace(id=card.column_id, ai_instructions=None)
        board = SimpleNamespace(id=card.board_id, name="B", owner_id=uuid.uuid4())
        workflow = SimpleNamespace(id=uuid.uuid4(), name="Approve")
        run = SimpleNamespace(
            id=history_id,
            card_id=card.id,
            column_id=column.id,
            workflow_id=workflow.id,
            workflow_name="Approve",
            chain_position=0,
            chain_length=2 if remaining else 1,
            status="pending",
            output=None,
            error=None,
            finished_at=None,
            execution_history_id=history_id,
            active_execution_id=None,
            actor_user_id=actor_user_id,
        )
        history = SimpleNamespace(
            id=history_id, status="success", inputs={}, outputs={"text": "approved"}
        )
        session = _Session(
            {
                (BoardCardRun.__name__, history_id): run,
                (ExecutionHistory.__name__, history_id): history,
                (BoardCard.__name__, card.id): card,
                (BoardColumn.__name__, column.id): column,
                (Board.__name__, board.id): board,
                (Workflow.__name__, workflow.id): workflow,
            }
        )
        links = [{"workflow_id": workflow.id, "workflow_name": "Approve", "position": 0}]
        if remaining:
            links.append({"workflow_id": uuid.uuid4(), "workflow_name": "Notify", "position": 1})
        return history_id, run, session, links

    async def _continue(self, entry: str, *, remaining: bool, actor: uuid.UUID | None):
        history_id, run, session, links = self._paused_env(remaining=remaining, actor_user_id=actor)
        if entry == "resume":
            found = MagicMock()
            found.scalars.return_value.first.return_value = run
            session.execute = AsyncMock(return_value=found)
        else:
            run.execution_history_id = None  # recovery fills it in
        with (
            patch.object(board_run_service, "_column_links", AsyncMock(return_value=links)),
            patch.object(board_run_service, "_record_output_activity", AsyncMock()),
            patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance,
            patch.object(board_run_service, "_spawn_chain", MagicMock()) as spawn,
        ):
            if entry == "resume":
                await board_run_service.resume_card_chain(
                    history_id, session_factory=lambda: session
                )
            else:
                await board_run_service.sync_recovered_board_run(
                    history_id, session_factory=lambda: session
                )
        return spawn, advance

    async def test_after_a_review_answer_the_rest_runs_as_the_user_who_started(self) -> None:
        actor = uuid.uuid4()
        for entry in ("resume", "recovery"):
            with self.subTest(entry=entry):
                spawn, advance = await self._continue(entry, remaining=True, actor=actor)
                spawn.assert_called_once()
                self.assertEqual(spawn.call_args.kwargs["actor_user_id"], actor)
                advance.assert_not_awaited()

    async def test_the_next_column_runs_as_the_user_who_started(self) -> None:
        actor = uuid.uuid4()
        for entry in ("resume", "recovery"):
            with self.subTest(entry=entry):
                spawn, advance = await self._continue(entry, remaining=False, actor=actor)
                spawn.assert_not_called()
                self.assertEqual(advance.await_args.kwargs["actor_user_id"], actor)

    async def test_a_run_from_before_the_column_continues_as_it_started(self) -> None:
        for entry in ("resume", "recovery"):
            with self.subTest(entry=entry):
                spawn, _advance = await self._continue(entry, remaining=True, actor=None)
                # None reaches _run_chain, which runs it as the board owner.
                self.assertIsNone(spawn.call_args.kwargs["actor_user_id"])

    async def test_an_answer_comment_releases_the_card_as_the_user_who_answered(self) -> None:
        actor = uuid.uuid4()
        card = SimpleNamespace(id=uuid.uuid4(), run_status="success")
        column = SimpleNamespace(id=uuid.uuid4())
        board = SimpleNamespace(id=uuid.uuid4(), auto_advance=True)
        columns = MagicMock()
        columns.scalars.return_value.all.return_value = [uuid.uuid4(), column.id, uuid.uuid4()]
        active = MagicMock()
        active.scalars.return_value.all.return_value = []
        answered = MagicMock()
        answered.first.return_value = (uuid.uuid4(),)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[columns, active, answered])

        with patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance:
            released = await board_run_service.answer_card_comment(
                db, card=card, column=column, board=board, actor_user_id=actor
            )

        self.assertTrue(released)
        self.assertEqual(advance.await_args.kwargs["actor_user_id"], actor)

    async def test_auto_advance_starts_the_next_chain_as_the_same_user(self) -> None:
        actor = uuid.uuid4()
        source, target = uuid.uuid4(), uuid.uuid4()
        card = SimpleNamespace(id=uuid.uuid4(), column_id=source, position=0, run_status="success")
        enabled = MagicMock()
        enabled.scalar_one_or_none.return_value = True
        columns = MagicMock()
        columns.scalars.return_value.all.return_value = [
            SimpleNamespace(id=uuid.uuid4(), name="Backlog"),
            SimpleNamespace(id=uuid.uuid4(), name="Planning"),
            SimpleNamespace(id=source, name="Development"),
            SimpleNamespace(id=target, name="Review"),
        ]
        reindex = MagicMock()
        reindex.scalars.return_value.all.return_value = []
        link_rows = MagicMock()
        link_rows.all.return_value = [(SimpleNamespace(workflow_id=uuid.uuid4(), position=0), "QA")]
        session = _Session(
            {(BoardCard.__name__, card.id): card},
            results=[enabled, columns, reindex, reindex, link_rows],
        )

        with patch.object(board_run_service, "_spawn_chain", MagicMock()) as spawn:
            await board_run_service._auto_advance(
                card_id=card.id,
                board_id=uuid.uuid4(),
                from_column_id=source,
                actor_user_id=actor,
                session_factory=lambda: session,
            )

        self.assertEqual(card.column_id, target)
        spawn.assert_called_once()
        self.assertEqual(spawn.call_args.kwargs["actor_user_id"], actor)
        self.assertEqual(spawn.call_args.kwargs["column_id"], target)

    async def test_enqueue_records_the_user_on_the_claimed_run(self) -> None:
        actor = uuid.uuid4()
        card = SimpleNamespace(id=uuid.uuid4(), run_status="idle")
        locked = MagicMock()
        locked.first.return_value = (card.id,)
        active = MagicMock()
        active.scalars.return_value.all.return_value = []
        links = MagicMock()
        links.all.return_value = [(SimpleNamespace(workflow_id=uuid.uuid4(), position=0), "WF")]
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(side_effect=[locked, active, links])

        with patch.object(board_run_service, "_spawn_chain", MagicMock()) as spawn:
            result = await board_run_service.enqueue_card_chain(
                db,
                card=card,
                column=SimpleNamespace(id=uuid.uuid4()),
                board=SimpleNamespace(id=uuid.uuid4()),
                move=None,
                rerun=True,
                actor_user_id=actor,
            )

        self.assertEqual(result, board_run_service.ENQUEUE_STARTED)
        claimed = db.add.call_args.args[0]
        self.assertEqual(claimed.actor_user_id, actor)
        self.assertEqual(spawn.call_args.kwargs["actor_user_id"], actor)

    async def test_a_move_into_an_empty_column_passes_the_user_on(self) -> None:
        actor = uuid.uuid4()
        locked = MagicMock()
        locked.first.return_value = (uuid.uuid4(),)
        active = MagicMock()
        active.scalars.return_value.all.return_value = []
        no_links = MagicMock()
        no_links.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[locked, active, no_links])

        with patch.object(board_run_service, "_auto_advance", AsyncMock()) as advance:
            result = await board_run_service.enqueue_card_chain(
                db,
                card=SimpleNamespace(id=uuid.uuid4()),
                column=SimpleNamespace(id=uuid.uuid4()),
                board=SimpleNamespace(id=uuid.uuid4()),
                move={"from_column": "Backlog", "to_column": "Development"},
                rerun=False,
                actor_user_id=actor,
            )

        self.assertEqual(result, board_run_service.ENQUEUE_NO_CHAIN)
        self.assertEqual(advance.await_args.kwargs["actor_user_id"], actor)


# ─── PostgreSQL: Burak's board, shared with Ceren for writing ─────────────────────────


async def _drain_chains() -> None:
    """Wait for every background chain, including the ones auto-advance starts."""
    for _ in range(20):
        tasks = list(board_run_service._BACKGROUND_CHAIN_TASKS)
        if not tasks:
            return
        await asyncio.gather(*tasks)
    raise AssertionError("board chains kept starting")


class SharedBoardRunScopePgTests(unittest.IsolatedAsyncioTestCase):
    """Real board API, access checks and credential loading; only the executor is faked.

    Burak and Ceren each own a bearer credential called ``ApiKey`` and a global variable
    called ``region``. The fake executor records which values a run received.
    """

    async def asyncSetUp(self) -> None:
        self.engine = await connect_or_skip(self)
        self.burak = await make_user(self.engine, "burak")
        self.ceren = await make_user(self.engine, "ceren")
        self.board, self.columns = await make_board(self.engine, self.burak, "Launch")
        await share_board(self.engine, self.board, self.ceren, "write")
        async with self.session() as db:
            for user, token, region in (
                (self.burak, "burak-token", "eu"),
                (self.ceren, "ceren-token", "us"),
            ):
                db.add(
                    Credential(
                        owner_id=user.id,
                        name="ApiKey",
                        type=CredentialType.bearer,
                        encrypted_config=encrypt_config({"bearer_token": token}),
                    )
                )
                db.add(
                    GlobalVariable(
                        owner_id=user.id, name="region", value={"v": region}, value_type="string"
                    )
                )
            await db.commit()

        self.executed: list[dict] = []

        def fake_execute(**kwargs: object) -> SimpleNamespace:
            self.executed.append(kwargs)
            return _result()

        for name, mock in {
            "execute_workflow": MagicMock(side_effect=fake_execute),
            "register_execution": MagicMock(side_effect=lambda **_kwargs: threading.Event()),
            "clear_execution": MagicMock(),
            # Analytics rows have no owner foreign key and would outlive the cleanup.
            "upsert_workflow_analytics_snapshot": AsyncMock(),
        }.items():
            patcher = patch.object(board_run_service, name, mock)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def asyncTearDown(self) -> None:
        await _drain_chains()
        await cleanup(self.engine, [self.burak, self.ceren])

    def session(self) -> AsyncSession:
        return AsyncSession(self.engine, expire_on_commit=False)

    async def workflow(self, owner, name: str, *, shared_with=None) -> uuid.UUID:
        async with self.session() as db:
            workflow = Workflow(name=name, owner_id=owner.id, nodes=[], edges=[])
            db.add(workflow)
            await db.flush()
            if shared_with is not None:
                db.add(WorkflowShare(workflow_id=workflow.id, user_id=shared_with.id))
            await db.commit()
            return workflow.id

    async def link(self, column_index: int, workflow_ids: list[uuid.UUID], as_user) -> None:
        async with self.session() as db:
            await boards_api.update_column(
                board_id=self.board.id,
                column_id=self.columns[column_index].id,
                request=ColumnUpdateRequest(workflow_ids=workflow_ids),
                db=db,
                current_user=as_user,
            )

    async def card(self, column_index: int) -> uuid.UUID:
        async with self.session() as db:
            card = await boards_api.create_card(
                board_id=self.board.id,
                request=CardCreateRequest(
                    title="Launch email", column_id=self.columns[column_index].id
                ),
                db=db,
                current_user=self.burak,
            )
            return card.id

    async def run_card(self, card_id: uuid.UUID, as_user) -> None:
        async with self.session() as db:
            await boards_api.run_card_chain(
                board_id=self.board.id,
                card_id=card_id,
                skip_auto_advance=True,
                db=db,
                current_user=as_user,
            )
        await _drain_chains()

    async def runs(self, card_id: uuid.UUID) -> list[BoardCardRun]:
        async with self.session() as db:
            result = await db.execute(
                select(BoardCardRun)
                .where(BoardCardRun.card_id == card_id)
                .order_by(BoardCardRun.started_at, BoardCardRun.chain_position)
            )
            return list(result.scalars().all())

    def assert_ran_as(self, execution: dict, user, token: str, region: str) -> None:
        self.assertEqual(execution["actor_user_id"], user.id)
        self.assertEqual(execution["trace_user_id"], user.id)
        self.assertEqual(execution["credentials_context"]["ApiKey"], f"Bearer {token}")
        self.assertEqual(execution["global_variables_context"]["region"], region)

    async def test_the_owner_runs_their_workflow_with_their_own_scope(self) -> None:
        workflow_id = await self.workflow(self.burak, "Draft")
        await self.link(2, [workflow_id], self.burak)
        card_id = await self.card(2)

        await self.run_card(card_id, self.burak)

        self.assertEqual(len(self.executed), 1)
        self.assert_ran_as(self.executed[0], self.burak, "burak-token", "eu")
        runs = await self.runs(card_id)
        self.assertEqual([(r.status, r.actor_user_id) for r in runs], [("success", self.burak.id)])

    async def test_a_collaborator_runs_a_shared_workflow_with_their_own_scope(self) -> None:
        workflow_id = await self.workflow(self.burak, "Draft", shared_with=self.ceren)
        await self.link(2, [workflow_id], self.burak)
        card_id = await self.card(2)

        await self.run_card(card_id, self.ceren)

        self.assertEqual(len(self.executed), 1)
        self.assert_ran_as(self.executed[0], self.ceren, "ceren-token", "us")
        runs = await self.runs(card_id)
        self.assertEqual([(r.status, r.actor_user_id) for r in runs], [("success", self.ceren.id)])

    async def test_a_collaborator_cannot_run_the_owners_unshared_workflow(self) -> None:
        workflow_id = await self.workflow(self.burak, "Draft")
        await self.link(2, [workflow_id], self.burak)
        card_id = await self.card(2)

        await self.run_card(card_id, self.ceren)

        self.assertEqual(self.executed, [])
        runs = await self.runs(card_id)
        self.assertEqual([r.status for r in runs], ["failed"])
        self.assertEqual(runs[0].error, board_run_service.WORKFLOW_NOT_SHARED_ERROR)
        async with self.session() as db:
            self.assertEqual((await db.get(BoardCard, card_id)).run_status, "failed")

    async def test_a_collaborators_workflow_on_the_owners_board_never_gets_the_owners_scope(
        self,
    ) -> None:
        # Ceren adds her own workflow, not shared with Burak, to Burak's board.
        workflow_id = await self.workflow(self.ceren, "Ceren's draft")
        await self.link(2, [workflow_id], self.ceren)
        card_id = await self.card(2)

        await self.run_card(card_id, self.ceren)
        self.assertEqual(len(self.executed), 1)
        self.assert_ran_as(self.executed[0], self.ceren, "ceren-token", "us")

        # Burak cannot reach the workflow, so his run does not start it at all.
        await self.run_card(card_id, self.burak)
        self.assertEqual(len(self.executed), 1)
        latest = (await self.runs(card_id))[-1]
        self.assertEqual((latest.status, latest.actor_user_id), ("failed", self.burak.id))
        self.assertEqual(latest.error, board_run_service.WORKFLOW_NOT_SHARED_ERROR)

    async def test_auto_advance_keeps_running_as_the_user_who_moved_the_card(self) -> None:
        draft = await self.workflow(self.burak, "Draft", shared_with=self.ceren)
        publish = await self.workflow(self.burak, "Publish", shared_with=self.ceren)
        await self.link(2, [draft], self.burak)
        await self.link(3, [publish], self.burak)
        card_id = await self.card(0)

        async with self.session() as db:
            await boards_api.move_card(
                board_id=self.board.id,
                card_id=card_id,
                request=CardMoveRequest(to_column_id=self.columns[2].id),
                db=db,
                current_user=self.ceren,
            )
        await _drain_chains()

        self.assertEqual([e["workflow_id"] for e in self.executed], [draft, publish])
        for execution in self.executed:
            self.assert_ran_as(execution, self.ceren, "ceren-token", "us")
        runs = await self.runs(card_id)
        self.assertEqual(
            [(r.status, r.actor_user_id) for r in runs],
            [("success", self.ceren.id), ("success", self.ceren.id)],
        )

    async def test_auto_advance_does_not_fall_back_to_the_owner(self) -> None:
        draft = await self.workflow(self.burak, "Draft", shared_with=self.ceren)
        private = await self.workflow(self.burak, "Private")
        await self.link(2, [draft], self.burak)
        await self.link(3, [private], self.burak)
        card_id = await self.card(0)

        async with self.session() as db:
            await boards_api.move_card(
                board_id=self.board.id,
                card_id=card_id,
                request=CardMoveRequest(to_column_id=self.columns[2].id),
                db=db,
                current_user=self.ceren,
            )
        await _drain_chains()

        self.assertEqual([e["workflow_id"] for e in self.executed], [draft])
        runs = await self.runs(card_id)
        self.assertEqual(
            [(r.status, r.actor_user_id) for r in runs],
            [("success", self.ceren.id), ("failed", self.ceren.id)],
        )


if __name__ == "__main__":
    unittest.main()
