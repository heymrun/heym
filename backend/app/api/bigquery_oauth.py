"""Google BigQuery OAuth2 authorization and callback endpoints."""

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from jwt import InvalidTokenError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db.models import Credential, CredentialType, User
from app.db.session import get_db
from app.services.encryption import decrypt_config, encrypt_config
from app.services.public_url import resolve_public_origin

router = APIRouter()

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery https://www.googleapis.com/auth/drive"
_STATE_TYPE = "bq_oauth_state"
_STATE_TTL_MINUTES = 10


class AuthorizeRequest(BaseModel):
    credential_id: str


def create_oauth_state(
    user_id: str,
    credential_id: str | None,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> str:
    """Encode OAuth2 state as a signed JWT."""
    payload = {
        "user_id": user_id,
        "credential_id": credential_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "type": _STATE_TYPE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def handle_callback_state(state: str) -> dict | None:
    """Decode and validate the OAuth2 state JWT. Returns payload dict or None on failure."""
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != _STATE_TYPE:
            return None
        return payload
    except InvalidTokenError:
        return None


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Build the Google OAuth2 authorization URL for BigQuery scope."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _BIGQUERY_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"


def _popup_html(success: bool, credential_id: str = "", message: str = "") -> str:
    """Return an HTML page that posts a message to the opener and closes."""
    if success:
        script = f"""
            if (window.opener) {{
                window.opener.postMessage(
                    {{type: 'google-oauth-success', credentialId: '{credential_id}'}},
                    '*'
                );
            }}
            window.close();
        """
    else:
        safe_msg = message.replace("'", "\\'").replace("\n", " ")
        script = f"""
            if (window.opener) {{
                window.opener.postMessage(
                    {{type: 'google-oauth-error', message: '{safe_msg}'}},
                    '*'
                );
            }}
            window.close();
        """
    return f"<html><body><script>{script}</script></body></html>"


@router.post("/authorize")
async def authorize(
    body: AuthorizeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the Google OAuth2 authorization URL for the BigQuery popup flow."""
    cred_uuid = uuid.UUID(body.credential_id)
    result = await db.execute(
        select(Credential).where(
            Credential.id == cred_uuid,
            Credential.owner_id == current_user.id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    config = decrypt_config(credential.encrypted_config)
    client_id = config.get("client_id", "").strip()
    client_secret = config.get("client_secret", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential is missing client_id or client_secret",
        )

    redirect_uri = (
        resolve_public_origin(request).rstrip("/") + "/api/credentials/bigquery/oauth/callback"
    )
    state = create_oauth_state(
        user_id=str(current_user.id),
        credential_id=str(cred_uuid),
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    auth_url = build_auth_url(client_id, redirect_uri, state)
    return {"auth_url": auth_url, "state": state}


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Handle the Google OAuth2 callback, exchange code for tokens, persist credential."""
    if error or not code or not state:
        return HTMLResponse(_popup_html(False, message=error or "Authorization cancelled"))

    payload = handle_callback_state(state)
    if not payload:
        return HTMLResponse(_popup_html(False, message="Invalid or expired state"))

    redirect_uri = payload["redirect_uri"]
    client_id = payload["client_id"]
    client_secret = payload["client_secret"]
    user_id = uuid.UUID(payload["user_id"])
    credential_id = payload.get("credential_id")

    try:
        resp = httpx.post(
            _GOOGLE_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        token_data = resp.json()
    except Exception as exc:
        return HTMLResponse(_popup_html(False, message=f"Token exchange failed: {exc}"))

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)
    token_expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    config = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expiry": token_expiry,
        "scope": _BIGQUERY_SCOPE,
    }
    encrypted = encrypt_config(config)

    if credential_id:
        cred_uuid = uuid.UUID(credential_id)
        result = await db.execute(select(Credential).where(Credential.id == cred_uuid))
        cred = result.scalar_one_or_none()
        if cred:
            cred.encrypted_config = encrypted
            await db.commit()
            return HTMLResponse(_popup_html(True, credential_id=str(cred.id)))

    new_cred = Credential(
        name="BigQuery",
        type=CredentialType.bigquery,
        owner_id=user_id,
        encrypted_config=encrypted,
    )
    db.add(new_cred)
    await db.commit()
    await db.refresh(new_cred)
    return HTMLResponse(_popup_html(True, credential_id=str(new_cred.id)))
