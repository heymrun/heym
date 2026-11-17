from __future__ import annotations

from email.utils import formataddr
from typing import Any

from app.services.email_compose import (
    build_mime_message,
    load_attachments,
    resolve_email_fields,
    sent_output,
)
from app.services.node_execution.base import NodeExecutionContext


def _send_as_entry(service: Any, address: str) -> dict[str, Any]:
    """The account's Send mail as entry for ``address``; Gmail would rewrite any other From."""
    wanted = address.strip().lower()
    for entry in service.list_send_as():
        email = str(entry.get("sendAsEmail") or "").strip().lower()
        usable = entry.get("isPrimary") is True or entry.get("verificationStatus") == "accepted"
        if email == wanted and usable:
            return entry
    raise ValueError(
        f"Gmail Send: {address} is not a Send mail as address of this Gmail account; "
        "add it in Gmail settings or leave From blank"
    )


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the gmailSend node: send the email from the connected Gmail account."""
    from app.db.models import CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config
    from app.services.gmail_service import GmailApiError, GmailService

    fields = resolve_email_fields(ctx)
    from_address = ctx.executor.evaluate_nonempty_message_template(
        ctx.node_data.get("fromAddress", ""), ctx.inputs, ctx.node_id
    ).strip()

    credential_id = str(ctx.node_data.get("credentialId") or "")
    if not credential_id:
        raise ValueError("Gmail Send node requires a Gmail credential")

    with SessionLocal() as db:
        cred = ctx.executor._get_accessible_credential(db, credential_id)
        if cred is None or getattr(cred, "type", None) != CredentialType.gmail:
            raise ValueError("Gmail credential not found or not accessible")
        config: dict = decrypt_config(cred.encrypted_config)

    if not fields.to:
        raise ValueError("Email recipient (to) is required")

    attachments = load_attachments(ctx, fields, "Gmail Send")
    account = str(config.get("email_address") or "").strip()

    try:
        with SessionLocal() as db:
            service = GmailService(credential_id, config, db)
            # A blank From lets Gmail use the account's default address and its name.
            sender = ""
            if from_address and from_address.lower() != account.lower():
                entry = _send_as_entry(service, from_address)
                sender = formataddr(
                    (str(entry.get("displayName") or ""), str(entry["sendAsEmail"]))
                )
            msg = build_mime_message(fields, sender, attachments, bcc_header=True, account=account)
            sent = service.send_message(msg.as_bytes())
    except GmailApiError as exc:
        raise ValueError(f"Failed to send email: {exc}") from exc

    return sent_output(
        fields,
        len(attachments),
        **{
            "from": from_address or account,
            "message_id": str(sent.get("id") or ""),
            "thread_id": str(sent.get("threadId") or ""),
        },
    )
