"""`python -m app.key_check`: refuse to start with keys this database wasn't encrypted with.

A wrong ENCRYPTION_KEY used to fail late and quietly: a run just lost `$credentials.x`.
This runs before uvicorn, after migrations (docker/release-entrypoint.sh, and the worker
commands, which start uvicorn directly). It can't run inside the app's lifespan: with
`--workers 8`, uvicorn respawns a worker whose lifespan fails, so the process never
stops.

It refuses two things, each with an error that names the cause:

- keys that can't decrypt the canary, a value written with this database's key;
- an ENCRYPTION_KEY that a completed rotation moved the database away from, such as a
  restored old `.env` (the rotation's new key is what every row is under now).

The canary is created only once a stored value has decrypted, so a wrong key at first
boot is never recorded as the right one.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass

from cryptography.fernet import InvalidToken
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    ENCRYPTION_CANARY_ID,
    SSO_SETTINGS_ID,
    Credential,
    EncryptionCanary,
    KeyRotation,
    KeyRotationState,
    SsoSettings,
)
from app.services.cluster import identity
from app.services.encryption import encrypt_config, get_multi_fernet

logger = logging.getLogger("key_check")

# How many stored values to try before calling the key wrong. Newest first: on an
# install that changed the key the hard way, rows written since are the readable ones.
SEED_SAMPLE_SIZE = 20
_CANARY_VALUE = {"heym": "encryption-canary"}
DOCS_HINT = 'See ENVIRONMENT-VARIABLES.md, "Rotating ENCRYPTION_KEY".'


class KeyCheckError(Exception):
    """This process's keys don't fit this database; the message says why."""


@dataclass(frozen=True)
class KeyCheckResult:
    message: str


def _decrypts(token: str) -> bool:
    try:
        get_multi_fernet().decrypt(token.encode())
    except InvalidToken:
        return False
    return True


async def _tables_exist(db: AsyncSession) -> bool:
    row = (
        await db.execute(
            text(
                "SELECT to_regclass('encryption_canary') IS NOT NULL "
                "AND to_regclass('key_rotations') IS NOT NULL"
            )
        )
    ).scalar()
    return bool(row)


async def _refuse_retired_primary(db: AsyncSession) -> None:
    primary = identity.primary_fingerprint()
    rotations = (
        await db.execute(
            select(KeyRotation).where(KeyRotation.state == KeyRotationState.completed.value)
        )
    ).scalars()
    for rotation in rotations:
        if primary in (rotation.retired_fingerprints or []):
            finished = rotation.completed_at.isoformat() if rotation.completed_at else "earlier"
            raise KeyCheckError(
                "ENCRYPTION_KEY is a key that a completed rotation moved this database away "
                f"from (finished {finished}). Set ENCRYPTION_KEY to the rotation's new key; "
                f"the old one may only appear in ENCRYPTION_KEYS_EXTRA. {DOCS_HINT}"
            )


async def _sample_tokens(db: AsyncSession) -> list[str]:
    """Newest stored ciphertexts: credentials (not Secret-backed ones) and the SSO secret."""
    rows = await db.execute(
        select(Credential.encrypted_config)
        .where(Credential.source.is_(None))
        .order_by(Credential.updated_at.desc())
        .limit(SEED_SAMPLE_SIZE)
    )
    tokens = [token for (token,) in rows.all() if token]
    sso = await db.get(SsoSettings, SSO_SETTINGS_ID)
    if sso is not None and sso.encrypted_client_secret:
        tokens.append(sso.encrypted_client_secret)
    return tokens


async def _write_canary(db: AsyncSession, *, replace: bool) -> None:
    token = encrypt_config(_CANARY_VALUE)
    stmt = pg_insert(EncryptionCanary).values(id=ENCRYPTION_CANARY_ID, token=token)
    if replace:
        stmt = stmt.on_conflict_do_update(
            index_elements=[EncryptionCanary.id], set_={"token": token}
        )
    else:
        # Several processes may start at once; the first one's canary stands.
        stmt = stmt.on_conflict_do_nothing(index_elements=[EncryptionCanary.id])
    await db.execute(stmt)
    await db.commit()


def _mismatch(detail: str) -> KeyCheckError:
    return KeyCheckError(
        "ENCRYPTION_KEY does not match the key this database was encrypted with: "
        f"{detail} If ENCRYPTION_KEY is right and the stored values can't be recovered, "
        f"start once with HEYM_ACCEPT_CURRENT_ENCRYPTION_KEY=true. {DOCS_HINT}"
    )


async def check(db: AsyncSession) -> KeyCheckResult:
    """Refuse this process's keys, or say why they're fine. Writes the canary when due."""
    if not await _tables_exist(db):
        # A worker restarted on a new image before main has migrated. Starting it keeps
        # today's behaviour: it runs, and the Instances view shows it as a mismatch.
        return KeyCheckResult("key check skipped: the database has not been migrated yet")

    await _refuse_retired_primary(db)

    canary = await db.get(EncryptionCanary, ENCRYPTION_CANARY_ID)
    accept = settings.accept_current_encryption_key
    if canary is not None:
        if _decrypts(canary.token):
            return KeyCheckResult("ENCRYPTION_KEY matches this database")
        if not accept:
            raise _mismatch("none of the configured keys decrypts the stored check value.")
        await _write_canary(db, replace=True)
        logger.warning("HEYM_ACCEPT_CURRENT_ENCRYPTION_KEY: replaced the key check value")
        return KeyCheckResult("ENCRYPTION_KEY accepted as this database's key")

    tokens = await _sample_tokens(db)
    if tokens and not any(_decrypts(token) for token in tokens) and not accept:
        raise _mismatch(f"none of the {len(tokens)} most recently stored values decrypts with it.")
    await _write_canary(db, replace=False)
    # A concurrent first start with other keys may have won the insert.
    db.expire_all()
    canary = await db.get(EncryptionCanary, ENCRYPTION_CANARY_ID)
    if canary is None or not _decrypts(canary.token):
        raise _mismatch("another process recorded a different key at the same time.")
    return KeyCheckResult("ENCRYPTION_KEY recorded as this database's key")


async def _run() -> KeyCheckResult:
    from app.db.session import async_session_maker, engine

    try:
        async with async_session_maker() as db:
            return await check(db)
    finally:
        await engine.dispose()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        result = asyncio.run(_run())
    except KeyCheckError as exc:
        print(f"Heym key check failed: {exc}", file=sys.stderr, flush=True)
        return 1
    print(result.message, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
