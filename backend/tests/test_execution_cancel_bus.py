"""Cancel must reach the worker running the execution, not just the one serving HTTP.

Under `uvicorn --workers N` the cancel request almost never lands on the owning
worker, and the fallback poll reads the busiest table in the schema. These tests
cover the NOTIFY path that carries the stop independently of that table.
"""

import threading
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import SQLAlchemyError

from app.services.execution_cancel_bus import (
    CANCEL_CHANNEL,
    ExecutionCancelListener,
    decode_cancel_payload,
    encode_cancel_payload,
    publish_execution_cancel,
)
from app.services.execution_cancellation import (
    _ACTIVE_EXECUTIONS,
    register_execution,
    request_persisted_execution_cancel,
)


class CancelPayloadTests(unittest.TestCase):
    def test_round_trips(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        decoded = decode_cancel_payload(encode_cancel_payload(workflow_id, execution_id))
        self.assertEqual((workflow_id, execution_id), decoded)

    def test_malformed_payloads_are_rejected(self) -> None:
        for payload in ["", "nope", "not-a-uuid:also-not", str(uuid.uuid4()), None]:
            self.assertIsNone(decode_cancel_payload(payload))  # type: ignore[arg-type]


class CancelListenerTests(unittest.TestCase):
    def setUp(self) -> None:
        _ACTIVE_EXECUTIONS.clear()
        self.listener = ExecutionCancelListener()

    def tearDown(self) -> None:
        _ACTIVE_EXECUTIONS.clear()

    def test_broadcast_stops_a_locally_owned_execution(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        event = register_execution(workflow_id=workflow_id, execution_id=execution_id)
        self.assertFalse(event.is_set())

        applied = self.listener.handle_payload(encode_cancel_payload(workflow_id, execution_id))

        self.assertTrue(applied)
        self.assertTrue(event.is_set())

    def test_broadcast_for_another_worker_is_a_no_op(self) -> None:
        event = threading.Event()
        register_execution(workflow_id=uuid.uuid4(), execution_id=uuid.uuid4(), event=event)

        applied = self.listener.handle_payload(encode_cancel_payload(uuid.uuid4(), uuid.uuid4()))

        self.assertFalse(applied)
        self.assertFalse(event.is_set())

    def test_mismatched_workflow_does_not_cancel(self) -> None:
        execution_id = uuid.uuid4()
        event = register_execution(workflow_id=uuid.uuid4(), execution_id=execution_id)

        applied = self.listener.handle_payload(encode_cancel_payload(uuid.uuid4(), execution_id))

        self.assertFalse(applied)
        self.assertFalse(event.is_set())

    def test_malformed_payload_is_ignored(self) -> None:
        self.assertFalse(self.listener.handle_payload("garbage"))


class PublishCancelTests(unittest.IsolatedAsyncioTestCase):
    async def test_publishes_on_the_shared_channel(self) -> None:
        session = AsyncMock()
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()

        await publish_execution_cancel(session, workflow_id=workflow_id, execution_id=execution_id)

        params = session.execute.await_args.args[1]
        self.assertEqual(CANCEL_CHANNEL, params["channel"])
        self.assertEqual(encode_cancel_payload(workflow_id, execution_id), params["payload"])
        self.assertIn("pg_notify", str(session.execute.await_args.args[0]))


class RequestPersistedCancelTests(unittest.IsolatedAsyncioTestCase):
    def _session(self, *, update_raises: bool = False, rowcount: int = 1) -> MagicMock:
        db = MagicMock()
        savepoint = MagicMock()
        savepoint.__aenter__ = AsyncMock(return_value=savepoint)
        savepoint.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=savepoint)
        db.commit = AsyncMock()

        calls: list[object] = []

        async def execute(statement, params=None):
            calls.append(statement)
            if "pg_notify" in str(statement):
                return MagicMock()
            if update_raises:
                raise SQLAlchemyError("could not read block 189")
            res = MagicMock(rowcount=rowcount)
            res.scalar_one_or_none.return_value = None
            return res

        db.execute = AsyncMock(side_effect=execute)
        db.calls = calls
        return db

    async def test_broadcast_still_goes_out_when_the_row_update_fails(self) -> None:
        db = self._session(update_raises=True)

        result = await request_persisted_execution_cancel(
            db, workflow_id=uuid.uuid4(), execution_id=uuid.uuid4()
        )

        self.assertTrue(any("pg_notify" in str(call) for call in db.calls))
        db.commit.assert_awaited_once()
        # State is unknown, so the caller must not report "not found".
        self.assertTrue(result)

    async def test_reports_not_found_only_when_the_row_is_provably_absent(self) -> None:
        db = self._session(rowcount=0)

        result = await request_persisted_execution_cancel(
            db, workflow_id=uuid.uuid4(), execution_id=uuid.uuid4()
        )

        self.assertFalse(result)
        self.assertTrue(any("pg_notify" in str(call) for call in db.calls))

    async def test_marked_row_reports_success(self) -> None:
        db = self._session(rowcount=1)

        result = await request_persisted_execution_cancel(
            db, workflow_id=uuid.uuid4(), execution_id=uuid.uuid4()
        )

        self.assertTrue(result)


class ListenerReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_failure_is_retried_not_fatal(self) -> None:
        listener = ExecutionCancelListener()
        attempts = 0

        async def connect(_dsn):
            nonlocal attempts
            attempts += 1
            if attempts >= 3:
                listener._running = False
            raise OSError("connection refused")

        with (
            patch("app.services.execution_cancel_bus.asyncpg.connect", connect),
            patch("app.services.execution_cancel_bus._RECONNECT_DELAY_SECONDS", 0),
        ):
            listener._running = True
            await listener._run_loop()

        self.assertGreaterEqual(attempts, 3)
        self.assertFalse(listener.is_connected)


if __name__ == "__main__":
    unittest.main()
