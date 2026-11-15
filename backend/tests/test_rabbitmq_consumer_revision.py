"""Tests for RabbitMQ consumers reconnecting when their credential or node settings change."""

from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from aio_pika.robust_channel import RobustChannel
from aio_pika.robust_connection import RobustConnection
from aio_pika.robust_queue import RobustQueue

from app.services.encryption import encrypt_config
from app.services.rabbitmq_consumer import (
    ConsumerInfo,
    RabbitMQConsumerManager,
    config_revision,
)


def _rabbitmq_config(password: str = "first-password") -> dict[str, object]:
    return {
        "rabbitmq_host": "rabbitmq.internal",
        "rabbitmq_port": 5672,
        "rabbitmq_username": "heym",
        "rabbitmq_password": password,
        "rabbitmq_vhost": "/",
    }


def _workflow(credential_id: uuid.UUID) -> MagicMock:
    workflow = MagicMock()
    workflow.id = uuid.uuid4()
    workflow.nodes = [
        {
            "id": "rmq-node-1",
            "type": "rabbitmq",
            "data": {
                "rabbitmqOperation": "receive",
                "active": True,
                "credentialId": str(credential_id),
                "rabbitmqQueueName": "orders_queue",
            },
        }
    ]
    return workflow


class ConfigRevisionTests(unittest.TestCase):
    def test_same_value_gives_same_revision_whatever_the_key_order(self) -> None:
        config = _rabbitmq_config()
        reordered = dict(reversed(list(config.items())))

        self.assertEqual(config_revision(config), config_revision(reordered))

    def test_changed_value_gives_a_different_revision(self) -> None:
        self.assertNotEqual(
            config_revision(_rabbitmq_config("first-password")),
            config_revision(_rabbitmq_config("second-password")),
        )

    def test_revision_is_short_and_does_not_contain_the_value(self) -> None:
        revision = config_revision(_rabbitmq_config("first-password"))

        self.assertEqual(len(revision), 16)
        self.assertNotIn("first-password", revision)

    def test_revision_cannot_be_checked_without_the_process_key(self) -> None:
        """A plain digest of canonical JSON would let anyone test password guesses."""
        config = _rabbitmq_config()
        canonical = json.dumps(config, sort_keys=True).encode("utf-8")

        self.assertNotEqual(config_revision(config), hashlib.sha256(canonical).hexdigest()[:16])
        with patch("app.services.rabbitmq_consumer._REVISION_KEY", b"another-process"):
            other_process = config_revision(config)
        self.assertNotEqual(config_revision(config), other_process)

    def test_missing_config_has_a_fixed_revision(self) -> None:
        self.assertEqual(config_revision(None), "unavailable")


