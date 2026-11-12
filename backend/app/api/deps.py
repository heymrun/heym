import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.config import settings
from app.db.models import User
from app.db.session import async_session_maker, get_db
from app.services.account_status import access_token_current, session_still_valid
from app.services.auth import TokenClaims, read_access_claims
from app.services.instance_admin import is_instance_admin
from app.services.work_integration import WORK_CLIENT, WORK_KEY_HEADER, work_token_is_bound


def get_client_ip(request: Request) -> str:
    """Resolve real client IP.

    Proxy/CDN headers are only trusted when TRUST_PROXY_HEADERS=true, which
    should only be set when the application sits behind a trusted reverse proxy
    or Cloudflare.  Without that flag, the direct TCP peer address is used,
    preventing IP-spoofing attacks against rate limiters.
    """
    if settings.trust_proxy_headers:
        cf_ip = request.headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip.strip()
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"


security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)


def _extract_token(
    request: Request, credentials: HTTPAuthorizationCredentials | None
) -> str | None:
    """Return the bearer token from the Authorization header or the access_token cookie."""
    if credentials is not None:
        return credentials.credentials
    return request.cookies.get("access_token")


async def resolve_token_claims(request: HTTPConnection, token: str) -> TokenClaims | None:
    """Return the claims of a bearer token, enforcing Heym Work's key binding."""
    claims = read_access_claims(token)
    if claims is None:
        return None
    if claims.client is None:
        return claims
    if claims.client == WORK_CLIENT and await work_token_is_bound(
        request.headers.get(WORK_KEY_HEADER), claims.key_version
    ):
        return claims
    return None


async def resolve_token_user_id(request: HTTPConnection, token: str) -> uuid.UUID | None:
    """Return the user a bearer token names, enforcing Heym Work's key binding.

    This says nothing about whether the account may still act; callers that load the user
    must also check `access_token_current`.
    """
    claims = await resolve_token_claims(request, token)
    return claims.user_id if claims is not None else None


async def _load_token_user(db: AsyncSession, claims: TokenClaims | None) -> User | None:
    """The user a token speaks for, or None when the account is gone, off, or signed out."""
    if claims is None:
        return None
    result = await db.execute(select(User).where(User.id == claims.user_id))
    user = result.scalar_one_or_none()
    if user is None or not access_token_current(user, claims):
        return None
    return user


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = _extract_token(request, credentials)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = await resolve_token_claims(request, token)

    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await _load_token_user(db, claims)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
) -> uuid.UUID:
    """Resolve the authenticated user's id from the JWT without opening a DB session.

    Streaming endpoints use this so they do not hold a request-scoped DB connection for
    the entire response lifetime (which can exhaust the pool under many open streams).
    """
    token = _extract_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = await resolve_token_claims(request, token)
    if claims is None or not await _account_accepts_token(claims):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims.user_id


async def _account_accepts_token(claims: TokenClaims) -> bool:
    # A short session for the account check only, released before the stream starts.
    async with async_session_maker() as db:
        result = await db.execute(
            select(
                User.is_active, User.sessions_revoked_at, User.hashed_password, User.sso_subject
            ).where(User.id == claims.user_id)
        )
        row = result.first()
    if row is None:
        return False
    return session_still_valid(
        claims,
        is_active=row[0],
        sessions_revoked_at=row[1],
        has_password=bool(row[2]),
        has_sso_identity=bool(row[3]),
    )


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    token = _extract_token(request, credentials)
    if not token:
        return None

    claims = await resolve_token_claims(request, token)
    return await _load_token_user(db, claims)


#: Sent by Heym's own frontend on every API call (``heymClientHeaders`` in
#: ``frontend/src/constants/httpIdentity.ts``). A custom header cannot be added to a
#: top-level navigation, and a cross-site script cannot send one without a CORS
#: preflight that only ``CORS_ORIGINS`` pass, so its presence marks a request that Heym
#: itself made.
HEYM_CLIENT_HEADER = "X-Heym-Client"


async def get_execution_caller(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """The signed-in user a workflow run may execute as, or None (GHSA-m2cg-mg73-qc82).

    The run's credential and global-variable context belong to whoever this returns, so
    the browser's session cookie must not decide it on its own. A link followed from
    another site, or opened from an e-mail, carries the ``access_token`` cookie
    (``SameSite=Lax``) but the user never asked Heym to run anything. A session that
    arrives only as that cookie therefore counts only on Heym's own API calls, which
    carry ``X-Heym-Client``. Everything else is treated as a caller with no session: an
    anonymous workflow runs in its owner's context, a jwt workflow answers 401.

    A bearer token in ``Authorization`` (API clients, Heym Work, execution tokens) is an
    explicit choice of credential and is resolved as before.
    """
    if credentials is None and not request.headers.get(HEYM_CLIENT_HEADER):
        return None
    return await get_current_user_optional(request, credentials, db)


def require_instance_admin(current_user: User) -> None:
    """Raise 403 unless the caller is an instance administrator."""
    if not is_instance_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to manage instance settings.",
        )
