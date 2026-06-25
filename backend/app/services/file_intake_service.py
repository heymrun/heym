"""Mint, validate, and audit single-use file-upload capability slots."""

import fnmatch
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FileUploadAudit, FileUploadSlot

DEFAULT_TTL_MINUTES = 60
MIN_TTL_MINUTES = 1
MAX_TTL_MINUTES = 10080  # 7 days
HARD_MAX_SIZE_MB = 100
DEFAULT_MAX_SIZE_MB = 100


@dataclass
class SlotConfig:
    ttl_minutes: int
    max_size_bytes: int
    allowed_mime: list[str] | None


def generate_token() -> str:
    """Return a high-entropy URL-safe capability token (the secret IS the URL)."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def find_file_upload_trigger(nodes: list[dict]) -> dict | None:
    """Return the first fileUploadTrigger node in a workflow, or None."""
    for node in nodes or []:
        if node.get("type") == "fileUploadTrigger":
            return node
    return None


def resolve_slot_config(node: dict) -> SlotConfig:
    data = node.get("data", {}) or {}

    try:
        ttl = int(data.get("ttlMinutes", DEFAULT_TTL_MINUTES))
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL_MINUTES
    ttl = max(MIN_TTL_MINUTES, min(MAX_TTL_MINUTES, ttl))

    try:
        size_mb = int(data.get("maxSizeMb", DEFAULT_MAX_SIZE_MB))
    except (TypeError, ValueError):
        size_mb = DEFAULT_MAX_SIZE_MB
    size_mb = max(1, min(HARD_MAX_SIZE_MB, size_mb))

    allowed_raw = (data.get("allowedTypes") or "").strip()
    allowed_mime = [p.strip() for p in allowed_raw.split(",") if p.strip()] if allowed_raw else None

    return SlotConfig(
        ttl_minutes=ttl,
        max_size_bytes=size_mb * 1024 * 1024,
        allowed_mime=allowed_mime,
    )


def is_mime_allowed(allowed: list[str] | None, mime: str, filename: str) -> bool:
    if not allowed:
        return True
    lower_name = (filename or "").lower()
    for entry in allowed:
        e = entry.lower()
        if e.startswith("."):
            if lower_name.endswith(e):
                return True
        elif fnmatch.fnmatch((mime or "").lower(), e):
            return True
    return False


async def mint_slot(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    node: dict,
    created_by_user_id: uuid.UUID,
    mint_source: str,
) -> tuple[FileUploadSlot, str]:
    """Create a pending slot. Returns (slot, raw_token). Only the hash is stored."""
    cfg = resolve_slot_config(node)
    token = generate_token()
    slot = FileUploadSlot(
        workflow_id=workflow_id,
        token_hash=hash_token(token),
        status="pending",
        max_size_bytes=cfg.max_size_bytes,
        allowed_mime=cfg.allowed_mime,
        trigger_node_id=str(node.get("id", "")),
        trigger_node_label=(node.get("data", {}) or {}).get("label"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=cfg.ttl_minutes),
        created_by_user_id=created_by_user_id,
        mint_source=mint_source,
    )
    db.add(slot)
    await db.flush()
    return slot, token


async def consume_slot(db: AsyncSession, slot_id: uuid.UUID) -> bool:
    """Atomically flip pending->consumed. Returns True for the single winner."""
    result = await db.execute(
        update(FileUploadSlot)
        .where(FileUploadSlot.id == slot_id, FileUploadSlot.status == "pending")
        .values(status="consumed", consumed_at=datetime.now(timezone.utc))
    )
    return result.rowcount == 1


async def write_audit(
    db: AsyncSession,
    *,
    event: str,
    slot_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    file_name: str | None = None,
    file_size: int | None = None,
    mime: str | None = None,
) -> None:
    db.add(
        FileUploadAudit(
            event=event,
            slot_id=slot_id,
            workflow_id=workflow_id,
            client_ip=client_ip,
            user_agent=(user_agent or "")[:512] or None,
            file_name=file_name,
            file_size=file_size,
            mime=mime,
        )
    )
    await db.flush()


def build_mint_payload(
    *,
    base_url: str,
    token: str,
    expires_at_iso: str,
    max_size_bytes: int,
    allowed_mime: list[str] | None,
    slot_id: str,
) -> dict:
    """Caller-facing mint response: prefilled curl + upload metadata."""
    upload_url = f"{base_url.rstrip('/')}/api/file-intake/u/{token}"
    curl = f"curl -F 'file=@/path/to/your/file' '{upload_url}'"
    return {
        "file_upload_required": True,
        "curl": curl,
        "upload_url": upload_url,
        "expires_at": expires_at_iso,
        "max_size_mb": max_size_bytes // (1024 * 1024),
        "allowed_types": allowed_mime or [],
        "slot_id": slot_id,
        "instructions": (
            "This workflow expects a file upload. Run the curl command above with "
            "your file path. The link is single-use and expires at expires_at. The "
            "curl response contains the workflow result."
        ),
    }
