"""Public SSO login: status, initiation, and callback."""

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_ip
from app.config import settings
from app.db.session import get_db
from app.models.schemas import SsoStatusResponse
from app.services.auth_rate_limiter import login_limiter
from app.services.oidc_client import build_authorization_url, fetch_discovery, make_pkce_pair
from app.services.sso_settings import callback_url, decrypt_client_secret, get_sso_settings

router = APIRouter()

_TX_COOKIE = "sso_tx"
_TX_COOKIE_PATH = "/api/auth/sso/"
_TX_TTL_MINUTES = 10
_TX_TYPE = "sso_tx"


def safe_next_path(candidate: str | None) -> str:
    """Reduce a post-login target to a same-origin path.

    An unchecked value turns the callback into an open redirect, so anything that is not a
    single-slash relative path is discarded rather than repaired.
    """
    if not candidate or not candidate.startswith("/"):
        return "/"
    if candidate.startswith("//") or candidate.startswith("/\\"):
        return "/"
    return candidate


def _encode_transaction(state: str, nonce: str, code_verifier: str, next_path: str) -> str:
    """Sign the in-flight login state for the browser cookie.

    The PKCE verifier lives here and never in the ``state`` parameter: ``state`` round-trips
    through the provider, and a signed JWT is not an encrypted one.
    """
    payload = {
        "type": _TX_TYPE,
        "state": state,
        "nonce": nonce,
        "code_verifier": code_verifier,
        "next": next_path,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_TX_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def _decode_transaction(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("type") == _TX_TYPE else None


@router.get("/status", response_model=SsoStatusResponse)
async def sso_status(db: AsyncSession = Depends(get_db)) -> SsoStatusResponse:
    """What the login screen needs. The issuer and client id are not disclosed here."""
    row = await get_sso_settings(db)
    configured = bool(row.enabled and row.issuer and row.client_id)
    return SsoStatusResponse(
        enabled=configured,
        button_label=row.button_label,
        password_login_enabled=not (configured and row.password_login_disabled),
    )


@router.get("/login")
async def sso_login(
    request: Request,
    next: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    allowed, retry_after = login_limiter.is_allowed(get_client_ip(request))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    row = await get_sso_settings(db)
    if not (row.enabled and row.issuer and row.client_id):
        return RedirectResponse(url="/login?sso_error=sso_disabled", status_code=302)
    if not decrypt_client_secret(row.encrypted_client_secret):
        return RedirectResponse(url="/login?sso_error=sso_disabled", status_code=302)

    try:
        discovery = await fetch_discovery(row.issuer)
    except Exception:  # noqa: BLE001 - the browser gets one error code, never provider text
        return RedirectResponse(url="/login?sso_error=token_exchange_failed", status_code=302)

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier, code_challenge = make_pkce_pair()

    auth_url = build_authorization_url(
        discovery,
        client_id=row.client_id,
        redirect_uri=callback_url(request),
        scopes=row.scopes,
        state=state,
        nonce=nonce,
        code_challenge=code_challenge,
    )

    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        key=_TX_COOKIE,
        value=_encode_transaction(state, nonce, code_verifier, safe_next_path(next)),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=_TX_TTL_MINUTES * 60,
        path=_TX_COOKIE_PATH,
    )
    return response