class RabbitMQConsumerSyncTests(unittest.IsolatedAsyncioTestCase):
    """A consumer reconnects when what it connected with changes, and only then."""

    def setUp(self) -> None:
        self.manager = RabbitMQConsumerManager()
        self.credential_id = uuid.uuid4()
        self.workflow = _workflow(self.credential_id)
        self.encrypted_config = encrypt_config(_rabbitmq_config())

        self.db = AsyncMock()
        self.db.execute = AsyncMock(side_effect=self._credential_rows)
        self.session_ctx = MagicMock()
        self.session_ctx.__aenter__ = AsyncMock(return_value=self.db)
        self.session_ctx.__aexit__ = AsyncMock(return_value=None)

        # One parent mock records both, so a test can assert that stop came before start.
        self.calls = MagicMock()
        self.calls.start = AsyncMock()
        self.calls.stop = AsyncMock()

    def _credential_rows(self, _statement: object) -> MagicMock:
        result = MagicMock()
        result.all.return_value = [(self.credential_id, self.encrypted_config)]
        return result

    async def _sync(self) -> None:
        with (
            patch(
                "app.services.rabbitmq_consumer.async_session_maker",
                return_value=self.session_ctx,
            ),
            patch.object(
                self.manager,
                "_get_workflows_with_rabbitmq_receive",
                new=AsyncMock(return_value=[self.workflow]),
            ),
            patch.object(self.manager, "_start_consumer", new=self.calls.start),
            patch.object(self.manager, "_stop_consumer", new=self.calls.stop),
        ):
            await self.manager._sync_consumers()
            # Let the start task created by the sync run.
            await asyncio.sleep(0)

    async def test_unchanged_credential_keeps_its_consumer(self) -> None:
        await self._sync()
        await self._sync()

        self.calls.start.assert_awaited_once()
        self.calls.stop.assert_not_called()

    async def test_registered_consumer_holds_its_start_task(self) -> None:
        """The loop keeps tasks weakly; an unreferenced start could be collected mid-connect."""
        await self._sync()

        (consumer_info,) = self.manager._consumers.values()
        self.assertIsInstance(consumer_info.start_task, asyncio.Task)

    async def test_consumer_starts_with_the_decrypted_config(self) -> None:
        await self._sync()

        consumer_info, config = self.calls.start.await_args.args
        self.assertEqual(consumer_info.queue_name, "orders_queue")
        self.assertEqual(consumer_info.credential_id, str(self.credential_id))
        self.assertEqual(config, _rabbitmq_config())

    async def test_re_encrypting_the_same_value_keeps_the_consumer(self) -> None:
        """A key rotation rewrites every row: the ciphertext changes, the value does not."""
        await self._sync()
        re_encrypted = encrypt_config(_rabbitmq_config())
        self.assertNotEqual(re_encrypted, self.encrypted_config)
        self.encrypted_config = re_encrypted

        await self._sync()

        self.calls.start.assert_awaited_once()
        self.calls.stop.assert_not_called()

    async def test_edited_credential_reconnects_with_the_new_value(self) -> None:
        await self._sync()
        old_consumer = self.calls.start.await_args.args[0]
        self.encrypted_config = encrypt_config(_rabbitmq_config("second-password"))

        await self._sync()

        self.calls.stop.assert_awaited_once_with(old_consumer)
        self.assertEqual(self.calls.start.await_count, 2)
        _, config = self.calls.start.await_args.args
        self.assertEqual(config["rabbitmq_password"], "second-password")
        self.assertEqual(len(self.manager._consumers), 1)

    async def test_reconnect_stops_the_old_consumer_before_starting_the_new_one(self) -> None:
        await self._sync()
        self.encrypted_config = encrypt_config(_rabbitmq_config("second-password"))

        await self._sync()

        self.assertEqual(
            [name for name, _, _ in self.calls.mock_calls],
            ["start", "stop", "start"],
        )

    async def test_switching_to_another_credential_reconnects(self) -> None:
        await self._sync()
        self.credential_id = uuid.uuid4()
        self.workflow.nodes[0]["data"]["credentialId"] = str(self.credential_id)

        await self._sync()

        self.calls.stop.assert_awaited_once()
        self.assertEqual(self.calls.start.await_count, 2)
        consumer_info, _ = self.calls.start.await_args.args
        self.assertEqual(consumer_info.credential_id, str(self.credential_id))

    async def test_renamed_queue_reconnects(self) -> None:
        await self._sync()
        self.workflow.nodes[0]["data"]["rabbitmqQueueName"] = "invoices_queue"

        await self._sync()

        self.calls.stop.assert_awaited_once()
        consumer_info, _ = self.calls.start.await_args.args
        self.assertEqual(consumer_info.queue_name, "invoices_queue")

    async def test_removed_node_stops_its_consumer(self) -> None:
        await self._sync()
        self.workflow.nodes = []

        await self._sync()

        self.calls.stop.assert_awaited_once()
        self.assertEqual(self.manager._consumers, {})

    async def test_missing_credential_is_reported_once_not_every_sync(self) -> None:
        self.db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        await self._sync()
        await self._sync()

        self.calls.start.assert_awaited_once()
        _, config = self.calls.start.await_args.args
        self.assertIsNone(config)

    async def test_unreadable_credential_is_reported_once_not_every_sync(self) -> None:
        self.encrypted_config = "not-a-fernet-token"

        await self._sync()
        await self._sync()

        self.calls.start.assert_awaited_once()
        _, config = self.calls.start.await_args.args
        self.assertIsNone(config)

    async def test_credential_that_becomes_readable_reconnects(self) -> None:
        self.encrypted_config = "not-a-fernet-token"
        await self._sync()
        self.encrypted_config = encrypt_config(_rabbitmq_config())

        await self._sync()

        self.calls.stop.assert_awaited_once()
        _, config = self.calls.start.await_args.args
        self.assertEqual(config, _rabbitmq_config())

    async def test_malformed_credential_id_skips_the_lookup(self) -> None:
        self.workflow.nodes[0]["data"]["credentialId"] = "not-a-uuid"

        await self._sync()

        self.db.execute.assert_not_called()
        _, config = self.calls.start.await_args.args
        self.assertIsNone(config)


