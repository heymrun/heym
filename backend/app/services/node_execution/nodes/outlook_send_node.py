from __future__ import annotations

from typing import Any

from app.services.email_compose import (
    EmailFields,
    is_html_body,
    load_attachments,
    recipients,
    resolve_email_fields,
    sent_output,
)
from app.services.node_execution.base import NodeExecutionContext


def _recipient_list(group: str) -> list[dict[str, Any]]:
    """A To, Cc or Bcc field as Graph recipients, display names kept."""
    items: list[dict[str, Any]] = []
    for name, address in recipients(group):
        email_address: dict[str, str] = {"address": address}
        if name:
            email_address["name"] = name
        items.append({"emailAddress": email_address})
    return items


def graph_message(fields: EmailFields, from_address: str) -> dict[str, Any]:
    """The Graph message for the node's fields; Exchange writes the plain-text alternative."""
    message: dict[str, Any] = {
        "subject": fields.subject,
        "body": {
            "contentType": "HTML" if is_html_body(fields.body) else "Text",
            "content": fields.body,
        },
        "toRecipients": _recipient_list(fields.to),
    }
    if fields.cc:
        message["ccRecipients"] = _recipient_list(fields.cc)
    if fields.bcc:
        message["bccRecipients"] = _recipient_list(fields.bcc)
    if from_address:
        message["from"] = {"emailAddress": {"address": from_address}}
    return message


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the outlookSend node: send the email from the connected Outlook mailbox."""
    from app.db.models import CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config
    from app.services.exchange_server import send as exchange_send
    from app.services.exchange_server.connection import ews_settings, is_ews
    from app.services.outlook_service import OutlookApiError, OutlookService, has_send_scope

    fields = resolve_email_fields(ctx)
    from_address = ctx.executor.evaluate_nonempty_message_template(
        ctx.node_data.get("fromAddress", ""), ctx.inputs, ctx.node_id
    ).strip()

    credential_id = str(ctx.node_data.get("credentialId") or "")
    if not credential_id:
        raise ValueError("Outlook Send node requires an Outlook credential")

    with SessionLocal() as db:
        cred = ctx.executor._get_accessible_credential(db, credential_id)
        if cred is None or getattr(cred, "type", None) != CredentialType.outlook:
            raise ValueError("Outlook credential not found or not accessible")
        config: dict = decrypt_config(cred.encrypted_config)

    ews = is_ews(config)
    if not ews and not has_send_scope(config.get("scope")):
        # Credentials connected before Outlook Send hold Mail.ReadWrite only.
        raise ValueError(
            "Outlook credential cannot send mail yet; reconnect it in Credentials to allow "
            "Mail.Send"
        )

    if not fields.to:
        raise ValueError("Email recipient (to) is required")

    attachments = load_attachments(ctx, fields, "Outlook Send")
    if ews:
        try:
            exchange_send.send_message(config, fields, from_address, attachments)
        except OutlookApiError as exc:
            raise ValueError(f"Failed to send email: {exc}") from exc
        account = ews_settings(config).email
        return sent_output(fields, len(attachments), **{"from": from_address or account})

    message = graph_message(fields, from_address)
    try:
        with SessionLocal() as db:
            OutlookService(credential_id, config, db).send_message(
                message,
                [(item.filename, item.mime_type, item.content) for item in attachments],
            )
    except OutlookApiError as exc:
        raise ValueError(f"Failed to send email: {exc}") from exc

    account = str(config.get("email_address") or "").strip()
    return sent_output(fields, len(attachments), **{"from": from_address or account})
