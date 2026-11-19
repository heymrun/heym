"""Run history encryption: what reaches the database, who can unlock it, and what's audited."""

from __future__ import annotations

import inspect
import json
import uuid
from datetime import datetime, timezone
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

from app.api.workflows import set_run_history_encryption, unlock_execution_history_entry
from app.db.models import (
    ActiveWorkflowExecution,
    ExecutionHistory,
    User,
    UserHistoryKey,
    Workflow,
    WorkflowRunQueue,
    WorkflowShare,
)
from app.models import schemas
from app.models.schemas import NodeResultSchema, RunHistoryEncryptionUpdate
from app.services import run_history_encryption as rhe
from app.services import workflow_concurrency
from app.services.cluster import run_queue
from app.services.secret_tokens import hash_secret
from app.services.workflow_run_history_tool import get_workflow_run_history
from tests.isolated_postgres import create_isolated_database

SECRET_INPUT = "jane.doe@example.com"
SECRET_OUTPUT = "IBAN DE89 3704 0044 0532 0130 00"


def _node_results() -> list[dict]:
    return [
        {
            "node_id": "n1",
            "node_label": "Lookup",
            "node_type": "httpRequest",
            "status": "success",
            "output": {"body": SECRET_OUTPUT},
            "execution_time_ms": 12.5,
            "error": f"failed for {SECRET_INPUT}",
            "metadata": {
                "started_at_ms": 1_750_000_000_000,
                "tool_calls": [{"arguments": SECRET_INPUT}],
                "hitl": {"summary": SECRET_INPUT},
            },
        }
    ]


class SealingTests(TestCase):
    def setUp(self) -> None:
        self.key = rhe._derive_key(b"k" * 32)
        self.row_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()

    def test_round_trip(self) -> None:
        payload = {"inputs": {"email": SECRET_INPUT}, "outputs": {}, "node_results": []}
        token = rhe.seal_payload(self.key, self.row_id, self.workflow_id, payload)
        self.assertNotIn(SECRET_INPUT, token)
        self.assertEqual(rhe.open_payload(self.key, self.row_id, self.workflow_id, token), payload)

    def test_ciphertext_opens_only_on_its_own_row(self) -> None:
        token = rhe.seal_payload(self.key, self.row_id, self.workflow_id, {"inputs": {}})
        with self.assertRaises(rhe.RunHistoryUnavailableError):
            rhe.open_payload(self.key, uuid.uuid4(), self.workflow_id, token)
        with self.assertRaises(rhe.RunHistoryUnavailableError):
            rhe.open_payload(self.key, self.row_id, uuid.uuid4(), token)

    def test_wrong_key_and_tampering_fail(self) -> None:
        token = rhe.seal_payload(self.key, self.row_id, self.workflow_id, {"inputs": {}})
        other = rhe._derive_key(b"o" * 32)
        with self.assertRaises(rhe.RunHistoryUnavailableError):
            rhe.open_payload(other, self.row_id, self.workflow_id, token)
        tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
        with self.assertRaises(rhe.RunHistoryUnavailableError):
            rhe.open_payload(self.key, self.row_id, self.workflow_id, tampered)

    def test_skeleton_keeps_no_data(self) -> None:
        skeleton = rhe.node_results_skeleton(_node_results())
        dumped = json.dumps(skeleton)
        self.assertNotIn(SECRET_INPUT, dumped)
        self.assertNotIn(SECRET_OUTPUT, dumped)
        self.assertEqual(skeleton[0]["node_label"], "Lookup")
        self.assertEqual(skeleton[0]["status"], "success")
        self.assertEqual(skeleton[0]["metadata"], {"started_at_ms": 1_750_000_000_000})
        NodeResultSchema.model_validate(skeleton[0])

    def test_no_api_schema_carries_key_material(self) -> None:
        forbidden = {"wrapped_key", "encrypted_payload", "encryption_key_user_id", "history_key"}
        for _name, model in inspect.getmembers(schemas, inspect.isclass):
            if issubclass(model, BaseModel) and model is not BaseModel:
                self.assertFalse(forbidden & set(model.model_fields), model.__name__)


class RunHistoryEncryptionPostgresTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = await create_isolated_database(self)
        self.owner = User(id=uuid.uuid4(), email="owner@example.com", hashed_password="x", name="o")
        self.reader = User(
            id=uuid.uuid4(), email="reader@example.com", hashed_password="x", name="r"
        )
        self.stranger = User(
            id=uuid.uuid4(), email="stranger@example.com", hashed_password="x", name="s"
        )
        self.workflow = Workflow(
            id=uuid.uuid4(),
            name="Payroll",
            owner_id=self.owner.id,
            nodes=[],
            edges=[],
            encrypt_run_history=True,
        )
        self.plain_workflow = Workflow(
            id=uuid.uuid4(), name="Plain", owner_id=self.owner.id, nodes=[], edges=[]
        )
        self.sub_workflow = Workflow(
            id=uuid.uuid4(), name="Sub", owner_id=self.owner.id, nodes=[], edges=[]
        )
        async with self.database.sessions() as db:
            db.add_all([self.owner, self.reader, self.stranger])
            await db.flush()
            db.add_all([self.workflow, self.plain_workflow, self.sub_workflow])
            await db.flush()
            db.add(
                WorkflowShare(
                    workflow_id=self.workflow.id, user_id=self.reader.id, permission="read"
                )
            )
            await db.commit()

    async def asyncTearDown(self) -> None:
        await self.database.drop()

    async def _write(self, workflow_id: uuid.UUID, **extra: object) -> uuid.UUID:
        row_id = uuid.uuid4()
        async with self.database.sessions() as db:
            db.add(
                ExecutionHistory(
                    id=row_id,
                    workflow_id=workflow_id,
                    inputs={"email": SECRET_INPUT},
                    outputs={"iban": SECRET_OUTPUT},
                    node_results=_node_results(),
                    execution_time_ms=20.0,
                    **{"status": "success", **extra},
                )
            )
            await db.commit()
        return row_id

    async def _raw(self, row_id: uuid.UUID) -> dict:
        async with self.database.sessions() as db:
            row = (
                await db.execute(
                    select(
                        ExecutionHistory.inputs,
                        ExecutionHistory.outputs,
                        ExecutionHistory.node_results,
                        ExecutionHistory.encrypted,
                        ExecutionHistory.encrypted_payload,
                        ExecutionHistory.encryption_key_user_id,
                    ).where(ExecutionHistory.id == row_id)
                )
            ).one()
        return dict(row._mapping)

    async def _open(self, row_id: uuid.UUID) -> rhe.RunPayload:
        async with self.database.sessions() as db:
            row = await db.get(ExecutionHistory, row_id)
            return await rhe.open_run_payload(db, row)

    def assert_no_plaintext(self, raw: dict) -> None:
        dumped = json.dumps(raw, default=str)
        self.assertNotIn(SECRET_INPUT, dumped)
        self.assertNotIn(SECRET_OUTPUT, dumped)

    async def test_orm_write_is_encrypted_at_rest(self) -> None:
        row_id = await self._write(self.workflow.id)
        raw = await self._raw(row_id)
        self.assertTrue(raw["encrypted"])
        self.assertEqual(raw["encryption_key_user_id"], self.owner.id)
        self.assertEqual(raw["inputs"], {})
        self.assertEqual(raw["outputs"], {})
        self.assert_no_plaintext(raw)
        opened = await self._open(row_id)
        self.assertEqual(opened.inputs, {"email": SECRET_INPUT})
        self.assertEqual(opened.outputs, {"iban": SECRET_OUTPUT})
        self.assertEqual(opened.node_results, _node_results())

    async def test_key_is_wrapped_and_stored_once_per_owner(self) -> None:
        await self._write(self.workflow.id)
        await self._write(self.workflow.id)
        async with self.database.sessions() as db:
            keys = (await db.execute(select(UserHistoryKey))).scalars().all()
        self.assertEqual([key.user_id for key in keys], [self.owner.id])
        from app.services.encryption import decrypt_text

        self.assertTrue(decrypt_text(keys[0].wrapped_key))

    async def test_other_workflows_stay_plain(self) -> None:
        raw = await self._raw(await self._write(self.plain_workflow.id))
        self.assertFalse(raw["encrypted"])
        self.assertEqual(raw["inputs"], {"email": SECRET_INPUT})

    async def test_turning_it_off_leaves_earlier_runs_encrypted(self) -> None:
        sealed = await self._write(self.workflow.id)
        async with self.database.sessions() as db:
            await db.execute(
                update(Workflow)
                .where(Workflow.id == self.workflow.id)
                .values(encrypt_run_history=False)
            )
            await db.commit()
        plain = await self._write(self.workflow.id)
        self.assertTrue((await self._raw(sealed))["encrypted"])
        self.assertFalse((await self._raw(plain))["encrypted"])

    async def test_sub_workflow_runs_of_an_encrypted_run_are_encrypted(self) -> None:
        parent_id, sub_id = uuid.uuid4(), uuid.uuid4()
        async with self.database.sessions() as db:
            db.add(
                ExecutionHistory(
                    id=parent_id,
                    workflow_id=self.workflow.id,
                    inputs={"email": SECRET_INPUT},
                    outputs={},
                    node_results=[],
                    status="success",
                    execution_time_ms=1.0,
                )
            )
            # A separate flush, as when an analytics upsert autoflushes between the two.
            await db.flush()
            db.add(
                ExecutionHistory(
                    id=sub_id,
                    workflow_id=self.sub_workflow.id,
                    inputs={"email": SECRET_INPUT},
                    outputs={"iban": SECRET_OUTPUT},
                    node_results=[],
                    status="success",
                    execution_time_ms=1.0,
                    trigger_source=rhe.SUB_RUN_TRIGGER,
                )
            )
            await db.commit()
        raw = await self._raw(sub_id)
        self.assertTrue(raw["encrypted"])
        self.assert_no_plaintext(raw)
        self.assertEqual((await self._open(sub_id)).inputs, {"email": SECRET_INPUT})

    async def test_updating_some_fields_keeps_the_others(self) -> None:
        row_id = await self._write(self.workflow.id, status="pending")
        async with self.database.sessions() as db:
            row = await db.get(ExecutionHistory, row_id)
            row.outputs = {"answer": "approved"}
            row.status = "success"
            await db.commit()
        opened = await self._open(row_id)
        self.assertEqual(opened.inputs, {"email": SECRET_INPUT})
        self.assertEqual(opened.outputs, {"answer": "approved"})
        self.assertEqual(opened.node_results, _node_results())

    async def test_unseal_in_place_round_trips_a_read_modify_write(self) -> None:
        row_id = await self._write(self.workflow.id)
        async with self.database.sessions() as db:
            row = await db.get(ExecutionHistory, row_id)
            await rhe.unseal_in_place(db, row)
            row.node_results = [{**row.node_results[0], "status": "cancelled"}]
            await db.commit()
        raw = await self._raw(row_id)
        self.assert_no_plaintext(raw)
        opened = await self._open(row_id)
        self.assertEqual(opened.node_results[0]["status"], "cancelled")
        self.assertEqual(opened.node_results[0]["output"], {"body": SECRET_OUTPUT})

    async def test_core_insert_values_are_sealed(self) -> None:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        row_id = uuid.uuid4()
        async with self.database.sessions() as db:
            values = await rhe.seal_insert_values(
                db,
                {
                    "id": row_id,
                    "workflow_id": self.workflow.id,
                    "inputs": {"email": SECRET_INPUT},
                    "outputs": {"error": "Execution was cancelled"},
                    "node_results": [],
                    "status": "cancelled",
                    "execution_time_ms": 0.0,
                },
            )
            await db.execute(pg_insert(ExecutionHistory).values(**values))
            await db.commit()
        raw = await self._raw(row_id)
        self.assertTrue(raw["encrypted"])
        self.assert_no_plaintext(raw)
        self.assertEqual((await self._open(row_id)).inputs, {"email": SECRET_INPUT})

    async def test_ciphertext_copied_to_another_row_does_not_open(self) -> None:
        source = await self._write(self.workflow.id)
        target = await self._write(self.workflow.id)
        stolen = (await self._raw(source))["encrypted_payload"]
        async with self.database.sessions() as db:
            await db.execute(
                update(ExecutionHistory)
                .where(ExecutionHistory.id == target)
                .values(encrypted_payload=stolen)
            )
            await db.commit()
        with self.assertRaises(rhe.RunHistoryUnavailableError):
            await self._open(target)

    async def test_unlock_returns_the_data_and_audits_a_read_share(self) -> None:
        row_id = await self._write(self.workflow.id)
        async with self.database.sessions() as db:
            reader = await db.get(User, self.reader.id)
            with self.assertLogs("winston.audit", level="INFO") as logs:
                response = await unlock_execution_history_entry(row_id, current_user=reader, db=db)
        self.assertEqual(response.inputs, {"email": SECRET_INPUT})
        self.assertTrue(response.encrypted)
        line = "\n".join(logs.output)
        self.assertIn("action=workflow.history_unlock", line)
        self.assertIn("outcome=success", line)
        self.assertIn("permission=read", line)

    async def test_unlock_is_refused_without_workflow_access(self) -> None:
        row_id = await self._write(self.workflow.id)
        async with self.database.sessions() as db:
            stranger = await db.get(User, self.stranger.id)
            with self.assertLogs("winston.audit", level="INFO") as logs:
                with self.assertRaises(HTTPException) as caught:
                    await unlock_execution_history_entry(row_id, current_user=stranger, db=db)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertIn("outcome=denied", "\n".join(logs.output))

    async def test_unlock_refuses_a_plain_run(self) -> None:
        row_id = await self._write(self.plain_workflow.id)
        async with self.database.sessions() as db:
            owner = await db.get(User, self.owner.id)
            with self.assertRaises(HTTPException) as caught:
                await unlock_execution_history_entry(row_id, current_user=owner, db=db)
        self.assertEqual(caught.exception.status_code, 400)

    async def test_only_the_owner_toggles_and_every_toggle_is_audited(self) -> None:
        async with self.database.sessions() as db:
            reader = await db.get(User, self.reader.id)
            with self.assertLogs("winston.audit", level="INFO") as logs:
                with self.assertRaises(HTTPException) as caught:
                    await set_run_history_encryption(
                        self.workflow.id,
                        RunHistoryEncryptionUpdate(enabled=False),
                        current_user=reader,
                        db=db,
                    )
        self.assertEqual(caught.exception.status_code, 403)
        self.assertIn("outcome=denied", "\n".join(logs.output))

        async with self.database.sessions() as db:
            owner = await db.get(User, self.owner.id)
            with self.assertLogs("winston.audit", level="INFO") as logs:
                response = await set_run_history_encryption(
                    self.plain_workflow.id,
                    RunHistoryEncryptionUpdate(enabled=True),
                    current_user=owner,
                    db=db,
                )
        self.assertTrue(response.encrypt_run_history)
        line = "\n".join(logs.output)
        self.assertIn("action=workflow.run_history_encryption", line)
        self.assertIn("enabled=true", line.lower())
        self.assertTrue((await self._raw(await self._write(self.plain_workflow.id)))["encrypted"])

    async def test_chat_run_history_tool_skips_encrypted_runs(self) -> None:
        sealed = await self._write(self.workflow.id)
        async with self.database.sessions() as db:
            listing = await get_workflow_run_history(
                db, self.owner.id, {"workflow_id": str(self.workflow.id)}
            )
            detail = await get_workflow_run_history(
                db,
                self.owner.id,
                {"workflow_id": str(self.workflow.id), "execution_id": str(sealed)},
            )
        self.assertEqual(listing["runs"], [])
        self.assertEqual(listing["encrypted_runs_skipped"], 1)
        self.assertEqual(listing["total_runs"], 1)
        self.assertTrue(detail["encrypted"])
        self.assertNotIn("inputs", detail)