class RabbitMQStartConsumerTests(unittest.IsolatedAsyncioTestCase):
    def _consumer_info(self) -> ConsumerInfo:
        return ConsumerInfo(
            workflow_id=uuid.uuid4(),
            credential_id=str(uuid.uuid4()),
            queue_name="orders_queue",
            node_id="rmq-node-1",
        )

    async def test_connects_with_the_given_config_without_reading_the_credential(self) -> None:
        queue = MagicMock()
        queue.consume = AsyncMock(return_value="ctag-1")
        channel = MagicMock(spec=RobustChannel)
        channel.set_qos = AsyncMock()
        channel.declare_queue = AsyncMock(return_value=queue)
        connection = MagicMock()
        connection.channel = AsyncMock(return_value=channel)
        consumer_info = self._consumer_info()

        with (
            patch(
                "app.services.rabbitmq_consumer.aio_pika.connect_robust",
                new=AsyncMock(return_value=connection),
            ) as connect,
            patch("app.services.rabbitmq_consumer.async_session_maker") as session_maker,
        ):
            await RabbitMQConsumerManager()._start_consumer(
                consumer_info, _rabbitmq_config("second-password")
            )

        session_maker.assert_not_called()
        connect.assert_awaited_once_with(
            host="rabbitmq.internal",
            port=5672,
            login="heym",
            password="second-password",
            virtualhost="/",
        )
        self.assertEqual(consumer_info.consumer_tag, "ctag-1")

    async def test_takes_the_queue_so_the_robust_channel_restores_it(self) -> None:
        """get_queue(ensure=False) is not registered with a RobustChannel.

        After a broker restart the robust connection then came back without the queue or
        its consumer, and the trigger never received another message.
        """
        queue = MagicMock()
        queue.consume = AsyncMock(return_value="ctag-1")
        channel = MagicMock(spec=RobustChannel)
        channel.set_qos = AsyncMock()
        channel.declare_queue = AsyncMock(return_value=queue)
        connection = MagicMock()
        connection.channel = AsyncMock(return_value=channel)

        with patch(
            "app.services.rabbitmq_consumer.aio_pika.connect_robust",
            new=AsyncMock(return_value=connection),
        ):
            await RabbitMQConsumerManager()._start_consumer(
                self._consumer_info(), _rabbitmq_config()
            )

        channel.declare_queue.assert_awaited_once_with("orders_queue", passive=True)
        channel.get_queue.assert_not_called()

    async def test_missing_config_logs_and_does_not_connect(self) -> None:
        with (
            patch(
                "app.services.rabbitmq_consumer.aio_pika.connect_robust", new=AsyncMock()
            ) as connect,
            self.assertLogs("rabbitmq_consumer", level="ERROR") as logs,
        ):
            await RabbitMQConsumerManager()._start_consumer(self._consumer_info(), None)

        connect.assert_not_called()
        self.assertIn("not found or unreadable", logs.output[0])


class RabbitMQStopConsumerTests(unittest.IsolatedAsyncioTestCase):
    """A stopped consumer must release its connection, or it keeps taking messages."""

    def _started_consumer(self) -> ConsumerInfo:
        consumer_info = ConsumerInfo(
            workflow_id=uuid.uuid4(),
            credential_id=str(uuid.uuid4()),
            queue_name="orders_queue",
            node_id="rmq-node-1",
        )
        # Specced from the real classes: aio-pika channels have no cancel(), and a mock
        # that accepted any attribute is how calling it went unnoticed.
        consumer_info.queue = MagicMock(spec=RobustQueue)
        consumer_info.queue.cancel = AsyncMock()
        consumer_info.channel = MagicMock(spec=RobustChannel)
        consumer_info.channel.is_closed = False
        consumer_info.channel.close = AsyncMock()
        consumer_info.connection = MagicMock(spec=RobustConnection)
        consumer_info.connection.is_closed = False
        consumer_info.connection.close = AsyncMock()
        consumer_info.consumer_tag = "ctag-1"
        return consumer_info

    async def test_cancels_through_the_queue_and_closes_everything(self) -> None:
        consumer_info = self._started_consumer()

        await RabbitMQConsumerManager()._stop_consumer(consumer_info)

        consumer_info.queue.cancel.assert_awaited_once_with("ctag-1")
        consumer_info.channel.close.assert_awaited_once()
        consumer_info.connection.close.assert_awaited_once()

    async def test_connection_closes_even_when_cancel_fails(self) -> None:
        consumer_info = self._started_consumer()
        consumer_info.queue.cancel = AsyncMock(side_effect=RuntimeError("broker gone"))

        with self.assertLogs("rabbitmq_consumer", level="ERROR"):
            await RabbitMQConsumerManager()._stop_consumer(consumer_info)

        consumer_info.channel.close.assert_awaited_once()
        consumer_info.connection.close.assert_awaited_once()

    async def test_stopping_cancels_a_start_that_is_still_connecting(self) -> None:
        consumer_info = self._started_consumer()
        never_answers = asyncio.Event()
        consumer_info.start_task = asyncio.create_task(never_answers.wait())
        await asyncio.sleep(0)

        await RabbitMQConsumerManager()._stop_consumer(consumer_info)

        self.assertTrue(consumer_info.start_task.cancelled())
        consumer_info.connection.close.assert_awaited_once()

    async def test_consumer_that_never_connected_stops_quietly(self) -> None:
        consumer_info = ConsumerInfo(
            workflow_id=uuid.uuid4(),
            credential_id=str(uuid.uuid4()),
            queue_name="orders_queue",
            node_id="rmq-node-1",
        )

        with self.assertNoLogs("rabbitmq_consumer", level="ERROR"):
            await RabbitMQConsumerManager()._stop_consumer(consumer_info)


