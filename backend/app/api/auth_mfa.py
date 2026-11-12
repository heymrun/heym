"""Self-service two-factor sign-in while HEYM_REQUIRE_MFA is on.

Enrolment itself happens at sign-in. Here a password account can move to a new
authenticator and replace its recovery codes. There is no way to turn it off: the
instance requires it, and a lost authenticator is reset by an administrator.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db.models import User
from app.db.session import get_db
from app.models.schemas import (
    MfaCodeRequest,
    MfaEnableRequest,
    MfaRecoveryCodesResponse,
    MfaSetupRequest,
    MfaSetupResponse,
    MfaStatusResponse,
)
from app.services import mfa
from app.services.audit_log import OUTCOME_FAILURE, audit
from app.services.auth import verify_password

router = APIRouter()

_CODE_INVALID = "That code is not valid. Check your authenticator app and try again."


def _require_available(user: User) -> None:
    if not settings.require_mfa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Two-factor authentication is not turned on for this instance.",
        )
    # SSO accounts never reach here from the UI: their provider owns the second factor.
    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account signs in through single sign-on.",
        )


def _check_rate(user: User) -> None:
    allowed, retry_after = mfa.mfa_limiter.is_allowed(str(user.id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


@router.get("", response_model=MfaStatusResponse)
async def mfa_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MfaStatusResponse:
    enabled = mfa.mfa_enabled(current_user)
    return MfaStatusResponse(
        enabled=enabled,
        required=settings.require_mfa,
        available=settings.require_mfa and bool(current_user.hashed_password),
        enabled_at=current_user.mfa_enabled_at,
        recovery_codes_remaining=(
            await mfa.recovery_codes_remaining(db, current_user.id) if enabled else 0
        ),
    )


@router.post("/setup", response_model=MfaSetupResponse)
async def mfa_setup(
    body: MfaSetupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MfaSetupResponse:
    """Offer a secret for a new authenticator. Nothing changes until a code confirms it.

    The password and a code from the current authenticator are both asked for: a stolen
    session alone must not be able to swap the factor and lock the owner out.
    """
    _require_available(current_user)
    _check_rate(current_user)
    if not verify_password(body.password, current_user.hashed_password):
        audit(action="auth.mfa_replace", outcome=OUTCOME_FAILURE, actor=current_user)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect"
        )
    if mfa.mfa_enabled(current_user):
        if await mfa.verify_second_factor(db, current_user, body.code or "") is None:
            audit(action="auth.mfa_replace", outcome=OUTCOME_FAILURE, actor=current_user)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_CODE_INVALID)
        mfa.mfa_limiter.record_success(str(current_user.id))
    offer = mfa.create_setup_offer(current_user)
    return MfaSetupResponse(
        setup_token=offer.setup_token,
        secret=offer.secret,
        otpauth_uri=offer.otpauth_uri,
        qr_code=offer.qr_code,
    )


@router.post("/enable", response_model=MfaRecoveryCodesResponse)
async def mfa_enable(
    body: MfaEnableRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MfaRecoveryCodesResponse:
    """Store the new authenticator once a code from it verifies. Recovery codes are new too."""
    _require_available(current_user)
    _check_rate(current_user)
    secret = mfa.read_setup_secret(body.setup_token, current_user.id)
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The setup expired. Start again."
        )
    replacing = mfa.mfa_enabled(current_user)
    codes = await mfa.enable_mfa(db, current_user, secret, body.code)
    if codes is None:
        audit(action="auth.mfa_replace", outcome=OUTCOME_FAILURE, actor=current_user)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_CODE_INVALID)
    mfa.mfa_limiter.record_success(str(current_user.id))
    audit(action="auth.mfa_replace" if replacing else "auth.mfa_enable", actor=current_user)
    return MfaRecoveryCodesResponse(recovery_codes=codes)


@router.post("/recovery-codes", response_model=MfaRecoveryCodesResponse)
async def mfa_regenerate_recovery_codes(
    body: MfaCodeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MfaRecoveryCodesResponse:
    """Replace every recovery code. The old ones stop working at once."""
    _require_available(current_user)
    _check_rate(current_user)
    if await mfa.verify_second_factor(db, current_user, body.code) is None:
        audit(
            action="auth.mfa_recovery_codes_regenerate",
            outcome=OUTCOME_FAILURE,
            actor=current_user,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_CODE_INVALID)
    mfa.mfa_limiter.record_success(str(current_user.id))
    codes = await mfa.regenerate_recovery_codes(db, current_user)
    audit(action="auth.mfa_recovery_codes_regenerate", actor=current_user)
    return MfaRecoveryCodesResponse(recovery_codes=codes)
