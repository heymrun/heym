"""Public SSO login: status, initiation, and callback."""

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _set_auth_cookies
from app.api.deps import get_client_ip
from app.config import settings
from app.db.models import SsoSettings, User
from app.db.session import get_db
from app.models.schemas import SsoStatusResponse
from app.services.audit_log import OUTCOME_DENIED, OUTCOME_FAILURE, audit
from app.services.auth import create_access_token, create_refresh_token, store_refresh_token
from app.services.auth_rate_limiter import login_limiter
from app.services.oidc_client import (
    OidcError,
    build_authorization_url,
    exchange_code,
    fetch_discovery,
    fetch_userinfo,
    get_signing_key,
    make_pkce_pair,
    verify_id_token,
)
from app.services.sso_settings import (
    callback_url,
    decrypt_client_secret,
    email_domain_allowed,
    get_sso_settings,
)

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


class SsoLoginError(Exception):
    """A login was refused for a reason the login screen may name."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def resolve_sso_user(db: AsyncSession, row: SsoSettings, issuer: str, claims: dict) -> User:
    """Find, claim, or provision the Heym account for a verified set of ID token claims."""
    subject = str(claims.get("sub") or "")
    result = await db.execute(
        select(User).where(User.sso_issuer == issuer, User.sso_subject == subject)
    )
    matched = result.scalar_one_or_none()
    if matched is not None:
        return matched

    email = str(claims.get("email") or "").strip().lower()
    if not email:
        raise SsoLoginError("email_missing")
    # An address the provider will not vouch for must not claim an account, and must not
    # create one either: that is a direct account-takeover path.
    if claims.get("email_verified") is not True:
        raise SsoLoginError("email_not_verified")
    if not email_domain_allowed(email, row.allowed_email_domains):
        raise SsoLoginError("domain_not_allowed")

    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.sso_issuer = issuer
        existing.sso_subject = subject
        return existing

    if not row.auto_provision_users:
        raise SsoLoginError("provisioning_disabled")

    user = User(
        email=email,
        hashed_password=None,
        name=str(claims.get("name") or claims.get("preferred_username") or email),
        sso_issuer=issuer,
        sso_subject=subject,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/callback")
async def sso_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    def failure(reason: str) -> RedirectResponse:
        # The provider's own error text is never echoed: it is an XSS surface and leaks
        # configuration detail to anyone who can reach the login page.
        response = RedirectResponse(
            url=f"/login?{urlencode({'sso_error': reason})}", status_code=302
        )
        response.delete_cookie(_TX_COOKIE, path=_TX_COOKIE_PATH)
        return response

    transaction = _decode_transaction(request.cookies.get(_TX_COOKIE))
    if transaction is None or not state or transaction.get("state") != state:
        audit(action="auth.sso_login", outcome=OUTCOME_FAILURE, reason="state_mismatch")
        return failure("state_mismatch")
    if error or not code:
        audit(action="auth.sso_login", outcome=OUTCOME_FAILURE, reason="provider_error")
        return failure("token_exchange_failed")

    row = await get_sso_settings(db)
    if not (row.enabled and row.issuer and row.client_id):
        return failure("sso_disabled")

    try:
        discovery = await fetch_discovery(row.issuer)
        tokens = await exchange_code(
            discovery,
            client_id=row.client_id,
            client_secret=decrypt_client_secret(row.encrypted_client_secret),
            code=code,
            redirect_uri=callback_url(request),
            code_verifier=str(transaction["code_verifier"]),
        )
        signing_key = get_signing_key(discovery, tokens["id_token"])
        claims = verify_id_token(
            tokens["id_token"],
            signing_key=signing_key,
            discovery=discovery,
            client_id=row.client_id,
            expected_nonce=str(transaction["nonce"]),
        )
    except OidcError as exc:
        audit(action="auth.sso_login", outcome=OUTCOME_FAILURE, reason=str(exc))
        return failure("invalid_token")
    except Exception as exc:  # noqa: BLE001 - network failures reach the browser as one code
        audit(action="auth.sso_login", outcome=OUTCOME_FAILURE, reason=str(exc))
        return failure("token_exchange_failed")

    if not claims.get("email") and tokens.get("access_token"):
        claims = {**(await fetch_userinfo(discovery, tokens["access_token"])), **claims}

    try:
        user = await resolve_sso_user(db, row, discovery.issuer, claims)
    except SsoLoginError as rejection:
        audit(
            action="auth.sso_login",
            outcome=OUTCOME_DENIED,
            actor_email=str(claims.get("email") or ""),
            reason=rejection.code,
        )
        return failure(rejection.code)

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    await store_refresh_token(db, refresh_token, user.id)

    response = RedirectResponse(url=safe_next_path(transaction.get("next")), status_code=302)
    _set_auth_cookies(response, access_token, refresh_token)
    response.delete_cookie(_TX_COOKIE, path=_TX_COOKIE_PATH)

    audit(action="auth.sso_login", actor=user)
    return response
