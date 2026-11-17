"""Owner-scoped Microsoft OAuth for the Outlook credential (Outlook.com and Microsoft 365)."""

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.google_drive_oauth import _popup_html
from app.config import settings
from app.db.models import Credential, CredentialType, User
from app.db.session import get_db
from app.services.encryption import decrypt_config, encrypt_config
from app.services.outlook_service import (
    GRAPH_BASE,
    LOGIN_BASE,
    OUTLOOK_SCOPES,
    account_address,
    has_mail_scope,
    oauth_tenant,
    token_url,
)
from app.services.public_url import resolve_public_origin

router = APIRouter()
_STATE_TYPE = "outlook_oauth_state"
_CALLBACK_PATH = "/api/credentials/outlook/oauth/callback"


class AuthorizeRequest(BaseModel):
    credential_id: uuid.UUID


class AuthorizeResponse(BaseModel):
    auth_url: str


def create_oauth_state(
    user_id: str, credential_id: str, client_id: str, tenant: str, redirect_uri: str
) -> str:
    """Sign short-lived state without putting the client secret in the browser URL."""
    return jwt.encode(
        {
            "user_id": user_id,
            "credential_id": credential_id,
            "client_id": client_id,
            "tenant": tenant,
            "redirect_uri": redirect_uri,
            "type": _STATE_TYPE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def handle_callback_state(state: str) -> dict | None:
    """Reject expired, foreign-provider or malformed authorization state."""
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != _STATE_TYPE:
            return None
        uuid.UUID(payload["user_id"])
        uuid.UUID(payload["credential_id"])
        if not payload.get("client_id") or not payload.get("redirect_uri"):
            return None
        oauth_tenant({"tenant": payload.get("tenant")})
        return payload
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError):
        return None


def build_auth_url(client_id: str, tenant: str, redirect_uri: str, state: str) -> str:
    """Request mail read/write with a refresh token; the account picker lets users choose."""
    return f"{LOGIN_BASE}/{tenant}/oauth2/v2.0/authorize?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": " ".join(OUTLOOK_SCOPES),
            "prompt": "select_account",
            "state": state,
        }
    )


@router.post("/authorize", response_model=AuthorizeResponse)
async def authorize(
    body: AuthorizeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuthorizeResponse:
    """Authorize an existing Outlook credential owned by the current user."""
    result = await db.execute(
        select(Credential).where(
            Credential.id == body.credential_id,
            Credential.owner_id == current_user.id,
            Credential.type == CredentialType.outlook,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(404, "Outlook credential not found")
    config = decrypt_config(credential.encrypted_config)
    client_id = str(config.get("client_id", "")).strip()
    if not client_id or not str(config.get("client_secret", "")).strip():
        raise HTTPException(400, "Outlook credential requires client_id and client_secret")
    try:
        tenant = oauth_tenant(config)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    redirect_uri = resolve_public_origin(request).rstrip("/") + _CALLBACK_PATH
    state = create_oauth_state(
        str(current_user.id), str(credential.id), client_id, tenant, redirect_uri
    )
    return AuthorizeResponse(auth_url=build_auth_url(client_id, tenant, redirect_uri, state))


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Exchange a code and update only the state owner's original credential."""
    if error or not code or not state:
        return HTMLResponse(_popup_html(False, message="Microsoft authorization was cancelled"))
    payload = handle_callback_state(state)
    if not payload:
        return HTMLResponse(_popup_html(False, message="Invalid or expired state"))
    result = await db.execute(
        select(Credential).where(
            Credential.id == uuid.UUID(payload["credential_id"]),
            Credential.owner_id == uuid.UUID(payload["user_id"]),
            Credential.type == CredentialType.outlook,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        return HTMLResponse(_popup_html(False, message="Outlook credential not found"))
    config = decrypt_config(credential.encrypted_config)
    try:
        tenant = oauth_tenant(config)
    except ValueError:
        tenant = ""
    if (
        config.get("client_id") != payload["client_id"]
        or tenant != payload["tenant"]
        or not config.get("client_secret")
    ):
        return HTMLResponse(_popup_html(False, message="Credential changed; reconnect it"))
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                token_url(tenant),
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "redirect_uri": payload["redirect_uri"],
                    "scope": " ".join(OUTLOOK_SCOPES),
                },
            )
            response.raise_for_status()
            tokens = response.json()
            if not tokens.get("access_token") or not (
                tokens.get("refresh_token") or config.get("refresh_token")
            ):
                return HTMLResponse(
                    _popup_html(False, message="Microsoft did not grant offline access; reconnect")
                )
            scope = str(tokens.get("scope") or "")
            if not has_mail_scope(scope):
                return HTMLResponse(
                    _popup_html(False, message="Allow Heym to read and organize your Outlook mail")
                )
            profile = await client.get(
                GRAPH_BASE,
                params={"$select": "mail,userPrincipalName"},
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return HTMLResponse(
            _popup_html(False, message="Microsoft token exchange failed; reconnect")
        )
    try:
        profile.raise_for_status()
        email_address = account_address(profile.json())
    except (httpx.HTTPError, ValueError, AttributeError):
        return HTMLResponse(
            _popup_html(False, message="Microsoft Graph did not answer; check the app permissions")
        )
    config.update(
        {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token") or config.get("refresh_token"),
            "token_expiry": (
                datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
            ).isoformat(),
            "scope": scope,
            "email_address": email_address,
        }
    )
    credential.encrypted_config = encrypt_config(config)
    await db.commit()
    return HTMLResponse(_popup_html(True, credential_id=str(credential.id)))
