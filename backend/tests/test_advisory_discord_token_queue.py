"""The Discord interaction token stays out of every row a queued run writes.

A run that goes through the concurrency queue, or to another instance, is written by
the dispatcher, the queue and the worker, not by the Discord route that redacts its own
rows. The token is sealed in the queue row and redacted from everything persisted, while
the run itself still sees the real value.
"""

from __future__ import annotations

import json
import uuid
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from sqlalchemy import select
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.api import discord as discord_api
from app.db.models import ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.services import workflow_concurrency
from app.services.cluster import dispatch as dispatch_module
from app.services.cluster.dispatch import RunQueueWorker, dispatch_workflow
from app.services.cluster.run_secrets import (
    REDACTED,
    SEALED_SECRETS_OPTION,
    redactor_for,
    seal_input_secrets,
    unseal_input_secrets,
)

TOKEN = "itok-" + "a1b2c3d4" * 8
PATHS = (("interaction", "token"),)
NODES = [
    {"id": "d1", "type": "discordTrigger", "data": {"label": "slash"}},
    # Echoes the token, so the run proves it saw the real value.
    {
        "id": "o1",
        "type": "output",
        "data": {"label": "reply", "message": "$slash.interaction.token"},
    },
]
EDGES = [{"id": "e1", "source": "d1", "target": "o1"}]


def _inputs(token: str = TOKEN) -> dict:
    return {
        "triggered_by": "Discord",
        "interaction": {"type": 2, "application_id": "1111", "token": token, "id": "42"},
        "type": 2,
        "data": {"name": "ping"},
        "headers": {},
    }


def _dumped(*values: object) -> str:
    return json.dumps(values, default=str)


class SealTests(TestCase):
    def test_the_stored_inputs_hold_a_placeholder_and_the_caller_keeps_the_token(self) -> None:
        inputs = _inputs()

        stored, sealed = seal_input_secrets(inputs, PATHS)

        self.assertEqual(stored["interaction"]["token"], REDACTED)
        self.assertEqual(stored["interaction"]["application_id"], "1111")
        self.assertEqual(inputs["interaction"]["token"], TOKEN)
        self.assertIsNotNone(sealed)
        self.assertNotIn(TOKEN, _dumped(stored, sealed))

    def test_unsealing_returns_the_exact_inputs_and_the_value_to_redact(self) -> None:
        stored, sealed = seal_input_secrets(_inputs(), PATHS)

        restored, secrets = unseal_input_secrets(stored, sealed)

        self.assertEqual(restored, _inputs())
        self.assertEqual(secrets, [TOKEN])
        self.assertEqual(stored["interaction"]["token"], REDACTED)

    def test_inputs_without_a_secret_are_passed_through_untouched(self) -> None:
        inputs = {"body": {"text": "hi"}}

        stored, sealed = seal_input_secrets(inputs, PATHS)
        self.assertIs(stored, inputs)
        self.assertIsNone(sealed)
        undeclared = _inputs()
        self.assertEqual(seal_input_secrets(undeclared, ()), (undeclared, None))
        self.assertIsNone(seal_input_secrets(_inputs(token=""), PATHS)[1])

    def test_a_row_queued_before_sealing_runs_as_it_was_stored(self) -> None:
        inputs = _inputs()

        for sealed in (None, [], "unexpected"):
            restored, secrets = unseal_input_secrets(inputs, sealed)
            self.assertIs(restored, inputs)
            self.assertEqual(secrets, [])

    def test_the_redactor_reaches_nested_copies_and_rendered_strings(self) -> None:
        redact = redactor_for([TOKEN])
        node_results = [
            {"output": {"interaction": {"token": TOKEN}}},
            {"output": {"url": f"https://discord.com/api/v10/webhooks/1111/{TOKEN}"}},
        ]

        self.assertNotIn(TOKEN, _dumped(redact(node_results)))
        self.assertEqual(node_results[0]["output"]["interaction"]["token"], TOKEN)

    def test_a_run_without_secrets_gets_the_identity(self) -> None:
        value = {"outputs": {"text": "x"}}

        self.assertIs(redactor_for([])(value), value)


