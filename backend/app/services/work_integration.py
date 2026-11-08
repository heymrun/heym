"""Heym Work integration: key, singleton row, bound tokens and SSO hand-off codes."""

import asyncio
import hmac
import ipaddress
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WORK_INTEGRATION_ID, WorkIntegration, WorkSsoCode
from app.services.auth import create_access_token, create_refresh_token, store_refresh_token
from app.services.secret_tokens import hash_secret

WORK_CLIENT = "work"
WORK_KEY_HEADER = "X-Heym-Work-Key"
WORK_CLIENT_IP_HEADER = "X-Heym-Work-Client-IP"
WORK_KEY_PREFIX = "hwi_"
KEY_VERSION_LENGTH = 12
KEY_CACHE_SECONDS = 5.0
SSO_CODE_TTL = timedelta(seconds=60)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_WORK_STATE = re.compile(r"[A-Za-z0-9_-]{16,128}")


class WorkUrlError(ValueError):
    """The Work URL is not an acceptable redirect target."""


def mint_work_key() -> str:
    """Return a new integration key; the prefix keeps it distinguishable from a digest."""
    return WORK_KEY_PREFIX + secrets.token_urlsafe(32)


def key_version(key_hash: str) -> str:
    """Fingerprint of the stored digest. Tokens minted under an older key stop matching."""
    return key_hash[:KEY_VERSION_LENGTH]


def key_matches(stored_hash: str | None, presented: str | None) -> bool:
    """Compare a presented key with the stored digest. The digest itself never matches."""
    if not stored_hash or not presented:
        return False
    return hmac.compare_digest(stored_hash, hash_secret(presented))


def normalize_work_url(raw: str) -> str:
    """Validate and normalize the Work URL; https only, except local development hosts."""
    value = raw.strip().rstrip("/")
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.query or parts.fragment or not parts.hostname:
        raise WorkUrlError("Enter the Heym Work address without a query or fragment.")
    if parts.scheme == "https":
        return value
    if parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS:
        return value
    raise WorkUrlError("The Heym Work address must use https.")


def valid_work_state(value: str | None) -> bool:
    """True for the opaque state value Work sends with an SSO start."""
    return bool(value and _WORK_STATE.fullmatch(value))


def sso_callback_target(work_url: str, code: str, work_state: str) -> str:
    """Where a successful Work SSO sign-in lands: always the registered Work URL."""
    return f"{work_url}/auth/callback?{urlencode({'code': code, 'state': work_state})}"


def sso_failure_target(work_url: str, reason: str) -> str:
    """Where a failed Work SSO sign-in lands."""
    return f"{work_url}/login?{urlencode({'sso_error': reason})}"


async def get_work_integration(db: AsyncSession) -> WorkIntegration:
    """Return the singleton row, creating the disabled default on first access."""
    result = await db.execute(
        select(WorkIntegration).where(WorkIntegration.id == WORK_INTEGRATION_ID)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = WorkIntegration(id=WORK_INTEGRATION_ID)
        db.add(row)
        await db.flush()
        await db.refresh(row)
    return row


@dataclass(frozen=True)
class _KeySnapshot:
    enabled: bool
    key_hash: str | None
    loaded_at: float


_snapshot: _KeySnapshot | None = None
_snapshot_lock = asyncio.Lock()


def clear_key_cache() -> None:
    """Forget the cached key so the next check reads the database."""
    global _snapshot
    _snapshot = None


async def _load_snapshot() -> _KeySnapshot:
    from app.db.session import async_session_maker

    async with async_session_maker() as session:
        result = await session.execute(
            select(WorkIntegration.enabled, WorkIntegration.key_hash).where(
                WorkIntegration.id == WORK_INTEGRATION_ID
            )
        )
        row = result.one_or_none()
    if row is None:
        return _KeySnapshot(enabled=False, key_hash=None, loaded_at=time.monotonic())
    return _KeySnapshot(
        enabled=bool(row.enabled), key_hash=row.key_hash, loaded_at=time.monotonic()
    )


def _fresh(snapshot: _KeySnapshot | None) -> bool:
    return snapshot is not None and time.monotonic() - snapshot.loaded_at < KEY_CACHE_SECONDS


async def _current_snapshot() -> _KeySnapshot:
    global _snapshot
    snapshot = _snapshot
    if snapshot is not None and _fresh(snapshot):
        return snapshot
    async with _snapshot_lock:
        snapshot = _snapshot
        if snapshot is None or not _fresh(snapshot):
            snapshot = await _load_snapshot()
            _snapshot = snapshot
    return snapshot


async def work_token_is_bound(presented_key: str | None, token_key_version: str | None) -> bool:
    """True when a Work-bound token arrives with the current key of an enabled integration."""
    snapshot = await _current_snapshot()
    if not (snapshot.enabled and key_matches(snapshot.key_hash, presented_key)):
        return False
    return token_key_version == key_version(snapshot.key_hash or "")


def work_client_ip(request: Request, fallback: str) -> str:
    """The end user's IP as Work reports it; only call after the key was verified."""
    raw = (request.headers.get(WORK_CLIENT_IP_HEADER) or "").strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return fallback


@dataclass(frozen=True)
class WorkTokens:
    """An access and refresh token pair bound to Heym Work."""

    access_token: str
    refresh_token: str


async def issue_work_tokens(
    db: AsyncSession, user_id: uuid.UUID, row: WorkIntegration, *, method: str
) -> WorkTokens:
    """Mint and persist a token pair bound to Work and to the current key."""
    version = key_version(row.key_hash or "")
    access = create_access_token(user_id, client=WORK_CLIENT, key_version=version, method=method)
    refresh = create_refresh_token(user_id, client=WORK_CLIENT, key_version=version, method=method)
    await store_refresh_token(db, refresh, user_id)
    return WorkTokens(access_token=access, refresh_token=refresh)


async def create_sso_code(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Store a hashed one-time code for the user and return the plain code."""
    now = datetime.now(timezone.utc)
    await db.execute(delete(WorkSsoCode).where(WorkSsoCode.expires_at < now - timedelta(hours=1)))
    code = secrets.token_urlsafe(32)
    db.add(WorkSsoCode(code_hash=hash_secret(code), user_id=user_id, expires_at=now + SSO_CODE_TTL))
    await db.flush()
    return code


async def consume_sso_code(db: AsyncSession, code: str) -> uuid.UUID | None:
    """Return the user for an unused, unexpired code and mark it used."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(WorkSsoCode)
        .where(
            WorkSsoCode.code_hash == hash_secret(code),
            WorkSsoCode.used_at.is_(None),
            WorkSsoCode.expires_at > now,
        )
        .with_for_update()
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    row.used_at = now
    await db.flush()
    return row.user_id
