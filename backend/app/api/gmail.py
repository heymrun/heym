"""Gmail pickers: the account's own labels and its addresses (primary and Send mail as)."""

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import CredentialType, User
from app.db.session import SessionLocal, get_db
from app.models.gmail_schemas import (
    GmailAddress,
    GmailAddressesResponse,
    GmailLabel,
    GmailLabelsResponse,
)
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config
from app.services.gmail_service import GmailApiError, GmailService

router = APIRouter()


async def _gmail_config(db: AsyncSession, credential_id: uuid.UUID, user: User) -> dict:
    credential = await get_accessible_credential(db, credential_id, user.id)
    if credential is None or credential.type != CredentialType.gmail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Gmail credential not found"
        )
    return decrypt_config(credential.encrypted_config)


def _gmail_error(exc: GmailApiError) -> HTTPException:
    if exc.status_code in (401, 403):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Gmail failed")


def _read(credential_id: uuid.UUID, config: dict, what: str) -> list[dict[str, Any]]:
    with SessionLocal() as sync_db:
        service = GmailService(str(credential_id), config, sync_db)
        return service.list_labels() if what == "labels" else service.list_send_as()


@router.get("/{credential_id}/labels", response_model=GmailLabelsResponse)
async def list_labels(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GmailLabelsResponse:
    """The account's own labels, by name. System mailboxes are fixed options in the form."""
    config = await _gmail_config(db, credential_id, current_user)
    try:
        labels = await asyncio.to_thread(_read, credential_id, config, "labels")
    except GmailApiError as exc:
        raise _gmail_error(exc) from exc
    user_labels = [
        GmailLabel(id=str(label["id"]), name=str(label.get("name") or label["id"]))
        for label in labels
        if label.get("type") == "user" and label.get("id")
    ]
    return GmailLabelsResponse(labels=sorted(user_labels, key=lambda label: label.name.lower()))


@router.get("/{credential_id}/addresses", response_model=GmailAddressesResponse)
async def list_addresses(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GmailAddressesResponse:
    """The account's primary address and its Send mail as aliases, primary first."""
    config = await _gmail_config(db, credential_id, current_user)
    try:
        items = await asyncio.to_thread(_read, credential_id, config, "addresses")
    except GmailApiError as exc:
        raise _gmail_error(exc) from exc
    addresses = [
        GmailAddress(
            email=str(item["sendAsEmail"]),
            display_name=str(item.get("displayName") or ""),
            is_primary=item.get("isPrimary") is True,
        )
        for item in items
        if item.get("sendAsEmail")
    ]
    addresses.sort(key=lambda address: (not address.is_primary, address.email.lower()))
    return GmailAddressesResponse(addresses=addresses)
