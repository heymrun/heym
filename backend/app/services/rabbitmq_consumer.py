import asyncio
import json
import logging
import uuid
from typing import Any

import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.workflows import (
    _persist_global_variables_from_execution,
    collect_referenced_workflows,
    get_credentials_context,
)
from app.db.models import Credential, ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.services.distributed_lock import lock_service
from app.services.encryption import decrypt_config
from app.services.global_variables_service import get_global_variables_context
from app.services.workflow_executor import execute_workflow

logger = logging.getLogger("rabbitmq_consumer")


class ConsumerInfo:
    def __init__(
        self,
        workflow_id: uuid.UUID,
        credential_id: str,
        queue_name: str,
        node_id: str,
    ) -> None:
        self.workflow_id = workflow_id
        self.credential_id = credential_id
        self.queue_name = queue_name
        self.node_id = node_id
        self.consumer_tag: str | None = None
        self.connection: aio_pika.abc.AbstractConnection | None = None
        self.channel: aio_pika.abc.AbstractChannel | None = None


class RabbitMQConsumerManager:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._consumers: dict[str, ConsumerInfo] = {}
        self._lock = asyncio.Lock()
        self._was_leader = False

    def _get_consumer_key(self, workflow_id: uuid.UUID, node_id: str) -> str:
        return f"{workflow_id}_{node_id}"

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("RabbitMQ consumer manager started (worker_id=%s)", lock_service.worker_id)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        await self._stop_all_consumers()
        logger.info("RabbitMQ consumer manager stopped")

    async def _stop_all_consumers(self) -> None:
        async with self._lock:
            for key, consumer in list(self._consumers.items()):
                await self._stop_consumer(consumer)
            self._consumers.clear()

    async def _run_loop(self) -> None:
        await asyncio.sleep(5)

        while self._running:
            try:
                is_leader = lock_service.is_leader

                if is_leader and not self._was_leader:
                    logger.info("Becoming leader, starting consumers...")
                    self._was_leader = True

                if not is_leader and self._was_leader:
                    logger.info("Lost leadership, stopping consumers...")
                    await self._stop_all_consumers()
                    self._was_leader = False

                if is_leader:
                    await self._sync_consumers()

            except Exception as e:
                logger.exception("Error in RabbitMQ consumer sync loop: %s", e)
            await asyncio.sleep(30)

    async def _sync_consumers(self) -> None:
        async with async_session_maker() as db:
            workflows = await self._get_workflows_with_rabbitmq_receive(db)
            current_keys = set()

            for workflow in workflows:
                receive_nodes = self._find_rabbitmq_receive_nodes(workflow.nodes)
                for node in receive_nodes:
                    node_id = node.get("id", "")
                    node_data = node.get("data", {})
                    credential_id = node_data.get("credentialId")
                    queue_name = node_data.get("rabbitmqQueueName", "")

                    if not credential_id or not queue_name:
                        continue

                    key = self._get_consumer_key(workflow.id, node_id)
                    current_keys.add(key)

                    async with self._lock:
                        if key not in self._consumers:
                            consumer_info = ConsumerInfo(
                                workflow_id=workflow.id,
                                credential_id=credential_id,
                                queue_name=queue_name,
                                node_id=node_id,
                            )
                            self._consumers[key] = consumer_info
                            asyncio.create_task(self._start_consumer(consumer_info))
                            logger.info(
                                "Registered RabbitMQ consumer for workflow %s, queue %s",
                                workflow.id,
                                queue_name,
                            )

            async with self._lock:
                keys_to_remove = set(self._consumers.keys()) - current_keys
                for key in keys_to_remove:
                    consumer = self._consumers.pop(key, None)
                    if consumer:
                        await self._stop_consumer(consumer)
                        logger.info(
                            "Unregistered RabbitMQ consumer for workflow %s",
                            consumer.workflow_id,
                        )

    async def _get_workflows_with_rabbitmq_receive(self, db: AsyncSession) -> list[Workflow]:
        result = await db.execute(select(Workflow))
        all_workflows = result.scalars().all()
        return [w for w in all_workflows if self._has_rabbitmq_receive_node(w.nodes)]

    def _has_rabbitmq_receive_node(self, nodes: list[dict]) -> bool:
        return any(
            n.get("type") == "rabbitmq"
            and n.get("data", {}).get("rabbitmqOperation") == "receive"
            and n.get("data", {}).get("active", True) is not False
            for n in nodes
        )

    def _find_rabbitmq_receive_nodes(self, nodes: list[dict]) -> list[dict]:
        return [
            n
            for n in nodes
            if n.get("type") == "rabbitmq"
            and n.get("data", {}).get("rabbitmqOperation") == "receive"
            and n.get("data", {}).get("active", True) is not False
        ]

    async def _start_consumer(
        self,
        consumer_info: ConsumerInfo,
    ) -> None:
        try:
            async with async_session_maker() as db:
                cred_result = await db.execute(
                    select(Credential).where(Credential.id == consumer_info.credential_id)
                )
                credential = cred_result.scalar_one_or_none()
                if not credential:
                    logger.error(
                        "Credential %s not found for workflow %s",
                        consumer_info.credential_id,
                        consumer_info.workflow_id,
                    )
                    return

                config = decrypt_config(credential.encrypted_config)
            host = config.get("rabbitmq_host", "localhost")
            port = int(config.get("rabbitmq_port", 5672))
            username = config.get("rabbitmq_username", "guest")
            password = config.get("rabbitmq_password", "guest")
            vhost = config.get("rabbitmq_vhost", "/")

            connection = await aio_pika.connect_robust(
                host=host,
                port=port,
                login=username,
                password=password,
                virtualhost=vhost,
            )
            consumer_info.connection = connection

            channel = await connection.channel()
            consumer_info.channel = channel

            await channel.set_qos(prefetch_count=1)

            queue = await channel.get_queue(consumer_info.queue_name, ensure=False)

            async def on_message(message: AbstractIncomingMessage) -> None:
                await self._handle_message(
                    consumer_info.workflow_id,
                    consumer_info.node_id,
                    message,
                )

            consumer_info.consumer_tag = await queue.consume(on_message)
            logger.info(
                "Started consuming from queue %s for workflow %s",
                consumer_info.queue_name,
                consumer_info.workflow_id,
            )

        except Exception as e:
            logger.exception(
                "Failed to start consumer for workflow %s: %s",
                consumer_info.workflow_id,
                e,
            )

    async def _stop_consumer(self, consumer_info: ConsumerInfo) -> None:
        try:
            if consumer_info.channel and not consumer_info.channel.is_closed:
                if consumer_info.consumer_tag:
                    await consumer_info.channel.cancel(consumer_info.consumer_tag)
                await consumer_info.channel.close()

            if consumer_info.connection and not consumer_info.connection.is_closed:
                await consumer_info.connection.close()

        except Exception as e:
            logger.error(
                "Error stopping consumer for workflow %s: %s",
                consumer_info.workflow_id,
                e,
            )

    async def _handle_message(
        self,
        workflow_id: uuid.UUID,
        node_id: str,
        message: AbstractIncomingMessage,
    ) -> None:
        logger.info(
            "Received message for workflow %s from queue, message_id: %s",
            workflow_id,
            message.message_id,
        )

        try:
            async with async_session_maker() as db:
                workflow_result = await db.execute(
                    select(Workflow).where(Workflow.id == workflow_id)
                )
                workflow = workflow_result.scalar_one_or_none()

                if not workflow:
                    logger.error("Workflow %s not found", workflow_id)
                    await message.nack(requeue=True)
                    return

                trigger_node = next(
                    (n for n in workflow.nodes if n.get("id") == node_id),
                    None,
                )
                if not trigger_node:
                    logger.warning(
                        "Trigger node %s not found in workflow %s, rejecting message",
                        node_id,
                        workflow_id,
                    )
                    await message.nack(requeue=False)
                    return

                node_data = trigger_node.get("data", {})
                if node_data.get("active") is False:
                    logger.info(
                        "Trigger node %s in workflow %s is deactivated, rejecting message",
                        node_id,
                        workflow_id,
                    )
                    await message.nack(requeue=True)
                    return

            body_str = message.body.decode()
            try:
                body = json.loads(body_str)
            except json.JSONDecodeError:
                body = body_str

            message_data: dict[str, Any] = {
                "body": body,
                "headers": dict(message.headers) if message.headers else {},
                "message_id": message.message_id,
                "routing_key": message.routing_key,
                "exchange": message.exchange,
                "timestamp": message.timestamp.isoformat() if message.timestamp else None,
            }

            async with async_session_maker() as db:
                workflow_result = await db.execute(
                    select(Workflow).where(Workflow.id == workflow_id)
                )
                workflow = workflow_result.scalar_one_or_none()

                if not workflow:
                    logger.error("Workflow %s not found", workflow_id)
                    await message.nack(requeue=True)
                    return

                workflow_cache = await collect_referenced_workflows(db, workflow.nodes)
                credentials_context = await get_credentials_context(db, workflow.owner_id)
                global_variables_context = await get_global_variables_context(db, workflow.owner_id)

                inputs = {
                    "triggered_by": "rabbitmq",
                    "trigger_node_id": node_id,
                    **message_data,
                }

                result = execute_workflow(
                    workflow_id=workflow.id,
                    nodes=workflow.nodes,
                    edges=workflow.edges,
                    inputs=inputs,
                    workflow_cache=workflow_cache,
                    credentials_context=credentials_context,
                    global_variables_context=global_variables_context,
                    trace_user_id=workflow.owner_id,
                )

                history_entry = ExecutionHistory(
                    workflow_id=workflow.id,
                    inputs=inputs,
                    outputs=result.outputs,
                    node_results=result.node_results,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                )
                db.add(history_entry)
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                )

                for sub_exec in result.sub_workflow_executions:
                    sub_history = ExecutionHistory(
                        workflow_id=uuid.UUID(sub_exec.workflow_id),
                        inputs=sub_exec.inputs,
                        outputs=sub_exec.outputs,
                        node_results=sub_exec.node_results,
                        status=sub_exec.status,
                        execution_time_ms=sub_exec.execution_time_ms,
                        trigger_source=sub_exec.trigger_source,
                    )
                    db.add(sub_history)
                    await upsert_workflow_analytics_snapshot(
                        db,
                        workflow_id=uuid.UUID(sub_exec.workflow_id),
                        owner_id=None,
                        workflow_name_snapshot=sub_exec.workflow_name or "Sub-workflow",
                        status=sub_exec.status,
                        execution_time_ms=sub_exec.execution_time_ms,
                    )

                await _persist_global_variables_from_execution(
                    db,
                    workflow.owner_id,
                    workflow.nodes,
                    workflow_cache,
                    result.node_results,
                    result.sub_workflow_executions,
                )

                await db.commit()

                if result.status == "success":
                    await message.ack()
                    logger.info(
                        "Workflow %s executed successfully via RabbitMQ trigger",
                        workflow_id,
                    )
                else:
                    await message.nack(requeue=False)
                    logger.warning(
                        "Workflow %s failed via RabbitMQ trigger",
                        workflow_id,
                    )

        except Exception as e:
            logger.exception(
                "Failed to execute workflow %s via RabbitMQ trigger: %s",
                workflow_id,
                e,
            )
            await message.nack(requeue=False)


rabbitmq_consumer_manager = RabbitMQConsumerManager()
