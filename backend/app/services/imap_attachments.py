"""IMAP Trigger attachments into Heym Drive, for a trigger with `imapDownloadAttachments` on.

The poller hands the run metadata only (`email.attachments`). With the toggle on, the trigger
node logs in again during the run, fetches the same message by UID from a read-only mailbox
and saves each attachment in the run owner's Drive. The download happens in the run, not in the
poller, because the poller runs on the cluster leader while Drive files live on the main
instance; the placement predicate pins these runs there.

A download problem never fails the run, which is never retried once it has started: the item
carries a `skipped_reason` instead. A storage error fails the step and leaves no file behind.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.services.file_sandbox.scope import as_uuid
from app.services.node_execution.base import NodeExecutionContext

if TYPE_CHECKING:
    from app.services.imap_trigger_service import EmailAttachment

logger = logging.getLogger("imap_trigger")

MAX_FILES = 10
TOO_LARGE = "too_large"
TOO_MANY = "too_many"
UNAVAILABLE = "unavailable"


@dataclass
class _Planned:
    """One attachment as the output lists it, with its bytes while it waits to be saved."""

    filename: str
    content_type: str
    size_bytes: int
    content: bytes | None = None
    skipped_reason: str | None = None


def metadata_items(email: dict[str, Any]) -> list[dict[str, Any]]:
    """`email.attachments` as the trigger's `attachments` output when nothing is saved."""
    items: list[dict[str, Any]] = []
    for item in email.get("attachments") or []:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "filename": item.get("filename"),
                "content_type": item.get("content_type"),
                "size_bytes": item.get("size_bytes"),
            }
        )
    return items


def _skipped(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "id": None,
        "filename": item.get("filename"),
        "content_type": item.get("content_type"),
        "size_bytes": item.get("size_bytes"),
        "download_url": None,
        "skipped_reason": reason,
    }


def _unavailable(email: dict[str, Any]) -> dict[str, Any]:
    items = [_skipped(item, UNAVAILABLE) for item in metadata_items(email)]
    return {"attachments": items, "file_ids": []}


def _load_credential_config(ctx: NodeExecutionContext) -> dict[str, Any]:
    """The node's `imap` credential, read with the run owner's access."""
    from app.db.models import CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    credential_id = ctx.node_data.get("credentialId")
    if not credential_id:
        raise ValueError("IMAP Trigger requires a credential to download attachments")
    with SessionLocal() as db:
        credential = ctx.executor._get_accessible_credential(db, credential_id)
        if credential is None or getattr(credential, "type", None) != CredentialType.imap:
            raise ValueError("IMAP credential not found or not accessible")
        return decrypt_config(credential.encrypted_config)


def _plan(attachments: list[EmailAttachment], max_bytes: int) -> list[_Planned]:
    """Which attachments to save, in email order: too large first, then the cap of ten."""
    planned: list[_Planned] = []
    kept = 0
    for attachment in attachments:
        item = _Planned(
            filename=attachment.filename,
            content_type=attachment.content_type,
            size_bytes=len(attachment.content),
        )
        if item.size_bytes > max_bytes:
            item.skipped_reason = TOO_LARGE
        elif kept >= MAX_FILES:
            item.skipped_reason = TOO_MANY
        else:
            item.content = attachment.content
            kept += 1
        planned.append(item)
    return planned


def _remove_written(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass


def _store(
    ctx: NodeExecutionContext, planned: list[_Planned], email: dict[str, Any]
) -> list[dict[str, Any]]:
    """Every kept attachment into Drive in one transaction; on any failure none of them stays."""
    from app.db.session import SessionLocal
    from app.services.file_storage import build_download_url, get_file_path, store_file_sync

    executor = ctx.executor
    owner_id = getattr(executor, "trace_user_id", None)
    if not owner_id:
        raise ValueError("IMAP Trigger: no owner context available to store the attachments")
    workflow_id = as_uuid(getattr(executor, "workflow_id", None))
    metadata = {"imap_uid": str(email.get("uid") or "")}
    if email.get("messageId"):
        metadata["message_id"] = str(email["messageId"])

    items: list[dict[str, Any]] = []
    written: list[Path] = []
    with SessionLocal() as db:
        try:
            for item in planned:
                if item.content is None:
                    items.append(
                        {
                            "id": None,
                            "filename": item.filename,
                            "content_type": item.content_type,
                            "size_bytes": item.size_bytes,
                            "download_url": None,
                            "skipped_reason": item.skipped_reason,
                        }
                    )
                    continue
                row, access_token = store_file_sync(
                    db,
                    owner_id=owner_id,
                    file_bytes=item.content,
                    filename=item.filename,
                    mime_type=item.content_type or "application/octet-stream",
                    workflow_id=workflow_id,
                    source_node_id=ctx.node_id,
                    source_node_label=ctx.node_label,
                    context="IMAP Trigger",
                )
                written.append(get_file_path(row))
                row.metadata_json = dict(metadata)
                items.append(
                    {
                        "id": str(row.id),
                        "filename": row.filename,
                        "content_type": item.content_type,
                        "size_bytes": item.size_bytes,
                        "download_url": build_download_url(executor._base_url, access_token),
                        "skipped_reason": None,
                    }
                )
            if written:
                db.commit()
        except Exception:
            db.rollback()
            _remove_written(written)
            raise
    return items


def download_attachments(ctx: NodeExecutionContext, email: dict[str, Any]) -> dict[str, Any]:
    """Save the email's attachments in the run owner's Drive.

    Returns the trigger's `attachments` items and the `file_ids` of the saved files.
    """
    from app.config import settings
    from app.services import imap_trigger_service

    if not metadata_items(email):
        return {"attachments": [], "file_ids": []}
    uid = str(email.get("uid") or "").strip()
    uidvalidity = str(email.get("uidvalidity") or "").strip()
    if not uid or not uidvalidity:
        return _unavailable(email)

    credential_config = _load_credential_config(ctx)
    try:
        raw_bytes = imap_trigger_service.fetch_imap_message_by_uid(
            credential_config, uid, uidvalidity
        )
    except Exception as exc:
        logger.warning("IMAP Trigger could not fetch uid=%s to save its attachments: %s", uid, exc)
        return _unavailable(email)
    if raw_bytes is None:
        return _unavailable(email)

    message_id, attachments = imap_trigger_service.email_attachments(raw_bytes)
    expected_id = str(email.get("messageId") or "")
    if expected_id and message_id and expected_id != message_id:
        return _unavailable(email)

    max_bytes = settings.file_max_size_mb * 1024 * 1024
    items = _store(ctx, _plan(attachments, max_bytes), email)
    return {
        "attachments": items,
        "file_ids": [item["id"] for item in items if item["id"]],
    }
