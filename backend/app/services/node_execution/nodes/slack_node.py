from __future__ import annotations

from app.services import ssrf_guard
from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the slack node."""
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

    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred is None:
            raise ValueError("Slack credential not found or not accessible")
        config = decrypt_config(cred.encrypted_config)

    webhook_url = config.get("webhook_url", "")
    if not webhook_url:
        raise ValueError("Slack credential requires webhook_url")

    ssrf_guard.guard_http_url(webhook_url, "Slack credential webhook URL")
    http_client = ssrf_guard.get_guarded_http_client()
    response = http_client.post(webhook_url, json={"text": message})

    if response.status_code >= 400:
        raise ValueError(f"Slack webhook error: {response.text}")

    output = {
        "status": response.status_code,
        "response": response.text,
    }
    return output
