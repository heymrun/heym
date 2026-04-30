import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days)
    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except InvalidTokenError:
        return None


def verify_access_token(token: str) -> uuid.UUID | None:
    payload = decode_token(token)
    if payload is None:
        return None
    if payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    return uuid.UUID(user_id)


def verify_refresh_token(token: str) -> uuid.UUID | None:
    payload = decode_token(token)
    if payload is None:
        return None
    if payload.get("type") != "refresh":
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    return uuid.UUID(user_id)


def _hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a token string."""
    return hashlib.sha256(token.encode()).hexdigest()


async def store_refresh_token(db: AsyncSession, token: str, user_id: uuid.UUID) -> None:
    """Persist a hashed refresh token so it can be revoked on rotation."""
    from app.db.models import RefreshToken  # local import to avoid circular deps

    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days)
    record = RefreshToken(
        token_hash=_hash_token(token),
        user_id=user_id,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(record)
    await db.flush()


async def revoke_refresh_token(db: AsyncSession, token: str) -> None:
    """Mark a single refresh token as revoked (best-effort, ignores missing tokens)."""
    from app.db.models import RefreshToken  # local import to avoid circular deps

    token_hash = _hash_token(token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
        )
    )
    record = result.scalar_one_or_none()
    if record is not None:
        record.revoked = True
        await db.flush()


async def rotate_refresh_token(
    db: AsyncSession, old_token: str, new_token: str, user_id: uuid.UUID
) -> bool:
    """
    Revoke the old refresh token and store the new one atomically.

    Uses SELECT FOR UPDATE to prevent two concurrent refresh requests from both
    reading the same row as un-revoked (TOCTOU race condition that would cause
    one device/tab to be logged out when multiple sessions refresh simultaneously).

    Returns False if the old token is already revoked or expired (replay attack).
    """
    from app.db.models import RefreshToken  # local import to avoid circular deps

    old_hash = _hash_token(old_token)
    result = await db.execute(
        select(RefreshToken)
        .where(
            RefreshToken.token_hash == old_hash,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
        .with_for_update()
    )
    record = result.scalar_one_or_none()

    if record is None:
        return False

    record.revoked = True
    await db.flush()

    await store_refresh_token(db, new_token, user_id)
    return True


async def cleanup_expired_refresh_tokens(db: AsyncSession) -> int:
    """
    Delete refresh token rows that are past their expiry date.

    Intended to be called by the background cron scheduler periodically.
    Returns the number of rows deleted.
    """
    from sqlalchemy import delete

    from app.db.models import RefreshToken  # local import to avoid circular deps

    result = await db.execute(
        delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(timezone.utc))
    )
    await db.flush()
    return result.rowcount
