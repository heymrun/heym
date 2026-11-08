"""The Heym Work channel. Every endpoint requires the integration key."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import mfa_sign_in, password_sign_in, register_account
from app.api.deps import get_client_ip
from app.config import settings
from app.db.models import User, WorkIntegration
from app.db.session import get_db
from app.models.schemas import MfaLoginRequest, UserCreate, UserLogin
from app.models.work_integration_schemas import (
    WorkAuditRequest,
    WorkHandshakeRequest,
    WorkHandshakeResponse,
    WorkRefreshRequest,
    WorkSsoExchangeRequest,
    WorkTokenResponse,
    WorkUserSummary,
)
from app.services import mfa
from app.services.account_status import mark_signed_in, meets_mfa_policy
from app.services.audit_log import OUTCOME_DENIED, audit
from app.services.auth import (
    SIGN_IN_MFA,
    SIGN_IN_PASSWORD,
    SIGN_IN_SSO,
    create_access_token,
    create_refresh_token,
    read_refresh_claims,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.services.sso_settings import get_sso_settings
from app.services.work_integration import (
    WORK_CLIENT,
    WORK_KEY_HEADER,
    consume_sso_code,
    get_work_integration,
    issue_work_tokens,
    key_matches,
    key_version,
    work_client_ip,
)

router = APIRouter()


async def require_work_channel(
    request: Request, db: AsyncSession = Depends(get_db)
) -> WorkIntegration:
    """Admit only requests that carry the current key of an enabled integration."""
    row = await get_work_integration(db)
    if not (row.enabled and key_matches(row.key_hash, request.headers.get(WORK_KEY_HEADER))):
        audit(action="work.channel_auth", outcome=OUTCOME_DENIED, reason="bad_key_or_disabled")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Heym Work key"
        )
    return row


def _summary(user: User) -> WorkUserSummary:
    return WorkUserSummary(id=str(user.id), email=user.email, name=user.name)


async def _load_user(db: AsyncSession, user_id: object) -> User | None:
    """The account behind a code or refresh token, while it may still sign in."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


@router.post("/handshake", response_model=WorkHandshakeResponse)
async def handshake(
    body: WorkHandshakeRequest,
    row: WorkIntegration = Depends(require_work_channel),
    db: AsyncSession = Depends(get_db),
) -> WorkHandshakeResponse:
    now = datetime.now(timezone.utc)
    row.handshake_nonce = body.nonce
    row.handshake_at = now
    row.last_seen_at = now
    row.last_work_version = body.work_version
    row.last_license_status = body.license_status

    sso = await get_sso_settings(db)
    sso_enabled = bool(sso.enabled and sso.issuer and sso.client_id)
    password_login = "admins_only" if sso_enabled and sso.password_login_disabled else "allowed"

    # Work reads the nonce back from the database right after this response.
    await db.commit()
    return WorkHandshakeResponse(
        heym_version=settings.resolved_version,
        sso_enabled=sso_enabled,
        sso_button_label=sso.button_label,
        password_login=password_login,
        registration_allowed=bool(settings.allow_register and password_login == "allowed"),
        work_url=row.work_url,
    )


_SIGN_IN_AGAIN = "Sign in again to set up two-factor authentication."


def _second_factor_response(user: User) -> JSONResponse | None:
    """A 401 carrying the challenge when the password alone does not finish this sign-in.

    The challenge sits beside `detail` rather than inside it, so a Work release that does
    not know the second step still shows a readable message instead of failing to parse.
    An account without an authenticator also gets `mfa_setup`: Work shows its QR code, and
    the enrolment completes in Work before any session exists.
    """
    requirement = mfa.password_sign_in_requirement(user)
    if requirement is None:
        return None
    audit(action="auth.mfa_challenge", actor=user, client=WORK_CLIENT, purpose=requirement)
    content: dict[str, object] = {
        "detail": "Enter the code from your authenticator app.",
        "mfa_challenge": mfa.create_challenge_token(user.id, requirement, client=WORK_CLIENT),
    }
    if requirement == mfa.PURPOSE_ENROLL:
        offer = mfa.create_setup_offer(user)
        content["detail"] = "Set up two-factor authentication to continue."
        content["mfa_setup"] = {
            "setup_token": offer.setup_token,
            "secret": offer.secret,
            "otpauth_uri": offer.otpauth_uri,
            "qr_code": offer.qr_code,
        }
    return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content=content)


async def _work_session(
    db: AsyncSession, user: User, row: WorkIntegration, method: str
) -> WorkTokenResponse:
    mark_signed_in(user)
    tokens = await issue_work_tokens(db, user.id, row, method=method)
    return WorkTokenResponse(
        access_token=tokens.access_token, refresh_token=tokens.refresh_token, user=_summary(user)
    )


@router.post("/login", response_model=WorkTokenResponse)
async def channel_login(
    body: UserLogin,
    request: Request,
    row: WorkIntegration = Depends(require_work_channel),
    db: AsyncSession = Depends(get_db),
) -> WorkTokenResponse | JSONResponse:
    ip = work_client_ip(request, fallback=get_client_ip(request))
    user = await password_sign_in(db, body, ip, client=WORK_CLIENT)
    challenge = _second_factor_response(user)
    if challenge is not None:
        return challenge
    session = await _work_session(db, user, row, SIGN_IN_PASSWORD)
    audit(action="auth.login", actor=user, client=WORK_CLIENT)
    return session


