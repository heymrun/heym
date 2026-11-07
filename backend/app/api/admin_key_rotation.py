"""Admin view and start of ENCRYPTION_KEY re-encryption (#862), gated by HEYM_ADMIN_EMAILS."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_instance_admin
from app.db.models import KeyRotation, User
from app.db.session import get_db
from app.services import key_rotation
from app.services.audit_log import OUTCOME_DENIED, OUTCOME_SUCCESS, audit
from app.services.cluster import identity, registry

router = APIRouter()


class KeyRotationInstance(BaseModel):
    id: str
    name: str
    live: bool
    primary_fingerprint: str
    decrypt_fingerprints: list[str]


class KeyRotationProgress(BaseModel):
    id: uuid.UUID
    state: str
    target_fingerprint: str
    retired_fingerprints: list[str]
    done: int
    remaining: int
    unreadable: int
    message: str
    started_at: datetime
    completed_at: datetime | None = None


class UnreadableCredentialResponse(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    owner_email: str
    updated_at: datetime | None = None


class KeyRotationStatus(BaseModel):
    # This process's keys, by fingerprint.
    primary_fingerprint: str
    decrypt_fingerprints: list[str]
    instances: list[KeyRotationInstance]
    # Whether a rotation could start now, and if not, why.
    can_start: bool
    reason: str
    rotation: KeyRotationProgress | None = None
    unreadable: list[UnreadableCredentialResponse] = Field(default_factory=list)


def _progress(rotation: KeyRotation | None) -> KeyRotationProgress | None:
    if rotation is None:
        return None
    return KeyRotationProgress(
        id=rotation.id,
        state=rotation.state,
        target_fingerprint=rotation.target_fingerprint,
        retired_fingerprints=list(rotation.retired_fingerprints or []),
        done=rotation.done,
        remaining=rotation.remaining,
        unreadable=rotation.unreadable,
        message=rotation.message,
        started_at=rotation.started_at,
        completed_at=rotation.completed_at,
    )


async def _status(db: AsyncSession) -> KeyRotationStatus:
    instances = await registry.list_instances()
    now = datetime.now(timezone.utc)
    fleet = key_rotation.fleet_status(instances, now=now)
    active = await key_rotation.active_rotation(db)
    reason = "A key rotation is already in progress." if active else fleet.reason
    return KeyRotationStatus(
        primary_fingerprint=identity.primary_fingerprint(),
        decrypt_fingerprints=identity.decrypt_fingerprints(),
        instances=[
            KeyRotationInstance(
                id=i.id,
                name=i.name,
                live=registry.is_live(i, now=now),
                primary_fingerprint=registry.primary_fingerprint(i),
                decrypt_fingerprints=list(
                    i.decrypt_fingerprints or (registry.primary_fingerprint(i),)
                ),
            )
            for i in sorted(instances, key=lambda i: (i.role != "main", i.id))
        ],
        can_start=active is None and fleet.ready,
        reason=reason,
        rotation=_progress(active or await key_rotation.latest_rotation(db)),
        unreadable=[
            UnreadableCredentialResponse(**vars(c))
            for c in await key_rotation.unreadable_credentials(db)
        ],
    )


@router.get("", response_model=KeyRotationStatus)
async def get_key_rotation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KeyRotationStatus:
    """Each instance's keys, the latest rotation's progress, and credentials no key reads."""
    require_instance_admin(current_user)
    return await _status(db)


@router.post("", response_model=KeyRotationStatus, status_code=status.HTTP_201_CREATED)
async def start_key_rotation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KeyRotationStatus:
    """Start re-encrypting stored values under ENCRYPTION_KEY. The leader does the work.

    Refused (409) unless every live instance encrypts with the same key, and while
    another rotation is in progress.
    """
    require_instance_admin(current_user)
    try:
        rotation = await key_rotation.start_rotation(
            db, current_user, await registry.list_instances()
        )
    except key_rotation.RotationRefusedError as exc:
        audit(
            action="encryption_key.rotation_start",
            outcome=OUTCOME_DENIED,
            actor=current_user,
            reason=str(exc),
        )
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    audit(
        action="encryption_key.rotation_start",
        outcome=OUTCOME_SUCCESS,
        actor=current_user,
        target_type="key_rotation",
        target_id=rotation.id,
        target_fingerprint=rotation.target_fingerprint,
        retired_fingerprints=list(rotation.retired_fingerprints or []),
    )
    return await _status(db)
