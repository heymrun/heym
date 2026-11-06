"""Owner-scoped Google OAuth for Calendar invitations and availability."""

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
from app.services.google_meet_service import GOOGLE_MEET_SCOPE
from app.services.public_url import resolve_public_origin

router = APIRouter()
_STATE_TYPE = "google_meet_oauth_state"


class AuthorizeRequest(BaseModel):
    credential_id: uuid.UUID


class AuthorizeResponse(BaseModel):
    auth_url: str


def create_oauth_state(user_id: str, credential_id: str, client_id: str, redirect_uri: str) -> str:
    """Sign short-lived state without putting client secrets in the browser URL."""
    return jwt.encode(
        {
            "user_id": user_id,
            "credential_id": credential_id,
            "client_id": client_id,
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
        return payload
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError):
        return None


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Request Calendar event and free/busy permissions with offline token refresh."""
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_MEET_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
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
    """Authorize an existing Google Meet credential owned by the current user."""
    result = await db.execute(
        select(Credential).where(
            Credential.id == body.credential_id,
            Credential.owner_id == current_user.id,
            Credential.type == CredentialType.google_meet,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(404, "Google Meet credential not found")
    config = decrypt_config(credential.encrypted_config)
    client_id = str(config.get("client_id", "")).strip()
    if not client_id or not str(config.get("client_secret", "")).strip():
        raise HTTPException(400, "Google Meet credential requires client_id and client_secret")
    redirect_uri = (
        resolve_public_origin(request).rstrip("/") + "/api/credentials/google-meet/oauth/callback"
    )
    state = create_oauth_state(str(current_user.id), str(credential.id), client_id, redirect_uri)
    return AuthorizeResponse(auth_url=build_auth_url(client_id, redirect_uri, state))


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Exchange a code and update only the state owner's original credential."""
    if error or not code or not state:
        return HTMLResponse(_popup_html(False, message="Google authorization was cancelled"))
    payload = handle_callback_state(state)
    if not payload:
        return HTMLResponse(_popup_html(False, message="Invalid or expired state"))
    result = await db.execute(
        select(Credential).where(
            Credential.id == uuid.UUID(payload["credential_id"]),
            Credential.owner_id == uuid.UUID(payload["user_id"]),
            Credential.type == CredentialType.google_meet,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        return HTMLResponse(_popup_html(False, message="Google Meet credential not found"))
    config = decrypt_config(credential.encrypted_config)
    if config.get("client_id") != payload["client_id"] or not config.get("client_secret"):
        return HTMLResponse(_popup_html(False, message="Credential changed; reconnect it"))
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "redirect_uri": payload["redirect_uri"],
                },
            )
        response.raise_for_status()
        tokens = response.json()
        if not tokens.get("access_token") or not (
            tokens.get("refresh_token") or config.get("refresh_token")
        ):
            return HTMLResponse(
                _popup_html(False, message="Google did not grant offline access; reconnect")
            )
        scope = tokens.get("scope", GOOGLE_MEET_SCOPE)
        if not set(GOOGLE_MEET_SCOPE.split()).issubset(scope.split()):
            return HTMLResponse(
                _popup_html(
                    False, message="Allow both Calendar events and availability permissions"
                )
            )
        config.update(
            {
                "access_token": tokens["access_token"],
                "refresh_token": tokens.get("refresh_token") or config.get("refresh_token"),
                "token_expiry": (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=int(tokens.get("expires_in", 3600)))
                ).isoformat(),
                "scope": scope,
            }
        )
    except (httpx.HTTPError, ValueError, TypeError):
        return HTMLResponse(_popup_html(False, message="Google token exchange failed; reconnect"))
    credential.encrypted_config = encrypt_config(config)
    await db.commit()
    return HTMLResponse(_popup_html(True, credential_id=str(credential.id)))