class DispatchSealsTests(IsolatedAsyncioTestCase):
    """Without a database: what the dispatcher hands to the queue and the registry."""

    async def _offload(self, paths: tuple) -> tuple[object, dict]:
        inputs = _inputs()
        registered: dict = {}

        def record_registration(**kwargs: object) -> MagicMock:
            registered.update(kwargs)
            return MagicMock()

        enqueue = AsyncMock(return_value=None)
        with (
            patch.object(dispatch_module.settings, "cluster_enabled", True),
            patch.object(dispatch_module, "register_execution", side_effect=record_registration),
            patch.object(dispatch_module, "get_active_execution_handle", return_value=None),
            patch.object(dispatch_module, "relinquish_execution"),
            patch.object(dispatch_module.run_queue, "enqueue", enqueue),
        ):
            await dispatch_workflow(
                workflow_id=uuid.uuid4(),
                nodes=NODES,
                edges=EDGES,
                inputs=inputs,
                trigger_source="discord",
                wait_for_completion=False,
                secret_input_paths=paths,
            )
        self.assertEqual(inputs["interaction"]["token"], TOKEN)
        return enqueue.await_args.args[0], registered

    async def test_an_offloaded_run_is_queued_sealed(self) -> None:
        queued, registered = await self._offload(PATHS)

        self.assertEqual(queued.inputs["interaction"]["token"], REDACTED)
        self.assertEqual(registered["inputs"]["interaction"]["token"], REDACTED)
        self.assertIn(SEALED_SECRETS_OPTION, queued.run_options)
        self.assertNotIn(TOKEN, _dumped(queued.inputs, queued.run_options, registered["inputs"]))

    async def test_a_run_that_declares_no_secret_is_queued_as_before(self) -> None:
        queued, _registered = await self._offload(())

        self.assertEqual(queued.inputs["interaction"]["token"], TOKEN)
        self.assertIsNone(queued.run_options)

    async def test_a_run_here_executes_with_the_callers_own_inputs(self) -> None:
        inputs = _inputs()
        execute = MagicMock(return_value=MagicMock(status="success"))
        with (
            patch.object(dispatch_module.settings, "cluster_enabled", False),
            patch.object(dispatch_module, "execute_workflow", execute),
            patch.object(dispatch_module, "run_error_workflow_for_failed_run", AsyncMock()),
        ):
            await dispatch_workflow(
                workflow_id=uuid.uuid4(),
                nodes=NODES,
                edges=EDGES,
                inputs=inputs,
                secret_input_paths=PATHS,
            )

        self.assertIs(execute.call_args.kwargs["inputs"], inputs)

    async def test_the_discord_route_declares_where_its_token_sits(self) -> None:
        captured: dict = {}

        async def record_dispatch(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            return MagicMock(history_written=True)

        workflow = MagicMock(id=uuid.uuid4(), owner_id=uuid.uuid4(), concurrency_limit=None)
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: workflow))
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=db)
        session.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(discord_api, "async_session_maker", return_value=session),
            patch.object(discord_api, "collect_referenced_workflows", AsyncMock(return_value={})),
            patch.object(discord_api, "get_credentials_context", AsyncMock(return_value={})),
            patch.object(discord_api, "get_global_variables_context", AsyncMock(return_value={})),
            patch.object(discord_api, "dispatch_workflow", side_effect=record_dispatch),
            patch.object(discord_api, "_send_discord_followup_message", AsyncMock()),
        ):
            await discord_api._execute_workflow_background(
                workflow, "d1", {"type": 2, "application_id": "1111", "token": TOKEN}, {}
            )

        self.assertEqual([tuple(path) for path in captured["secret_input_paths"]], list(PATHS))
        self.assertEqual(captured["inputs"]["interaction"]["token"], TOKEN)


async def _history(execution_id: uuid.UUID) -> ExecutionHistory | None:
    async with async_session_maker() as db:
        return await db.get(ExecutionHistory, execution_id)


async def _histories(workflow_id: uuid.UUID) -> list[ExecutionHistory]:
    async with async_session_maker() as db:
        rows = await db.execute(
            select(ExecutionHistory).where(ExecutionHistory.workflow_id == workflow_id)
        )
        return list(rows.scalars().all())


