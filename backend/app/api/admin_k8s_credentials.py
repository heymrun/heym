"""Admin view of credentials declared as Kubernetes Secrets, gated by HEYM_ADMIN_EMAILS."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_instance_admin
from app.config import settings
from app.db.models import Credential, User
from app.db.session import get_db
from app.services.audit_log import OUTCOME_SUCCESS, audit
from app.services.k8s_credentials import rows
from app.services.k8s_credentials.store import store

router = APIRouter()


class K8sCredentialStatusResponse(BaseModel):
    namespace: str
    secret_name: str
    credential_id: uuid.UUID
    name: str
    type: str
    owner_email: str
    status: str
    detail: str | None = None
    warnings: list[str] = Field(default_factory=list)


class K8sCredentialsResponse(BaseModel):
    enabled: bool
    # This process's watch. Every process keeps its own; the Instances tab shows
    # whether each instance has one that is synced.
    synced: bool
    synced_at: datetime | None = None
    last_error: str | None = None
    credentials: list[K8sCredentialStatusResponse] = Field(default_factory=list)


@router.get("", response_model=K8sCredentialsResponse)
async def read_k8s_credentials(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> K8sCredentialsResponse:
    """Every labelled Secret and every Secret-backed row, with why each is or isn't usable."""
    require_instance_admin(current_user)
    if not settings.k8s_credentials:
        return K8sCredentialsResponse(enabled=False, synced=False)
    statuses, _ = await rows.plan(db, store.items()) if store.synced else ([], [])
    return K8sCredentialsResponse(
        enabled=True,
        synced=store.synced,
        synced_at=store.synced_at,
        last_error=store.last_error,
        credentials=[K8sCredentialStatusResponse(**vars(s)) for s in statuses],
    )


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_unavailable_k8s_credential(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove the row of a Secret that is gone. Rows are never removed automatically.

    Refused while the Secret exists: the row would come straight back on the next sync,
    and removing it would drop shares and break workflows for nothing.
    """
    require_instance_admin(current_user)
    credential = (
        await db.execute(
            select(Credential).where(Credential.id == credential_id, Credential.source.is_not(None))
        )
    ).scalar_one_or_none()
    if credential is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Credential not found")
    if not store.synced or store.get(credential.source or "") is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Its Secret still exists, or this process has not synced yet",
        )
    await db.delete(credential)
    await db.commit()
    audit(
        action="credential.delete",
        outcome=OUTCOME_SUCCESS,
        actor=current_user,
        target_type="credential",
        target_id=credential_id,
        target_name=credential.name,
        reason="kubernetes_secret_removed",
    )
