"""Instance administrators manage user accounts: deactivate, reactivate, sign out, reset MFA."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_instance_admin
from app.api.sso_admin import break_glass_available
from app.api.workflows import set_owner_triggers_paused
from app.db.models import User
from app.db.session import get_db
from app.models.admin_user_schemas import (
    AdminUserActionResponse,
    AdminUserItem,
    AdminUserListResponse,
)
from app.services import mfa
from app.services.account_status import revoke_sessions
from app.services.audit_log import OUTCOME_DENIED, audit
from app.services.instance_admin import is_instance_admin
from app.services.sso_settings import get_sso_settings

router = APIRouter()


def _item(user: User) -> AdminUserItem:
    methods: list[str] = []
    if user.hashed_password:
        methods.append("password")
    if user.sso_subject:
        methods.append("sso")
    return AdminUserItem(
        id=user.id,
        email=user.email,
        name=user.name,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        is_active=user.is_active,
        deactivated_at=user.deactivated_at,
        is_admin=is_instance_admin(user),
        sign_in_methods=methods,
        mfa_enabled=mfa.mfa_enabled(user),
    )


async def _target(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("", response_model=AdminUserListResponse)
async def list_users(
    q: str = Query(default="", max_length=255),
    status_filter: str = Query(default="all", alias="status", pattern="^(all|active|deactivated)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminUserListResponse:
    require_instance_admin(current_user)
    conditions = []
    term = q.strip().lower()
    if term:
        pattern = f"%{term}%"
        conditions.append(
            or_(func.lower(User.email).like(pattern), func.lower(User.name).like(pattern))
        )
    if status_filter == "active":
        conditions.append(User.is_active.is_(True))
    elif status_filter == "deactivated":
        conditions.append(User.is_active.is_(False))
    total = (
        await db.execute(select(func.count()).select_from(User).where(*conditions))
    ).scalar() or 0
    rows = await db.execute(
        select(User).where(*conditions).order_by(func.lower(User.email)).limit(limit).offset(offset)
    )
    return AdminUserListResponse(
        items=[_item(user) for user in rows.scalars().all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{user_id}/deactivate", response_model=AdminUserActionResponse)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminUserActionResponse:
    """Block every sign-in and credential, end all sessions, and pause owned triggers."""
    require_instance_admin(current_user)
    user = await _target(db, user_id)
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate yourself."
        )
    if not user.is_active:
        return AdminUserActionResponse(user=_item(user))

    user.is_active = False
    user.deactivated_at = datetime.now(timezone.utc)
    await db.flush()
    # The SSO lockout guard: someone must still be able to sign in with a password.
    sso_row = await get_sso_settings(db)
    if sso_row.password_login_disabled and not await break_glass_available(db):
        audit(
            action="user.deactivate",
            outcome=OUTCOME_DENIED,
            actor=current_user,
            target_type="user",
            target_id=user.id,
            target_name=user.email,
            reason="last_break_glass_admin",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Password sign-in is disabled and this is the last administrator who can "
                "still sign in with a password. Add another first."
            ),
        )

    await revoke_sessions(db, user)
    paused = await set_owner_triggers_paused(user.id, True, current_user, db)
    audit(
        action="user.deactivate",
        actor=current_user,
        target_type="user",
        target_id=user.id,
        target_name=user.email,
        workflows_paused=paused,
    )
    return AdminUserActionResponse(user=_item(user), workflows_changed=paused)


@router.post("/{user_id}/reactivate", response_model=AdminUserActionResponse)
async def reactivate_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminUserActionResponse:
    """Allow sign-in again and resume the triggers deactivation paused."""
    require_instance_admin(current_user)
    user = await _target(db, user_id)
    if user.is_active:
        return AdminUserActionResponse(user=_item(user))

    user.is_active = True
    user.deactivated_at = None
    await db.flush()
    resumed = await set_owner_triggers_paused(user.id, False, current_user, db)
    audit(
        action="user.reactivate",
        actor=current_user,
        target_type="user",
        target_id=user.id,
        target_name=user.email,
        workflows_resumed=resumed,
    )
    return AdminUserActionResponse(user=_item(user), workflows_changed=resumed)


@router.post("/{user_id}/sign-out", response_model=AdminUserActionResponse)
async def sign_out_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminUserActionResponse:
    """End every session the account holds, without blocking its next sign-in."""
    require_instance_admin(current_user)
    user = await _target(db, user_id)
    await revoke_sessions(db, user)
    audit(
        action="user.sessions_revoke",
        actor=current_user,
        target_type="user",
        target_id=user.id,
        target_name=user.email,
    )
    return AdminUserActionResponse(user=_item(user))


@router.post("/{user_id}/mfa/reset", response_model=AdminUserActionResponse)
async def reset_user_mfa(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminUserActionResponse:
    """Remove two-factor sign-in, for someone who lost their authenticator and codes."""
    require_instance_admin(current_user)
    user = await _target(db, user_id)
    await mfa.disable_mfa(db, user)
    audit(
        action="user.mfa_reset",
        actor=current_user,
        target_type="user",
        target_id=user.id,
        target_name=user.email,
    )
    return AdminUserActionResponse(user=_item(user))