class QueuedRunEncryptionPostgresTests(IsolatedAsyncioTestCase):
    """The queue row a queued run leaves behind, and who reads its outputs."""

    async def asyncSetUp(self) -> None:
        self.database = await create_isolated_database(self)
        self.owner = User(id=uuid.uuid4(), email="owner@example.com", hashed_password="x", name="o")
        self.workflow = Workflow(
            id=uuid.uuid4(),
            name="Payroll",
            owner_id=self.owner.id,
            nodes=[],
            edges=[],
            encrypt_run_history=True,
        )
        async with self.database.sessions() as db:
            db.add(self.owner)
            await db.flush()
            db.add(self.workflow)
            await db.commit()
        self.token = "run-token-for-tests"
        self.sessions = patch.multiple(
            "app.services.workflow_concurrency", async_session_maker=self.database.sessions
        )
        self.queue_sessions = patch.object(run_queue, "async_session_maker", self.database.sessions)
        self.sessions.start()
        self.queue_sessions.start()

    async def asyncTearDown(self) -> None:
        self.sessions.stop()
        self.queue_sessions.stop()
        await self.database.drop()

    async def _queue_row(self, *, status: str = "done") -> uuid.UUID:
        execution_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        async with self.database.sessions() as db:
            inputs = await rhe.seal_queue_inputs(
                db,
                workflow_id=self.workflow.id,
                execution_id=execution_id,
                inputs={"email": SECRET_INPUT},
            )
            db.add(
                WorkflowRunQueue(
                    workflow_id=self.workflow.id,
                    execution_id=execution_id,
                    placement="anywhere",
                    status=status,
                    inputs=inputs,
                    enqueued_at=now,
                    not_after=now,
                    status_token_hash=hash_secret(self.token),
                )
            )
            await db.commit()
        return execution_id

    async def _raw(self, execution_id: uuid.UUID) -> dict:
        async with self.database.sessions() as db:
            row = (
                await db.execute(
                    select(WorkflowRunQueue.inputs, WorkflowRunQueue.result).where(
                        WorkflowRunQueue.execution_id == execution_id
                    )
                )
            ).one()
        return dict(row._mapping)

    async def _finish(self, execution_id: uuid.UUID) -> None:
        await run_queue.complete(
            execution_id,
            result={
                "execution_id": str(execution_id),
                "status": "success",
                "outputs": {"iban": SECRET_OUTPUT},
                "execution_time_ms": 12.0,
                "error": None,
                "failed_node": None,
            },
            error=None,
        )

    async def test_queue_row_holds_no_plaintext(self) -> None:
        execution_id = await self._queue_row()
        await self._finish(execution_id)
        raw = await self._raw(execution_id)
        dumped = json.dumps(raw, default=str)
        self.assertNotIn(SECRET_INPUT, dumped)
        self.assertNotIn(SECRET_OUTPUT, dumped)
        self.assertEqual(raw["result"]["status"], "success")
        async with self.database.sessions() as db:
            opened = await rhe.open_queue_inputs(
                db, workflow_id=self.workflow.id, execution_id=execution_id, inputs=raw["inputs"]
            )
        self.assertEqual(opened, {"email": SECRET_INPUT})
        self.assertEqual(rhe.queue_inputs_for_display(raw["inputs"]), {})

    async def test_the_waiting_dispatcher_reads_the_real_result(self) -> None:
        execution_id = await self._queue_row()
        await self._finish(execution_id)
        status, result, error = await run_queue.read_terminal_result(execution_id)
        self.assertEqual((status, error), ("done", None))
        self.assertEqual(result["outputs"], {"iban": SECRET_OUTPUT})

    async def test_status_url_returns_outputs_only_with_the_run_token(self) -> None:
        execution_id = await self._queue_row()
        await self._finish(execution_id)

        anyone = await workflow_concurrency.build_status_body(self.workflow.id, execution_id)
        self.assertIsNone(anyone["outputs"])
        self.assertTrue(anyone["encrypted"])
        self.assertEqual(anyone["status"], "success")
        self.assertNotIn(SECRET_OUTPUT, json.dumps(anyone, default=str))

        wrong = await workflow_concurrency.build_status_body(
            self.workflow.id, execution_id, run_token="not-the-token"
        )
        self.assertIsNone(wrong["outputs"])

        caller = await workflow_concurrency.build_status_body(
            self.workflow.id, execution_id, run_token=self.token
        )
        self.assertEqual(caller["outputs"], {"iban": SECRET_OUTPUT})

        stream = await workflow_concurrency.build_status_body(
            self.workflow.id, execution_id, trusted=True
        )
        self.assertEqual(stream["outputs"], {"iban": SECRET_OUTPUT})

    async def test_status_url_reads_encrypted_history_the_same_way(self) -> None:
        execution_id = await self._queue_row(status="done")
        await run_queue.complete(
            execution_id,
            result={"execution_id": str(execution_id), "status": "pending", "outputs": {}},
            error=None,
        )
        async with self.database.sessions() as db:
            db.add(
                ExecutionHistory(
                    id=execution_id,
                    workflow_id=self.workflow.id,
                    inputs={"email": SECRET_INPUT},
                    outputs={"iban": SECRET_OUTPUT},
                    node_results=[],
                    status="success",
                    execution_time_ms=3.0,
                )
            )
            await db.commit()

        anyone = await workflow_concurrency.build_status_body(self.workflow.id, execution_id)
        self.assertIsNone(anyone["outputs"])
        self.assertTrue(anyone["encrypted"])
        caller = await workflow_concurrency.build_status_body(
            self.workflow.id, execution_id, run_token=self.token
        )
        self.assertEqual(caller["outputs"], {"iban": SECRET_OUTPUT})

    async def test_queue_ciphertext_does_not_open_as_history(self) -> None:
        execution_id = await self._queue_row()
        raw = await self._raw(execution_id)
        async with self.database.sessions() as db:
            key = await db.run_sync(
                lambda session: rhe.user_key(session.connection(), self.owner.id, create=False)
            )
        with self.assertRaises(rhe.RunHistoryUnavailableError):
            rhe.open_payload(key, execution_id, self.workflow.id, raw["inputs"][rhe.QUEUE_SEALED])


