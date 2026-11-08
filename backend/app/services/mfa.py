"""TOTP two-factor sign-in (RFC 6238) for password accounts.

SSO accounts never reach this module: their provider owns the second factor.

The authenticator secret is encrypted under ENCRYPTION_KEY because verifying a code needs
the secret itself. Recovery codes carry 80 random bits each, so a plain SHA-256 digest is
enough at rest (see `secret_tokens.py`) and a stored digest never verifies as a code.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

import jwt
import segno
from cryptography.fernet import InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User, UserMfaRecoveryCode
from app.services.auth import decode_token
from app.services.encryption import decrypt_text, encrypt_text
from app.services.secret_tokens import hash_secret
from app.services.shared_rate_limiter import SharedRateLimiter

ISSUER = "Heym"
PERIOD_SECONDS = 30
DIGITS = 6
# One step either side absorbs phone clock drift without widening the guess space much.
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_RECOVERY_LENGTH = 16
CHALLENGE_TTL_SECONDS = 300
SETUP_TTL_SECONDS = 600

PURPOSE_VERIFY = "verify"
PURPOSE_ENROLL = "enroll"

# Keyed by user id: a password guess unlocks a challenge, the code is the last barrier.
mfa_limiter = SharedRateLimiter(
    namespace="auth_mfa", max_attempts=5, window_seconds=300, ban_seconds=900
)


def generate_secret() -> str:
    """A new 160-bit base32 secret, the size RFC 4226 recommends."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _secret_bytes(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def code_at_step(secret: str, step: int) -> str:
    """The TOTP code for one 30-second step."""
    digest = hmac.new(_secret_bytes(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**DIGITS)).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD_SECONDS)


def _normalize_totp(code: str) -> str:
    return "".join(ch for ch in code if ch.isdigit())


def matching_step(
    secret: str, code: str, *, last_step: int | None, now: float | None = None
) -> int | None:
    """The step a code belongs to, or None. A step at or before `last_step` never matches."""
    candidate = _normalize_totp(code)
    if len(candidate) != DIGITS:
        return None
    step_now = current_step(now)
    for step in range(step_now - DRIFT_STEPS, step_now + DRIFT_STEPS + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at_step(secret, step), candidate):
            return step
    return None


def otpauth_uri(secret: str, email: str) -> str:
    """The URI authenticator apps read from the QR code."""
    label = quote(f"{ISSUER}:{email}")
    query = urlencode(
        {
            "secret": secret,
            "issuer": ISSUER,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": PERIOD_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def qr_data_uri(uri: str) -> str:
    """An SVG data URI of the QR code, rendered here so the page needs no QR library."""
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2)


def normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def generate_recovery_codes() -> list[str]:
    codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_LENGTH))
        codes.append("-".join(raw[i : i + 4] for i in range(0, _RECOVERY_LENGTH, 4)))
    return codes


def mfa_enabled(user: User) -> bool:
    return user.mfa_enabled_at is not None and bool(user.mfa_secret)


def password_sign_in_requirement(user: User) -> str | None:
    """What a correct password still needs: a code, an enrolment, or nothing.

    Two-factor sign-in exists only while HEYM_REQUIRE_MFA is on, and then for every
    password sign-in. Secrets stay stored while it is off, so turning it back on asks the
    same accounts for the same authenticator.
    """
    if not settings.require_mfa:
        return None
    if mfa_enabled(user):
        return PURPOSE_VERIFY
    return PURPOSE_ENROLL


@dataclass(frozen=True)
class ChallengeClaims:
    user_id: uuid.UUID
    purpose: str
    client: str | None


def create_challenge_token(user_id: uuid.UUID, purpose: str, *, client: str | None) -> str:
    """A short-lived proof that the password was right. It is not a session."""
    payload: dict[str, object] = {
        "sub": str(user_id),
        "type": "mfa_challenge",
        "purpose": purpose,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=CHALLENGE_TTL_SECONDS),
        "jti": str(uuid.uuid4()),
    }
    if client is not None:
        payload["cli"] = client
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def read_challenge_token(token: str) -> ChallengeClaims | None:
    payload = decode_token(token)
    if payload is None or payload.get("type") != "mfa_challenge":
        return None
    purpose = payload.get("purpose")
    if purpose not in (PURPOSE_VERIFY, PURPOSE_ENROLL):
        return None
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except ValueError:
        return None
    client = payload.get("cli")
    return ChallengeClaims(
        user_id=user_id, purpose=str(purpose), client=str(client) if client else None
    )


