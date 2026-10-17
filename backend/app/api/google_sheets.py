"""Google Sheets pickers: which tabs a spreadsheet has, and which columns a tab has.

They let a form build a Google Sheets step without the user typing tab and column names.
"""

import asyncio
import uuid
from string import ascii_uppercase

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import CredentialType, User
from app.db.session import SessionLocal, get_db
from app.models.google_sheets_schemas import SheetColumnsResponse, SpreadsheetTabsResponse
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config
from app.services.google_sheets_service import _SHEETS_BASE, GoogleSheetsService

router = APIRouter()


async def _sheets_config(db: AsyncSession, credential_id: uuid.UUID, user: User) -> dict:
    credential = await get_accessible_credential(db, credential_id, user.id)
    if credential is None or credential.type != CredentialType.google_sheets:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Google Sheets credential not found"
        )
    return decrypt_config(credential.encrypted_config)


def _google_error(exc: httpx.HTTPError) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (403, 404):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google Sheets could not open this spreadsheet with this connection",
        )
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Google Sheets failed")


def _read_tabs(credential_id: str, config: dict, spreadsheet_id: str) -> dict:
    with SessionLocal() as sync_db:
        service = GoogleSheetsService(credential_id, config, sync_db)
        response = httpx.get(
            f"{_SHEETS_BASE}/{spreadsheet_id}",
            headers={"Authorization": f"Bearer {service.access_token()}"},
            params={"fields": "properties.title,sheets.properties.title"},
            timeout=20,
        )
    response.raise_for_status()
    return response.json()


def _read_header(credential_id: str, config: dict, spreadsheet_id: str, tab: str) -> list:
    quoted = "'" + tab.replace("'", "''") + "'"
    with SessionLocal() as sync_db:
        service = GoogleSheetsService(credential_id, config, sync_db)
        response = httpx.get(
            f"{_SHEETS_BASE}/{spreadsheet_id}/values/{quoted}!A1:Z1",
            headers={"Authorization": f"Bearer {service.access_token()}"},
            timeout=20,
        )
    response.raise_for_status()
    values = response.json().get("values") or [[]]
    return values[0] if values else []


@router.get("/{credential_id}/tabs", response_model=SpreadsheetTabsResponse)
async def spreadsheet_tabs(
    credential_id: uuid.UUID,
    spreadsheet: str = Query(min_length=1, max_length=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpreadsheetTabsResponse:
    """The title and tabs of a spreadsheet, given its link or id."""
    config = await _sheets_config(db, credential_id, current_user)
    spreadsheet_id = GoogleSheetsService.parse_spreadsheet_id(spreadsheet)
    try:
        body = await asyncio.to_thread(_read_tabs, str(credential_id), config, spreadsheet_id)
    except httpx.HTTPError as exc:
        raise _google_error(exc) from exc
    return SpreadsheetTabsResponse(
        spreadsheet_id=spreadsheet_id,
        title=str((body.get("properties") or {}).get("title") or ""),
        tabs=[
            str((sheet.get("properties") or {}).get("title") or "")
            for sheet in body.get("sheets") or []
        ],
    )


@router.get("/{credential_id}/columns", response_model=SheetColumnsResponse)
async def sheet_columns(
    credential_id: uuid.UUID,
    spreadsheet: str = Query(min_length=1, max_length=500),
    tab: str = Query(min_length=1, max_length=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SheetColumnsResponse:
    """The header row of a tab (columns A to Z), as the Sheets node and trigger name them."""
    config = await _sheets_config(db, credential_id, current_user)
    spreadsheet_id = GoogleSheetsService.parse_spreadsheet_id(spreadsheet)
    try:
        header = await asyncio.to_thread(
            _read_header, str(credential_id), config, spreadsheet_id, tab
        )
    except httpx.HTTPError as exc:
        raise _google_error(exc) from exc
    columns = [
        str(value).strip() or ascii_uppercase[index]
        for index, value in enumerate(header[: len(ascii_uppercase)])
    ]
    return SheetColumnsResponse(columns=columns)
