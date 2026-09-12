from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse

from app.services import ssrf_guard
from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the discord node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    message_template = node_data.get("message", "$input.text")
    message = self.evaluate_message_template(message_template, inputs, node_id)
    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Discord node requires a credential")
    if not str(message).strip():
        raise ValueError("Discord node requires a non-empty message")

    username_template = str(node_data.get("username", "") or "").strip()
    avatar_url_template = str(node_data.get("avatarUrl", "") or "").strip()

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred is None:
            raise ValueError("Discord credential not found or not accessible")
        config = decrypt_config(cred.encrypted_config)

    webhook_url = config.get("webhook_url", "")
    if not webhook_url:
        raise ValueError("Discord credential requires webhook_url")

    payload: dict[str, object] = {"content": message}
    if username_template:
        payload["username"] = self.evaluate_message_template(username_template, inputs, node_id)
    if avatar_url_template:
        payload["avatar_url"] = self.evaluate_message_template(avatar_url_template, inputs, node_id)

    parsed_webhook_url = urlparse(webhook_url)
    existing_query = parse_qsl(parsed_webhook_url.query, keep_blank_values=True)
    filtered_query = [(key, value) for key, value in existing_query if key != "wait"]
    filtered_query.append(("wait", "true"))
    request_webhook_url = parsed_webhook_url._replace(
        query=urlencode(filtered_query, doseq=True)
    ).geturl()

    # Guards the rewritten URL, which is the one actually dialed.
    ssrf_guard.guard_http_url(request_webhook_url, "Discord credential webhook URL")
    http_client = ssrf_guard.get_guarded_http_client()
    response = http_client.post(request_webhook_url, json=payload)

    if response.status_code >= 400:
        raise ValueError(f"Discord webhook error: {response.text}")

    output = {
        "status": response.status_code,
        "response": response.text,
        "message": message,
        "username": payload.get("username"),
        "avatar_url": payload.get("avatar_url"),
    }
    return output