@dataclass(frozen=True)
class SetupOffer:
    """A secret offered for enrolment, not yet stored on the account."""

    setup_token: str
    secret: str
    otpauth_uri: str
    qr_code: str


def create_setup_offer(user: User) -> SetupOffer:
    """A fresh secret, carried encrypted in a signed token until a code confirms it."""
    secret = generate_secret()
    token = jwt.encode(
        {
            "sub": str(user.id),
            "type": "mfa_setup",
            "sec": encrypt_text(secret),
            "exp": datetime.now(timezone.utc) + timedelta(seconds=SETUP_TTL_SECONDS),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    uri = otpauth_uri(secret, user.email)
    return SetupOffer(setup_token=token, secret=secret, otpauth_uri=uri, qr_code=qr_data_uri(uri))


def read_setup_secret(token: str, user_id: uuid.UUID) -> str | None:
    payload = decode_token(token)
    if payload is None or payload.get("type") != "mfa_setup":
        return None
    if payload.get("sub") != str(user_id):
        return None
    try:
        return decrypt_text(str(payload.get("sec") or ""))
    except InvalidToken:
        return None


async def _replace_recovery_codes(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    await db.execute(delete(UserMfaRecoveryCode).where(UserMfaRecoveryCode.user_id == user_id))
    codes = generate_recovery_codes()
    for code in codes:
        db.add(
            UserMfaRecoveryCode(
                user_id=user_id, code_hash=hash_secret(normalize_recovery_code(code))
            )
        )
    await db.flush()
    return codes


async def enable_mfa(db: AsyncSession, user: User, secret: str, code: str) -> list[str] | None:
    """Store the secret once a code from it verifies. Returns the recovery codes, shown once."""
    step = matching_step(secret, code, last_step=None)
    if step is None:
        return None
    user.mfa_secret = encrypt_text(secret)
    user.mfa_enabled_at = datetime.now(timezone.utc)
    user.mfa_last_step = step
    return await _replace_recovery_codes(db, user.id)


async def disable_mfa(db: AsyncSession, user: User) -> None:
    user.mfa_secret = None
    user.mfa_enabled_at = None
    user.mfa_last_step = None
    await db.execute(delete(UserMfaRecoveryCode).where(UserMfaRecoveryCode.user_id == user.id))
    await db.flush()


async def regenerate_recovery_codes(db: AsyncSession, user: User) -> list[str]:
    return await _replace_recovery_codes(db, user.id)


async def recovery_codes_remaining(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(UserMfaRecoveryCode.id).where(UserMfaRecoveryCode.user_id == user_id)
    )
    return len(result.all())


async def _verify_totp(db: AsyncSession, user: User, code: str) -> bool:
    if not user.mfa_secret:
        return False
    # Lock the row so two requests carrying the same code cannot both pass.
    locked = await db.execute(
        select(User.mfa_last_step).where(User.id == user.id).with_for_update()
    )
    last_step = locked.scalar_one_or_none()
    try:
        secret = decrypt_text(user.mfa_secret)
    except InvalidToken:
        return False
    step = matching_step(secret, code, last_step=last_step)
    if step is None:
        return False
    user.mfa_last_step = step
    await db.flush()
    return True


async def _consume_recovery_code(db: AsyncSession, user: User, code: str) -> bool:
    normalized = normalize_recovery_code(code)
    if len(normalized) != _RECOVERY_LENGTH:
        return False
    result = await db.execute(
        delete(UserMfaRecoveryCode)
        .where(
            UserMfaRecoveryCode.user_id == user.id,
            UserMfaRecoveryCode.code_hash == hash_secret(normalized),
        )
        .returning(UserMfaRecoveryCode.id)
    )
    return result.first() is not None


async def verify_second_factor(db: AsyncSession, user: User, code: str) -> str | None:
    """Return "totp" or "recovery" for an accepted code, else None."""
    if not mfa_enabled(user):
        return None
    if await _verify_totp(db, user, code):
        return "totp"
    if await _consume_recovery_code(db, user, code):
        return "recovery"
    return None
