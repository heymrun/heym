from __future__ import annotations

import json
from typing import Any

from app.db.models import CredentialType
from app.db.session import SessionLocal
from app.services.cal_api_service import CalApiService
from app.services.encryption import decrypt_config
from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute a Cal.com webhook API operation."""
    executor = ctx.executor
    node_data = ctx.node_data
    credential_id = str(node_data.get("credentialId") or "").strip()
    if not credential_id:
        raise ValueError("Cal.com node requires a credential")

    config: dict[str, Any] = {}
    with SessionLocal() as db:
        credential = executor._get_accessible_credential(db, credential_id)
        if credential is not None:
            if credential.type != CredentialType.cal_api:
                raise ValueError("Cal.com node requires a Cal.com API credential")
            config = decrypt_config(credential.encrypted_config)
    if not config:
        raise ValueError("Cal.com API credential not found or invalid")

    operation = str(node_data.get("calOperation") or "").strip()
    if not operation:
        raise ValueError("Cal.com node requires an operation")

    def text_field(name: str, default: str = "") -> str:
        return executor.evaluate_message_template(
            str(node_data.get(name, default) or default),
            ctx.inputs,
            ctx.node_id,
        ).strip()

    def required_text(name: str, label: str) -> str:
        value = text_field(name)
        if not value:
            raise ValueError(f"Cal.com {operation} requires {label}")
        return value

    def json_object(name: str) -> dict[str, Any]:
        raw_value = str(node_data.get(name, "{}") or "{}").strip()
        if executor._is_single_dollar_expression(raw_value):
            resolved = executor.resolve_expression(
                raw_value,
                ctx.inputs,
                ctx.node_id,
                preserve_type=True,
            )
            if not isinstance(resolved, dict):
                raise ValueError(f"{name} must resolve to a JSON object")
            return resolved
        evaluated = executor.evaluate_message_template(raw_value, ctx.inputs, ctx.node_id)
        try:
            parsed = json.loads(evaluated or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{name} must be a JSON object")
        return parsed

    service = CalApiService(config)
    if operation == "listWebhooks":
        webhooks = service.list_webhooks()
        return {
            "success": True,
            "operation": operation,
            "webhooks": webhooks,
            "count": len(webhooks),
        }
    if operation == "createWebhook":
        webhook = service.create_webhook(json_object("calWebhook"))
        return {"success": True, "operation": operation, "webhook": webhook}
    if operation == "updateWebhook":
        webhook = service.update_webhook(
            required_text("calWebhookId", "a webhook ID"),
            json_object("calWebhook"),
        )
        return {"success": True, "operation": operation, "webhook": webhook}
    if operation == "deleteWebhook":
        webhook_id = required_text("calWebhookId", "a webhook ID")
        service.delete_webhook(webhook_id)
        return {
            "success": True,
            "operation": operation,
            "deleted": True,
            "webhookId": webhook_id,
        }
    raise ValueError(f"Unknown Cal.com operation: {operation}")
