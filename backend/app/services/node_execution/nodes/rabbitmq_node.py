from __future__ import annotations

import json
from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.json_fields import render_json_template


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the rabbitmq node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    run_async = _workflow_executor.run_async
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    operation = node_data.get("rabbitmqOperation", "")
    if not operation:
        raise ValueError("RabbitMQ node requires an operation")

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("RabbitMQ node requires a credential")

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    rabbitmq_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            rabbitmq_config = decrypt_config(cred.encrypted_config)

    if not rabbitmq_config:
        raise ValueError("RabbitMQ credential not found")

    if operation == "send":
        from app.services.rabbitmq_pool import publish_message_direct

        rabbitmq_host = rabbitmq_config.get("rabbitmq_host", "localhost")
        rabbitmq_port = int(rabbitmq_config.get("rabbitmq_port", 5672))
        rabbitmq_username = rabbitmq_config.get("rabbitmq_username", "guest")
        rabbitmq_password = rabbitmq_config.get("rabbitmq_password", "guest")
        rabbitmq_vhost = rabbitmq_config.get("rabbitmq_vhost", "/")

        # Blank fields stay blank: evaluate_message_template turns "" into str(inputs).
        exchange_template = node_data.get("rabbitmqExchange", "")
        exchange_name = self.evaluate_nonempty_message_template(exchange_template, inputs, node_id)

        routing_key_template = node_data.get("rabbitmqRoutingKey", "")
        routing_key = self.evaluate_nonempty_message_template(routing_key_template, inputs, node_id)

        if not routing_key and not exchange_name:
            queue_template = node_data.get("rabbitmqQueueName", "")
            routing_key = self.evaluate_nonempty_message_template(queue_template, inputs, node_id)

        # A named exchange may take an empty routing key (fanout, headers); the default
        # exchange routes by queue name, so it needs one.
        if not routing_key and not exchange_name:
            raise ValueError("RabbitMQ Send requires routing key or queue name")

        message_body_template = node_data.get("rabbitmqMessageBody", "$input")
        message_body_str = render_json_template(self, message_body_template, inputs, node_id)

        try:
            message_body = (
                json.loads(message_body_str)
                if isinstance(message_body_str, str)
                else message_body_str
            )
        except json.JSONDecodeError:
            message_body = message_body_str

        delay_ms = node_data.get("rabbitmqDelayMs")
        if delay_ms:
            delay_ms = int(delay_ms)

        output = run_async(
            publish_message_direct(
                host=rabbitmq_host,
                port=rabbitmq_port,
                username=rabbitmq_username,
                password=rabbitmq_password,
                vhost=rabbitmq_vhost,
                exchange_name=exchange_name or "",
                routing_key=routing_key,
                body=message_body,
                delay_ms=delay_ms,
            )
        )

    elif operation == "receive":
        trigger_inputs = node_data.get("_initial_inputs", {})
        output = {
            "body": trigger_inputs.get("body", {}),
            "headers": trigger_inputs.get("headers", {}),
            "message_id": trigger_inputs.get("message_id"),
            "routing_key": trigger_inputs.get("routing_key"),
            "exchange": trigger_inputs.get("exchange"),
            "timestamp": trigger_inputs.get("timestamp"),
        }

    else:
        raise ValueError(f"Unknown RabbitMQ operation: {operation}")
    return output
