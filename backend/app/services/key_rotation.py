"""Re-encrypting stored values under ENCRYPTION_KEY (phase 3 of a key rotation, #862).

The rotation is two configuration changes and one admin action:

1. Introduce: ENCRYPTION_KEY=old, ENCRYPTION_KEYS_EXTRA=new, on every instance.
2. Promote: ENCRYPTION_KEY=new, ENCRYPTION_KEYS_EXTRA=old, on every instance.
3. Re-encrypt: an admin starts this job once every live instance encrypts with new.
4. Retire: drop old from ENCRYPTION_KEYS_EXTRA once the job has completed.

The job runs on the leader in batches. Before each batch it checks that every live
instance still encrypts with the rotation's target, and pauses with the reason if
not: a leader still on the old key would otherwise rotate rows back to it. A row is
rewritten only if the target key alone can't decrypt it, so the job is idempotent,
and rows no configured key reads are counted as unreadable, never as remaining, so
it can finish. It completes on a recount that finds nothing remaining, which catches
rows written mid-pass by an instance that joined between heartbeats.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cryptography.fernet import InvalidToken
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    ENCRYPTION_CANARY_ID,
    SSO_SETTINGS_ID,
    Credential,
    EncryptionCanary,
    KeyRotation,
    KeyRotationState,
    SsoSettings,
    User,
)
from app.db.session import async_session_maker
from app.services.cluster import identity, registry
from app.services.encryption import get_multi_fernet, readable_by_primary, rotate_token

logger = logging.getLogger("key_rotation")

BATCH_SIZE = 100
LOOP_SECONDS = 2.0


class RotationRefusedError(Exception):
    """The rotation can't start now; the message says why."""


@dataclass
class TokenCounts:
    """How stored values stand against the current keys."""

    current: int = 0  # the primary alone decrypts it
    remaining: int = 0  # another configured key decrypts it: the job will rewrite it
    unreadable: int = 0  # no configured key decrypts it


@dataclass
class UnreadableCredential:
    id: uuid.UUID
    name: str
    type: str
    owner_email: str
    updated_at: datetime | None


@dataclass
class FleetStatus:
    ready: bool
    reason: str
    target: str
    instances: list[registry.InstanceView] = field(default_factory=list)


def _classify(token: str) -> str:
    if readable_by_primary(token):
        return "current"
    try:
        get_multi_fernet().decrypt(token.encode())
    except InvalidToken:
        return "unreadable"
    return "remaining"


def _classify_all(tokens: list[str]) -> list[str]:
    return [_classify(token) for token in tokens]


def _rotate_all(tokens: list[str]) -> list[str | None]:
    """The token re-encrypted under the primary, or None when it needs no rewrite or can't
    have one (the primary already reads it, or no configured key does)."""
    rotated: list[str | None] = []
    for token in tokens:
        if readable_by_primary(token):
            rotated.append(None)
            continue
        try:
            rotated.append(rotate_token(token))
        except InvalidToken:
            rotated.append(None)
    return rotated


def fleet_status(instances: list[registry.InstanceView], *, now: datetime) -> FleetStatus:
    """Whether every live instance, and this process, encrypts with this process's key."""
    target = identity.primary_fingerprint()
    live = [i for i in instances if registry.is_live(i, now=now)]
    if not live:
        return FleetStatus(False, "No instance has sent a heartbeat recently.", target, live)
    behind = sorted(i.name or i.id for i in live if registry.primary_fingerprint(i) != target)
    if behind:
        return FleetStatus(
            False,
            f"Waiting for every instance to encrypt with key {target}. "
            f"Still on another key: {', '.join(behind)}.",
            target,
            live,
        )
    return FleetStatus(True, "", target, live)


