"""Gmail Trigger attachments into Heym Drive, for a trigger with `gmailDownloadAttachments` on.

Same rules as the IMAP Trigger (see imap_attachments.py): the poller hands the run metadata
only, and the node fetches the message again by its Gmail id during the run, on the main
instance where Drive files live. A fetch problem never fails the run; the items are then
`unavailable`.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.imap_attachments import (
    metadata_items,
    plan_attachments,
    store_attachments,
    unavailable,
)
from app.services.node_execution.base import NodeExecutionContext

logger = logging.getLogger("gmail_trigger")


def _credential_config(ctx: NodeExecutionContext) -> tuple[str, dict[str, Any]]:
    """The node's `gmail` credential, read with the run owner's access."""
    from app.db.models import CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    credential_id = str(ctx.node_data.get("credentialId") or "")
    if not credential_id:
        raise ValueError("Gmail Trigger requires a credential to download attachments")
    with SessionLocal() as db:
        credential = ctx.executor._get_accessible_credential(db, credential_id)
        if credential is None or getattr(credential, "type", None) != CredentialType.gmail:
            raise ValueError("Gmail credential not found or not accessible")
        return credential_id, decrypt_config(credential.encrypted_config)


def _raw_message(credential_id: str, config: dict[str, Any], message_id: str) -> bytes | None:
    from app.db.session import SessionLocal
    from app.services.gmail_service import GmailService, decode_raw_message

    with SessionLocal() as db:
        message = GmailService(credential_id, config, db).get_raw_message(message_id)
    raw = str(message.get("raw") or "")
    return decode_raw_message(raw) if raw else None


def download_attachments(ctx: NodeExecutionContext, email: dict[str, Any]) -> dict[str, Any]:
    """Save the email's attachments in the run owner's Drive.

    Returns the trigger's `attachments` items and the `file_ids` of the saved files.
    """
    from app.config import settings
    from app.services.imap_trigger_service import email_attachments

    if not metadata_items(email):
        return {"attachments": [], "file_ids": []}
    message_id = str(email.get("id") or "").strip()
    if not message_id:
        return unavailable(email)

    credential_id, config = _credential_config(ctx)
    try:
        raw_bytes = _raw_message(credential_id, config, message_id)
    except Exception as exc:
        logger.warning(
            "Gmail Trigger could not fetch %s to save its attachments: %s", message_id, exc
        )
        return unavailable(email)
    if raw_bytes is None:
        return unavailable(email)

    found_id, attachments = email_attachments(raw_bytes)
    expected_id = str(email.get("messageId") or "")
    if expected_id and found_id and expected_id != found_id:
        return unavailable(email)

    metadata = {"gmail_message_id": message_id}
    if expected_id:
        metadata["message_id"] = expected_id
    max_bytes = settings.file_max_size_mb * 1024 * 1024
    items = store_attachments(
        ctx, plan_attachments(attachments, max_bytes), metadata, context="Gmail Trigger"
    )
    return {
        "attachments": items,
        "file_ids": [item["id"] for item in items if item["id"]],
    }
