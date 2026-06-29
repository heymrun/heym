from __future__ import annotations

from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the slack node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    get_http_client = _workflow_executor.get_http_client
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    message_template = node_data.get("message", "$input.text")
    message = self.evaluate_message_template(message_template, inputs, node_id)
    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Slack node requires a credential")

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    webhook_url = ""
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            config = decrypt_config(cred.encrypted_config)
            webhook_url = config.get("webhook_url", "")

    if not webhook_url:
        raise ValueError("Slack credential requires webhook_url")

    http_client = get_http_client()
    response = http_client.post(webhook_url, json={"text": message})

    if response.status_code >= 400:
        raise ValueError(f"Slack webhook error: {response.text}")

    output = {
        "status": response.status_code,
        "response": response.text,
    }
    return output