async def _stored_tokens(db: AsyncSession) -> AsyncIterator[tuple[str, uuid.UUID | None, str]]:
    """Every stored ciphertext: (kind, credential id or None, token)."""
    last: uuid.UUID | None = None
    while True:
        query = (
            select(Credential.id, Credential.encrypted_config)
            .where(Credential.source.is_(None))
            .order_by(Credential.id)
            .limit(500)
        )
        if last is not None:
            query = query.where(Credential.id > last)
        rows = (await db.execute(query)).all()
        for credential_id, token in rows:
            yield "credential", credential_id, token
        if len(rows) < 500:
            break
        last = rows[-1][0]
    sso = await db.get(SsoSettings, SSO_SETTINGS_ID)
    if sso is not None and sso.encrypted_client_secret:
        yield "sso", None, sso.encrypted_client_secret
    canary = await db.get(EncryptionCanary, ENCRYPTION_CANARY_ID)
    if canary is not None:
        yield "canary", None, canary.token


async def _classified(db: AsyncSession) -> list[tuple[str, uuid.UUID | None, str]]:
    """Every stored ciphertext's (kind, credential id, class).

    Decrypting each one is CPU work, done in a thread so a large install doesn't stall
    the event loop while the Encryption tab polls during a rotation.
    """
    stored = [item async for item in _stored_tokens(db)]
    classes = await asyncio.to_thread(_classify_all, [token for _, _, token in stored])
    return [(kind, credential_id, c) for (kind, credential_id, _), c in zip(stored, classes)]


async def count_tokens(db: AsyncSession) -> TokenCounts:
    counts = TokenCounts()
    for _kind, _id, kind in await _classified(db):
        setattr(counts, kind, getattr(counts, kind) + 1)
    return counts


async def unreadable_credentials(db: AsyncSession) -> list[UnreadableCredential]:
    """Credentials no configured key decrypts, for the admin list. Their owners see them too."""
    unreadable_ids = [
        credential_id
        for kind, credential_id, c in await _classified(db)
        if kind == "credential" and c == "unreadable"
    ]
    if not unreadable_ids:
        return []
    rows = await db.execute(
        select(Credential, User.email)
        .join(User, User.id == Credential.owner_id)
        .where(Credential.id.in_(unreadable_ids))
        .order_by(Credential.updated_at.desc())
    )
    return [
        UnreadableCredential(
            id=credential.id,
            name=credential.name,
            type=credential.type.value,
            owner_email=email,
            updated_at=credential.updated_at,
        )
        for credential, email in rows.all()
    ]


async def active_rotation(db: AsyncSession) -> KeyRotation | None:
    return (
        await db.execute(select(KeyRotation).where(KeyRotation.active.is_(True)))
    ).scalar_one_or_none()


async def latest_rotation(db: AsyncSession) -> KeyRotation | None:
    return (
        await db.execute(select(KeyRotation).order_by(KeyRotation.started_at.desc()).limit(1))
    ).scalar_one_or_none()


async def start_rotation(
    db: AsyncSession, user: User, instances: list[registry.InstanceView]
) -> KeyRotation:
    """Record a new rotation, refused unless every live instance encrypts with one key."""
    if await active_rotation(db) is not None:
        raise RotationRefusedError("A key rotation is already in progress.")
    now = datetime.now(timezone.utc)
    fleet = fleet_status(instances, now=now)
    if not fleet.ready:
        raise RotationRefusedError(fleet.reason)
    retired = sorted(
        {fp for i in fleet.instances for fp in i.decrypt_fingerprints} - {fleet.target}
    )
    counts = await count_tokens(db)
    rotation = KeyRotation(
        state=KeyRotationState.running.value,
        active=True,
        target_fingerprint=fleet.target,
        retired_fingerprints=retired,
        started_by_id=user.id,
        remaining=counts.remaining,
        unreadable=counts.unreadable,
    )
    db.add(rotation)
    await db.commit()
    return rotation


