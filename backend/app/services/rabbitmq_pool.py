import asyncio
import json
import uuid
from typing import Any

import aio_pika
from aio_pika import Message
from aio_pika.abc import AbstractChannel, AbstractConnection, AbstractExchange


class RabbitMQPool:
    _connections: dict[str, AbstractConnection] = {}
    _channels: dict[str, AbstractChannel] = {}
    _lock = asyncio.Lock()

    @classmethod
    def _get_connection_key(
        cls,
        host: str,
        port: int,
        username: str,
        vhost: str,
    ) -> str:
        return f"{username}@{host}:{port}/{vhost}"

    @classmethod
    async def get_connection(
        cls,
        host: str,
        port: int,
        username: str,
        password: str,
        vhost: str = "/",
    ) -> AbstractConnection:
        key = cls._get_connection_key(host, port, username, vhost)

        async with cls._lock:
            if key in cls._connections:
                conn = cls._connections[key]
                if not conn.is_closed:
                    return conn
                del cls._connections[key]
                if key in cls._channels:
                    del cls._channels[key]

            connection = await aio_pika.connect_robust(
                host=host,
                port=port,
                login=username,
                password=password,
                virtualhost=vhost,
            )
            cls._connections[key] = connection
            return connection

    @classmethod
    async def get_channel(
        cls,
        host: str,
        port: int,
        username: str,
        password: str,
        vhost: str = "/",
    ) -> AbstractChannel:
        key = cls._get_connection_key(host, port, username, vhost)

        async with cls._lock:
            if key in cls._channels:
                channel = cls._channels[key]
                if not channel.is_closed:
                    return channel
                del cls._channels[key]

            connection = await cls.get_connection(host, port, username, password, vhost)
            channel = await connection.channel()
            cls._channels[key] = channel
            return channel

    @classmethod
    async def close_all(cls) -> None:
        async with cls._lock:
            for channel in cls._channels.values():
                if not channel.is_closed:
                    await channel.close()
            cls._channels.clear()

            for connection in cls._connections.values():
                if not connection.is_closed:
                    await connection.close()
            cls._connections.clear()


async def publish_message_direct(
    host: str,
    port: int,
    username: str,
    password: str,
    vhost: str,
    exchange_name: str,
    routing_key: str,
    body: dict | str,
    headers: dict[str, Any] | None = None,
    delay_ms: int | None = None,
) -> dict[str, Any]:
    connection = await aio_pika.connect_robust(
        host=host,
        port=port,
        login=username,
        password=password,
        virtualhost=vhost,
    )
    try:
        channel = await connection.channel()

        if isinstance(body, dict):
            message_body = json.dumps(body).encode()
        else:
            message_body = str(body).encode()

        message_headers: dict[str, Any] = headers.copy() if headers else {}
        if delay_ms and delay_ms > 0:
            message_headers["x-delay"] = delay_ms

        message_id = str(uuid.uuid4())

        message = Message(
            body=message_body,
            headers=message_headers if message_headers else None,
            message_id=message_id,
            content_type="application/json",
        )

        if exchange_name:
            exchange: AbstractExchange = await channel.get_exchange(exchange_name, ensure=False)
            await exchange.publish(message, routing_key=routing_key)
        else:
            await channel.default_exchange.publish(message, routing_key=routing_key)

        return {
            "status": "published",
            "message_id": message_id,
            "exchange": exchange_name or "(default)",
            "routing_key": routing_key,
            "delay_ms": delay_ms,
        }
    finally:
        await connection.close()


async def publish_message(
    host: str,
    port: int,
    username: str,
    password: str,
    vhost: str,
    exchange_name: str,
    routing_key: str,
    body: dict | str,
    headers: dict[str, Any] | None = None,
    delay_ms: int | None = None,
) -> dict[str, Any]:
    channel = await RabbitMQPool.get_channel(host, port, username, password, vhost)

    if isinstance(body, dict):
        message_body = json.dumps(body).encode()
    else:
        message_body = str(body).encode()

    message_headers: dict[str, Any] = headers.copy() if headers else {}
    if delay_ms and delay_ms > 0:
        message_headers["x-delay"] = delay_ms

    message_id = str(uuid.uuid4())

    message = Message(
        body=message_body,
        headers=message_headers if message_headers else None,
        message_id=message_id,
        content_type="application/json",
    )

    if exchange_name:
        exchange: AbstractExchange = await channel.get_exchange(exchange_name, ensure=False)
        await exchange.publish(message, routing_key=routing_key)
    else:
        await channel.default_exchange.publish(message, routing_key=routing_key)

    return {
        "status": "published",
        "message_id": message_id,
        "exchange": exchange_name or "(default)",
        "routing_key": routing_key,
        "delay_ms": delay_ms,
    }


async def consume_single_message(
    host: str,
    port: int,
    username: str,
    password: str,
    vhost: str,
    queue_name: str,
    timeout_seconds: float = 5.0,
) -> dict[str, Any] | None:
    channel = await RabbitMQPool.get_channel(host, port, username, password, vhost)
    queue = await channel.get_queue(queue_name, ensure=False)

    try:
        message = await asyncio.wait_for(
            queue.get(no_ack=False),
            timeout=timeout_seconds,
        )
        if message:
            body_str = message.body.decode()
            try:
                body = json.loads(body_str)
            except json.JSONDecodeError:
                body = body_str

            await message.ack()

            return {
                "body": body,
                "headers": dict(message.headers) if message.headers else {},
                "message_id": message.message_id,
                "routing_key": message.routing_key,
                "exchange": message.exchange,
                "timestamp": message.timestamp.isoformat() if message.timestamp else None,
            }
    except asyncio.TimeoutError:
        return None
    except aio_pika.exceptions.QueueEmpty:
        return None

    return None


async def declare_queue(
    host: str,
    port: int,
    username: str,
    password: str,
    vhost: str,
    queue_name: str,
    durable: bool = True,
) -> None:
    channel = await RabbitMQPool.get_channel(host, port, username, password, vhost)
    await channel.declare_queue(queue_name, durable=durable)


async def declare_exchange(
    host: str,
    port: int,
    username: str,
    password: str,
    vhost: str,
    exchange_name: str,
    exchange_type: str = "direct",
    durable: bool = True,
    arguments: dict[str, Any] | None = None,
) -> None:
    channel = await RabbitMQPool.get_channel(host, port, username, password, vhost)
    await channel.declare_exchange(
        exchange_name,
        type=aio_pika.ExchangeType(exchange_type),
        durable=durable,
        arguments=arguments,
    )
