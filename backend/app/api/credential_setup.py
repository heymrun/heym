"""The page behind an MCP credential form: read it, finish it, or decline it.

Only the user the request was opened for can see or finish it, so a forwarded link is
useless to anyone else. The credential itself is saved through the Credentials API, which
keeps its own checks; this router only records which credential answered the request.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models import Credential, CredentialSetupRequest, User
from app.models.credential_setup_schemas import CredentialSetupComplete, CredentialSetupResponse
from app.services.credential_setup import (
    STATUS_COMPLETED,
    STATUS_DECLINED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    settle_form_step,
    setup_request_status,
)

router = APIRouter()


def _response(row: CredentialSetupRequest) -> CredentialSetupResponse:
    return CredentialSetupResponse(
        id=row.id,
        action=row.action,
        credential_type=row.credential_type,
        suggested_name=row.suggested_name,
        credential_id=row.credential_id,
        reason=row.reason,
        status=setup_request_status(row),
        expires_at=row.expires_at,
        completed_at=row.completed_at,
    )


async def _owned_request(
    db: AsyncSession, request_id: uuid.UUID, user_id: uuid.UUID, *, for_update: bool = False
) -> CredentialSetupRequest:
    query = select(CredentialSetupRequest).where(
        CredentialSetupRequest.id == request_id, CredentialSetupRequest.user_id == user_id
    )
    if for_update:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return row


def _ensure_pending(row: CredentialSetupRequest) -> None:
    current = setup_request_status(row)
    if current == STATUS_EXPIRED:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This form has expired")
    if current != STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This form is already closed"
        )


@router.get("/{request_id}", response_model=CredentialSetupResponse)
async def get_credential_setup(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CredentialSetupResponse:
    """Read a credential form request opened for the signed-in user."""
    return _response(await _owned_request(db, request_id, current_user.id))


@router.post("/{request_id}/complete", response_model=CredentialSetupResponse)
async def complete_credential_setup(
    request_id: uuid.UUID,
    body: CredentialSetupComplete,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CredentialSetupResponse:
    """Record the credential the user saved; the waiting chat turn picks it up."""
    row = await _owned_request(db, request_id, current_user.id, for_update=True)
    _ensure_pending(row)
    credential = (
        await db.execute(
            select(Credential.owner_id, Credential.name).where(Credential.id == body.credential_id)
        )
    ).first()
    if credential is None or credential.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    if row.action == "update" and body.credential_id != row.credential_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This form updates a different credential",
        )
    row.credential_id = body.credential_id
    row.status = STATUS_COMPLETED
    row.completed_at = datetime.now(timezone.utc)
    verb = "Updated" if row.action == "update" else "Created"
    await settle_form_step(db, row, f'{verb} credential "{credential.name}"')
    await db.commit()
    return _response(row)


@router.post("/{request_id}/decline", response_model=CredentialSetupResponse)
async def decline_credential_setup(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CredentialSetupResponse:
    """Close the form without a credential; the chat continues without one."""
    row = await _owned_request(db, request_id, current_user.id, for_update=True)
    _ensure_pending(row)
    row.status = STATUS_DECLINED
    row.completed_at = datetime.now(timezone.utc)
    await settle_form_step(db, row, "Credential form declined")
    await db.commit()
    return _response(row)
