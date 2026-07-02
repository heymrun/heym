from __future__ import annotations

from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the telegram node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    get_http_client = _workflow_executor.get_http_client
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    chat_id_template = node_data.get("chatId", "")
    message_template = node_data.get("message", "$input.text")

    if chat_id_template and str(chat_id_template).startswith("$"):
        chat_id = self.resolve_expression(str(chat_id_template), inputs, node_id)
    else:
        chat_id = self.evaluate_message_template(str(chat_id_template), inputs, node_id)
    message = self.evaluate_message_template(message_template, inputs, node_id)

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Telegram node requires a credential")
    if chat_id in (None, ""):
        raise ValueError("Telegram node requires chatId")

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    telegram_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            telegram_config = decrypt_config(cred.encrypted_config)

    bot_token = str(telegram_config.get("bot_token", "")).strip()
    if not bot_token:
        raise ValueError("Telegram credential requires bot_token")

    http_client = get_http_client()
    response = http_client.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": message,
        },
    )
    try:
        response_body = response.json()
    except ValueError:
        response_body = {"ok": False, "description": response.text}

    if response.status_code >= 400 or not response_body.get("ok", False):
        error_detail = response_body.get("description") or response.text
        raise ValueError(f"Telegram API error: {error_detail}")

    output = {
        "status": response.status_code,
        "ok": response_body.get("ok", False),
        "result": response_body.get("result", {}),
    }
    return output