async def _rewrite_batch(
    db: AsyncSession, cursor: uuid.UUID | None
) -> tuple[int, int, uuid.UUID | None]:
    """Rewrite one batch of credentials. Returns (rows read, rows rewritten, last id)."""
    query = (
        select(Credential.id, Credential.encrypted_config)
        .where(Credential.source.is_(None))
        .order_by(Credential.id)
        .limit(BATCH_SIZE)
        # An OAuth refresh writing the same row waits for this batch, so neither
        # overwrites the other with stale data.
        .with_for_update()
    )
    if cursor is not None:
        query = query.where(Credential.id > cursor)
    rows = (await db.execute(query)).all()
    new_tokens = await asyncio.to_thread(_rotate_all, [token for _, token in rows])
    rewritten = 0
    for (credential_id, _), new_token in zip(rows, new_tokens):
        if new_token is None:
            continue
        # Core UPDATE that keeps updated_at: a re-encryption isn't an edit, and must not
        # look like one or change anything keyed on it. The CHECK constraint still holds.
        await db.execute(
            update(Credential)
            .where(Credential.id == credential_id)
            .values(encrypted_config=new_token, updated_at=Credential.updated_at)
        )
        rewritten += 1
    return len(rows), rewritten, rows[-1][0] if rows else cursor


async def _rewrite_singletons(db: AsyncSession) -> int:
    """The SSO client secret and the key check's canary."""
    rewritten = 0
    sso = (
        await db.execute(
            select(SsoSettings).where(SsoSettings.id == SSO_SETTINGS_ID).with_for_update()
        )
    ).scalar_one_or_none()
    if sso is not None and sso.encrypted_client_secret:
        if not readable_by_primary(sso.encrypted_client_secret):
            with contextlib.suppress(InvalidToken):
                sso.encrypted_client_secret = rotate_token(sso.encrypted_client_secret)
                rewritten += 1
    canary = (
        await db.execute(
            select(EncryptionCanary)
            .where(EncryptionCanary.id == ENCRYPTION_CANARY_ID)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if canary is not None and not readable_by_primary(canary.token):
        with contextlib.suppress(InvalidToken):
            canary.token = rotate_token(canary.token)
            rewritten += 1
    return rewritten


async def step(
    instances: list[registry.InstanceView],
    *,
    sessions: async_sessionmaker = async_session_maker,
) -> KeyRotation | None:
    """Advance the active rotation by one batch, or pause it. Run by the leader."""
    async with sessions() as db:
        rotation = await active_rotation(db)
        if rotation is None:
            return None
        fleet = fleet_status(instances, now=datetime.now(timezone.utc))
        if not fleet.ready or fleet.target != rotation.target_fingerprint:
            reason = fleet.reason or (
                f"This rotation re-encrypts under key {rotation.target_fingerprint}, but the "
                f"instances now encrypt with {fleet.target}."
            )
            if rotation.state != KeyRotationState.paused.value or rotation.message != reason:
                rotation.state = KeyRotationState.paused.value
                rotation.message = reason
                await db.commit()
                logger.warning("Key rotation paused: %s", reason)
            return rotation
        if rotation.state == KeyRotationState.paused.value:
            rotation.state = KeyRotationState.running.value
            rotation.message = ""

        read, rewritten, rotation.cursor = await _rewrite_batch(db, rotation.cursor)
        rotation.done += rewritten
        rotation.remaining = max(rotation.remaining - rewritten, 0)
        if read == BATCH_SIZE:
            await db.commit()
            return rotation

        # End of a pass: the singletons, then a recount decides.
        rotation.done += await _rewrite_singletons(db)
        await db.commit()
        counts = await count_tokens(db)
        rotation.remaining = counts.remaining
        rotation.unreadable = counts.unreadable
        rotation.cursor = None
        if counts.remaining == 0:
            rotation.state = KeyRotationState.completed.value
            rotation.active = False
            rotation.completed_at = datetime.now(timezone.utc)
            rotation.message = ""
            logger.info(
                "Key rotation completed: %d rewritten, %d unreadable",
                rotation.done,
                rotation.unreadable,
            )
        await db.commit()
        return rotation


class KeyRotationService:
    """Runs the active rotation on whichever process is the leader."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        from app.services.distributed_lock import lock_service

        while True:
            try:
                if lock_service.is_leader:
                    rotation = await step(await registry.list_instances())
                    # Batches back to back while a pass is under way; between passes, and
                    # while paused or idle, check back later.
                    mid_pass = rotation is not None and rotation.cursor is not None
                    if mid_pass and rotation.state == KeyRotationState.running.value:
                        await asyncio.sleep(0)
                        continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Key rotation step failed")
            await asyncio.sleep(LOOP_SECONDS)


key_rotation_service = KeyRotationService()
