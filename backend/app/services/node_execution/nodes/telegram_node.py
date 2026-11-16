from __future__ import annotations

from importlib import import_module

from app.services.message_parts import split_message_text
from app.services.node_execution.base import NodeExecutionContext

# sendMessage accepts 1-4096 characters, counted in UTF-16 code units.
TELEGRAM_MESSAGE_LIMIT = 4096


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

    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred is None:
            raise ValueError("Telegram credential not found or not accessible")
        telegram_config: dict = decrypt_config(cred.encrypted_config)

    bot_token = str(telegram_config.get("bot_token", "")).strip()
    if not bot_token:
        raise ValueError("Telegram credential requires bot_token")

    http_client = get_http_client()
    # Telegram rejects a longer text outright, so a long message goes out as several.
    parts = split_message_text(str(message), TELEGRAM_MESSAGE_LIMIT)
    results: list[dict] = []
    for index, part in enumerate(parts):
        response = http_client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": part,
            },
        )
        try:
            response_body = response.json()
        except ValueError:
            response_body = {"ok": False, "description": response.text}

        if response.status_code >= 400 or not response_body.get("ok", False):
            error_detail = response_body.get("description") or response.text
            where = f" (part {index + 1} of {len(parts)})" if len(parts) > 1 else ""
            raise ValueError(f"Telegram API error{where}: {error_detail}")
        results.append(response_body.get("result", {}))

    output = {
        "status": response.status_code,
        "ok": True,
        "result": results[0],
        "results": results,
    }
    return output
