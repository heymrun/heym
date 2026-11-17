"""Outlook pickers: the mailbox's folders and the account's addresses (primary and aliases)."""

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import CredentialType, User
from app.db.session import SessionLocal, get_db
from app.models.outlook_schemas import (
    OutlookAddress,
    OutlookAddressesResponse,
    OutlookFolder,
    OutlookFoldersResponse,
)
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config
from app.services.outlook_service import OutlookApiError, OutlookService, account_address

router = APIRouter()


async def _outlook_config(db: AsyncSession, credential_id: uuid.UUID, user: User) -> dict:
    credential = await get_accessible_credential(db, credential_id, user.id)
    if credential is None or credential.type != CredentialType.outlook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Outlook credential not found"
        )
    return decrypt_config(credential.encrypted_config)


def _outlook_error(exc: OutlookApiError) -> HTTPException:
    if exc.status_code in (401, 403):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Outlook failed")


def _folders(credential_id: uuid.UUID, config: dict) -> list[dict[str, Any]]:
    with SessionLocal() as sync_db:
        return OutlookService(str(credential_id), config, sync_db).list_folders()


def _profile(credential_id: uuid.UUID, config: dict) -> dict[str, Any]:
    with SessionLocal() as sync_db:
        return OutlookService(str(credential_id), config, sync_db).get_profile()


def profile_addresses(profile: dict[str, Any]) -> list[OutlookAddress]:
    """The primary address first, then every SMTP alias Exchange lists for the account."""
    primary = account_address(profile).lower()
    addresses: list[OutlookAddress] = []
    seen: set[str] = set()

    def add(email: str, is_primary: bool) -> None:
        value = email.strip().lower()
        if "@" in value and value not in seen:
            seen.add(value)
            addresses.append(OutlookAddress(email=value, is_primary=is_primary))

    if primary:
        add(primary, True)
    for proxy in profile.get("proxyAddresses") or []:
        kind, sep, email = str(proxy).partition(":")
        if sep and kind.lower() == "smtp":
            add(email, False)
    addresses[1:] = sorted(addresses[1:], key=lambda address: address.email)
    return addresses


@router.get("/{credential_id}/folders", response_model=OutlookFoldersResponse)
async def list_folders(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OutlookFoldersResponse:
    """Every mail folder of the account, nested folders as ``Parent / Child``."""
    config = await _outlook_config(db, credential_id, current_user)
    try:
        folders = await asyncio.to_thread(_folders, credential_id, config)
    except OutlookApiError as exc:
        raise _outlook_error(exc) from exc
    return OutlookFoldersResponse(
        folders=[OutlookFolder(id=folder["id"], path=folder["path"]) for folder in folders]
    )


@router.get("/{credential_id}/addresses", response_model=OutlookAddressesResponse)
async def list_addresses(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OutlookAddressesResponse:
    """The account's primary address and its aliases, primary first."""
    config = await _outlook_config(db, credential_id, current_user)
    try:
        profile = await asyncio.to_thread(_profile, credential_id, config)
    except OutlookApiError as exc:
        raise _outlook_error(exc) from exc
    return OutlookAddressesResponse(addresses=profile_addresses(profile))
