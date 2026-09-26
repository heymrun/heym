"""Tests for RabbitMQ consumer acknowledgement behaviour across execution outcomes."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.cluster.dispatch import _timeout_error
from app.services.cluster.run_history import OffloadedRun, offloaded_error
from app.services.rabbitmq_consumer import RabbitMQConsumerManager


def _make_mock_message(body: bytes = b'{"task": "process_order"}') -> MagicMock:
    """Return a mock aio_pika incoming message."""
    msg = MagicMock()
    msg.body = body
    msg.headers = {}
    msg.message_id = "msg-uuid-1"
    msg.routing_key = "orders_queue"
    msg.exchange = ""
    msg.timestamp = None
    msg.ack = AsyncMock()
    msg.nack = AsyncMock()
    return msg


def _make_mock_workflow(workflow_id: uuid.UUID, node_id: str = "rmq-node-1") -> MagicMock:
    """Return a mock Workflow entity containing a rabbitmq receive trigger node."""
    wf = MagicMock()
    wf.id = workflow_id
    wf.owner_id = uuid.uuid4()
    wf.name = "Order Processing Workflow"
    wf.nodes = [
        {
            "id": node_id,
            "type": "rabbitmq",
            "data": {
                "rabbitmqOperation": "receive",
                "active": True,
                "credentialId": "cred-1",
                "rabbitmqQueueName": "orders_queue",
            },
        }
    ]
    wf.edges = []
    return wf


class RabbitMQConsumerAcknowledgementTests(unittest.IsolatedAsyncioTestCase):
    """Verify RabbitMQ message ACK / NACK semantics for offloaded and local executions."""

    def setUp(self) -> None:
        self.consumer_manager = RabbitMQConsumerManager()
        self.workflow_id = uuid.uuid4()
        self.node_id = "rmq-node-1"
        self.workflow = _make_mock_workflow(self.workflow_id, self.node_id)
        self.message = _make_mock_message()

        # Database session mock
        self.db = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalar_one_or_none.return_value = self.workflow
        self.db.execute = AsyncMock(return_value=exec_result)
        self.db.add = MagicMock()
        self.db.commit = AsyncMock()

        self.session_ctx = MagicMock()
        self.session_ctx.__aenter__ = AsyncMock(return_value=self.db)
        self.session_ctx.__aexit__ = AsyncMock(return_value=None)

    async def _handle_with_dispatch_result(
        self, dispatch_result: object
    ) -> tuple[MagicMock, MagicMock]:
        with (
            patch(
                "app.services.rabbitmq_consumer.async_session_maker",
                return_value=self.session_ctx,
            ),
            patch(
                "app.services.rabbitmq_consumer.collect_referenced_workflows",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.rabbitmq_consumer.get_credentials_context",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.rabbitmq_consumer.get_global_variables_context",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.rabbitmq_consumer.dispatch_workflow",
                new=AsyncMock(return_value=dispatch_result),
            ),
            patch("app.services.rabbitmq_consumer.log_offloaded_run") as mock_log,
            patch(
                "app.services.rabbitmq_consumer.persist_pending_execution",
                new=AsyncMock(return_value=(MagicMock(), None)),
            ) as mock_pending,
            patch(
                "app.services.rabbitmq_consumer.upsert_workflow_analytics_snapshot",
                new=AsyncMock(),
            ),
            patch(
                "app.services.rabbitmq_consumer._persist_global_variables_from_execution",
                new=AsyncMock(),
            ),
        ):
            await self.consumer_manager._handle_message(
                self.workflow_id, self.node_id, self.message
            )
            return mock_log, mock_pending

    # -----------------------------------------------------------------------
    # Offloaded execution outcomes (history_written=True)
    # -----------------------------------------------------------------------

    async def test_offloaded_success_acks_message(self) -> None:
        """A successful offloaded run must acknowledge the message."""
        result = OffloadedRun(
            status="success",
            outputs={"result": "ok"},
            history_written=True,
            instance="worker-a",
        )

        mock_log, mock_pending = await self._handle_with_dispatch_result(result)

        self.message.ack.assert_awaited_once()
        self.message.nack.assert_not_called()
        mock_log.assert_called_once_with(
            unittest.mock.ANY,
            workflow_id=self.workflow.id,
            trigger="RabbitMQ trigger",
            result=result,
        )
        # History must not be written again locally
        self.db.add.assert_not_called()
        mock_pending.assert_not_called()

    async def test_offloaded_pending_acks_message(self) -> None:
        """An offloaded run paused for human review must be ACKed since the worker already persisted the pause."""
        result = OffloadedRun(
            status="pending",
            outputs={},
            history_written=True,
            instance="worker-a",
        )

        mock_log, mock_pending = await self._handle_with_dispatch_result(result)

        self.message.ack.assert_awaited_once()
        self.message.nack.assert_not_called()
        mock_log.assert_called_once_with(
            unittest.mock.ANY,
            workflow_id=self.workflow.id,
            trigger="RabbitMQ trigger",
            result=result,
        )
        # The pause was already minted on the worker, caller must not mint or write history again
        self.db.add.assert_not_called()
        mock_pending.assert_not_called()

    async def test_offloaded_error_nacks_without_requeue(self) -> None:
        """A failed offloaded run must NACK with requeue=False to prevent runaway redelivery."""
        result = OffloadedRun(
            status="error",
            outputs={"error": "Node failed"},
            error="Node failed",
            history_written=True,
            instance="worker-a",
        )

        mock_log, _ = await self._handle_with_dispatch_result(result)

        self.message.nack.assert_awaited_once_with(requeue=False)
        self.message.ack.assert_not_called()
        mock_log.assert_called_once_with(
            unittest.mock.ANY,
            workflow_id=self.workflow.id,
            trigger="RabbitMQ trigger",
            result=result,
        )
        self.db.add.assert_not_called()

    async def test_offloaded_wait_timeout_nacks_without_requeue(self) -> None:
        """An offloaded run that times out waiting for results must NACK with requeue=False."""
        result = _timeout_error(uuid.uuid4())

        mock_log, _ = await self._handle_with_dispatch_result(result)

        self.message.nack.assert_awaited_once_with(requeue=False)
        self.message.ack.assert_not_called()
        mock_log.assert_called_once_with(
            unittest.mock.ANY,
            workflow_id=self.workflow.id,
            trigger="RabbitMQ trigger",
            result=result,
        )
        self.db.add.assert_not_called()

    async def test_offloaded_retired_run_nacks_without_requeue(self) -> None:
        """A run retired by the queue before being claimed must NACK with requeue=False."""
        result = offloaded_error(
            "The run was retired before any instance executed it", reported=False
        )

        mock_log, _ = await self._handle_with_dispatch_result(result)

        self.message.nack.assert_awaited_once_with(requeue=False)
        self.message.ack.assert_not_called()
        mock_log.assert_called_once_with(
            unittest.mock.ANY,
            workflow_id=self.workflow.id,
            trigger="RabbitMQ trigger",
            result=result,
        )
        self.db.add.assert_not_called()

    # -----------------------------------------------------------------------
    # In-process execution outcomes (history_written=False)
    # -----------------------------------------------------------------------

    async def test_local_success_persists_history_and_acks(self) -> None:
        """A local successful run persists ExecutionHistory and acknowledges the message."""
        result = SimpleNamespace(
            status="success",
            outputs={"result": "ok"},
            node_results=[],
            sub_workflow_executions=[],
            execution_time_ms=10.0,
            history_written=False,
        )

        mock_log, mock_pending = await self._handle_with_dispatch_result(result)

        self.message.ack.assert_awaited_once()
        self.message.nack.assert_not_called()
        mock_log.assert_not_called()
        self.db.add.assert_called()
        self.db.commit.assert_awaited()
        mock_pending.assert_not_called()

    async def test_local_pending_persists_pause_and_acks(self) -> None:
        """A local paused run persists pending execution review and acknowledges the message."""
        result = SimpleNamespace(
            status="pending",
            outputs={},
            node_results=[],
            sub_workflow_executions=[],
            execution_time_ms=5.0,
            pending_review={"summary": "Approve"},
            resume_snapshot={"paused_node_id": "n1"},
            history_written=False,
        )

        mock_log, mock_pending = await self._handle_with_dispatch_result(result)

        self.message.ack.assert_awaited_once()
        self.message.nack.assert_not_called()
        mock_log.assert_not_called()
        mock_pending.assert_awaited_once()
        self.db.commit.assert_awaited()

    async def test_local_error_persists_history_and_nacks_without_requeue(self) -> None:
        """A local failed run persists ExecutionHistory and NACKs with requeue=False."""
        result = SimpleNamespace(
            status="error",
            outputs={"error": "Failed"},
            node_results=[],
            sub_workflow_executions=[],
            execution_time_ms=8.0,
            history_written=False,
        )

        mock_log, mock_pending = await self._handle_with_dispatch_result(result)

        self.message.nack.assert_awaited_once_with(requeue=False)
        self.message.ack.assert_not_called()
        mock_log.assert_not_called()
        self.db.add.assert_called()
        self.db.commit.assert_awaited()
        mock_pending.assert_not_called()

    async def test_execution_cleanup_passes_dispatcher_handle(self) -> None:
        """RabbitMQ consumer cleanup must pass the registered handle to clear_execution."""
        result = SimpleNamespace(
            status="success",
            outputs={},
            node_results=[],
            sub_workflow_executions=[],
            execution_time_ms=5.0,
            history_written=False,
        )
        with patch("app.services.execution_cancellation.clear_execution") as mock_clear:
            await self._handle_with_dispatch_result(result)
            mock_clear.assert_called_once()
            self.assertIn("handle", mock_clear.call_args.kwargs)
            self.assertIsNotNone(mock_clear.call_args.kwargs["handle"])
            handle = mock_clear.call_args.kwargs["handle"]
            from app.services.execution_cancellation import ExecutionCancellationHandle

            self.assertIsInstance(handle, ExecutionCancellationHandle)
            self.assertEqual(mock_clear.call_args.args[0], handle.execution_id)


if __name__ == "__main__":
    unittest.main()