class QueueFullTokenTests(ConcurrencyPostgresCase):
    max_queue = 1

    async def test_a_run_the_full_queue_turns_away_is_recorded_without_the_token(self) -> None:
        async with async_session_maker() as db:
            workflow = await db.get(Workflow, self.workflow_id)
            assert workflow is not None
            workflow.nodes, workflow.edges = NODES, EDGES
            await db.commit()
        await workflow_concurrency.admit(self.held_run())
        await workflow_concurrency.admit(self.held_run())
        async with async_session_maker() as db:
            workflow = await db.get(Workflow, self.workflow_id)

        with patch.object(httpx.AsyncClient, "post", AsyncMock()):
            await discord_api._execute_workflow_background(
                workflow, "d1", {"type": 2, "application_id": "1111", "token": TOKEN}, {}
            )

        rows = [row for row in await _histories(self.workflow_id) if row.status == "queue_full"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].inputs["interaction"]["token"], REDACTED)
        self.assertNotIn(TOKEN, _dumped(rows[0].inputs, rows[0].outputs))


class HeldRunTokenTests(ConcurrencyPostgresCase):
    async def test_a_waiting_run_is_held_sealed_listed_and_cancelled_without_the_token(
        self,
    ) -> None:
        await workflow_concurrency.admit(self.held_run())
        execution_id = uuid.uuid4()

        await dispatch_workflow(
            workflow_id=self.workflow_id,
            nodes=NODES,
            edges=EDGES,
            inputs=_inputs(),
            trigger_source="discord",
            actor_user_id=self.user_id,
            credentials_owner_id=self.user_id,
            execution_id=execution_id,
            concurrency_limit=1,
            wait_for_completion=False,
            secret_input_paths=PATHS,
        )

        row = await self.queue_row(execution_id)
        assert row is not None
        self.assertEqual(row.status, "held")
        self.assertEqual(row.inputs["interaction"]["token"], REDACTED)
        self.assertNotIn(TOKEN, _dumped(row.inputs, row.run_options))
        restored, _secrets = unseal_input_secrets(
            row.inputs, row.run_options[SEALED_SECRETS_OPTION]
        )
        self.assertEqual(restored["interaction"]["token"], TOKEN)

        async with async_session_maker() as db:
            listed = await workflow_concurrency.list_held_runs_for_user(db, self.user_id)
        self.assertNotIn(TOKEN, _dumped([record.inputs for record in listed]))

        self.assertTrue(await workflow_concurrency.cancel_held(self.workflow_id, execution_id))
        history = await _history(execution_id)
        assert history is not None
        self.assertEqual(history.status, "cancelled")
        self.assertNotIn(TOKEN, _dumped(history.inputs, history.outputs))


class WorkerTokenTests(ConcurrencyPostgresCase):
    limit = None

    async def test_the_worker_runs_with_the_token_and_writes_rows_without_it(self) -> None:
        async with async_session_maker() as db:
            workflow = await db.get(Workflow, self.workflow_id)
            assert workflow is not None
            workflow.nodes, workflow.edges = NODES, EDGES
            await db.commit()
        execution_id = uuid.uuid4()
        with patch.object(dispatch_module.settings, "cluster_enabled", True):
            await dispatch_workflow(
                workflow_id=self.workflow_id,
                nodes=NODES,
                edges=EDGES,
                inputs=_inputs(),
                trigger_source="discord",
                actor_user_id=self.user_id,
                credentials_owner_id=self.user_id,
                execution_id=execution_id,
                wait_for_completion=False,
                secret_input_paths=PATHS,
            )
        row = await self.queue_row(execution_id)
        assert row is not None
        self.assertNotIn(TOKEN, _dumped(row.inputs, row.run_options))

        seen: list[dict] = []
        real_execute = dispatch_module.execute_workflow

        def recording_execute(**kwargs: object) -> object:
            seen.append(kwargs["inputs"])  # type: ignore[arg-type]
            return real_execute(**kwargs)

        with patch.object(dispatch_module, "execute_workflow", recording_execute):
            await RunQueueWorker()._execute_claimed(row)

        self.assertEqual(seen[0]["interaction"]["token"], TOKEN)
        history = await _history(execution_id)
        assert history is not None
        self.assertEqual(history.status, "success")
        self.assertIn(REDACTED, _dumped(history.outputs))
        self.assertNotIn(TOKEN, _dumped(history.inputs, history.outputs, history.node_results))
        finished = await self.queue_row(execution_id)
        assert finished is not None
        self.assertEqual(finished.status, "done")
        self.assertNotIn(TOKEN, _dumped(finished.inputs, finished.result, finished.run_options))