class QueuedRunTokenTests(TestCase):
    def test_a_queued_mcp_result_carries_the_run_token(self) -> None:
        from app.services import mcp_execution_status

        admission = workflow_concurrency.Admission(
            kind="queued", execution_id=uuid.uuid4(), status_token="tok"
        )
        text, is_error = mcp_execution_status.admission_tool_text(admission)
        self.assertFalse(is_error)
        self.assertEqual(json.loads(text)["run_token"], "tok")
        tool = mcp_execution_status.build_execution_status_tool()
        self.assertIn("run_token", tool.inputSchema.properties)


class LiveRunEncryptionPostgresTests(IsolatedAsyncioTestCase):
    """A running execution's registry row, and the audited unlock before watching it."""

    async def asyncSetUp(self) -> None:
        self.database = await create_isolated_database(self)
        self.owner = User(id=uuid.uuid4(), email="owner@example.com", hashed_password="x", name="o")
        self.workflow = Workflow(
            id=uuid.uuid4(),
            name="Payroll",
            owner_id=self.owner.id,
            nodes=[],
            edges=[],
            encrypt_run_history=True,
        )
        async with self.database.sessions() as db:
            db.add(self.owner)
            await db.flush()
            db.add(self.workflow)
            await db.commit()
        self.patches = [
            patch("app.api.workflows.async_session_maker", self.database.sessions),
        ]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self) -> None:
        for item in self.patches:
            item.stop()
        await self.database.drop()

    async def _start(self) -> uuid.UUID:
        from app.services.execution_cancellation import ActiveExecutionRegistry, _RegistryCommand

        execution_id = uuid.uuid4()
        command = _RegistryCommand(
            action="start",
            execution_id=execution_id,
            workflow_id=self.workflow.id,
            inputs={"email": SECRET_INPUT},
            trigger_source="api",
        )
        async with self.database.sessions() as db:
            await ActiveExecutionRegistry()._apply_command(db, command, datetime.now(timezone.utc))
            await db.commit()
        return execution_id

    async def test_registry_row_holds_no_plaintext(self) -> None:
        execution_id = await self._start()
        async with self.database.sessions() as db:
            sealed = await rhe.seal_active_values(
                db,
                workflow_id=self.workflow.id,
                execution_id=execution_id,
                node_results=_node_results(),
            )
            await db.execute(
                update(ActiveWorkflowExecution)
                .where(ActiveWorkflowExecution.execution_id == execution_id)
                .values(**sealed)
            )
            await db.commit()
            row = (
                await db.execute(
                    select(ActiveWorkflowExecution).where(
                        ActiveWorkflowExecution.execution_id == execution_id
                    )
                )
            ).scalar_one()
            dumped = json.dumps(
                [row.inputs, row.node_results, row.encrypted_node_results], default=str
            )
            self.assertNotIn(SECRET_INPUT, dumped)
            self.assertNotIn(SECRET_OUTPUT, dumped)
            inputs = await rhe.open_active_inputs(
                db, workflow_id=self.workflow.id, execution_id=execution_id, inputs=row.inputs
            )
            node_results = await rhe.open_active_node_results(
                db,
                workflow_id=self.workflow.id,
                execution_id=execution_id,
                node_results=row.node_results,
                sealed=row.encrypted_node_results,
            )
        self.assertEqual(inputs, {"email": SECRET_INPUT})
        self.assertEqual(node_results, _node_results())
        self.assertEqual(rhe.queue_inputs_for_display(row.inputs), {})

    def _request(self) -> object:
        from unittest.mock import AsyncMock, MagicMock

        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=True)
        return request

    async def test_watching_live_needs_an_unlock_and_is_audited(self) -> None:
        from app.api.workflows import stream_active_workflow_execution

        execution_id = await self._start()
        async with self.database.sessions() as db:
            owner = await db.get(User, self.owner.id)
            with self.assertRaises(HTTPException) as caught:
                await stream_active_workflow_execution(
                    self.workflow.id,
                    execution_id,
                    self._request(),
                    unlock=False,
                    current_user=owner,
                    db=db,
                )
            self.assertEqual(caught.exception.status_code, 423)

            with self.assertLogs("winston.audit", level="INFO") as logs:
                response = await stream_active_workflow_execution(
                    self.workflow.id,
                    execution_id,
                    self._request(),
                    unlock=True,
                    current_user=owner,
                    db=db,
                )
        line = "\n".join(logs.output)
        self.assertIn("action=workflow.live_run_unlock", line)
        self.assertIn("owned=true", line.lower())
        first = await response.body_iterator.__anext__()
        self.assertIn(SECRET_INPUT, first)

    async def test_a_paused_encrypted_run_streams_its_data_only_after_an_unlock(self) -> None:
        from app.api.workflows import stream_workflow_execution_history_entry

        execution_id = uuid.uuid4()
        async with self.database.sessions() as db:
            db.add(
                ExecutionHistory(
                    id=execution_id,
                    workflow_id=self.workflow.id,
                    inputs={"email": SECRET_INPUT},
                    outputs={},
                    node_results=_node_results(),
                    status="pending",
                    execution_time_ms=1.0,
                )
            )
            await db.commit()

        async def first_frame(unlock: bool) -> str:
            async with self.database.sessions() as db:
                owner = await db.get(User, self.owner.id)
                response = await stream_workflow_execution_history_entry(
                    self.workflow.id,
                    execution_id,
                    self._request_open(),
                    unlock=unlock,
                    current_user=owner,
                    db=db,
                )
            return await response.body_iterator.__anext__()

        locked = await first_frame(False)
        self.assertNotIn(SECRET_INPUT, locked)
        self.assertIn('"encrypted": true', locked)
        with self.assertLogs("winston.audit", level="INFO") as logs:
            opened = await first_frame(True)
        self.assertIn(SECRET_INPUT, opened)
        self.assertIn(SECRET_OUTPUT, opened)
        self.assertIn("action=workflow.live_run_unlock", "\n".join(logs.output))

    def _request_open(self) -> object:
        from unittest.mock import AsyncMock, MagicMock

        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)
        return request