@router.post("/login/mfa", response_model=WorkTokenResponse)
async def channel_login_mfa(
    body: MfaLoginRequest,
    row: WorkIntegration = Depends(require_work_channel),
    db: AsyncSession = Depends(get_db),
) -> WorkTokenResponse:
    """Finish a Work password sign-in with a code, enrolling first when `setup_token` is set."""
    user, codes, method = await mfa_sign_in(db, body, client=WORK_CLIENT)
    session = await _work_session(db, user, row, SIGN_IN_MFA)
    session.recovery_codes = codes
    audit(action="auth.login", actor=user, client=WORK_CLIENT, mfa=method)
    return session


@router.post("/register", response_model=WorkTokenResponse, status_code=status.HTTP_201_CREATED)
async def channel_register(
    body: UserCreate,
    request: Request,
    row: WorkIntegration = Depends(require_work_channel),
    db: AsyncSession = Depends(get_db),
) -> WorkTokenResponse | JSONResponse:
    ip = work_client_ip(request, fallback=get_client_ip(request))
    user = await register_account(db, body, ip, client=WORK_CLIENT)
    challenge = _second_factor_response(user)
    if challenge is not None:
        audit(action="auth.register", actor=user, client=WORK_CLIENT)
        # The account exists before its enrolment; a 401 must not roll it back.
        await db.commit()
        return challenge
    mark_signed_in(user)
    tokens = await issue_work_tokens(db, user.id, row, method=SIGN_IN_PASSWORD)
    audit(action="auth.register", actor=user, client=WORK_CLIENT)
    return WorkTokenResponse(
        access_token=tokens.access_token, refresh_token=tokens.refresh_token, user=_summary(user)
    )


@router.post("/sso/exchange", response_model=WorkTokenResponse)
async def channel_sso_exchange(
    body: WorkSsoExchangeRequest,
    row: WorkIntegration = Depends(require_work_channel),
    db: AsyncSession = Depends(get_db),
) -> WorkTokenResponse:
    user_id = await consume_sso_code(db, body.code)
    user = await _load_user(db, user_id) if user_id is not None else None
    if user is None:
        audit(
            action="auth.sso_exchange",
            outcome=OUTCOME_DENIED,
            client=WORK_CLIENT,
            reason="invalid_code",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign-in code is invalid or expired",
        )
    tokens = await issue_work_tokens(db, user.id, row, method=SIGN_IN_SSO)
    audit(action="auth.sso_exchange", actor=user, client=WORK_CLIENT)
    return WorkTokenResponse(
        access_token=tokens.access_token, refresh_token=tokens.refresh_token, user=_summary(user)
    )


@router.post("/refresh", response_model=WorkTokenResponse)
async def channel_refresh(
    body: WorkRefreshRequest,
    row: WorkIntegration = Depends(require_work_channel),
    db: AsyncSession = Depends(get_db),
) -> WorkTokenResponse:
    current = key_version(row.key_hash or "")
    claims = read_refresh_claims(body.refresh_token)
    if claims is None or claims.client != WORK_CLIENT or claims.key_version != current:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    user = await _load_user(db, claims.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not meets_mfa_policy(
        claims.method,
        has_password=bool(user.hashed_password),
        has_sso_identity=bool(user.sso_subject),
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_SIGN_IN_AGAIN)

    new_access = create_access_token(
        user.id, client=WORK_CLIENT, key_version=current, method=claims.method
    )
    new_refresh = create_refresh_token(
        user.id, client=WORK_CLIENT, key_version=current, method=claims.method
    )
    if not await rotate_refresh_token(db, body.refresh_token, new_refresh, user.id):
        audit(
            action="auth.token_refresh",
            outcome=OUTCOME_DENIED,
            actor=user,
            client=WORK_CLIENT,
            reason="refresh_token_replayed_or_revoked",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token already used or revoked",
        )
    audit(action="auth.token_refresh", actor=user, client=WORK_CLIENT)
    return WorkTokenResponse(
        access_token=new_access, refresh_token=new_refresh, user=_summary(user)
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def channel_logout(
    body: WorkRefreshRequest,
    row: WorkIntegration = Depends(require_work_channel),
    db: AsyncSession = Depends(get_db),
) -> None:
    claims = read_refresh_claims(body.refresh_token)
    if claims is not None and claims.client == WORK_CLIENT:
        await revoke_refresh_token(db, body.refresh_token)
        audit(action="auth.logout", actor_id=claims.user_id, client=WORK_CLIENT)


@router.post("/audit", status_code=status.HTTP_204_NO_CONTENT)
async def channel_audit(
    body: WorkAuditRequest,
    row: WorkIntegration = Depends(require_work_channel),
) -> None:
    audit(
        action=body.action,
        outcome=body.outcome,
        actor_id=body.actor_id,
        target_type=body.target_type,
        target_id=body.target_id,
        target_name=body.target_name,
        source="work",
        **body.detail,
    )
