"""Admin-only OIDC configuration."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_instance_admin
from app.db.models import SsoSettings, User
from app.db.session import get_db
from app.models.schemas import SsoSettingsResponse, SsoSettingsUpdate, SsoTestResponse
from app.services.audit_log import OUTCOME_FAILURE, audit
from app.services.oidc_client import fetch_discovery
from app.services.sso_settings import callback_url, encrypt_client_secret, get_sso_settings

router = APIRouter()


def apply_settings_update(row: SsoSettings, update: SsoSettingsUpdate) -> None:
    """Apply a partial update to the settings row, enforcing the lockout preconditions."""
    for field in ("issuer", "client_id", "scopes"):
        value = getattr(update, field)
        if value is not None and value.strip() != getattr(row, field):
            setattr(row, field, value.strip())
            # The recorded test result belongs to the old connection details.
            row.last_test_ok = False

    if update.client_secret:
        row.encrypted_client_secret = encrypt_client_secret(update.client_secret)
        row.last_test_ok = False

    if update.enabled is not None:
        row.enabled = update.enabled
    if update.button_label is not None:
        row.button_label = update.button_label.strip() or "Sign in with SSO"
    if update.auto_provision_users is not None:
        row.auto_provision_users = update.auto_provision_users
    if update.allowed_email_domains is not None:
        row.allowed_email_domains = update.allowed_email_domains.strip()

    if update.password_login_disabled is not None:
        if update.password_login_disabled and not (row.enabled and row.last_test_ok):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Password login can only be disabled once SSO is enabled and a "
                    "connection test has passed."
                ),
            )
        row.password_login_disabled = update.password_login_disabled


@router.get("", response_model=SsoSettingsResponse)
async def get_sso_config(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SsoSettingsResponse:
    require_instance_admin(current_user)
    row = await get_sso_settings(db)
    return SsoSettingsResponse.from_row(row, redirect_uri=callback_url(request))


@router.put("", response_model=SsoSettingsResponse)
async def update_sso_config(
    update: SsoSettingsUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SsoSettingsResponse:
    require_instance_admin(current_user)
    row = await get_sso_settings(db)
    apply_settings_update(row, update)
    row.updated_by_id = current_user.id
    await db.flush()
    await db.refresh(row)

    audit(
        action="sso_settings.update",
        actor=current_user,
        target_type="sso_settings",
        enabled=row.enabled,
        password_login_disabled=row.password_login_disabled,
    )
    return SsoSettingsResponse.from_row(row, redirect_uri=callback_url(request))


@router.post("/test", response_model=SsoTestResponse)
async def test_sso_connection(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SsoTestResponse:
    require_instance_admin(current_user)
    row = await get_sso_settings(db)
    if not row.issuer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Set an issuer URL first"
        )

    try:
        discovery = await fetch_discovery(row.issuer, use_cache=False)
    except Exception as exc:  # noqa: BLE001 - any network failure surfaces to the admin as text
        row.last_test_ok = False
        row.last_test_at = datetime.now(timezone.utc)
        await db.flush()
        audit(
            action="sso_settings.test",
            actor=current_user,
            outcome=OUTCOME_FAILURE,
            reason=str(exc),
        )
        return SsoTestResponse(ok=False, error=str(exc))

    row.last_test_ok = True
    row.last_test_at = datetime.now(timezone.utc)
    await db.flush()
    audit(action="sso_settings.test", actor=current_user)
    return SsoTestResponse(
        ok=True,
        issuer=discovery.issuer,
        authorization_endpoint=discovery.authorization_endpoint,
        token_endpoint=discovery.token_endpoint,
        jwks_uri=discovery.jwks_uri,
        userinfo_endpoint=discovery.userinfo_endpoint,
    )
