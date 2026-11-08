"""Whether an account may still authenticate, and ending every session it holds.

Deactivation and "sign out everywhere" both come down to two facts on the user row:
`is_active`, checked wherever a credential resolves to a user, and
`sessions_revoked_at`, which refuses access tokens issued before it. Refresh and OAuth
tokens are revoked in their own tables, so no rotation can mint a new access token.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import OAuthAccessToken, RefreshToken, User
from app.services.auth import SIGN_IN_MFA, SIGN_IN_SSO, TokenClaims

DEACTIVATED_DETAIL = "This account has been deactivated. Contact your administrator."


def token_still_valid(
    is_active: bool, sessions_revoked_at: datetime | None, issued_at: int | None
) -> bool:
    """Whether an access token issued at `issued_at` (epoch milliseconds) still holds."""
    if not is_active:
        return False
    if sessions_revoked_at is None:
        return True
    if issued_at is None:
        return False
    return issued_at >= int(sessions_revoked_at.timestamp() * 1000)


def meets_mfa_policy(method: str | None, *, has_password: bool, has_sso_identity: bool) -> bool:
    """Whether a session may continue under HEYM_REQUIRE_MFA.

    Turning the flag on ends password sessions that began without a code, so an account
    that has not enrolled yet does so at its next sign-in before it reaches anything.
    SSO sessions are the provider's business and always continue.
    """
    if not settings.require_mfa:
        return True
    if method in (SIGN_IN_MFA, SIGN_IN_SSO):
        return True
    if method is None:
        # Minted before sessions recorded their method. An account with an SSO identity may
        # have signed in through SSO and continues; a password-only one signs in again.
        return not has_password or has_sso_identity
    return False


def session_still_valid(
    claims: TokenClaims,
    *,
    is_active: bool,
    sessions_revoked_at: datetime | None,
    has_password: bool,
    has_sso_identity: bool,
) -> bool:
    """Whether a token still speaks for its account: active, not signed out, MFA policy."""
    if not token_still_valid(is_active, sessions_revoked_at, claims.issued_at):
        return False
    return meets_mfa_policy(
        claims.method, has_password=has_password, has_sso_identity=has_sso_identity
    )


def access_token_current(user: User, claims: TokenClaims) -> bool:
    return session_still_valid(
        claims,
        is_active=user.is_active,
        sessions_revoked_at=user.sessions_revoked_at,
        has_password=bool(user.hashed_password),
        has_sso_identity=bool(user.sso_subject),
    )


async def revoke_sessions(db: AsyncSession, user: User) -> None:
    """End every session: access tokens by timestamp, refresh and OAuth tokens by row."""
    user.sessions_revoked_at = datetime.now(timezone.utc)
    await revoke_session_rows(db, user.id)


async def revoke_session_rows(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    await db.execute(
        update(OAuthAccessToken)
        .where(OAuthAccessToken.user_id == user_id, OAuthAccessToken.revoked.is_(False))
        .values(revoked=True)
    )
    await db.flush()


def mark_signed_in(user: User) -> None:
    user.last_login_at = datetime.now(timezone.utc)