if __name__ == "__main__":
    unittest.main()


class RabbitMQFailedStartTests(unittest.IsolatedAsyncioTestCase):
    """A consumer whose start fails is retried by the next sync, not left dead."""

    def setUp(self) -> None:
        self.manager = RabbitMQConsumerManager()
        self.credential_id = uuid.uuid4()
        self.workflow = _workflow(self.credential_id)
        encrypted = encrypt_config(_rabbitmq_config())
        rows = MagicMock()
        rows.all.return_value = [(self.credential_id, encrypted)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=rows)
        self.session_ctx = MagicMock()
        self.session_ctx.__aenter__ = AsyncMock(return_value=db)
        self.session_ctx.__aexit__ = AsyncMock(return_value=None)

    def _connection(self, *, declare_error: Exception | None = None) -> MagicMock:
        queue = MagicMock()
        queue.consume = AsyncMock(return_value="ctag-1")
        channel = MagicMock(spec=RobustChannel)
        channel.set_qos = AsyncMock()
        channel.declare_queue = AsyncMock(side_effect=declare_error, return_value=queue)
        connection = MagicMock(spec=RobustConnection)
        connection.is_closed = False
        connection.channel = AsyncMock(return_value=channel)
        connection.close = AsyncMock()
        return connection

    async def _sync(self, connect: AsyncMock) -> None:
        with (
            patch(
                "app.services.rabbitmq_consumer.async_session_maker",
                return_value=self.session_ctx,
            ),
            patch.object(
                self.manager,
                "_get_workflows_with_rabbitmq_receive",
                new=AsyncMock(return_value=[self.workflow]),
            ),
            patch("app.services.rabbitmq_consumer.aio_pika.connect_robust", new=connect),
            self.assertLogs("rabbitmq_consumer", level="INFO"),
        ):
            await self.manager._sync_consumers()
            await asyncio.gather(
                *(c.start_task for c in self.manager._consumers.values() if c.start_task)
            )
            # A failed start unregisters itself after its task is gathered above.
            for _ in range(3):
                await asyncio.sleep(0)

    async def test_broker_not_up_at_the_first_sync_is_retried(self) -> None:
        connect = AsyncMock(
            side_effect=[ConnectionRefusedError(111, "refused"), self._connection()]
        )

        await self._sync(connect)
        self.assertEqual(self.manager._consumers, {})
        await self._sync(connect)

        self.assertEqual(connect.await_count, 2)
        (consumer_info,) = self.manager._consumers.values()
        self.assertEqual(consumer_info.consumer_tag, "ctag-1")

    async def test_queue_missing_at_start_closes_its_connection_and_is_retried(self) -> None:
        missing = self._connection(declare_error=RuntimeError("NOT_FOUND - no queue"))
        connect = AsyncMock(side_effect=[missing, self._connection()])

        await self._sync(connect)
        missing.close.assert_awaited_once()
        self.assertEqual(self.manager._consumers, {})
        await self._sync(connect)

        (consumer_info,) = self.manager._consumers.values()
        self.assertEqual(consumer_info.consumer_tag, "ctag-1")

    async def test_a_failed_start_leaves_a_replacement_consumer_alone(self) -> None:
        failed = ConsumerInfo(
            workflow_id=self.workflow.id,
            credential_id=str(self.credential_id),
            queue_name="orders_queue",
            node_id="rmq-node-1",
        )
        replacement = ConsumerInfo(
            workflow_id=self.workflow.id,
            credential_id=str(self.credential_id),
            queue_name="orders_queue",
            node_id="rmq-node-1",
        )
        self.manager._consumers["key"] = replacement

        await self.manager._forget_failed_start(failed)

        self.assertIs(self.manager._consumers["key"], replacement)
